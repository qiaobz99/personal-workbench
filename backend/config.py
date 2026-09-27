"""Local KB Workbench — central configuration.

All paths are derived from the project root so the project is fully
self-contained and portable. Everything can be overridden via env vars.
"""
import os

# --- Project layout -------------------------------------------------------
# backend/ lives one level below the project root.
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# The Vault is the single source of truth: a tree of Markdown files.
# Kept OUT of git on purpose (see .gitignore): your notes stay local-only.
VAULT_DIR = os.environ.get("KB_VAULT", os.path.join(PROJECT_ROOT, "vault"))
os.makedirs(VAULT_DIR, exist_ok=True)

# Runtime data (SQLite DB, optional Chroma index). Not committed to git.
DATA_DIR = os.environ.get("KB_DATA", os.path.join(PROJECT_ROOT, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# SQLite database (full-text index + tasks + meta).
DB_PATH = os.path.join(DATA_DIR, "kb.db")

# Optional Chroma vector store (semantic search layer).
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
COLLECTION_NAME = "kb_docs"

# Local embedding model used when the semantic layer is enabled.
EMBEDDING_MODEL = os.environ.get("KB_EMBED_MODEL", "BAAI/bge-m3")

# Frontend static assets (served by the built-in HTTP server).
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

# --- HTTP server ----------------------------------------------------------
# Deliberately NOT 3000/5000/8000/8080/8888 — those are the ports every other
# dev tool grabs, which caused avoidable "address already in use" collisions.
HOST = os.environ.get("KB_HOST", "0.0.0.0")
PORT = int(os.environ.get("KB_PORT", "17321"))

# --- Misc -----------------------------------------------------------------
APP_NAME = "Local KB Workbench"
APP_VERSION = "0.1.0"
