#!/usr/bin/env python3
"""Local KB Workbench — backend HTTP server.

A tiny, dependency-free web server (Python standard library only) that:

* serves the Vue single-page frontend from ``frontend/``,
* exposes a JSON API over the Vault (Markdown files) and the local SQLite
  store (FTS5 full-text index + kanban tasks),
* optionally uses Chroma for semantic search when it is installed.

Run:  ``python backend/app.py``  then open  http://localhost:8080
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Make sibling modules importable when launched as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import store
import vault
import indexer
import report
import chroma_client

# --------------------------------------------------------------------------
# Content types
# --------------------------------------------------------------------------
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".map": "application/json",
}


def _send_json(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _send_text(handler, text, status=200, ctype="text/plain; charset=utf-8"):
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


# --------------------------------------------------------------------------
# API dispatch
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = f"LocalKB/{config.APP_VERSION}"

    # Quieter logs.
    def log_message(self, fmt, *args):
        sys.stderr.write("[kb] " + (fmt % args) + "\n")

    # -- helpers -----------------------------------------------------------
    def _serve_static(self, url_path: str):
        # Map "/" to index.html; everything else is relative to frontend/.
        if url_path in ("/", "/index.html"):
            rel = "index.html"
        else:
            rel = url_path.lstrip("/")
        abs_path = os.path.normpath(os.path.join(config.FRONTEND_DIR, rel))
        root = os.path.normpath(config.FRONTEND_DIR)
        if not abs_path.startswith(root) or not os.path.isfile(abs_path):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(abs_path)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(abs_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Disable caching so UI/CSS/JS changes show up immediately on refresh.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, action: str, params: dict, body: dict):
        # ---- read-style endpoints ----------------------------------------
        if action == "tree":
            return _send_json(self, vault.list_tree())
        if action == "list":
            return _send_json(self, vault.list_dir(params.get("path", "")))
        if action == "file":
            try:
                return _send_json(
                    self,
                    {"path": params["path"], "content": vault.read_file(params["path"])},
                )
            except (KeyError, FileNotFoundError):
                return _send_json(self, {"error": "not found"}, 404)
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
        if action == "search":
            q = params.get("q", "").strip()
            if not q:
                return _send_json(self, {"query": q, "results": []})
            fts = store.search_fts(q, limit=50)
            sub = store.search_substring(q, limit=50)
            sem = []
            if chroma_client.is_available():
                sem = chroma_client.semantic_search(q, n=10)
            # Merge: semantic first, then FTS5, then a CJK substring fallback.
            # Dedupe by path; the fallback recovers short CJK phrases that the
            # default FTS5 tokenizer cannot split. Tag provenance for the UI.
            seen = set()
            merged = []
            for r in sem + fts + sub:
                p = r.get("path")
                if p in seen:
                    continue
                seen.add(p)
                merged.append(dict(r))
            for i, r in enumerate(merged):
                r["fromSemantic"] = i < len(sem)
            return _send_json(self, {"query": q, "results": merged[:50]})
        if action == "tasks":
            status = params.get("status")
            return _send_json(self, {"tasks": store.list_tasks(status)})
        if action == "report":
            rtype = params.get("type", "daily")
            date = params.get("date")
            data = (
                report.weekly_report(date)
                if rtype == "weekly"
                else report.daily_report(date)
            )
            return _send_json(self, data)
        if action == "stats":
            return _send_json(self, report.overview_stats())
        if action == "config":
            return _send_json(
                self,
                {
                    "app": config.APP_NAME,
                    "version": config.APP_VERSION,
                    "vault_dir": vault.vault_root(),
                    "port": config.PORT,
                    "semantic_available": chroma_client.is_available(),
                    "embedding_model": config.EMBEDDING_MODEL,
                },
            )
        if action == "reindex":
            stats = indexer.reindex()
            return _send_json(self, stats)

        return _send_json(self, {"error": "unknown action"}, 404)

    # -- HTTP verbs --------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        params = {k: (v[0] if v else "") for k, v in params.items()}

        if path.startswith("/api/"):
            return self._api(path[len("/api/") :].rstrip("/"), params, {})
        return self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        action = parsed.path[len("/api/") :].rstrip("/")
        body = _read_body(self)

        if action == "file":
            p = body.get("path")
            content = body.get("content", "")
            if not p:
                return _send_json(self, {"error": "path required"}, 400)
            try:
                meta = vault.write_file(p, content)
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
            # Keep the index fresh for the edited file.
            try:
                store.upsert_doc(
                    meta["path"],
                    (content.splitlines()[0].lstrip("# ").strip()
                     if content.startswith("#") else os.path.basename(p)),
                    content,
                    meta["mtime"],
                )
                if chroma_client.is_available():
                    chroma_client.index_doc(meta["path"], os.path.basename(p), content)
            except Exception:
                pass
            return _send_json(self, {"ok": True, **meta})

        if action == "tasks":
            t = store.create_task(
                title=body.get("title", "未命名任务"),
                notes=body.get("notes", ""),
                status=body.get("status", "todo"),
                priority=body.get("priority", "medium"),
                tags=body.get("tags", ""),
                due=body.get("due", ""),
            )
            return _send_json(self, t, 201)

        if action == "reindex":
            return _send_json(self, indexer.reindex())

        return _send_json(self, {"error": "unknown action"}, 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path[len("/api/") :].rstrip("/").split("/")
        body = _read_body(self)
        if parts and parts[0] == "tasks" and len(parts) > 1:
            try:
                tid = int(parts[1])
            except ValueError:
                return _send_json(self, {"error": "bad id"}, 400)
            t = store.update_task(tid, **body)
            if t is None:
                return _send_json(self, {"error": "not found"}, 404)
            return _send_json(self, t)
        return _send_json(self, {"error": "unknown action"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path[len("/api/") :].rstrip("/").split("/")
        params = urllib.parse.parse_qs(parsed.query)
        if parts and parts[0] == "tasks" and len(parts) > 1:
            try:
                tid = int(parts[1])
            except ValueError:
                return _send_json(self, {"error": "bad id"}, 400)
            ok = store.delete_task(tid)
            return _send_json(self, {"ok": ok})
        if parts and parts[0] == "file":
            p = (params.get("path") or [""])[0]
            if not p:
                return _send_json(self, {"error": "path required"}, 400)
            ok = vault.delete_file(p)
            if ok:
                store.delete_doc(p)
                if chroma_client.is_available():
                    chroma_client.delete_doc(p)
            return _send_json(self, {"ok": ok})
        return _send_json(self, {"error": "unknown action"}, 404)


def main():
    store.init_db()
    print(f"[kb] Initialising index…")
    stats = indexer.reindex()
    print(
        f"[kb] Indexed {stats['indexed_fts']} docs "
        f"(semantic: {stats['indexed_semantic']}, available={stats['semantic_available']})"
    )
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    url = f"http://localhost:{config.PORT}"
    print(f"[kb] {config.APP_NAME} v{config.APP_VERSION}")
    print(f"[kb] Serving frontend : {config.FRONTEND_DIR}")
    print(f"[kb] Vault            : {vault.vault_root()}")
    print(f"[kb] Open your browser: {url}")
    print(f"[kb] Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[kb] Stopped.")


if __name__ == "__main__":
    main()
