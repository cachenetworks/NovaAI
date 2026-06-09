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
from urllib.parse import parse_qs, unquote, urlsplit

from . import webgui, webproxy
from .paths import AVATAR_UPLOADS_DIR, STATIC_DIR
from .storage import ensure_runtime_dirs

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8800
# The avatar + earnings overlays get their own dedicated port so OBS / a tunnel
# can point at just the overlays, separate from the dashboard. Override with
# NOVA_OVERLAY_PORT; set it to the same value as the web port to merge them.
DEFAULT_OVERLAY_PORT = 8801

# The avatar bridge is the one sibling merged onto the web port; the Minecraft
# live view keeps its own port. These mirror AvatarBridge's defaults and are
# proxied over localhost so only the web port itself is public.
AVATAR_HTTP_PORT = 8766
AVATAR_WS_PORT = 8765

# GET paths forwarded to the avatar HTTP server (8766). The overlay page itself
# is served locally; only its media/upload routes live on the avatar bridge.
_AVATAR_GET_PREFIXES = ("/mmd/",)
_AVATAR_GET_EXACT = {"/tts-audio", "/browser-audio"}

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

    # Set on the bound handler subclass in serve().
    api: webgui.Api
    clients: _SseClients
    avatar_http: tuple[str, int]
    avatar_ws: tuple[str, int]

    def log_message(self, format: str, *args: object) -> None:  # quieter logs
        return

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        # WebSocket handshakes arrive as a GET with an Upgrade header. Bridge them
        # to the right sibling so the browser only ever speaks to this one origin
        # (wss://host/avatar-ws instead of the old wss://host:8765).
        if webproxy.is_ws_upgrade(self):
            self._route_ws()
            return

        path = unquote(self.path.split("?", 1)[0])
        if path in {"/", "/index.html"}:
            self._serve_index()
            return
        if path == "/events":
            self._serve_events()
            return
        if path in {"/avatar", "/avatar/"}:
            # The avatar overlay page. Served here so it shares this origin; its
            # WebSocket and media then resolve to /avatar-ws and /tts-audio etc.
            self._serve_file(STATIC_DIR / "avatar.html")
            return
        if path.startswith("/uploads/"):
            name = Path(path[len("/uploads/"):]).name  # strip traversal
            self._serve_file(AVATAR_UPLOADS_DIR / name)
            return
        if path in {"/overlay/earnings", "/earnings"}:
            self._serve_file(STATIC_DIR / "earnings.html")
            return
        # Avatar bridge media (TTS/singing audio, MMD dance assets) -> 8766.
        if path in _AVATAR_GET_EXACT or path.startswith(_AVATAR_GET_PREFIXES):
            webproxy.proxy_http(self, self.avatar_http, self.path)
            return
        # Anything else: serve from the static dir (logo, avatar.html, etc.).
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR.resolve() in target.parents or target == STATIC_DIR.resolve():
            self._serve_file(target)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _route_ws(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/avatar-ws", "/avatar-ws/"}:
            webproxy.proxy_ws(self, self.avatar_ws, "/")
            return
        # The Minecraft live view keeps its own port, so no other WS lives here.
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

    def _handle_stream_webhook(self) -> None:
        """Ingress for stream alert events from any source.

        POST /webhook/stream?source=streamlabs|streamelements|twitch|webhook
        Body is the platform's JSON payload (or a simple {type,user,amount,...}
        for the generic webhook). Lets Twitch EventSub forwarders, Tangia,
        sound-alert tools, or any bot drive NovaAI's reactions + earnings.
        """
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        # Optional shared-secret check so randoms can't spoof alerts.
        secret = os.getenv("NOVA_WEBHOOK_SECRET", "")
        if secret:
            provided = self.headers.get("X-Nova-Secret", "")
            qs = parse_qs(urlsplit(self.path).query)
            if provided != secret and (qs.get("secret", [""])[0] != secret):
                self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
                return
        try:
            payload = json.loads(body or b"{}")
        except Exception:
            self._send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        source = parse_qs(urlsplit(self.path).query).get("source", ["webhook"])[0]
        try:
            result = self.api.ingest_stream_event(payload, source)
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
        try:
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # browser disconnected mid-transfer; nothing to do

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self) -> None:
        raw_path = self.path.split("?", 1)[0]
        if raw_path == "/webhook/stream":
            self._handle_stream_webhook()
            return
        # NOTE: the public /upload proxy was removed on purpose. VRM uploads now
        # go through the operator dashboard (/api/call -> upload_vrm) so a viewer
        # hitting the public avatar overlay origin can't swap the model.
        if raw_path != "/api/call":
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


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host if host is not None else os.getenv("NOVA_WEB_HOST", DEFAULT_HOST)
    if port is None:
        try:
            port = int(os.getenv("NOVA_WEB_PORT", str(DEFAULT_PORT)))
        except ValueError:
            port = DEFAULT_PORT

    # The avatar overlay (page + media on 8766, WebSocket on 8765) is now reached
    # *through* this web port via proxy paths (/avatar, /avatar-ws, /tts-audio,
    # …), so one origin — one Cloudflare tunnel hostname on 443 — serves it all.
    # That means the avatar bridge only needs to listen on localhost; this port
    # is the only public one.
    os.environ.setdefault("NOVA_BIND_HOST", "127.0.0.1")
    # The Minecraft live view keeps its own port, reachable as before — pin it to
    # all interfaces so it stays public even though the avatar went localhost
    # (minecraft.py otherwise inherits NOVA_BIND_HOST). Override with MC_VIEWER_HOST.
    os.environ.setdefault("MC_VIEWER_HOST", "0.0.0.0")

    avatar_http_port = _int_env("NOVA_AVATAR_HTTP_PORT", AVATAR_HTTP_PORT)
    avatar_ws_port = _int_env("NOVA_AVATAR_WS_PORT", AVATAR_WS_PORT)
    overlay_port = _int_env("NOVA_OVERLAY_PORT", DEFAULT_OVERLAY_PORT)

    ensure_runtime_dirs()

    clients = _SseClients()
    # Route every Api._js(code) push to all connected browsers.
    webgui._emit_js = clients.broadcast

    api = webgui.Api()

    handler_attrs = {
        "api": api,
        "clients": clients,
        "avatar_http": ("127.0.0.1", avatar_http_port),
        "avatar_ws": ("127.0.0.1", avatar_ws_port),
    }
    handler_cls = type("NovaWebHandlerBound", (NovaWebHandler,), handler_attrs)

    httpd = ThreadingHTTPServer((host, port), handler_cls)
    httpd.daemon_threads = True

    # The overlays (avatar page + WebSocket + media, earnings) get their own port
    # so OBS / a tunnel can target just them, independent of the dashboard. The
    # same handler serves every route, so 8801 answers the overlay paths directly.
    # Setting NOVA_OVERLAY_PORT == the web port merges them back onto one port.
    overlay_httpd = None
    if overlay_port != port:
        try:
            overlay_httpd = ThreadingHTTPServer((host, overlay_port), handler_cls)
            overlay_httpd.daemon_threads = True
            threading.Thread(target=overlay_httpd.serve_forever, daemon=True).start()
        except OSError as exc:
            print(f"  (overlay port {overlay_port} unavailable: {exc} — "
                  "overlays remain on the web port)")
            overlay_httpd = None

    shown_host = _local_ip() if host in {"0.0.0.0", "::"} else host
    overlay_host = shown_host
    overlay_shown = overlay_port if overlay_httpd is not None else port
    print("NovaAI web UI is running (headless mode).")
    print(f"  Open in a browser on your network:  http://{shown_host}:{port}")
    if host in {"0.0.0.0", "::"}:
        print(f"  Local:                              http://127.0.0.1:{port}")
    print(f"  Dashboard:         http://{shown_host}:{port}")
    print(f"  Overlays live on their own port ({overlay_shown}):")
    print(f"    avatar overlay   http://{overlay_host}:{overlay_shown}/avatar")
    print(f"    avatar socket    ws://{overlay_host}:{overlay_shown}/avatar-ws")
    print(f"    earnings overlay http://{overlay_host}:{overlay_shown}/overlay/earnings")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down NovaAI web UI...")
    finally:
        httpd.shutdown()
        httpd.server_close()
        if overlay_httpd is not None:
            overlay_httpd.shutdown()
            overlay_httpd.server_close()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
