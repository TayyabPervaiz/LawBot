"""
Vector Store module for the Pakistan Law Bot.
Handles embedding legal text chunks and storing/querying them using ChromaDB
with locally-run sentence-transformers (no API calls, no cost).
"""

import chromadb
try:
    from chromadb import EmbeddingFunction
except ImportError:
    class EmbeddingFunction:
        pass

from sentence_transformers import SentenceTransformer
from src.config import (
    EMBEDDING_MODEL, CHROMA_DB_PATH, COLLECTION_NAME, CANDIDATE_POOL_SIZE,
    PROCESSED_DATA_DIR,
)


class LocalEmbeddingFunction(EmbeddingFunction):
    """
    Custom embedding function that uses sentence-transformers locally.
    ChromaDB calls this automatically when adding or querying documents.
    This runs entirely on your CPU — no API key, no internet, no cost.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        print(f"Loading embedding model '{model_name}'... (first run downloads ~80MB)")
        self.model = SentenceTransformer(model_name)
        print("Embedding model loaded successfully.")

    def __call__(self, input: list[str]) -> list[list[float]]:
        """
        ChromaDB calls this with a list of strings and expects a list of
        embedding vectors (each vector is a list of floats).
        """
        embeddings = self.model.encode(input, show_progress_bar=False)
        return embeddings.tolist()


# --- Module-level singleton instances ---
# These are created once and reused across all function calls.
_embedding_function = None
_chroma_client = None
_collection = None


def _get_embedding_function() -> LocalEmbeddingFunction:
    """Get or create the singleton embedding function."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = LocalEmbeddingFunction()
    return _embedding_function


def _get_client() -> chromadb.PersistentClient:
    """Get or create the singleton ChromaDB client."""
    global _chroma_client
    if _chroma_client is None:
        print(f"Connecting to ChromaDB at: {CHROMA_DB_PATH}")
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _chroma_client


def get_or_create_collection() -> chromadb.Collection:
    """
    Get the existing ChromaDB collection or create a new one.
    Uses local sentence-transformers for embeddings.

    Returns:
        chromadb.Collection: The ChromaDB collection ready for adding/querying.
    """
    global _collection
    if _collection is None:
        client = _get_client()
        embed_fn = _get_embedding_function()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=embed_fn,
            metadata={"description": "Punjab Tenancy & Rent Law embeddings"}
        )
        print(f"Collection '{COLLECTION_NAME}' ready. Current document count: {_collection.count()}")
    return _collection


def add_chunks(chunks: list[dict]) -> int:
    """
    Add legal text chunks to the vector store.

    Each chunk must be a dictionary with these keys:
        - "id" (str): Unique identifier, e.g., "punjab_rpa_2009_sec_15"
        - "text" (str): The full text content of the chunk
        - "metadata" (dict): Metadata dict with keys like:
            - "law_title": "The Punjab Rented Premises Act, 2009"
            - "section_number": "15"
            - "section_title": "Application for eviction"
            - "chapter": "Chapter V: Eviction"

    Args:
        chunks: List of chunk dictionaries.

    Returns:
        int: Number of chunks added.
    """
    if not chunks:
        print("Warning: No chunks provided to add.")
        return 0

    collection = get_or_create_collection()

    # Extract the three parallel lists that ChromaDB expects
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    metadatas = [chunk["metadata"] for chunk in chunks]

    # Upsert (insert or update) into ChromaDB
    # ChromaDB will automatically call our LocalEmbeddingFunction to embed the documents
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )

    print(f"Added/updated {len(chunks)} chunks. Total documents in collection: {collection.count()}")
    return len(chunks)


def query(question: str, top_k: int = 20, where: dict | None = None) -> list[dict]:
    """
    Query the vector store with a natural language question.
    Returns the most relevant legal text chunks.

    Args:
        question: The user's legal question in natural language.
        top_k: Number of top results to return. Phase 2A default is a large
               CANDIDATE POOL (config.CANDIDATE_POOL_SIZE) because hybrid
               fusion/reranking in src/retrieval.py needs a pool, not the
               final answer set.
        where: Optional ChromaDB metadata filter, e.g.
               {"law_id": "peca_2016"} or {"category": "criminal"}.
               Used by tests and debugging, not the default path
               (revised plan Section 5.4 point 7).

    Returns:
        List of dicts:
            - "text": the chunk text
            - "metadata": chunk metadata (law_id, law_title, section_number, ...)
            - "distance": similarity distance (lower = more similar)
            - "id": the chunk id
    """
    collection = get_or_create_collection()

    if collection.count() == 0:
        print("Warning: Collection is empty. Run the parser and indexing first.")
        return []

    kwargs: dict = {
        "query_texts": [question],
        "n_results": min(top_k, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    # Reformat ChromaDB's nested list structure into a flat list of dicts
    formatted_results = []
    if results and results["documents"] and results["documents"][0]:
        for i in range(len(results["documents"][0])):
            formatted_results.append({
                "id": results["ids"][0][i] if results.get("ids") else None,
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
            })

    return formatted_results


def reset_collection() -> None:
    """
    Delete and recreate the collection. Use this to start fresh.
    WARNING: This permanently deletes all stored embeddings.
    """
    global _collection
    client = _get_client()

    try:
        client.delete_collection(name=COLLECTION_NAME)
        print(f"Deleted collection '{COLLECTION_NAME}'.")
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' did not exist. Creating fresh.")

    _collection = None
    get_or_create_collection()
    print("Fresh collection created.")


# --- CLI entry point for testing ---
if __name__ == "__main__":
    print("=== Vector Store Module Test ===\n")

    # Test 1: Create collection
    print("1. Creating/loading collection...")
    collection = get_or_create_collection()
    print(f"   Document count: {collection.count()}\n")

    # Test 2: Add sample chunks
    print("2. Adding sample test chunks...")
    sample_chunks = [
        {
            "id": "test_chunk_1",
            "text": "Section 15. Application for eviction. A landlord may apply to the Rent Tribunal for the eviction of a tenant on one or more of the following grounds.",
            "metadata": {
                "law_title": "The Punjab Rented Premises Act, 2009",
                "section_number": "15",
                "section_title": "Application for eviction",
                "chapter": "Chapter V: Eviction"
            }
        },
        {
            "id": "test_chunk_2",
            "text": "Section 5. Tenancy agreement. Every tenancy agreement shall be in writing and shall be registered with the Rent Registrar.",
            "metadata": {
                "law_title": "The Punjab Rented Premises Act, 2009",
                "section_number": "5",
                "section_title": "Tenancy agreement",
                "chapter": "Chapter II: Creation of Tenancy"
            }
        }
    ]
    add_chunks(sample_chunks)

    # Test 3: Query
    print("\n3. Querying: 'Can my landlord evict me?'")
    results = query("Can my landlord evict me?", top_k=2)
    for i, r in enumerate(results):
        print(f"\n   Result {i+1}:")
        print(f"   Section: {r['metadata'].get('section_number', 'N/A')}")
        print(f"   Title: {r['metadata'].get('section_title', 'N/A')}")
        print(f"   Distance: {r['distance']:.4f}")
        print(f"   Text: {r['text'][:100]}...")

    # Test 4: Reset
    print("\n4. Resetting collection (cleaning up test data)...")
    reset_collection()

    print("\n=== All vector store tests passed! ===")
