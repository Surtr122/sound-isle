"""Local HTTP server and JSON API for Sound & Form."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import posixpath
import re
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

from . import APP_NAME, APP_NAME_EN, __version__
from .config import load_config, remember_library, remember_workspace
from .folder_picker import pick_folder, reveal
from .library import LibraryError
from .workspace import Workspace

LOGGER = logging.getLogger("soundisle")

_WEB_ROOT = Path(__file__).resolve().parent / "web"

_AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_MODEL_MIME = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".fbx": "application/octet-stream",
    ".obj": "text/plain; charset=utf-8",
    ".bin": "application/octet-stream",
}

_STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8",
}

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' data: blob:; "
    "base-uri 'none'; "
    "form-action 'none'"
)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class AppState:
    def __init__(self, root: Optional[str] = None):
        self._lock = threading.RLock()
        self._open_lock = threading.Lock()
        self.library: Optional[Workspace] = None
        self.error = ""
        paths: List[str] = []
        if root:
            paths = [root]
        else:
            config = load_config()
            candidates = list(config.get("workspace_sources") or [])
            fallback = config.get("last_library")
            if fallback and fallback not in candidates:
                candidates.append(fallback)
            paths = [item for item in candidates if Path(item).is_dir()]
        if paths:
            try:
                library = Workspace(paths)
            except LibraryError as exc:
                self.error = str(exc)
            else:
                self.library = library
                try:
                    remember_workspace(library.paths)
                except OSError:
                    pass

    def set_library(self, path: str) -> Dict[str, Any]:
        path = (path or "").strip().strip('"')
        if not path:
            raise ApiError(400, "请选择一个素材文件夹。")
        with self._open_lock:
            try:
                library = Workspace([path])
            except LibraryError as exc:
                raise ApiError(400, str(exc)) from None
            try:
                remember_workspace(library.paths)
            except OSError:
                pass
            with self._lock:
                self.library = library
                self.error = ""
        return self.payload()

    def add_source(self, path: str) -> Dict[str, Any]:
        path = (path or "").strip().strip('"')
        if not path:
            raise ApiError(400, "请选择一个素材文件夹。")
        with self._open_lock:
            with self._lock:
                library = self.library
            if library is None:
                return self.set_library(path)
            try:
                library.add_source(path)
            except LibraryError as exc:
                raise ApiError(400, str(exc)) from None
            try:
                remember_workspace(library.paths)
            except OSError:
                pass
            self.error = ""
        return self.payload()

    def remove_source(self, source_id: str) -> Dict[str, Any]:
        with self._open_lock:
            with self._lock:
                library = self.library
            if library is None:
                raise ApiError(409, "还没有打开素材文件夹。")
            try:
                library.remove_source(str(source_id or ""))
            except LibraryError as exc:
                raise ApiError(400, str(exc)) from None
            try:
                remember_workspace(library.paths)
            except OSError:
                pass
        return self.payload()

    def have_library(self) -> Workspace:
        with self._lock:
            library = self.library
        if library is None:
            raise ApiError(409, "还没有打开素材文件夹。")
        return library

    def payload(self) -> Dict[str, Any]:
        with self._lock:
            library = self.library
            initial_error = self.error
        snapshot = library.snapshot() if library else None
        return {
            "app": {
                "name": APP_NAME,
                "name_en": APP_NAME_EN,
                "version": __version__,
                "platform": sys.platform,
            },
            "library": snapshot,
            "recents": _recent_payload(library.root if library else None),
            "error": initial_error,
        }


def _recent_payload(current: Optional[Path]) -> List[Dict[str, Any]]:
    config = load_config()
    result: List[Dict[str, Any]] = []
    current_key = os.path.normcase(str(current)) if current else ""
    for raw in config.get("recent_libraries", []):
        path = Path(raw)
        key = os.path.normcase(str(path))
        result.append(
            {
                "path": raw,
                "name": path.name or raw,
                "exists": path.is_dir(),
                "current": bool(current_key and key == current_key),
            }
        )
    return result


class SoundIsleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], state: AppState, quiet: bool = False):
        self.state = state
        self.quiet = quiet
        super().__init__(address, SoundIsleHandler)


class SoundIsleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SoundIsle/" + __version__

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        if not getattr(self.server, "quiet", False):
            LOGGER.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json_safe(self, payload: Any, status: int = 200) -> None:
        try:
            self._send_json(payload, status=status)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _handle(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path.startswith("/api/"):
                self._handle_api(path)
            elif self.command in ("GET", "HEAD"):
                self._serve_static(path)
            else:
                self._method_not_allowed()
        except ApiError as exc:
            self._send_json_safe({"error": exc.message}, status=exc.status)
        except LibraryError as exc:
            self._send_json_safe({"error": str(exc)}, status=400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            LOGGER.error("Unhandled request error:\n%s", traceback.format_exc())
            self._send_json_safe({"error": "服务器内部错误，请查看终端日志。"}, status=500)

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, HEAD, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self._end_headers()
        self.end_headers()

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, HEAD, POST")
        self.send_header("Content-Length", "0")
        self._end_headers()
        self.end_headers()

    def _end_headers(self) -> None:
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        port = self.server.server_address[1]
        allowed = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"http://[::1]:{port}",
        }
        if origin not in allowed:
            raise ApiError(403, "只接受本机页面的请求。")

    def _read_json(self) -> Dict[str, Any]:
        self._check_origin()
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "请求需要 application/json。")
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise ApiError(400, "请求长度无效。") from None
        if length > 1_000_000:
            raise ApiError(413, "请求内容过大。")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "请求内容不是有效的 JSON。") from None
        if not isinstance(value, dict):
            raise ApiError(400, "请求内容应为 JSON 对象。")
        return value

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._end_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def _handle_api(self, path: str) -> None:
        state: AppState = self.server.state  # type: ignore[attr-defined]
        method = self.command

        if method in ("GET", "HEAD"):
            if path == "/api/state":
                self._send_json(state.payload())
                return
            if path == "/api/health":
                self._send_json({"ok": True, "version": __version__})
                return
            if path.startswith("/api/stream/"):
                self._stream(state, path[len("/api/stream/") :])
                return
            if path.startswith("/api/cover/"):
                self._cover(state, path[len("/api/cover/") :])
                return
            if path.startswith("/api/thumb/"):
                self._thumb(state, path[len("/api/thumb/") :])
                return
            if path.startswith("/api/model/"):
                self._model(state, path[len("/api/model/") :])
                return
            if path.startswith("/api/inspect/"):
                self._inspect(state, path[len("/api/inspect/") :])
                return
            if path.startswith("/api/motion/"):
                self._motion(state, path[len("/api/motion/") :])
                return
            raise ApiError(404, "接口不存在。")

        if method != "POST":
            self._method_not_allowed()
            return

        body = self._read_json()
        if path == "/api/library/open":
            payload = state.set_library(str(body.get("path") or ""))
            self._send_json(payload)
            return
        if path == "/api/library/add":
            payload = state.add_source(str(body.get("path") or ""))
            self._send_json(payload)
            return
        if path == "/api/library/remove":
            payload = state.remove_source(str(body.get("source_id") or ""))
            self._send_json(payload)
            return
        if path == "/api/library/pick":
            library = state.library
            initial = str(body.get("initial") or (str(library.root) if library else ""))
            choice = pick_folder(initial_dir=initial)
            self._send_json(
                {
                    "path": choice.path or "",
                    "cancelled": choice.cancelled,
                    "error": choice.error,
                }
            )
            return
        if path == "/api/library/rescan":
            library = state.have_library()
            source_id = str(body.get("source_id") or "")
            snapshot = library.rescan(source_id)
            message = "已重新读取这个文件夹。" if source_id else "已重新读取文件夹。"
            self._send_json({"library": snapshot, "message": message})
            return
        if path == "/api/missing/dismiss":
            library = state.have_library()
            source_id = str(body.get("source_id") or "")
            paths = body.get("paths") or []
            snapshot = library.dismiss_missing(source_id, paths)
            self._send_json({"library": snapshot, "message": "已从缺失列表移除。"})
            return
        if path == "/api/metadata/export":
            library = state.have_library()
            self._send_json({"metadata": library.export_metadata()})
            return
        if path == "/api/metadata/import":
            library = state.have_library()
            result = library.import_metadata(body.get("metadata"))
            self._send_json(
                {
                    "library": result["library"],
                    "message": f"已导入 {result['imported']} 项资料；跳过 {result['skipped']} 项。",
                }
            )
            return
        if path == "/api/tags/add":
            library = state.have_library()
            ids = body.get("ids") or []
            tags = body.get("tags") or []
            if not isinstance(tags, list):
                raise ApiError(400, "tags 必须是数组。")
            snapshot = library.add_tags(ids, tags)
            self._send_json({"library": snapshot, "message": f"已为 {len(ids)} 项素材添加标签。"})
            return
        if path == "/api/tags/remove":
            library = state.have_library()
            ids = body.get("ids") or []
            tag = str(body.get("tag") or "")
            snapshot = library.remove_tag(ids, tag)
            self._send_json({"library": snapshot, "message": f"已移除标签「{tag}」。"})
            return
        if path == "/api/tags/set":
            library = state.have_library()
            track_id = str(body.get("id") or "")
            tags = body.get("tags") or []
            if not isinstance(tags, list):
                raise ApiError(400, "tags 必须是数组。")
            snapshot = library.set_tags(track_id, tags)
            self._send_json({"library": snapshot, "message": "标签已保存。"})
            return
        if path == "/api/categories/create":
            library = state.have_library()
            category = library.create_category(
                body.get("name"), body.get("accent", ""), body.get("parent", "")
            )
            label = "小类" if category.get("parent") else "分类"
            self._send_json(
                {
                    "library": library.snapshot(),
                    "category": category,
                    "message": f"已创建{label}「{category['name']}」。",
                }
            )
            return
        if path == "/api/category/set":
            library = state.have_library()
            snapshot = library.set_category(body.get("ids") or [], body.get("category") or "auto")
            self._send_json({"library": snapshot, "message": "分类已更新。"})
            return
        if path == "/api/memberships/set":
            library = state.have_library()
            snapshot = library.set_memberships(body.get("ids") or [], body.get("categories") or [])
            self._send_json({"library": snapshot, "message": "分类归属已更新。"})
            return
        if path == "/api/category/remove":
            library = state.have_library()
            snapshot = library.remove_from_category(body.get("ids") or [], body.get("category") or "")
            self._send_json({"library": snapshot, "message": "已从这个分类移除。"})
            return
        if path == "/api/subcategory/set":
            library = state.have_library()
            snapshot = library.set_subcategory(body.get("ids") or [], body.get("subcategory") or "auto")
            self._send_json({"library": snapshot, "message": "音效细类已更新。"})
            return
        if path == "/api/favorites":
            library = state.have_library()
            ids = body.get("ids") or []
            favorite = bool(body.get("favorite"))
            snapshot = library.set_favorite(ids, favorite)
            message = "已加入收藏。" if favorite else "已取消收藏。"
            self._send_json({"library": snapshot, "message": message})
            return
        if path == "/api/rename/preview":
            library = state.have_library()
            plan = library.preview_rename(
                body.get("ids") or [],
                str(body.get("name") or ""),
                body.get("start", 1),
                body.get("digits", 2),
                str(body.get("separator", " ")),
            )
            self._send_json({"plan": plan})
            return
        if path == "/api/rename/apply":
            library = state.have_library()
            result = library.rename(
                body.get("ids") or [],
                str(body.get("name") or ""),
                body.get("start", 1),
                body.get("digits", 2),
                str(body.get("separator", " ")),
            )
            if result.get("ok"):
                result["library"] = library.snapshot()
                renamed = result.get("renamed")
                if renamed is None:
                    renamed = (result.get("plan") or {}).get("renamed", 0)
                result["message"] = f"已重命名 {int(renamed or 0)} 个文件。"
            self._send_json(result)
            return
        if path == "/api/reveal":
            library = state.have_library()
            track_id = str(body.get("id") or "")
            if track_id:
                track = library.get_track(track_id)
                if not track:
                    raise ApiError(404, "素材不存在。")
                reveal(str(track["_path"]), select_file=True)
            else:
                reveal(str(library.root))
            self._send_json({"ok": True})
            return

        raise ApiError(404, "接口不存在。")

    # ------------------------------------------------------------------
    # Audio streaming
    # ------------------------------------------------------------------

    def _stream(self, state: AppState, track_id: str) -> None:
        library = state.have_library()
        path = library.stream_path(track_id)
        if path is None:
            raise ApiError(404, "找不到这个音频文件。")
        try:
            size = path.stat().st_size
        except OSError:
            raise ApiError(404, "找不到这个音频文件。") from None
        mime = _AUDIO_MIME.get(path.suffix.lower(), "application/octet-stream")
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self._range_not_satisfiable(size)
                return
            first, last = match.group(1), match.group(2)
            if not first and not last:
                self._range_not_satisfiable(size)
                return
            if not first:
                suffix_length = int(last)
                if suffix_length <= 0:
                    self._range_not_satisfiable(size)
                    return
                start = max(0, size - suffix_length)
                end = size - 1
            else:
                start = int(first)
                end = int(last) if last else size - 1
            if start >= size or end < start:
                self._range_not_satisfiable(size)
                return
            end = min(end, size - 1)
            status = 206

        length = end - start + 1 if size else 0
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Disposition", "inline")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._end_headers()
        self.end_headers()
        if self.command == "HEAD" or length <= 0:
            return
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _range_not_satisfiable(self, size: int) -> None:
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self._end_headers()
        self.end_headers()

    def _cover(self, state: AppState, track_id: str) -> None:
        library = state.have_library()
        cover = library.cover(track_id)
        if cover is None:
            raise ApiError(404, "这件素材没有内嵌封面。")
        mime, data = cover
        self.send_response(200)
        self.send_header("Content-Type", mime or "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self._end_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _thumb(self, state: AppState, track_id: str) -> None:
        library = state.have_library()
        path = library.thumb_path(track_id)
        if path is None:
            raise ApiError(404, "这个资产没有可用的缩略图。")
        try:
            data = path.read_bytes()
        except OSError:
            raise ApiError(404, "缩略图读取失败。") from None
        mime = _IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self._end_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _model(self, state: AppState, track_id: str) -> None:
        library = state.have_library()
        path = library.asset_path(track_id)
        if path is None:
            raise ApiError(404, "模型文件不存在。")
        suffix = path.suffix.lower()
        mime = _MODEL_MIME.get(suffix)
        if mime is None:
            raise ApiError(415, "这个文件不能用于 3D 预览。")
        try:
            size = path.stat().st_size
            if size > 512 * 1024 * 1024:
                raise ApiError(413, "模型文件超过 512 MB，暂不支持预览。")
            data = path.read_bytes()
        except OSError:
            raise ApiError(404, "模型文件读取失败。") from None
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("Content-Disposition", 'inline; filename="model' + suffix + '"')
        self._end_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _inspect(self, state: AppState, track_id: str) -> None:
        library = state.have_library()
        asset = library.inspect(track_id)
        if asset is None:
            raise ApiError(404, "资产不存在。")
        self._send_json({"asset": asset})

    def _motion(self, state: AppState, track_id: str) -> None:
        library = state.have_library()
        track = library.get_track(track_id)
        if not track or track.get("kind") != "asset":
            raise ApiError(404, "动作素材不存在。")
        motion = library.motion(track_id)
        if motion is None:
            raise ApiError(422, "这个动作无法解析出骨骼预览，可能没有蒙皮或动画数据。")
        self._send_json({"motion": motion, "track": {"id": track["id"], "title": track["title"]}})

    # ------------------------------------------------------------------
    # Static files
    # ------------------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        if path.endswith("/"):
            path += "index.html"
        relative = posixpath.normpath(path).lstrip("/")
        if relative.startswith("../") or relative in ("..", ".") or "\x00" in relative:
            raise ApiError(404, "页面不存在。")
        target = (_WEB_ROOT / relative).resolve()
        try:
            target.relative_to(_WEB_ROOT)
        except ValueError:
            raise ApiError(404, "页面不存在。") from None
        if not target.is_file():
            raise ApiError(404, "页面不存在。")
        try:
            data = target.read_bytes()
        except OSError:
            raise ApiError(404, "页面不存在。") from None
        mime = _STATIC_MIME.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        if target.suffix.lower() == ".html":
            self.send_header("Content-Security-Policy", _CSP)
        self._end_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def create_server(
    root: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    quiet: bool = False,
) -> Tuple[SoundIsleServer, AppState]:
    state = AppState(root)
    server = SoundIsleServer((host, port), state, quiet=quiet)
    return server, state


def serve(
    root: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    quiet: bool = False,
) -> None:
    server, _ = create_server(root=root, host=host, port=port, quiet=quiet)
    actual_port = server.server_address[1]
    LOGGER.info("Sound & Form listening on http://%s:%s", host, actual_port)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
