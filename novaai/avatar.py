from __future__ import annotations

import json
import os
import re
import socket
import socketserver
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

try:
    import websockets

    try:
        # Removed from the top-level namespace in websockets >= 14; used here
        # only as a type annotation, so fall back to ``object`` when absent.
        from websockets import WebSocketServerProtocol
    except ImportError:  # pragma: no cover
        WebSocketServerProtocol = object
except ImportError:  # pragma: no cover
    websockets = None
    WebSocketServerProtocol = object

from .paths import AVATAR_UPLOADS_DIR, MMD_DIR, ROOT_DIR, STATIC_DIR

# Generous cap for VRM uploads (they can be tens of MB).
MAX_UPLOAD_BYTES = 256 * 1024 * 1024


def _local_ip() -> str:
    """Best-effort LAN IP so we can show a reachable URL (no traffic sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def _extract_boundary(content_type: str) -> str | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            return part[len("boundary="):].strip().strip('"')
    return None


def _parse_first_file(body: bytes, boundary: str) -> tuple[str | None, bytes | None]:
    """Extract the first file part (filename + bytes) from a multipart body.

    A small hand-rolled parser so we don't depend on the removed-in-3.13 ``cgi``
    module and can read the whole body ourselves (avoids connection resets on
    large uploads).
    """
    delimiter = b"--" + boundary.encode("utf-8", "ignore")
    for segment in body.split(delimiter):
        segment = segment.lstrip(b"\r\n")
        if not segment or segment in (b"--", b"--\r\n"):
            continue
        if b"\r\n\r\n" not in segment:
            continue
        raw_headers, content = segment.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", "ignore")
        if "filename=" not in headers.lower():
            continue
        match = re.search(r'filename="([^"]*)"', headers, re.IGNORECASE)
        filename = match.group(1) if match else "upload.vrm"
        if content.endswith(b"\r\n"):
            content = content[:-2]
        return filename, content
    return None, None


class AvatarHttpRequestHandler(BaseHTTPRequestHandler):
    server_version = "NovaAIAvatarHTTP/1.0"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]  # ignore query string (e.g. ?transparent=1)
        if path in {"/", "/index.html"}:
            self._serve_file(STATIC_DIR / "avatar.html", content_type="text/html; charset=utf-8")
            return

        if path.startswith("/uploads/"):
            raw_name = unquote(path[len("/uploads/") :])
            # Strip any path components to prevent directory traversal.
            local_path = AVATAR_UPLOADS_DIR / Path(raw_name).name
            self._serve_file(local_path, content_type="application/octet-stream")
            return

        if path.startswith("/mmd/"):
            # Audio needs a real media MIME type or the browser won't play it.
            audio_types = {
                ".mp3": "audio/mpeg", ".wav": "audio/wav",
                ".ogg": "audio/ogg", ".m4a": "audio/mp4",
            }
            parts = [p for p in unquote(path[len("/mmd/") :]).split("/") if p]
            local_path = None
            # /mmd/sets/<id>/<file> — a bundled dance (motion + song + camera).
            if len(parts) == 3 and parts[0] == "sets":
                local_path = MMD_DIR / "sets" / Path(parts[1]).name / Path(parts[2]).name
            # /mmd/<kind>/<name> — legacy loose files.
            elif len(parts) == 2 and parts[0] in {"motion", "audio", "camera"}:
                local_path = MMD_DIR / parts[0] / Path(parts[1]).name
            if local_path is not None:
                ctype = audio_types.get(local_path.suffix.lower(), "application/octet-stream")
                self._serve_file(local_path, content_type=ctype)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")

    def do_POST(self) -> None:
        if self.path != "/upload":
            self._drain_body()
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")
            return

        content_type = self.headers.get("Content-Type", "")
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            content_length = 0

        if "multipart/form-data" not in content_type.lower():
            self._drain_body(content_length)
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected multipart/form-data")
            return
        if content_length <= 0:
            self.send_error(HTTPStatus.LENGTH_REQUIRED, "Missing Content-Length")
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._drain_body(content_length)
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload too large")
            return

        try:
            # Read the entire body first so we never reset the connection by
            # responding before the request is fully consumed.
            body = self._read_exact(content_length)
            boundary = _extract_boundary(content_type)
            if not boundary:
                self.send_error(HTTPStatus.BAD_REQUEST, "Missing multipart boundary")
                return
            filename, file_data = _parse_first_file(body, boundary)
            if not filename or file_data is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "No file uploaded")
                return

            # URL-safe filename (no spaces/special chars) so the /uploads/ GET
            # path matches without encoding mismatches; also blocks traversal.
            base = Path(filename).name
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "upload.vrm"
            target_path = AVATAR_UPLOADS_DIR / safe_name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(file_data)

            url = f"/uploads/{target_path.name}"
            payload = json.dumps(
                {"success": True, "url": url, "name": target_path.name},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.CREATED)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

            if isinstance(self.server, AvatarHttpServer):
                self.server.on_upload(target_path)
        except Exception as exc:  # never leave the socket hanging -> avoids RST
            try:
                self.send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR, f"Upload failed: {exc}"
                )
            except Exception:
                pass

    def _read_exact(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _drain_body(self, length: int | None = None) -> None:
        if length is None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                length = 0
        if length and length <= MAX_UPLOAD_BYTES:
            try:
                self._read_exact(length)
            except Exception:
                pass

    def log_message(self, format: str, *args: object) -> None:
        # Suppress standard HTTP request logging in the GUI.
        pass

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")
            return

        try:
            with path.open("rb") as source:
                content = source.read()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to read file")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class AvatarHttpServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, on_upload: Callable[[Path], None]):
        super().__init__(server_address, RequestHandlerClass)
        self.on_upload = on_upload


class AvatarBridge:
    def __init__(
        self,
        on_vrm_loaded: Callable[[Path], None],
        http_host: str | None = None,
        http_port: int = 8766,
        ws_port: int = 8765,
    ) -> None:
        self.on_vrm_loaded = on_vrm_loaded
        # Bind host follows the launch mode: web mode sets NOVA_BIND_HOST to
        # 0.0.0.0 so the avatar HTTP page and WebSocket bridge are reachable from
        # the LAN, Tailscale, Cloudflare, etc.; the desktop GUI sets it to
        # 127.0.0.1 (local-only). NOVA_AVATAR_HOST overrides just this service.
        if http_host is None:
            http_host = (
                os.getenv("NOVA_AVATAR_HOST")
                or os.getenv("NOVA_BIND_HOST")
                or "0.0.0.0"
            )
        self.http_host = http_host
        self.http_port = http_port
        self.ws_port = ws_port
        self.http_server: AvatarHttpServer | None = None
        self.http_thread: threading.Thread | None = None
        self.ws_thread: threading.Thread | None = None
        self.ws_loop = None
        self.ws_clients: set[WebSocketServerProtocol] = set()
        self.current_avatar_url: str | None = None

    def start(self) -> None:
        AVATAR_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        STATIC_DIR.mkdir(parents=True, exist_ok=True)

        self.http_server = AvatarHttpServer(
            (self.http_host, self.http_port),
            AvatarHttpRequestHandler,
            on_upload=self._handle_upload,
        )
        self.http_server.RequestHandlerClass.server = self.http_server
        self.http_thread = threading.Thread(
            target=self.http_server.serve_forever,
            daemon=True,
            name="NovaAIAvatarHTTP",
        )
        self.http_thread.start()

        if websockets is None:
            print(
                "[NovaAI Avatar] websockets package is not installed. "
                "Install it with: pip install websockets"
            )
            return

        self.ws_loop = __import__("asyncio").new_event_loop()
        self.ws_thread = threading.Thread(
            target=self._run_ws_loop,
            daemon=True,
            name="NovaAIAvatarWS",
        )
        self.ws_thread.start()

    def _run_ws_loop(self) -> None:
        import asyncio

        asyncio.set_event_loop(self.ws_loop)

        async def _serve() -> None:
            # websockets >= 14 builds the server against the *running* loop, so
            # serve() must be awaited from inside the loop (calling it before
            # run_until_complete raises "no running event loop"). Awaiting the
            # returned Server also works on the older (<14) API.
            server = await websockets.serve(
                self._ws_handler, self.http_host, self.ws_port
            )
            try:
                await asyncio.Future()  # run until the loop is stopped
            finally:
                server.close()
                await server.wait_closed()

        try:
            self.ws_loop.run_until_complete(_serve())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[NovaAI Avatar] WebSocket bridge failed to start: {exc}")

    async def _ws_handler(self, websocket: WebSocketServerProtocol) -> None:
        self.ws_clients.add(websocket)
        try:
            await websocket.send(json.dumps({"type": "hello", "status": "connected"}))
            if self.current_avatar_url:
                await websocket.send(
                    json.dumps(
                        {"type": "avatar", "event": "current", "url": self.current_avatar_url}
                    )
                )
            while True:
                await websocket.recv()
        except Exception:
            pass
        finally:
            self.ws_clients.discard(websocket)

    def _handle_upload(self, path: Path) -> None:
        self.on_vrm_loaded(path)

    @staticmethod
    def _to_servable_url(url: str) -> str:
        """Turn any stored VRM reference into a URL the browser can fetch.

        VRMs live in this install's uploads dir (``data/avatars``) and are served
        at ``/uploads/<name>``. A profile may instead carry an absolute path from
        another machine (e.g. an imported profile with a Windows path like
        ``D:\\DEV\\NovaAI\\data\\avatars\\model.vrm``) — the browser can't fetch
        that. Reduce anything that isn't already a web/relative URL to its
        filename and serve it from wherever NovaAI is actually running.
        """
        if not url:
            return url
        u = str(url).strip()
        if u.startswith(("http://", "https://", "/uploads/", "data:", "blob:")):
            return u
        # ntpath.basename splits on BOTH "/" and "\\", so it handles Windows
        # paths even when NovaAI runs on Linux/macOS.
        import ntpath

        base = ntpath.basename(u)
        return f"/uploads/{base}" if base else u

    def publish_avatar(self, url: str) -> None:
        url = self._to_servable_url(url)
        self.current_avatar_url = url
        self._broadcast({"type": "avatar", "event": "load", "url": url})

    def publish_state(self, state: dict[str, object]) -> None:
        self._broadcast({"type": "state", "payload": state})

    def publish_viseme(self, mouth: float) -> None:
        self._broadcast({"type": "viseme", "mouth": float(mouth)})

    def publish_speaking(self, speaking: bool, emotion: str = "neutral") -> None:
        self._broadcast(
            {"type": "speaking", "speaking": bool(speaking), "emotion": emotion}
        )

    def publish_mmd(self, motion_url: str, audio_url: str = "", camera_url: str = "", loop: bool = False) -> None:
        """Tell the overlay to play an MMD dance (motion + optional audio/camera)."""
        self._broadcast({
            "type": "mmd",
            "action": "play",
            "motion": motion_url,
            "audio": audio_url,
            "camera": camera_url,
            "loop": bool(loop),
        })

    def publish_mmd_stop(self) -> None:
        self._broadcast({"type": "mmd", "action": "stop"})

    def publish_dance(self, on: bool) -> None:
        self._broadcast({"type": "dance", "on": bool(on)})

    def publish_reminder(self, reminder: dict[str, object]) -> None:
        self._broadcast({"type": "reminder", "event": "due", "reminder": reminder})

    def _broadcast(self, payload: dict[str, object]) -> None:
        if self.ws_loop is None or websockets is None:
            return
        import asyncio

        async def send_all() -> None:
            if not self.ws_clients:
                return
            data = json.dumps(payload)
            await asyncio.gather(
                *[client.send(data) for client in list(self.ws_clients)],
                return_exceptions=True,
            )

        asyncio.run_coroutine_threadsafe(send_all(), self.ws_loop)

    def _advertised_host(self) -> str:
        """A reachable host for URLs; 0.0.0.0/:: aren't connectable addresses."""
        if self.http_host in {"0.0.0.0", "::", ""}:
            return _local_ip()
        return self.http_host

    def get_frontend_url(self) -> str:
        return f"http://{self._advertised_host()}:{self.http_port}/"

    def get_ws_url(self) -> str:
        return f"ws://{self._advertised_host()}:{self.ws_port}/"
