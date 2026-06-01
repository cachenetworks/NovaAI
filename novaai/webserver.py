"""NovaAI - headless web server (browser UI for Raspberry Pi / Linux boxes).

This serves the exact same Tailwind frontend as the native desktop GUI, but over
plain HTTP so you can reach NovaAI from any device's browser on your network —
no display, no pywebview, no audio hardware required. It's the recommended way to
run NovaAI on a headless machine such as a Raspberry Pi 5.

How it bridges the existing UI without rewriting it:

* The frontend talks to Python only through ``window.pywebview.api.<method>(...)``.
  A small JavaScript shim (injected into index.html on the way out) recreates that
  object as a Proxy that POSTs each call to ``/api/call`` and resolves with the JSON
  result — so every existing ``api().foo()`` call keeps working unchanged.

* The backend pushes updates to the UI through ``Api._js(code)`` (see webgui.py).
  We register a sink (``webgui._emit_js``) that relays each pushed JS snippet to all
  connected browsers over a Server-Sent Events stream (``/events``); the shim evals
  them. SSE is one-way server->client (exactly what _js needs) and is pure stdlib.

Run it with:  ``python app.py --web``  (host/port via NOVA_WEB_HOST / NOVA_WEB_PORT).
"""
from __future__ import annotations

import json
import os
import queue
import socket
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import webgui
from .paths import AVATAR_UPLOADS_DIR, STATIC_DIR
from .storage import ensure_runtime_dirs

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8800

# Methods the frontend may NOT call over HTTP (private/dunder are blocked anyway).
_BLOCKED_METHODS = {"start_reminder_checker"}

# Injected into index.html right after <head>. Recreates the pywebview JS bridge
# on top of fetch + EventSource so the unmodified frontend works in a browser.
_BRIDGE_SHIM = """
<script>
(function () {
  // ---- client -> server: window.pywebview.api.<method>(...args) -> POST /api/call
  function call(method, args) {
    return fetch('/api/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method: method, args: Array.prototype.slice.call(args) })
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.error) { throw new Error(j.error); }
      return j ? j.result : undefined;
    });
  }
  var apiProxy = new Proxy({}, {
    get: function (_t, prop) {
      if (typeof prop !== 'string' || prop === 'then') { return undefined; }
      return function () { return call(prop, arguments); };
    }
  });
  window.pywebview = window.pywebview || {};
  window.pywebview.api = apiProxy;

  // ---- server -> client: SSE stream of JS snippets pushed via Api._js(code)
  function connectEvents() {
    var es = new EventSource('/events');
    es.onmessage = function (e) {
      try { (0, eval)(JSON.parse(e.data)); }
      catch (err) { console.error('NovaAI event eval failed:', err); }
    };
    es.onerror = function () { /* EventSource auto-reconnects */ };
  }
  connectEvents();

  // The frontend waits for pywebview to attach its API, both via a flag poll and
  // a 'pywebviewready' event. Fire it now that the bridge is in place.
  window.dispatchEvent(new Event('pywebviewready'));
})();
</script>
"""


class _SseClients:
    """Thread-safe registry of connected SSE browser clients."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: set[queue.SimpleQueue] = set()

    def register(self) -> "queue.SimpleQueue[str]":
        q: queue.SimpleQueue[str] = queue.SimpleQueue()
        with self._lock:
            self._queues.add(q)
        return q

    def unregister(self, q: "queue.SimpleQueue[str]") -> None:
        with self._lock:
            self._queues.discard(q)

    def broadcast(self, code: str) -> None:
        with self._lock:
            targets = list(self._queues)
        for q in targets:
            q.put(code)


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".json": "application/json; charset=utf-8",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".vrm": "application/octet-stream",
    }.get(suffix, "application/octet-stream")


class NovaWebHandler(BaseHTTPRequestHandler):
    server_version = "NovaAIWeb/1.0"

    # Set on the server instance in serve().
    api: webgui.Api
    clients: _SseClients

    def log_message(self, format: str, *args: object) -> None:  # quieter logs
        return

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path in {"/", "/index.html"}:
            self._serve_index()
            return
        if path == "/events":
            self._serve_events()
            return
        if path.startswith("/uploads/"):
            name = Path(path[len("/uploads/"):]).name  # strip traversal
            self._serve_file(AVATAR_UPLOADS_DIR / name)
            return
        # Anything else: serve from the static dir (logo, avatar.html, etc.).
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR.resolve() in target.parents or target == STATIC_DIR.resolve():
            self._serve_file(target)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _serve_index(self) -> None:
        index_path = STATIC_DIR / "index.html"
        try:
            html = index_path.read_text(encoding="utf-8")
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "UI not found")
            return
        # Inject the bridge shim as the first thing inside <head> so it runs
        # before the frontend's own scripts look for window.pywebview.
        lower = html.lower()
        idx = lower.find("<head>")
        if idx != -1:
            insert_at = idx + len("<head>")
            html = html[:insert_at] + _BRIDGE_SHIM + html[insert_at:]
        else:
            html = _BRIDGE_SHIM + html
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = self.clients.register()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    code = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # keepalive
                    self.wfile.flush()
                    continue
                payload = "data: " + json.dumps(code) + "\n\n"
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # browser disconnected
        finally:
            self.clients.unregister(q)

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            content = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to read file")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _guess_content_type(path))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/call":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            length = 0
        body = self.rfile.read(length) if length > 0 else b""

        try:
            request = json.loads(body or b"{}")
            method = request.get("method")
            args = request.get("args") or []
        except Exception:
            self._send_json({"error": "Invalid request body"}, HTTPStatus.BAD_REQUEST)
            return

        if (
            not isinstance(method, str)
            or method.startswith("_")
            or method in _BLOCKED_METHODS
        ):
            self._send_json(
                {"error": f"Unknown method: {method}"}, HTTPStatus.NOT_FOUND
            )
            return

        fn = getattr(self.api, method, None)
        if not callable(fn):
            self._send_json(
                {"error": f"Unknown method: {method}"}, HTTPStatus.NOT_FOUND
            )
            return

        try:
            result = fn(*args)
            self._send_json({"result": result})
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"error": str(exc)})

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        try:
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        except Exception:
            data = json.dumps({"error": "Result not serializable"}).encode("utf-8")
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


def _local_ip() -> str:
    """Best-effort LAN IP so we can print a reachable URL (no traffic sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host if host is not None else os.getenv("NOVA_WEB_HOST", DEFAULT_HOST)
    if port is None:
        try:
            port = int(os.getenv("NOVA_WEB_PORT", str(DEFAULT_PORT)))
        except ValueError:
            port = DEFAULT_PORT

    ensure_runtime_dirs()

    clients = _SseClients()
    # Route every Api._js(code) push to all connected browsers.
    webgui._emit_js = clients.broadcast

    api = webgui.Api()

    handler_attrs = {"api": api, "clients": clients}
    handler_cls = type("NovaWebHandlerBound", (NovaWebHandler,), handler_attrs)

    httpd = ThreadingHTTPServer((host, port), handler_cls)
    httpd.daemon_threads = True

    shown_host = _local_ip() if host in {"0.0.0.0", "::"} else host
    print("NovaAI web UI is running (headless mode).")
    print(f"  Open in a browser on your network:  http://{shown_host}:{port}")
    if host in {"0.0.0.0", "::"}:
        print(f"  Local:                              http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down NovaAI web UI...")
    finally:
        httpd.shutdown()
        httpd.server_close()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
