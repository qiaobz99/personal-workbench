#!/usr/bin/env python3
"""KB Workbench — backend HTTP server.

A tiny, dependency-free web server (Python standard library only) that:

* serves the Vue single-page frontend from ``frontend/``,
* exposes a JSON API over the Vault (Markdown files) and the bundled SQLite
  store (FTS5 full-text index + kanban tasks),
* optionally uses Chroma for semantic search when it is installed.

Run:  ``python backend/app.py``  then open  http://localhost:17321
      (override the port with the ``KB_PORT`` environment variable)
"""
import json
import os
import re
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
import work
import diary
import dreport
import chroma_client
import llm
import settings

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
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".map": "application/json",
}


# Cache-busting for self-hosted use: an HTML response gets ?v=<mtime> appended to
# every /css/*.css and /js/*.js reference. Browsers cache static assets hard,
# so an edited stylesheet used to keep looking identical until a manual hard
# refresh. The mtime changes the moment a file is saved, so a plain F5 is
# enough from now on.
_ASSET_REF_RE = re.compile(
    rb'((?:href|src)=")(/(?:css|js|vendor)/[^"?#]+[.](?:css|js))(")'
)


def _bust_html(body: bytes) -> bytes:
    def repl(m):
        prefix, url, suffix = m.group(1), m.group(2), m.group(3)
        rel = url.decode("ascii").lstrip("/")
        path = os.path.normpath(os.path.join(config.FRONTEND_DIR, rel))
        try:
            stamp = str(int(os.path.getmtime(path)))
        except OSError:
            return m.group(0)
        return prefix + url + b"?v=" + stamp.encode("ascii") + suffix

    return _ASSET_REF_RE.sub(repl, body)


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


def _reindex_file(rel_path: str):
    """Refresh the full-text/semantic index for one Vault file after a write."""
    try:
        indexer.index_file(rel_path)
    except Exception:  # noqa: BLE001 - indexing must never break a write
        pass


def _retrieve(query: str, scope: str = "", top: int = 6) -> list:
    """Mixed retrieval (semantic + FTS5 + NL keywords + CJK substring).

    Shared by /api/search and the RAG answer layer. ``scope`` optionally
    restricts hits to a Vault subtree, e.g. "learn/ai".
    """
    fts = store.search_fts(query, limit=50)
    nl = store.search_nl(query, limit=50)
    sub = store.search_substring(query, limit=50)
    sem = []
    if chroma_client.is_available():
        sem = chroma_client.semantic_search(query, n=10)
    prefix = scope.strip("/") + "/" if scope.strip("/") else ""
    seen = set()
    merged = []
    for r in sem + fts + nl + sub:
        p = r.get("path")
        if not p or p in seen:
            continue
        if prefix and not p.startswith(prefix):
            continue
        seen.add(p)
        merged.append(dict(r))
    return merged[:top]


# --------------------------------------------------------------------------
# API dispatch
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = f"KB/{config.APP_VERSION}"

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
        if ext == ".html":
            body = _bust_html(body)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Disable caching so UI/CSS/JS changes show up immediately on refresh.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _serve_vault(self, url_path: str):
        # Serve static assets (images) from the vault so Markdown files can
        # reference on-disk images and have them render inside the app.
        rel = url_path[len("/vault/"):].lstrip("/")
        abs_path = os.path.normpath(os.path.join(config.VAULT_DIR, rel))
        root = os.path.normpath(config.VAULT_DIR)
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
        self.send_header("Cache-Control", "public, max-age=86400")
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
                    "llm": llm.provider_info(),
                },
            )
        if action == "settings/llm":
            # ?provider=... previews another vendor's stored config.
            return _send_json(
                self, settings.public_view(params.get("provider") or "")
            )
        if action == "reindex":
            stats = indexer.reindex()
            return _send_json(self, stats)

        # ---- Work Zone ---------------------------------------------------
        if action == "work/meta":
            return _send_json(self, work.meta())
        if action == "work/board":
            return _send_json(self, work.board())
        if action == "work/items":
            return _send_json(
                self,
                {
                    "items": work.list_items(
                        type=params.get("type") or None,
                        project=params.get("project") or None,
                        status=params.get("status") or None,
                        q=params.get("q") or None,
                    )
                },
            )
        if action == "work/item":
            rel = params.get("path") or ""
            if not rel:
                return _send_json(self, {"error": "path required"}, 400)
            try:
                return _send_json(self, work.load(rel))
            except FileNotFoundError:
                return _send_json(self, {"error": "not found"}, 404)
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
        if action == "work/conventions":
            return _send_json(self, {"items": work.list_items(type="convention")})
        if action == "work/progress":
            try:
                days = int(params.get("days") or 7)
            except ValueError:
                days = 7
            return _send_json(self, work.progress(days))

        # ---- 金融日记 (diary) -------------------------------------------
        if action == "diary/years":
            return _send_json(self, {"years": diary.years()})
        if action == "diary/year":
            return _send_json(self, diary.year(params.get("y") or ""))
        if action == "diary/day":
            try:
                return _send_json(self, diary.load_day(params.get("d") or ""))
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)

        # ---- 日报 / 周报（手动主观记录） --------------------------------
        if action == "dreport/years":
            return _send_json(self, dreport.years(params.get("kind") or "daily"))
        if action == "dreport/year":
            return _send_json(self, dreport.year(
                params.get("kind") or "daily", params.get("y") or ""))
        if action == "dreport/weeks":
            return _send_json(self, dreport.weeks(
                params.get("kind") or "weekly", params.get("y") or ""))
        if action == "dreport/entry":
            try:
                return _send_json(self, dreport.load(
                    params.get("kind") or "daily", params.get("key") or ""))
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)

        return _send_json(self, {"error": "unknown action"}, 404)

    # -- HTTP verbs --------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        params = {k: (v[0] if v else "") for k, v in params.items()}

        if path.startswith("/api/"):
            return self._api(path[len("/api/") :].rstrip("/"), params, {})
        if path.startswith("/vault/"):
            return self._serve_vault(path)
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

        # ---- Settings: LLM configuration --------------------------------
        if action == "settings/llm":
            # Fields omitted from the body are left untouched, so the UI can
            # edit the model without ever sending the API key back.
            return _send_json(self, settings.save(body))
        if action == "settings/llm/test":
            # Persist first so "fill the key and hit test" just works, then
            # fire one minimal request to prove the credentials work.
            if body:
                settings.save(body)
            cfg = settings.effective()
            try:
                reply = llm.chat(
                    "你是连通性测试助手，只需按要求回复，不要多说。",
                    "请回复两个字：正常",
                    temperature=0,
                    timeout=25,
                )
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                return _send_json(
                    self,
                    {"ok": False, "model": cfg["model"], "error": str(e)},
                    502,
                )
            return _send_json(
                self,
                {"ok": True, "model": cfg["model"], "reply": (reply or "")[:80]},
            )

        # ---- RAG 问答 (LLM answer layer) --------------------------------
        if action == "chat":
            q = (body.get("q") or "").strip()
            scope = (body.get("scope") or "").strip()
            if not q:
                return _send_json(self, {"error": "请输入问题"}, 400)
            if not llm.is_configured():
                return _send_json(
                    self,
                    {
                        "error": "尚未配置大模型：请到「设置 → AI 模型」填写 API Key"
                        "（或设置环境变量 KB_LLM_KEY）"
                    },
                    400,
                )
            hits = _retrieve(q, scope, top=config.LLM_CTX_MAX_DOCS)
            ctx = []
            for h in hits:
                full = store.get_content(h["path"]) or h.get("snippet") or ""
                ctx.append(
                    (
                        h["path"],
                        h.get("title") or h["path"],
                        full[: config.LLM_CTX_MAX_CHARS_PER_DOC],
                    )
                )
            system = (
                "你是用户的私人知识助手。只能依据<笔记上下文>中的内容作答，"
                "不得编造；若笔记未覆盖该问题，请明确回答「笔记中未提及」，"
                "如需补充通用常识必须显式标注。回答中用 [1][2] 标注引用的笔记编号。"
            )
            if ctx:
                block = "\n\n".join(
                    f"[{i + 1}] 《{t}》\n{c}" for i, (_p, t, c) in enumerate(ctx)
                )
                user = f"## 用户问题\n{q}\n\n## 笔记上下文\n{block}"
            else:
                user = f"## 用户问题\n{q}\n\n（未检索到相关笔记，请如实说明。）"
            try:
                answer = llm.chat(system, user)
            except Exception as e:  # noqa: BLE001
                return _send_json(self, {"error": f"大模型调用失败：{e}"}, 502)
            sources = [{"path": p, "title": t} for (p, t, _c) in ctx]
            return _send_json(self, {"answer": answer, "sources": sources})

        # ---- Work Zone ---------------------------------------------------
        if action == "work/item":
            try:
                item = work.create(
                    type=body.get("type", "note"),
                    title=body.get("title", ""),
                    project=body.get("project", ""),
                    priority=body.get("priority", "medium"),
                    tags=body.get("tags", ""),
                    status=body.get("status") or None,
                    severity=body.get("severity", ""),
                    verdict=body.get("verdict", ""),
                )
            except (ValueError, OSError) as e:
                return _send_json(self, {"error": str(e)}, 400)
            _reindex_file(item["path"])
            return _send_json(self, item, 201)

        if action == "work/import/scan":
            try:
                return _send_json(self, work.scan_import_dir(body.get("dir", "")))
            except (ValueError, OSError) as e:
                return _send_json(self, {"error": str(e)}, 400)

        if action == "work/import":
            try:
                res = work.import_files(
                    files=body.get("files") or [],
                    project=body.get("project", ""),
                    type=body.get("type") or None,
                )
            except (ValueError, OSError) as e:
                return _send_json(self, {"error": str(e)}, 400)
            for it in res.get("items", []):
                _reindex_file(it["path"])
            return _send_json(self, res)

        # ---- 金融日记 (diary) -------------------------------------------
        if action == "diary/day":
            try:
                item = diary.save_day(
                    date_str=body.get("date", ""),
                    title=body.get("title", ""),
                    tags=body.get("tags", ""),
                    body=body.get("body", ""),
                )
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
            _reindex_file(item["path"])
            return _send_json(self, item, 201)

        # ---- 日报 / 周报（手动主观记录） --------------------------------
        if action == "dreport/entry":
            try:
                item = dreport.save(
                    kind=body.get("kind", "daily"),
                    key=body.get("key", ""),
                    title=body.get("title", ""),
                    tags=body.get("tags", ""),
                    body=body.get("body", ""),
                )
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
            _reindex_file(item["path"])
            return _send_json(self, item, 201)

        return _send_json(self, {"error": "unknown action"}, 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path[len("/api/") :].rstrip("/").split("/")
        body = _read_body(self)

        if parts and parts[0] == "work":
            if len(parts) > 1 and parts[1] == "item":
                rel = body.get("path") or ""
                if not rel:
                    return _send_json(self, {"error": "path required"}, 400)
                fields = {
                    k: body[k]
                    for k in (
                        "title", "project", "status", "priority", "owner",
                        "tags", "refs", "severity", "verdict",
                    )
                    if k in body
                }
                try:
                    item = work.update(rel, fields=fields, body=body.get("body"))
                except FileNotFoundError:
                    return _send_json(self, {"error": "not found"}, 404)
                except (ValueError, OSError) as e:
                    return _send_json(self, {"error": str(e)}, 400)
                _reindex_file(item["path"])
                return _send_json(self, item)
            return _send_json(self, {"error": "unknown action"}, 404)

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
        if parts and parts[0] == "work" and len(parts) > 1 and parts[1] == "item":
            p = (params.get("path") or [""])[0]
            if not p:
                return _send_json(self, {"error": "path required"}, 400)
            ok = work.delete(p)
            if ok:
                store.delete_doc(p)
                if chroma_client.is_available():
                    chroma_client.delete_doc(p)
            return _send_json(self, {"ok": ok})

        if parts and parts[0] == "diary" and len(parts) > 1 and parts[1] == "day":
            d = (params.get("d") or [""])[0]
            if not d:
                return _send_json(self, {"error": "d required"}, 400)
            try:
                ok = diary.delete_day(d)
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
            if ok:
                rel = f"diary/{d[:4]}/{d}.md"
                store.delete_doc(rel)
                if chroma_client.is_available():
                    chroma_client.delete_doc(rel)
            return _send_json(self, {"ok": ok})

        if parts and parts[0] == "dreport" and len(parts) > 1 and parts[1] == "entry":
            kind = (params.get("kind") or ["daily"])[0]
            key = (params.get("key") or [""])[0]
            if not key:
                return _send_json(self, {"error": "key required"}, 400)
            try:
                ok = dreport.delete(kind, key)
            except ValueError as e:
                return _send_json(self, {"error": str(e)}, 400)
            if ok:
                rel = f"dreport/{kind}/{key[:4]}/{key}.md"
                store.delete_doc(rel)
                if chroma_client.is_available():
                    chroma_client.delete_doc(rel)
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
