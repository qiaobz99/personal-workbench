"""KB Workbench — central configuration.

All paths are derived from the project root so the project is fully
self-contained and portable. Everything can be overridden via env vars.
"""
import os

# --- Project layout -------------------------------------------------------
# backend/ lives one level below the project root.
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# The Vault is the single source of truth: a tree of Markdown files.
# Kept OUT of git on purpose (see .gitignore): your notes stay on your machine.
# 2026-10-17: data moved to E:\4个人知识库\vault. Resolution order:
#   KB_VAULT env  >  <project>/vault (legacy)  >  E:\4个人知识库\vault (current)
_LEGACY_VAULT = os.path.join(PROJECT_ROOT, "vault")
_RELOCATED_VAULT = r"E:\4个人知识库\vault"
_env_vault = os.environ.get("KB_VAULT")
if _env_vault:
    VAULT_DIR = _env_vault
elif os.path.isdir(_LEGACY_VAULT):
    VAULT_DIR = _LEGACY_VAULT
elif os.path.isdir(_RELOCATED_VAULT):
    VAULT_DIR = _RELOCATED_VAULT
else:
    VAULT_DIR = _LEGACY_VAULT
os.makedirs(VAULT_DIR, exist_ok=True)

# Runtime data (SQLite DB, optional Chroma index). Not committed to git.
DATA_DIR = os.environ.get("KB_DATA", os.path.join(PROJECT_ROOT, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# SQLite database (full-text index + tasks + meta).
DB_PATH = os.path.join(DATA_DIR, "kb.db")

# Optional Chroma vector store (semantic search layer).
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
COLLECTION_NAME = "kb_docs"

# On-device embedding model used when the semantic layer is enabled.
EMBEDDING_MODEL = os.environ.get("KB_EMBED_MODEL", "BAAI/bge-m3")

# --- LLM / RAG answer layer ----------------------------------------------
# The provider / API key / model / base URL are managed by settings.py so
# they can be edited from the in-app Settings page (env vars still win).
# Only the retrieval context budget lives here.
# Context budget so a single answer never blows the model's token window.
# Long structured notes (interview study notes run 18-38 KB) were being cut
# after the first 1500 chars, so the answer layer could see a note's title and
# intro but never its body -- it would reply "the notes don't say". The budget
# below is sized for the real vault: ~5 docs x 8000 chars ~= 20k tokens.
LLM_CTX_MAX_CHARS_PER_DOC = int(os.environ.get("KB_LLM_CTX_CHARS", "8000"))
LLM_CTX_MAX_DOCS = int(os.environ.get("KB_LLM_CTX_DOCS", "5"))

# Frontend static assets (served by the built-in HTTP server).
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

# --- HTTP server ----------------------------------------------------------
# Deliberately NOT 3000/5000/8000/8080/8888 — those are the ports every other
# dev tool grabs, which caused avoidable "address already in use" collisions.
HOST = os.environ.get("KB_HOST", "0.0.0.0")
PORT = int(os.environ.get("KB_PORT", "17321"))

# --- Misc -----------------------------------------------------------------
APP_NAME = "KB Workbench"
APP_VERSION = "0.1.0"
