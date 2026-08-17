"""Small local HTTP API and static desktop viewer host."""

from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .project import Project, ProjectError
from .providers import ConsentRequired, MeshyImageTo3D, ProviderError, provider_catalog
from .unity import UnityValidator
from .workers import BlenderSandbox, WorkerError, WorkerUnavailable


MAX_BODY = 1024 * 1024


class Open3DHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], project: Project, web_root: Path):
        super().__init__(address, _Handler)
        self.project = project
        self.web_root = web_root.resolve()
        self.lock = threading.RLock()


class _Handler(BaseHTTPRequestHandler):
    server: Open3DHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        # Keep the local server quiet; structured errors are returned to clients.
        return

    def _send(self, status: int, value: Any, *, content_type: str = "application/json") -> None:
        if isinstance(value, bytes):
            payload = value
        elif content_type == "application/json":
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        else:
            payload = str(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"error": message})

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_BODY:
            raise ProjectError("request body is too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectError("request body must be JSON") from exc
        if not isinstance(value, dict):
            raise ProjectError("request body must be an object")
        return value

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            with self.server.lock:
                if path == "/api/health":
                    return self._send(HTTPStatus.OK, {"status": "PASS", "project_id": self.server.project.current()["project_id"]})
                if path == "/api/inspect":
                    return self._send(HTTPStatus.OK, self.server.project.inspect())
                if path == "/api/validate":
                    return self._send(HTTPStatus.OK, self.server.project.validate())
                if path == "/api/history":
                    return self._send(HTTPStatus.OK, self.server.project.history())
                if path == "/api/providers":
                    return self._send(HTTPStatus.OK, provider_catalog())
                if path == "/api/artifact/current":
                    data = self.server.project.store.read_bytes(self.server.project.current()["glb_artifact"])
                    return self._send(HTTPStatus.OK, data, content_type="model/gltf-binary")
            self._static(path)
        except (ProjectError, OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            body = self._body()
            with self.server.lock:
                if path == "/api/edit-part":
                    scales = {axis: body[key] for axis, key in (("x", "scale_x"), ("y", "scale_y"), ("z", "scale_z")) if key in body}
                    value = self.server.project.edit_part(body["part_id"], scales, idempotency_key=body.get("idempotency_key"))
                elif path == "/api/rollback":
                    value = self.server.project.rollback(body["checkpoint_id"])
                elif path == "/api/provider/meshy":
                    value = MeshyImageTo3D().generate(self.server.project, image_url=body["image_url"], consent=body.get("consent") is True, timeout=float(body.get("timeout", 900)))
                elif path == "/api/blender/run":
                    value = BlenderSandbox(self.server.project.root).run(body["job"], timeout=float(body.get("timeout", 300)), allow_unsafe=body.get("allow_unsafe") is True)
                elif path == "/api/unity/validate":
                    unity_value = Path(body["unity_project"])
                    unity_project = (self.server.project.root / unity_value if not unity_value.is_absolute() else unity_value).resolve()
                    unity_project.relative_to(self.server.project.root)
                    value = UnityValidator(unity_project, unity=body.get("unity", "unity-editor")).run(body["input_asset"], body.get("output_report", ".open3d/unity-report.json"), timeout=float(body.get("timeout", 600)))
                else:
                    return self._error(HTTPStatus.NOT_FOUND, "route not found")
            self._send(HTTPStatus.OK, value)
        except ConsentRequired as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except WorkerUnavailable as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        except (KeyError, TypeError, ValueError, ProjectError, ProviderError, WorkerError, OSError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def _static(self, path: str) -> None:
        relative = Path(path.lstrip("/"))
        candidate = (self.server.web_root / relative).resolve()
        try:
            candidate.relative_to(self.server.web_root)
        except ValueError:
            return self._error(HTTPStatus.NOT_FOUND, "file not found")
        if not candidate.is_file():
            candidate = self.server.web_root / "index.html"
        if not candidate.is_file():
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, "viewer bundle is missing; run npm run build in web/")
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, candidate.read_bytes(), content_type=content_type)


def serve(project: Project, *, host: str = "127.0.0.1", port: int = 8289, web_root: str | Path | None = None) -> None:
    root = Path(web_root) if web_root else Path(__file__).resolve().parents[1] / "web" / "dist"
    server = Open3DHTTPServer((host, port), project, root)
    print(f"Open3D viewer: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
