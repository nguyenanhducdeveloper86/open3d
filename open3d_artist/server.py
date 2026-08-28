"""Small local HTTP API and static desktop viewer host."""

from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .agent_bridge import AGENTS, agent_catalog, agent_pool_status, run_agent_build, run_agent_plan
from .project import Project, ProjectError
from .production import REQUIRED_VIEWS, production_agent_receipt, production_state, promote_production, repair_production, run_production, verify_release
from .providers import All2ApiImageGenerator, ConsentRequired, MeshyImageTo3D, MeshyPipeline, ProviderError, provider_catalog
from .unity import UnityValidator
from .workers import BlenderSandbox, WorkerError, WorkerUnavailable


# Four compressed multi-view references plus the JSON envelope stay bounded.
MAX_BODY = 4 * 1024 * 1024
MAX_VISUAL_BUILD_ATTEMPTS = 3


def _visual_repair_prompt(judge: dict[str, Any]) -> str:
    evidence = {key: judge.get(key, []) for key in ("mismatched_components", "next_actions", "repair_components", "freeze_components")}
    return "\n\nTARGETED VISUAL REPAIR PASS: keep the frozen/matched components unchanged. Repair the following reference mismatches in Blender geometry and rerun the full pipeline; do not solve them with color-only edits, flat decals, or metadata claims:\n" + json.dumps(evidence, ensure_ascii=False, sort_keys=True)[:7000]


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
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
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
                if path == "/api/versions":
                    asset_id = parse_qs(parsed.query).get("asset_id", [None])[0]
                    return self._send(HTTPStatus.OK, self.server.project.asset_versions(asset_id))
                if path == "/api/workspace":
                    return self._send(HTTPStatus.OK, self.server.project.workspace())
                if path == "/api/providers":
                    return self._send(HTTPStatus.OK, provider_catalog())
                if path == "/api/agents":
                    return self._send(HTTPStatus.OK, agent_catalog())
                if path == "/api/agent-pool":
                    return self._send(HTTPStatus.OK, agent_pool_status())
                if path == "/api/artifact/current":
                    data = self.server.project.store.read_bytes(self.server.project.current()["glb_artifact"])
                    return self._send(HTTPStatus.OK, data, content_type="model/gltf-binary")
                if path.startswith("/api/preview/"):
                    view = path.rsplit("/", 1)[-1]
                    artifact = self.server.project.current().get("preview_artifacts", {}).get(view)
                    if not artifact:
                        return self._error(HTTPStatus.NOT_FOUND, "preview unavailable")
                    return self._send(HTTPStatus.OK, self.server.project.store.read_bytes(artifact), content_type="image/png")
                path_parts = path.split("/")
                if len(path_parts) == 4 and path_parts[1:3] == ["api", "assets"]:
                    return self._send(HTTPStatus.OK, self.server.project.workspace_asset(path_parts[3]))
                if len(path_parts) == 5 and path_parts[1] == "api" and path_parts[2] == "assets" and path_parts[4] == "artifact":
                    asset = self.server.project.workspace_asset(path_parts[3])
                    data = self.server.project.store.read_bytes(asset["glb_artifact"])
                    return self._send(HTTPStatus.OK, data, content_type="model/gltf-binary")
                if len(path_parts) == 5 and path_parts[1:3] == ["api", "assets"] and path_parts[4] == "versions":
                    return self._send(HTTPStatus.OK, self.server.project.asset_versions(path_parts[3]))
                if path == "/api/production/state":
                    return self._send(HTTPStatus.OK, production_state(self.server.project))
                if path == "/api/production/release":
                    return self._send(HTTPStatus.OK, {"release": production_state(self.server.project)["release"], "verification": verify_release(self.server.project)})
                if path.startswith("/api/production/render/"):
                    view = path.rsplit("/", 1)[-1]
                    if view not in REQUIRED_VIEWS:
                        return self._error(HTTPStatus.NOT_FOUND, "render not found")
                    artifact = self.server.project.current().get("production_artifacts", {}).get("renders", {}).get(view)
                    if not artifact:
                        return self._error(HTTPStatus.NOT_FOUND, "render unavailable")
                    return self._send(HTTPStatus.OK, self.server.project.store.read_bytes(artifact), content_type="image/png")
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
                elif path == "/api/undo":
                    value = self.server.project.undo()
                elif path == "/api/provider/meshy":
                    value = MeshyImageTo3D().generate(self.server.project, image_url=body["image_url"], consent=body.get("consent") is True, timeout=float(body.get("timeout", 900)))
                elif path == "/api/generation/meshy":
                    image_urls = body.get("image_urls")
                    if image_urls is not None and not isinstance(image_urls, list):
                        raise ProjectError("image_urls must be a list")
                    value = MeshyPipeline().run(self.server.project, asset_id=body["asset_id"], prompt=body["prompt"], mode=body.get("mode", "text"), kind=body.get("kind", "prop"), image_url=body.get("image_url"), image_urls=image_urls, consent=body.get("consent") is True, quality=body.get("quality", "high"), reference_provider=body.get("reference_provider"), timeout=float(body.get("timeout", 900)), poll_interval=float(body.get("poll_interval", 3)))
                    if value.get("status") == "PASS":
                        current = value.get("mutation", {}).get("current", {})
                        instances = self.server.project.workspace().get("scene", {}).get("instances", [])
                        if isinstance(body.get("spawn"), dict) or not any(item.get("asset_id") == current.get("asset_id") for item in instances):
                            value["scene_instance"] = self.server.project.add_scene_instance(current["asset_id"], body.get("spawn"))
                elif path == "/api/generation/all2api-agent":
                    if body.get("consent") is not True:
                        raise ConsentRequired("remote image generation requires explicit consent")
                    agent = body["agent"]
                    if agent not in AGENTS:
                        raise ProjectError(f"agent must be one of {', '.join(AGENTS)}")
                    asset_id = body["asset_id"]
                    user_prompt = body.get("prompt")
                    if not isinstance(user_prompt, str) or not user_prompt.strip():
                        raise ProjectError("prompt is required")
                    prompt = f"Create a new asset with asset_id {asset_id}. {user_prompt.strip()}"
                    reference_prompt = f"Independent concept reference for a Cloudvale production 3D asset {asset_id}: {user_prompt.strip()}. Show one centered full-body three-quarter character/object on a clean studio background. Prefer softcrafted organic volumes, rounded transitions, broad curves, and readable silhouette; no text, UI, watermark, or extra subjects."
                    build_timeout = min(float(body.get("timeout", 900)), 900)
                    supplied_reference = body.get("reference_image")
                    if supplied_reference is not None and not isinstance(supplied_reference, dict):
                        raise ProjectError("reference_image must be an object")
                    reference = supplied_reference or All2ApiImageGenerator().generate(prompt=reference_prompt, quality=body.get("quality", "high"), timeout=build_timeout)
                    attempts = []
                    value = None
                    attempt_prompt = prompt
                    retry_run = None
                    for attempt in range(1, MAX_VISUAL_BUILD_ATTEMPTS + 1):
                        value = run_agent_build(agent, attempt_prompt, self.server.project.root, timeout=build_timeout, reference_image=reference, reference_pipeline="img2threejs", target_asset_id=asset_id, create_asset=True, quality_profile="production", retry_run=retry_run)
                        visual = value.get("visual_judge") if isinstance(value, dict) else None
                        attempts.append({"attempt": attempt, "run": value.get("run"), "status": value.get("status"), "reason": value.get("reason"), "similarity_percent": visual.get("similarity_percent") if isinstance(visual, dict) else None})
                        reason = value.get("reason")
                        if value.get("status") == "PASS" or reason not in {"VISUAL_QA_REPAIR_REQUIRED", "BLENDER_BUILD_FAILED", "BLENDER_PIPELINE_REJECTED", "CONTRACT_REJECTED", "REFERENCE_SPEC_REJECTED", "BUILD_FILES_MISSING"}:
                            break
                        retry_run = value.get("run")
                        if reason == "VISUAL_QA_REPAIR_REQUIRED":
                            attempt_prompt = prompt + _visual_repair_prompt(visual if isinstance(visual, dict) else {})
                        else:
                            pipeline_error = value.get("blender", {}).get("pipeline", {}).get("result", {}).get("error", "") if isinstance(value.get("blender"), dict) else ""
                            failure_evidence = value.get("error") or pipeline_error or value.get("reason") or "unknown build failure"
                            attempt_prompt = prompt + "\n\nTECHNICAL REPAIR PASS: inspect previous_build.py and fix the contract/reference/Blender failure before changing style. Ensure asset.json has the exact required schema, `outputs` is an object, reference_spec.json targets the requested asset_id, and build.py emits asset.glb and scene.blend. Keep every organic form smooth and connected, but reduce authored geometry to stay within the contract triangle budget; use fewer segments/subdivision levels and never decimate away the silhouette. Failure evidence: " + str(failure_evidence)[:3000]
                    if value is None:
                        raise ProjectError("All2API agent loop produced no result")
                    value["visual_loop"] = {"threshold_percent": 85, "max_attempts": MAX_VISUAL_BUILD_ATTEMPTS, "attempts": attempts, "status": "PASS" if value.get("status") == "PASS" else "REPAIR_REQUIRED"}
                    value["generation"] = {key: item for key, item in reference.items() if key != "data"}
                    if value.get("status") == "PASS":
                        current = value.get("mutation", {}).get("current", {})
                        instances = self.server.project.workspace().get("scene", {}).get("instances", [])
                        if isinstance(body.get("spawn"), dict) or not any(item.get("asset_id") == current.get("asset_id") for item in instances):
                            value["scene_instance"] = self.server.project.add_scene_instance(current["asset_id"], body.get("spawn"))
                elif path == "/api/blender/run":
                    value = BlenderSandbox(self.server.project.root).run(body["job"], timeout=float(body.get("timeout", 300)), allow_unsafe=body.get("allow_unsafe") is True)
                elif path == "/api/unity/validate":
                    unity_value = Path(body["unity_project"])
                    unity_project = (self.server.project.root / unity_value if not unity_value.is_absolute() else unity_value).resolve()
                    unity_project.relative_to(self.server.project.root)
                    value = UnityValidator(unity_project, unity=body.get("unity", "unity-editor")).run(body["input_asset"], body.get("output_report", ".open3d/unity-report.json"), timeout=float(body.get("timeout", 600)))
                elif path == "/api/production/run":
                    value = run_production(body["brief"], body["output"], timeout=float(body.get("timeout", 300)))
                elif path == "/api/production/promote":
                    destination = Path(body.get("project", str(self.server.project.root))).resolve()
                    if destination != self.server.project.root:
                        raise ProjectError("HTTP promotion destination must be the served project")
                    value = promote_production(body["run"], destination)
                elif path == "/api/production/repair":
                    value = repair_production(body["run"], body["repair_id"], timeout=float(body.get("timeout", 300)))
                elif path == "/api/production/agent-receipt":
                    value = production_agent_receipt(body["agent"], body["run"], output_root=body.get("output_root"), timeout=float(body.get("timeout", 30)))
                elif path == "/api/agent/plan":
                    value = run_agent_plan(body["agent"], body["prompt"], self.server.project.root, timeout=float(body.get("timeout", 30)))
                elif path == "/api/agent/build":
                    reference_image = body.get("reference_image")
                    value = run_agent_build(body["agent"], body["prompt"], self.server.project.root, timeout=float(body.get("timeout", 900)), reference_image=reference_image, reference_pipeline="img2threejs" if reference_image is not None else None, target_asset_id=body.get("asset_id"), referenced_asset_ids=body.get("referenced_asset_ids"), create_asset=body.get("create_asset") is True, quality_profile="production")
                    if value.get("status") == "PASS" and (isinstance(body.get("spawn"), dict) or body.get("create_asset") is True):
                        current = value.get("mutation", {}).get("current", {})
                        instances = self.server.project.workspace().get("scene", {}).get("instances", [])
                        if isinstance(body.get("spawn"), dict) or not any(item.get("asset_id") == current.get("asset_id") for item in instances):
                            value["scene_instance"] = self.server.project.add_scene_instance(current["asset_id"], body.get("spawn"))
                elif path == "/api/scene/instances":
                    value = self.server.project.add_scene_instance(body["asset_id"], body.get("transform"), instance_id=body.get("instance_id"))
                elif path.startswith("/api/scene/instances/") and path.endswith("/update"):
                    instance_id = path.split("/")[4]
                    value = self.server.project.update_scene_instance(instance_id, body.get("transform", body))
                elif path == "/api/scene/instances/remove":
                    value = self.server.project.remove_scene_instance(body["instance_id"])
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
