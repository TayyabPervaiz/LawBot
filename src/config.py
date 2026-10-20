"""
Configuration module for the Pakistan Law Bot.
Loads settings from .env file and provides project-wide constants.

Everything law-specific lives in src/law_registry.py, not here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# === Project Paths ===
# Root of the project (two levels up from this file: src/config.py -> src/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Original, untouched PDF downloads. NEVER indexed, never edited.
# The parser reads ONLY from data/raw/.
SOURCE_PDFS_DIR = PROJECT_ROOT / "data" / "source_pdfs"

# Clean UTF-8 text files. THE PARSER READS ONLY THIS FOLDER_TREE.
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"

# Where processed chunks / validation reports / caches are saved
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
VALIDATION_REPORT_PATH = PROCESSED_DATA_DIR / "validation_report.txt"

# Where ChromaDB stores its persistent vector database
CHROMA_DB_PATH = str(PROJECT_ROOT / "data" / "chroma_db")

# === Embedding Model ===
# A MULTILINGUAL model, chosen now (Phase 2A) so adding Roman Urdu / Urdu later
# does not force a full re-index (revised plan Section 5.6).
# paraphrase-multilingual-MiniLM-L12-v2: ~118 languages, runs locally on CPU, free.
# Candidates considered: BAAI/bge-m3 (heaviest), intfloat/multilingual-e5-small/base.
# Final choice is tuned against the benchmark at GATE 1.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# === LLM Settings ===
# Groq provides free API access to Llama models
# Get your free API key at: https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# The LLM model used via Groq's free tier (matches README; fixable via .env)
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# Version tag included in the LLM answer-cache key. Bump this whenever the
# system prompt or generation logic changes so stale cached answers are not reused.
PROMPT_VERSION = "2A-1"

# === ChromaDB Settings ===
# One collection holds ALL laws; each chunk carries law_id / category / jurisdiction
# metadata (revised plan Section 5.1). Laws come from src/law_registry.py.
COLLECTION_NAME = "pakistan_laws"

# === RAG / Retrieval Settings (revised plan Section 5.4) ===
# Candidate pool pulled from the vector store before fusion/reranking.
# Larger than TOP_K because hybrid fusion needs a pool to rank.
CANDIDATE_POOL_SIZE = 20

# How many chunks finally reach the LLM.
TOP_K_RESULTS = 5

# Reciprocal Rank Fusion constant (standard 60).
RRF_K = 60

# Weight of the vector-search score vs BM25 score in the hybrid combination
# (0..1). Tuned at GATE 1.
HYBRID_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.6"))

# Soft keyword hint boost factor. Registry hint_keywords add up to this much
# relative boost and NEVER exclude a law from search. Tuned at GATE 1.
HINT_BOOST = float(os.getenv("HINT_BOOST", "0.05"))

# Retrieval relevance threshold (top fused score below this => the bot says
# the loaded laws do not cover the question). Tuned at GATE 1.
RETRIEVAL_MIN_SCORE = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.35"))

# Optional local cross-encoder reranker (revised plan Section 5.4 point 2).
# Set RERANK_MODEL (e.g. "cross-encoder/ms-marco-MiniLM-L-6-v2") in .env to
# enable; empty = disabled (RRF-only ranking). Tuned at GATE 1 for latency/accuracy.
RERANK_MODEL = os.getenv("RERANK_MODEL", "")

# === LLM answer cache (revised plan Section 6.4: survive free-tier 429s) ===
# Deterministic (temperature 0) answers are cached by hash of
# (prompt version, model, question, context). Set LLM_CACHE=0 to disable.
LLM_CACHE_ENABLED = os.getenv("LLM_CACHE", "1") != "0"
LLM_CACHE_PATH = PROCESSED_DATA_DIR / "llm_cache.json"

# === LLM call settings ===
MAX_TOKENS = 1024
TEMPERATURE = 0.0
