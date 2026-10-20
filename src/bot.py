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
import json
from pathlib import Path

from src.config import TOP_K_RESULTS, PROCESSED_DATA_DIR


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

    print(f"Loaded {len(chunks)} chunks from {chunks_path}")

    # Reset if forced
    if force:
        print("Resetting vector store collection...")
        vs.reset_collection()

    # Check if already indexed
    collection = vs.get_or_create_collection()
    if collection.count() >= len(chunks) and not force:
        print(f"Collection already has {collection.count()} documents. Skipping indexing.")
        print("Use --force to re-index from scratch.")
        return collection.count()

    # Index the chunks
    print("Indexing chunks into vector store...")
    count = vs.add_chunks(chunks)
    print(f"Indexing complete. {count} chunks indexed.")
    return count


# ---------------------------------------------------------------------------
# Query Pipeline
# ---------------------------------------------------------------------------

def ask(question: str, top_k: int = TOP_K_RESULTS, verbose: bool = False) -> dict:
    """
    Main query function. Takes a natural language question and returns
    a grounded legal answer.

    Pipeline:
        1. Retrieve relevant chunks from vector store
        2. Pass chunks + question to generator
        3. Return structured result

    Args:
        question: The user's legal question.
        top_k: Number of chunks to retrieve.
        verbose: If True, print intermediate steps.

    Returns:
        Dict with keys: answer, in_scope, detected_topic, citations, source_sections
    """
    question = question.strip()
    if not question:
        return {
            "answer": "Please ask a legal question about Punjab tenancy and rent law.",
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

    # Step 2: Retrieve relevant chunks
    vs = _get_vector_store()
    collection = vs.get_or_create_collection()

    if collection.count() == 0:
        return {
            "answer": (
                "The legal knowledge base is empty. Please run the indexing step first:\n"
                "  1. python -m src.parser\n"
                "  2. python -m src.bot --index"
            ),
            "in_scope": True,
            "detected_topic": None,
            "citations": {"has_citations": False, "citation_count": 0, "citations_found": []},
            "source_sections": [],
        }

    if verbose:
        print(f"  [Retrieval] Querying vector store for top {top_k} chunks...")

    retrieved = vs.query(question, top_k=top_k)

    if verbose:
        print(f"  [Retrieval] Found {len(retrieved)} relevant chunks:")
        for i, r in enumerate(retrieved):
            meta = r.get("metadata", {})
            print(f"    {i+1}. Section {meta.get('section_number', '?')}: "
                  f"{meta.get('section_title', '?')} "
                  f"(distance: {r.get('distance', '?'):.4f})")

    # Step 3: Generate answer
    if verbose:
        print(f"  [Generator] Calling LLM...")

    result = gen.generate_answer(question, retrieved)

    if verbose:
        print(f"  [Generator] Citations found: {result['citations']['citations_found']}")

    return result


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

def print_welcome():
    """Print the welcome banner for the interactive CLI."""
    print()
    print("=" * 60)
    print("  PAKISTAN LAW BOT - Punjab Tenancy & Rent Law")
    print("  The Punjab Rented Premises Act, 2009")
    print("=" * 60)
    print()
    print("  Ask any question about Punjab tenancy and rent law.")
    print("  Type 'quit' or 'exit' to stop.")
    print("  Type 'verbose' to toggle detailed output.")
    print()
    print("-" * 60)


def interactive_cli():
    """Run the interactive command-line interface."""
    print_welcome()

    verbose = False

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
        print(f"Knowledge base ready: {collection.count()} documents indexed.\n")

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

        if question.lower() == "verbose":
            verbose = not verbose
            print(f"  Verbose mode: {'ON' if verbose else 'OFF'}")
            continue

        print()
        try:
            result = ask(question, verbose=verbose)
            print(result["answer"])

            if verbose:
                print(f"\n  [Meta] In-scope: {result['in_scope']}")
                print(f"  [Meta] Source sections: {result['source_sections']}")
                print(f"  [Meta] Citations: {result['citations']}")

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

    else:
        # Default: interactive CLI
        interactive_cli()
