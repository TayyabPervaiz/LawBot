"""
Core Query Orchestration for the Pakistan Law Bot.

This module ties the full RAG pipeline together:
    User Question → Vector Store Retrieval → Generator (LLM + Guardrails) → Answer

It also provides the interactive CLI for testing.

Design decisions:
- The pipeline is a simple sequential flow (retrieve → generate) rather than
  an agent loop, because legal Q&A doesn't benefit from multi-step reasoning
  and simpler pipelines are easier to audit for correctness.
- Error handling is defensive: if ChromaDB returns nothing, the generator
  still gets called with an empty context (and the system prompt handles it
  by saying "provisions not found"). If the LLM API fails, a clear error
  message is returned instead of crashing.
"""

import sys
import re
import json
import hashlib
from pathlib import Path

from src.config import TOP_K_RESULTS, PROCESSED_DATA_DIR
import src.law_registry as registry


# ---------------------------------------------------------------------------
# Lazy imports — avoid loading heavy models until actually needed
# ---------------------------------------------------------------------------

_vector_store = None
_generator = None


def _get_vector_store():
    """Lazy-import the vector store module (triggers embedding model download on first use)."""
    global _vector_store
    if _vector_store is None:
        from src import vector_store as vs
        _vector_store = vs
    return _vector_store


def _get_generator():
    """Lazy-import the generator module."""
    global _generator
    if _generator is None:
        from src import generator as gen
        _generator = gen
    return _generator


# ---------------------------------------------------------------------------
# Index Building — One-time setup
# ---------------------------------------------------------------------------

def build_index(force: bool = False) -> int:
    """
    Load parsed chunks from JSON and index them into the vector store.

    Args:
        force: If True, reset the collection and re-index from scratch.

    Returns:
        Number of chunks indexed.
    """
    vs = _get_vector_store()
    chunks_path = PROCESSED_DATA_DIR / "chunks.json"
    state_path = PROCESSED_DATA_DIR / "index_state.json"

    if not chunks_path.exists():
        print(f"ERROR: Chunks file not found at {chunks_path}")
        print("Run the parser first: python -m src.parser")
        return 0

    # Load chunks
    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    if not chunks:
        print("ERROR: Chunks file is empty. Re-run the parser.")
        return 0

    chunks_hash = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    print(f"Loaded {len(chunks)} chunks from {chunks_path}")

    # Reset if forced
    if force:
        print("Resetting vector store collection...")
        vs.reset_collection()

    collection = vs.get_or_create_collection()

    # Wave 3-L: Check stored hash & count on collection metadata / state file
    # Skipping only on count misses same-size chunk text rewrites.
    cached_hash = None
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as sf:
                cached_hash = json.load(sf).get("chunks_hash")
        except Exception:
            pass
    if cached_hash is None and collection.metadata:
        cached_hash = collection.metadata.get("chunks_hash")

    if not force and collection.count() == len(chunks) and cached_hash == chunks_hash:
        print(f"Collection is up to date ({collection.count()} chunks, matching hash). Skipping indexing.")
        print("Use --force to re-index from scratch.")
        return collection.count()

    if not force and collection.count() > 0:
        print("Index mismatch detected (chunks hash or count changed). Resetting and rebuilding...")
        vs.reset_collection()
        collection = vs.get_or_create_collection()

    # Index the chunks
    print("Indexing chunks into vector store...")
    count = vs.add_chunks(chunks)

    # Store index state
    state = {
        "chunks_hash": chunks_hash,
        "count": count,
        "mtime": chunks_path.stat().st_mtime,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as sf:
        json.dump(state, sf, indent=2)

    try:
        new_meta = dict(collection.metadata or {})
        new_meta["chunks_hash"] = chunks_hash
        collection.modify(metadata=new_meta)
    except Exception:
        pass

    print(f"Indexing complete. {count} chunks indexed.")
    return count


# ---------------------------------------------------------------------------
# Query Pipeline
# ---------------------------------------------------------------------------

_FOLLOWUP_WORDS = {
    "it", "this", "that", "these", "those", "he", "she", "they", "them",
    "penalty", "punishment", "fine", "appeal", "saza", "jurmana", "zamanat",
    "iska", "uski", "unka", "yeh", "woh",
    "اسکا", "اسکی", "انکا", "یہ", "وہ", "سزا", "جرمانہ", "ضمانت", "اپیل",
}

_FOLLOWUP_PHRASES = (
    "what about", "what if", "and if", "can he", "can she", "is it",
    "kya hoga", "agar woh", "aur agar", "kya wo", "kya yeh", "iski saza",
    "zamanat kaise", "اور اگر", "کیا وہ", "کیا یہ", "اس کی سزا", "ضمانت کیسے",
    "اگر وہ",
)


def _is_followup_query(question: str) -> bool:
    """
    Detect if a user query relies on context from previous turns.
    Wave 3-H: Length-only heuristic removed so standalone short queries
    (e.g. 'What is murder?') do not concatenate previous context.
    """
    q_lower = question.lower().strip()
    if any(phrase in q_lower for phrase in _FOLLOWUP_PHRASES):
        return True
    words = set(re.findall(r"\b[\w]+\b", q_lower))
    return bool(words & _FOLLOWUP_WORDS)


def ask(
    question: str,
    conversation_history: list[dict] | None = None,
    top_k: int = TOP_K_RESULTS,
    verbose: bool = False,
) -> dict:
    """
    Main query function. Takes a natural language question and returns
    a grounded legal answer with statutory citations.

    Supports session conversation history for context-aware multi-turn follow-ups.

    Args:
        question: The user's legal question.
        conversation_history: Optional list of previous turn dicts: [{"role": "user"|"assistant", "content": "..."}]
        top_k: Number of chunks to retrieve.
        verbose: If True, print intermediate steps.

    Returns:
        Dict with keys: answer, in_scope, detected_topic, citations, source_sections
    """
    question = question.strip()
    if not question:
        loaded_line = registry.format_loaded_laws_for_refusal()
        return {
            "answer": (
                "Please ask a legal question regarding the laws currently covered:\n"
                f"{loaded_line}\n"
                "(Supports English, Roman Urdu, and اردو)."
            ),
            "in_scope": True,
            "detected_topic": None,
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": []},
            "source_sections": [],
        }

    gen = _get_generator()

    # Step 1: Quick scope check (doesn't need vector store or LLM)
    scope = gen.detect_scope(question)
    if not scope["in_scope"]:
        if verbose:
            print(f"  [Scope] OUT OF SCOPE - detected topic: {scope['detected_topic']}")
        refusal = gen.build_refusal_response(scope["detected_topic"], question)
        return {
            "answer": refusal,
            "in_scope": False,
            "detected_topic": scope["detected_topic"],
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": []},
            "source_sections": [],
        }

    # Contextualize query for retrieval if this is a follow-up question
    retrieval_query = question
    if conversation_history:
        last_user_q = next(
            (m["content"] for m in reversed(conversation_history) if m.get("role") == "user"),
            None,
        )
        if last_user_q and _is_followup_query(question):
            retrieval_query = f"{last_user_q} {question}"
            if verbose:
                print(f"  [Contextualizer] Follow-up query expanded for retrieval: '{retrieval_query}'")

    # Step 2: Ensure knowledge base is indexed (setup error if empty, revised plan 2-F)
    vs = _get_vector_store()
    _c = vs.get_or_create_collection()
    if _c.count() == 0:
        return {
            "answer": (
                "The legal knowledge base is empty. Please run the indexing step first:\n"
                "  1. python -m src.parser\n"
                "  2. python -m src.bot --index"
            ),
            "in_scope": True,
            "detected_topic": None,
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": [], "supported": [], "unsupported": []},
            "source_sections": [],
            "not_covered": False,
        }

    if verbose:
        from src import retrieval as retriever
        print(f"  [Retrieval] Hybrid search (vector + BM25, pool={retriever.config.CANDIDATE_POOL_SIZE})...")

    from src import retrieval as retrieval_module
    retrieval_result = retrieval_module.search(retrieval_query, top_k=top_k)
    retrieved = retrieval_result["results"]

    if verbose:
        print(f"  [Retrieval] {len(retrieved)} candidate chunks after fusion/rerank:")
        for i, r in enumerate(retrieved):
            meta = r.get("metadata") or {}
            print(f"    {i+1}. Sec {meta.get('section_number', '?')}: "
                  f"{meta.get('section_title', '?')[:40]} "
                  f"(fused: {r.get('fused_score', '?')})")

    # Jurisdiction awareness (revised plan 5.4 point 6)
    jnote = retrieval_module.jurisdiction_note(question)

    # Step 3: Relevance threshold — below it, the loaded laws don't cover this
    if retrieval_result["below_threshold"] or not retrieved:
        loaded_line = registry.format_loaded_laws_for_refusal()
        note = f"\n\n{jnote}" if jnote else ""
        return {
            "answer": (
                f"The laws currently loaded ({loaded_line}) do not explicitly "
                "address this specific issue. Please consult a qualified "
                "advocate for guidance precisely on your situation."
                + note
            ),
            "in_scope": True,
            "detected_topic": None,
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": []},
            "source_sections": [],
            "not_covered": True,
        }

    # Step 4: Generate answer with conversation context
    if verbose:
        print(f"  [Generator] Calling LLM...")

    result = gen.generate_answer(question, retrieved, conversation_history=conversation_history)
    if jnote and not result["answer"].startswith("Error:"):
        result["answer"] = result["answer"] + f"\n\n{jnote}"

    if verbose:
        print(f"  [Generator] Citations found: {result['citations']['citations_found']}")

    return result


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

def print_welcome():
    """Print the welcome banner for the interactive CLI."""
    loaded_laws = registry.get_loaded_laws()
    print()
    print("=" * 68)
    print("  PAKISTAN LAW BOT — Multi-Law Legal Information Assistant")
    print("  Grounded Statutory AI with Exact Section Citations")
    print("=" * 68)
    print("  Active Statutory Coverage:")
    for law_id, meta in loaded_laws.items():
        print(f"    • [{meta.get('category', 'general').capitalize()}] {meta['title']} ({meta.get('jurisdiction')})")
    print("=" * 68)
    print("  Supported Languages: English, Roman Urdu, and اردو")
    print("  Commands:")
    print("    • 'clear' or 'reset' : Clear conversation memory")
    print("    • 'verbose'          : Toggle retrieval & debug details")
    print("    • 'quit' or 'exit'   : Exit assistant")
    print("-" * 68)


def interactive_cli():
    """Run the interactive command-line interface with session memory."""
    print_welcome()

    verbose = False
    conversation_history: list[dict] = []

    # Ensure index exists
    print("Checking knowledge base...")
    vs = _get_vector_store()
    collection = vs.get_or_create_collection()
    if collection.count() == 0:
        print("\nKnowledge base is empty. Building index...")
        count = build_index()
        if count == 0:
            print("Failed to build index. Exiting.")
            return
    else:
        print(f"Knowledge base ready: {collection.count()} statutory chunks indexed across all loaded laws.\n")

    while True:
        try:
            question = input("\nYour question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if not question:
            continue

        if question.lower() in ("quit", "exit", "q"):
            print("\nGoodbye!")
            break

        if question.lower() in ("clear", "reset"):
            conversation_history.clear()
            print("  Conversation history cleared. Starting fresh topic.")
            continue

        if question.lower() == "verbose":
            verbose = not verbose
            print(f"  Verbose mode: {'ON' if verbose else 'OFF'}")
            continue

        print()
        try:
            result = ask(question, conversation_history=conversation_history, verbose=verbose)
            print(result["answer"])

            # Store in conversation memory for multi-turn follow-ups
            if result.get("in_scope") and not result["answer"].startswith("Error:"):
                conversation_history.append({"role": "user", "content": question})
                conversation_history.append({"role": "assistant", "content": result["answer"]})

            if verbose:
                print(f"\n  [Meta] In-scope: {result['in_scope']}")
                print(f"  [Meta] Source sections: {result['source_sections']}")
                print(f"  [Meta] Citations: {result['citations']}")
                print(f"  [Meta] History turns: {len(conversation_history) // 2}")

        except Exception as e:
            print(f"\nError: {e}")
            print("Please try again or check your configuration.")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--index" in args or "index" in args:
        # Index mode: build/rebuild the vector store
        force = "--force" in args
        print("Building vector store index...")
        build_index(force=force)

    elif "--ask" in args:
        # Single question mode (for scripting/testing)
        idx = args.index("--ask")
        if idx + 1 < len(args):
            question = " ".join(args[idx + 1:])
            result = ask(question, verbose=True)
            print("\n" + result["answer"])
        else:
            print("Usage: python -m src.bot --ask 'your question here'")

    elif "--web" in args or "web" in args:
        # Web server mode
        from src.server import run_server
        port = 8000
        for i, a in enumerate(args):
            if a in ("--port", "-p") and i + 1 < len(args):
                try:
                    port = int(args[i + 1])
                except ValueError:
                    pass
        run_server(port=port)

    else:
        # Default: interactive CLI
        interactive_cli()
