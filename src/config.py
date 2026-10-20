"""
Configuration module for the Pakistan Law Bot.
Loads settings from .env file and provides project-wide constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Project Paths ---
# Root of the project (two levels up from this file: src/config.py -> src/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where raw legal text files are stored
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw" / "tenancy_punjab"

# Where processed chunks are saved
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

# Where ChromaDB stores its persistent vector database
CHROMA_DB_PATH = str(PROJECT_ROOT / "data" / "chroma_db")

# --- Embedding Model ---
# This model runs locally on your CPU. No API key needed. No cost.
# all-MiniLM-L6-v2 is a good balance of speed and quality (80MB download on first run)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# --- LLM Settings ---
# Groq provides free API access to Llama models
# Get your free API key at: https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# The LLM model to use via Groq's free tier
# llama-3.3-70b-versatile: Best reasoning, free on Groq
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3.8-27b")

# --- ChromaDB Settings ---
# Name of the collection inside ChromaDB that stores our law embeddings
COLLECTION_NAME = "punjab_tenancy_law"

# --- RAG Settings ---
# How many chunks to retrieve from the vector store for each query
TOP_K_RESULTS = 5

# Maximum tokens for LLM response
MAX_TOKENS = 1024

# LLM temperature (0.0 = deterministic, good for legal accuracy)
TEMPERATURE = 0.0
