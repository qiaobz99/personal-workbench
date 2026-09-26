"""Optional semantic search layer backed by Chroma.

This module is **strictly optional**. If ``chromadb`` (and a local embedding
model) is not installed, every function here degrades gracefully: the rest of
the application keeps working with FTS5 full-text search only.

Enable the semantic layer by installing the optional dependencies:

    pip install chromadb sentence-transformers

and then re-indexing the Vault from the UI (Settings → Re-index) or the API.
"""
import os

import config

_client = None
_available = None


def is_available() -> bool:
    """True only when chromadb can be imported."""
    global _available
    if _available is None:
        try:
            import chromadb  # noqa: F401

            _available = True
        except Exception:
            _available = False
    return _available


def get_client():
    global _client
    if not is_available():
        return None
    if _client is None:
        import chromadb

        os.makedirs(config.CHROMA_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    return _client


def _collection():
    client = get_client()
    if client is None:
        return None
    try:
        return client.get_or_create_collection(config.COLLECTION_NAME)
    except Exception:
        return None


def index_doc(path: str, title: str, content: str) -> bool:
    """Add/replace a document in the vector store."""
    col = _collection()
    if col is None:
        return False
    try:
        col.upsert(
            ids=[path],
            documents=[content],
            metadatas=[{"path": path, "title": title}],
        )
        return True
    except Exception:
        return False


def delete_doc(path: str) -> None:
    col = _collection()
    if col is None:
        return
    try:
        col.delete(ids=[path])
    except Exception:
        pass


def semantic_search(query: str, n: int = 10) -> list:
    """Return [{path, title, snippet}] or [] when unavailable."""
    col = _collection()
    if col is None:
        return []
    try:
        res = col.query(query_texts=[query], n_results=n)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        out = []
        for doc, meta in zip(docs, metas):
            out.append(
                {
                    "path": meta.get("path"),
                    "title": meta.get("title"),
                    "snippet": (doc or "")[:240],
                }
            )
        return out
    except Exception:
        return []
