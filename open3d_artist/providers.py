"""Opt-in provider adapters. Secrets never enter project state or browser payloads."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .contracts import normalize_asset
from .geometry import patch_glb_metadata, read_glb_json
from .project import Project, ProjectError
from .qa import _glb_mesh_stats


class ProviderError(RuntimeError):
    pass


class ConsentRequired(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    label: str
    configured: bool
    requires_consent: bool
    network: bool
    license: str


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _all2api_key() -> str | None:
    return _env_value("ALL2API_API_KEY", "ALL2API_TOKEN")


def _all2api_base() -> str:
    return (_env_value("ALL2API_BASE") or "http://127.0.0.1:3737").rstrip("/")


def _all2api_available(base_url: str) -> bool:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    try:
        with urlopen(Request(f"{base_url}/api/health", method="GET", headers={"Accept": "application/json"}), timeout=0.5) as response:
            return int(getattr(response, "status", 200)) < 400
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def _codex_image_cli() -> Path:
    configured = os.environ.get("OPEN3D_IMAGE_GEN_CLI")
    if configured:
        return Path(configured).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    return codex_home / "skills/.system/imagegen/scripts/image_gen.py"


def provider_catalog() -> list[dict[str, Any]]:
    meshy = bool(os.environ.get("MESHY_API_KEY"))
    all2api = _all2api_available(_all2api_base())
    openai = bool(os.environ.get("OPENAI_API_KEY"))
    codex = bool(shutil.which("codex"))
    codex_image = bool(_codex_image_cli().is_file() and openai)
    return [
        {"provider_id": "procedural", "label": "Open3D procedural", "configured": True, "requires_consent": False, "network": False, "license": "Apache-2.0"},
        {"provider_id": "meshy-text-to-3d", "label": "Meshy Text to 3D", "configured": meshy, "requires_consent": True, "network": True, "license": "provider terms", "capabilities": ["preview", "refine", "glb"]},
        {"provider_id": "meshy-image-to-3d", "label": "Meshy Image to 3D", "configured": meshy, "requires_consent": True, "network": True, "license": "provider terms", "capabilities": ["image", "pbr", "4k", "glb"]},
        {"provider_id": "meshy-multi-image-to-3d", "label": "Meshy Multi-view to 3D", "configured": meshy, "requires_consent": True, "network": True, "license": "provider terms", "capabilities": ["multi-view", "pbr", "4k", "glb"]},
        {"provider_id": "codex-cli", "label": "Codex CLI agent", "configured": codex, "requires_consent": False, "network": True, "license": "OpenAI account", "capabilities": ["blender-build", "image-input"]},
        {"provider_id": "codex-cli-image", "label": "Codex CLI Image Generation", "configured": codex_image, "requires_consent": True, "network": True, "license": "OpenAI API terms", "capabilities": ["reference-image"], "reason": "Requires the bundled imagegen CLI and OPENAI_API_KEY"},
        {"provider_id": "all2api-image", "label": "All2API Image Generation", "configured": all2api, "requires_consent": True, "network": True, "license": "local bridge/provider terms", "capabilities": ["reference-image"], "reason": "Requires the local mcp-all2api bridge and a connected image worker"},
        {"provider_id": "openai-image", "label": "OpenAI Image Generation", "configured": openai, "requires_consent": True, "network": True, "license": "OpenAI API terms", "capabilities": ["reference-image"]},
    ]


def _image_value(value: str) -> str:
    if not isinstance(value, str):
        raise ProviderError("image_url must be HTTPS or a base64 image data URI")
    if value.startswith("data:image/"):
        try:
            header, encoded = value.split(",", 1)
            raw = base64.b64decode(encoded, validate=True)
        except (IndexError, ValueError) as exc:
            raise ProviderError("image data URI is invalid") from exc
        if not raw or len(raw) > 50 * 1024 * 1024:
            raise ProviderError("image data URI is empty or too large")
        if not any(raw.startswith(magic) for magic in (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF")):
            raise ProviderError("image data URI has an unsupported file signature")
        return f"{header},{encoded}"
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProviderError("image_url must be HTTPS or a base64 image data URI")
    return value


def _image_data_uri(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ProviderError("image generator returned an unsupported file signature")
    return mime, f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


class _MeshyHTTP:
    def __init__(self, *, api_key: str | None = None, opener: Callable[..., Any] = urlopen):
        self.api_key = api_key or os.environ.get("MESHY_API_KEY")
        self.opener = opener

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=data, method=method, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener(request, timeout=30) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Meshy request failed: {exc}") from exc
        if not isinstance(value, dict):
            raise ProviderError("Meshy response is not an object")
        return value

    def _poll(self, endpoint: str, task_id: str, *, deadline: float, poll_interval: float) -> dict[str, Any]:
        while True:
            status = self._request("GET", f"{endpoint}/{task_id}")
            state = str(status.get("status", "")).upper()
            if state == "SUCCEEDED":
                return status
            if state in {"FAILED", "CANCELED"}:
                raise ProviderError(f"Meshy task {state.lower()}: {status.get('task_error') or status.get('message') or 'unknown error'}")
            if time.monotonic() >= deadline:
                raise ProviderError("Meshy task polling timed out")
            time.sleep(max(0, poll_interval))

    def _download(self, url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderError("Meshy succeeded with an unsafe model URL")
        request = Request(url, method="GET", headers={"Accept": "model/gltf-binary"})
        try:
            with self.opener(request, timeout=60) as response:
                data = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Meshy GLB download failed: {exc}") from exc
        if len(data) < 20 or len(data) > 512 * 1024 * 1024:
            raise ProviderError("Meshy GLB size is outside the supported range")
        return data

    def _task_glb(self, status: dict[str, Any]) -> bytes:
        model_url = ((status.get("model_urls") or {}).get("glb"))
        if not isinstance(model_url, str) or not model_url.startswith("https://"):
            raise ProviderError("Meshy succeeded without an HTTPS GLB URL")
        glb = self._download(model_url)
        read_glb_json(glb)
        return glb


class MeshyImageTo3D(_MeshyHTTP):
    """Meshy image-to-3D v1 adapter with bounded polling and GLB verification."""

    def __init__(self, *, api_key: str | None = None, endpoint: str = "https://api.meshy.ai/openapi/v1/image-to-3d", opener: Callable[..., Any] = urlopen):
        super().__init__(api_key=api_key, opener=opener)
        self.endpoint = endpoint.rstrip("/")

    def generate(self, project: Project, *, image_url: str, consent: bool, timeout: float = 900, poll_interval: float = 3) -> dict[str, Any]:
        if not consent:
            raise ConsentRequired("remote image upload requires explicit consent")
        if not self.api_key:
            raise ProviderError("MESHY_API_KEY is not configured")
        image = _image_value(image_url)
        task = self._request("POST", self.endpoint, {"image_url": image, "ai_model": "meshy-7", "model_type": "standard", "enable_pbr": True, "texture_resolution": "4k", "should_texture": True, "should_remesh": False, "target_formats": ["glb"]})
        task_id = task.get("result")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError("Meshy did not return a task id")
        status = self._poll(self.endpoint, task_id, deadline=time.monotonic() + timeout, poll_interval=poll_interval)
        glb = self._task_glb(status)
        artifact_id = project.store.put_bytes(glb, kind="provider-glb", metadata={"provider": "meshy-image-to-3d", "task_id": task_id, "quality": "high"})
        return {"provider": "meshy-image-to-3d", "status": "SUCCEEDED", "task_id": task_id, "artifact_id": artifact_id}


class OpenAICompatibleImageGenerator:
    """OpenAI Image API-compatible reference generator, including All2API gateways."""

    def __init__(self, *, provider_id: str = "all2api-image", api_key: str | None = None, base_url: str | None = None, model: str | None = None, opener: Callable[..., Any] = urlopen):
        self.provider_id = provider_id
        self.api_key = api_key or (_all2api_key() if provider_id == "all2api-image" else None) or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or (_env_value("ALL2API_BASE_URL") if provider_id == "all2api-image" else None) or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or (_env_value("ALL2API_IMAGE_MODEL", "OPENAI_IMAGE_MODEL") or "gpt-image-2")
        self.opener = opener

    def generate(self, *, prompt: str, size: str = "1024x1024", quality: str = "high", timeout: float = 180) -> dict[str, Any]:
        if self.provider_id == "all2api-image" and not os.environ.get("ALL2API_BASE_URL") and self.base_url == "https://api.openai.com/v1":
            raise ProviderError("ALL2API_BASE_URL is not configured")
        if not self.api_key:
            variable = "ALL2API_API_KEY" if self.provider_id == "all2api-image" else "OPENAI_API_KEY"
            raise ProviderError(f"{variable} is not configured")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("image generation prompt is required")
        payload = {"model": self.model, "prompt": prompt.strip(), "n": 1, "size": size, "quality": quality, "output_format": "png"}
        request = Request(f"{self.base_url}/images/generations", data=json.dumps(payload, separators=(",", ":")).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{self.provider_id} image request failed: {exc}") from exc
        items = value.get("data") if isinstance(value, dict) else None
        item = items[0] if isinstance(items, list) and items else None
        if not isinstance(item, dict):
            raise ProviderError(f"{self.provider_id} returned no image")
        encoded = item.get("b64_json")
        if isinstance(encoded, str):
            try:
                raw = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ProviderError(f"{self.provider_id} returned invalid base64 image") from exc
        else:
            image_url = item.get("url")
            parsed = urlparse(image_url) if isinstance(image_url, str) else None
            base = urlparse(self.base_url)
            if not parsed or parsed.scheme not in {"https", "http"} or (parsed.scheme == "http" and parsed.netloc != base.netloc):
                raise ProviderError(f"{self.provider_id} returned an unsafe image URL")
            try:
                with self.opener(Request(image_url, method="GET", headers={"Accept": "image/*"}), timeout=60) as response:
                    raw = response.read()
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise ProviderError(f"{self.provider_id} image download failed: {exc}") from exc
        if len(raw) < 16 or len(raw) > 50 * 1024 * 1024:
            raise ProviderError(f"{self.provider_id} image size is outside the supported range")
        mime_type, data = _image_data_uri(raw)
        return {"provider": self.provider_id, "model": self.model, "mime_type": mime_type, "data": data}


class All2ApiImageGenerator:
    """Use the local mcp-all2api browser bridge; no API key or MCP subprocess is needed."""

    def __init__(self, *, base_url: str | None = None, tool: str | None = None, opener: Callable[..., Any] = urlopen):
        self.base_url = (base_url or _all2api_base()).rstrip("/")
        self.tool = tool or os.environ.get("ALL2API_IMAGE_TOOL", "chatgpt")
        self.opener = opener

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(f"{self.base_url}{path}", data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"All2API bridge request failed: {exc}") from exc
        if not isinstance(value, dict):
            raise ProviderError("All2API bridge response is not an object")
        return value

    def _image_model(self, quality: str) -> str | None:
        if self.tool == "chatgpt":
            return {"draft": "Instant", "high": "High", "hero": "Pro"}[quality]
        if self.tool == "flow":
            return "Nano Banana Pro" if quality != "draft" else "Nano Banana 2"
        return None

    def generate(self, *, prompt: str, quality: str = "high", timeout: float = 900) -> dict[str, Any]:
        if self.tool not in {"chatgpt", "flow", "grok"}:
            raise ProviderError("ALL2API_IMAGE_TOOL must be chatgpt, flow, or grok")
        if quality not in _QUALITY_PROFILES:
            raise ProviderError("quality must be draft, high, or hero")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("image generation prompt is required")
        health = self._request("GET", "/api/health", timeout=5)
        output_dir = health.get("outputDir")
        if not isinstance(output_dir, str) or not output_dir:
            raise ProviderError("All2API health did not report an output directory")
        payload: dict[str, Any] = {"tool": self.tool, "mode": "image", "prompt": prompt.strip(), "aspectRatio": "1:1", "outputCount": 1}
        model = self._image_model(quality)
        if model:
            payload["model"] = model
        if self.tool == "grok":
            payload["outputCount"] = "auto"
            payload["imageQuality"] = "speed" if quality == "draft" else "quality"

        deadline = time.monotonic() + timeout
        initial_timeout = min(max(timeout, 5), 95)
        result = self._request("POST", "/api/generate-sync", payload, timeout=initial_timeout)
        while str(result.get("status", "")).lower() in {"preparing", "pending", "running"}:
            job_id = result.get("jobId")
            if not isinstance(job_id, str) or not job_id:
                raise ProviderError("All2API returned a running job without a job id")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("All2API image generation timed out")
            wait_ms = min(60_000, max(1_000, int(remaining * 1000)))
            result = self._request("GET", f"/api/result/{quote(job_id, safe='')}?waitMs={wait_ms}", timeout=min(65, remaining + 5))
        status = str(result.get("status", "")).lower()
        if status in {"error", "failed"} or result.get("error"):
            raise ProviderError(f"All2API image generation failed: {result.get('error') or status}")
        saved_path = result.get("savedPath")
        if not isinstance(saved_path, str) or not saved_path:
            raise ProviderError("All2API completed without a saved image")
        root = Path(output_dir).expanduser().resolve()
        image_path = Path(saved_path).expanduser().resolve()
        try:
            image_path.relative_to(root)
        except ValueError as exc:
            raise ProviderError("All2API returned an image outside its declared output directory") from exc
        if not image_path.is_file():
            raise ProviderError("All2API saved image is missing")
        raw = image_path.read_bytes()
        if len(raw) < 16 or len(raw) > 50 * 1024 * 1024:
            raise ProviderError("All2API image size is outside the supported range")
        mime_type, data = _image_data_uri(raw)
        return {"provider": "all2api-image", "tool": self.tool, "model": model, "job_id": result.get("jobId"), "saved_path": str(image_path), "mime_type": mime_type, "data": data}


ALL2API_VISUAL_THRESHOLD = 85


class All2ApiVisualJudge(All2ApiImageGenerator):
    """Ask the connected ChatGPT worker to compare a reference and a render."""

    def _attachment(self, value: str | Path) -> Path:
        raw = Path(value).expanduser()
        if raw.is_symlink() or not raw.is_file():
            raise ProviderError("visual QA attachment must be a real file")
        path = raw.resolve()
        size = path.stat().st_size
        if size <= 16 or size > 16 * 1024 * 1024:
            raise ProviderError("visual QA attachment is empty or too large")
        with path.open("rb") as handle:
            signature = handle.read(12)
        if not (signature.startswith(b"\x89PNG\r\n\x1a\n") or signature.startswith(b"\xff\xd8\xff") or (signature.startswith(b"RIFF") and signature[8:12] == b"WEBP")):
            raise ProviderError("visual QA attachment is not a supported image")
        return path

    @staticmethod
    def _response_text(value: dict[str, Any]) -> str:
        text = value.get("text") or value.get("output") or value.get("message")
        if isinstance(text, str):
            return text
        if isinstance(text, list):
            return "\n".join(item.get("text", "") for item in text if isinstance(item, dict) and isinstance(item.get("text"), str))
        return ""

    @staticmethod
    def _json_result(text: str) -> dict[str, Any] | None:
        decoder = json.JSONDecoder()
        for start, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    def judge(self, reference_path: str | Path, candidate_path: str | Path, *, asset_id: str, timeout: float = 900) -> dict[str, Any]:
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ProviderError("visual QA asset_id is required")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ProviderError("visual QA timeout must be positive")
        reference = self._attachment(reference_path)
        candidate = self._attachment(candidate_path)
        prompt = (
            f"You are a strict production visual QA judge for Cloudvale 3D assets. Compare attachment 1 (REFERENCE) against attachment 2 (CANDIDATE_HERO_3Q) for asset {asset_id}. Judge geometry, form and construction, not merely color or rendering polish. The reference may use stylized low-poly facets; do not penalize smooth shading by itself when the silhouette and forms match. The candidate must be a softcrafted, game-ready cloud fox with one continuous inflated head/skull and shallow cheek/muzzle transitions, rounded pointed ears, thick paws, connected cloud tufts, and one thick tapered curled tail whose root is integrated into the body. Penalize boxes, cylinders used as limbs, sharp faceting that changes the silhouette, thin rods, bead-like tail segments, flat decals, separate cheek balls, floating pieces, and missing contact transitions. Color markings are secondary and cannot compensate for wrong geometry. "
            f"Score these weighted components and sum them to similarity_percent: silhouette 20, proportions 20, major_forms 15, placement 15, construction 10, material_blocks 10, surface_softness 5, cloudvale_readability 5. PASS is allowed only when the computed similarity_percent is >= {ALL2API_VISUAL_THRESHOLD}; otherwise use REPAIR. Compute the score from the two images, do not copy a sample value, and do not default to zero. Include at most three short geometry repairs in mismatched_components and next_actions; include at most three matched form names in freeze_components. Return exactly one compact JSON object on one line, no markdown, no explanation, and no extra keys, using this shape with computed values: {{\"similarity_percent\": SCORE,\"mismatched_components\":[\"...\"],\"next_actions\":[\"...\"],\"freeze_components\":[\"...\"]}}."
        )
        health = self._request("GET", "/api/health", timeout=5)
        if health.get("ok") is False:
            raise ProviderError("All2API visual judge health check failed")
        # Each comparison gets a fresh bridge conversation. Reusing the same
        # ChatGPT tab can otherwise return the previous judge's JSON.
        payload = {"tool": "chatgpt", "mode": "text", "model": "Thinking", "inlineOnly": True, "prompt": prompt, "filePaths": [str(reference), str(candidate)], "chatgptFreshSessionKey": f"open3d-visual-qa-{asset_id}-{uuid.uuid4().hex}"}
        deadline = time.monotonic() + float(timeout)
        result = None
        parsed = None
        raw_text = ""
        score_value = None
        for judge_attempt in range(1, 4):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("All2API visual judge timed out")
            result = self._request("POST", "/api/generate-sync", payload, timeout=min(max(remaining, 5), 95))
            while str(result.get("status", "")).lower() in {"preparing", "pending", "running"}:
                job_id = result.get("jobId")
                if not isinstance(job_id, str) or not job_id:
                    raise ProviderError("All2API visual judge returned a running job without a job id")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderError("All2API visual judge timed out")
                wait_ms = min(60_000, max(1_000, int(remaining * 1000)))
                result = self._request("GET", f"/api/result/{quote(job_id, safe='')}?waitMs={wait_ms}", timeout=min(65, remaining + 5))
            status = str(result.get("status", "")).lower()
            if status in {"error", "failed"} or result.get("error"):
                raise ProviderError(f"All2API visual judge failed: {result.get('error') or status}")
            raw_text = self._response_text(result)[:16 * 1024]
            parsed = self._json_result(raw_text)
            score_value = parsed.get("similarity_percent") if parsed else None
            if score_value is None and parsed:
                score_value = parsed.get("score")
            if not isinstance(score_value, bool) and isinstance(score_value, (int, float)) and math.isfinite(float(score_value)) and 0 <= float(score_value) <= 100:
                break
            if judge_attempt == 3:
                raise ProviderError("All2API visual judge returned no valid similarity_percent")
        assert result is not None
        score = round(float(score_value), 2)
        passed = score >= ALL2API_VISUAL_THRESHOLD
        return {
            "provider": "all2api-chatgpt", "model": "Thinking", "job_id": result.get("jobId"), "asset_id": asset_id,
            "attachment_order": ["REFERENCE", "CANDIDATE_HERO_3Q"], "reference_path": str(reference), "candidate_path": str(candidate),
            "similarity_percent": score, "score": score, "target_percent": ALL2API_VISUAL_THRESHOLD,
            "status": "PASS" if passed else "REPAIR_REQUIRED", "match_status": "PASS" if passed else "REPAIR_REQUIRED", "commit_allowed": passed,
            "judge_attempts": judge_attempt, "scores": parsed.get("scores", {}) if parsed else {}, "matched_components": parsed.get("matched_components", []) if parsed else [],
            "mismatched_components": parsed.get("mismatched_components", []) if parsed else [], "next_actions": parsed.get("next_actions", []) if parsed else [],
            "freeze_components": parsed.get("freeze_components", []) if parsed else [], "repair_components": parsed.get("repair_components", []) if parsed else [],
            "repair": parsed.get("repair") if parsed else None, "recommended_action": parsed.get("recommended_action") if parsed else None, "evidence_status": parsed.get("evidence_status", "COMPLETE") if parsed else "INCOMPLETE", "raw": raw_text,
        }


class CodexCliImageGenerator:
    """Use the bundled imagegen CLI explicitly; Codex CLI itself is image-input only."""

    def __init__(self, *, script: str | Path | None = None, model: str = "gpt-image-2"):
        self.script = Path(script).expanduser() if script else _codex_image_cli()
        self.model = model

    def generate(self, project: Project, *, prompt: str, size: str = "1024x1024", quality: str = "high", timeout: float = 240) -> dict[str, Any]:
        if not self.script.is_file():
            raise ProviderError(f"Codex image CLI not found: {self.script}")
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderError("OPENAI_API_KEY is not configured for the Codex image CLI")
        scratch = project.state / "tmp" / "imagegen"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="codex-", dir=scratch) as directory:
                output = Path(directory) / "reference.png"
                command = [sys.executable, str(self.script), "generate", "--prompt", prompt.strip(), "--model", self.model, "--size", size, "--quality", quality, "--out", str(output)]
                try:
                    result = subprocess.run(command, cwd=project.root, capture_output=True, text=True, timeout=timeout, check=False)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise ProviderError(f"Codex image CLI failed: {exc}") from exc
                if result.returncode != 0:
                    detail = "\n".join((result.stderr or "", result.stdout or "")).strip()[-4000:]
                    raise ProviderError(f"Codex image CLI failed ({result.returncode}): {detail or 'no output'}")
                if not output.is_file():
                    raise ProviderError("Codex image CLI finished without an image file")
                raw = output.read_bytes()
        finally:
            if scratch.is_dir() and not any(scratch.iterdir()):
                scratch.rmdir()
        mime_type, data = _image_data_uri(raw)
        return {"provider": "codex-cli-image", "model": self.model, "mime_type": mime_type, "data": data}


_QUALITY_PROFILES: dict[str, dict[str, Any]] = {
    "draft": {"ai_model": "meshy-6", "enable_pbr": False, "texture_resolution": "2k", "ultra_mode": False},
    "high": {"ai_model": "meshy-7", "enable_pbr": True, "texture_resolution": "4k", "ultra_mode": True},
    "hero": {"ai_model": "latest", "enable_pbr": True, "texture_resolution": "8k", "ultra_mode": True},
}


def _safe_part_id(value: Any, index: int, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "")).strip("-.")[:56]
    if not candidate or not candidate[0].isalpha():
        candidate = f"part-{index + 1:03d}" if not candidate else f"part-{candidate}"
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base[: max(1, 63 - len(str(suffix)))]}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _rewrite_glb_json(data: bytes, gltf: dict[str, Any]) -> bytes:
    json_length = struct.unpack_from("<I", data, 12)[0]
    old_json_end = 20 + json_length
    rest = data[old_json_end:]
    json_chunk = json.dumps(gltf, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    while len(json_chunk) % 4:
        json_chunk += b" "
    total_length = 12 + 8 + len(json_chunk) + len(rest)
    return b"glTF" + struct.pack("<II", 2, total_length) + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk + rest


def _provider_asset(glb: bytes, *, asset_id: str, kind: str) -> tuple[dict[str, Any], bytes]:
    gltf = read_glb_json(glb)
    stats = _glb_mesh_stats(gltf)
    bounds = stats.get("bounds") or {}
    size = bounds.get("size") if isinstance(bounds, dict) else None
    triangles = int(stats.get("triangles", 0))
    if not isinstance(size, list) or len(size) != 3 or triangles <= 0:
        raise ProviderError("Meshy returned geometry without measurable bounds or triangles")
    if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0 for value in size):
        raise ProviderError("Meshy returned invalid geometry bounds")

    used: set[str] = set()
    parts: list[dict[str, Any]] = []
    for index, node in enumerate(gltf.get("nodes", [])):
        if not isinstance(node, dict) or not isinstance(node.get("mesh"), int):
            continue
        source = node.get("name") or f"part-{index + 1:03d}"
        part_id = _safe_part_id(source, index, used)
        node["name"] = part_id
        node_extras = node.setdefault("extras", {})
        node_open3d = node_extras.setdefault("open3d", {})
        node_open3d["part_id"] = part_id
        parts.append({"part_id": part_id, "role": node_open3d.get("part_role") or "generated_mesh"})
    if not parts:
        raise ProviderError("Meshy returned a GLB without mesh nodes")

    candidate = normalize_asset({
        "schema_version": "0.1.0",
        "asset_id": asset_id,
        "name": asset_id,
        "kind": kind,
        "units": "m",
        "dimensions": {axis: round(float(value) * 1.02, 6) for axis, value in zip(("width", "depth", "height"), size)},
        "parts": parts,
        "geometry": {"triangle_budget": {"max": max(1000, int(math.ceil(triangles * 1.15)))}, "source": "meshy"},
        "outputs": {"editable": "agent", "preview": "glb", "source": "meshy"},
    })
    normalized_glb = patch_glb_metadata(_rewrite_glb_json(glb, gltf), candidate)
    return candidate, normalized_glb


class MeshyPipeline(_MeshyHTTP):
    """High-quality Meshy pipeline: text preview/refine or image/multi-view to GLB, then adopt atomically."""

    def __init__(self, *, api_key: str | None = None, text_endpoint: str = "https://api.meshy.ai/openapi/v2/text-to-3d", image_endpoint: str = "https://api.meshy.ai/openapi/v1/image-to-3d", multi_image_endpoint: str = "https://api.meshy.ai/openapi/v1/multi-image-to-3d", opener: Callable[..., Any] = urlopen):
        super().__init__(api_key=api_key, opener=opener)
        self.text_endpoint = text_endpoint.rstrip("/")
        self.image_endpoint = image_endpoint.rstrip("/")
        self.multi_image_endpoint = multi_image_endpoint.rstrip("/")

    def run(self, project: Project, *, asset_id: str, prompt: str, mode: str = "text", kind: str = "prop", image_url: str | None = None, image_urls: list[str] | None = None, consent: bool, quality: str = "high", reference_provider: str | None = None, timeout: float = 900, poll_interval: float = 3) -> dict[str, Any]:
        if not consent:
            raise ConsentRequired("remote generation requires explicit consent")
        if not self.api_key:
            raise ProviderError("MESHY_API_KEY is not configured")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ProjectError("asset_id is required")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("generation prompt is required")
        if mode not in {"text", "image", "multi_image"}:
            raise ProviderError("mode must be text, image, or multi_image")
        if quality not in _QUALITY_PROFILES:
            raise ProviderError("quality must be draft, high, or hero")
        if image_urls is not None and (not isinstance(image_urls, list) or any(not isinstance(value, str) for value in image_urls)):
            raise ProviderError("image_urls must be a list of strings")

        stages: list[dict[str, Any]] = []
        reference_generation = None
        images = list(image_urls or ([] if image_url is None else [image_url]))
        if reference_provider:
            if mode != "text":
                raise ProviderError("reference_provider is only valid with text mode")
            if reference_provider == "codex-cli":
                reference_generation = CodexCliImageGenerator().generate(project, prompt=prompt, quality="high", timeout=min(timeout, 240))
            elif reference_provider == "all2api":
                reference_generation = All2ApiImageGenerator().generate(prompt=prompt, quality="high", timeout=min(timeout, 900))
            elif reference_provider == "openai":
                reference_generation = OpenAICompatibleImageGenerator(provider_id="openai-image").generate(prompt=prompt, quality="high", timeout=min(timeout, 180))
            else:
                raise ProviderError("reference_provider must be codex-cli, all2api, or openai")
            images = [reference_generation["data"]]
            mode = "image"
            stages.append({"id": "reference-image", "status": "PASS", "provider": reference_generation["provider"]})

        profile = dict(_QUALITY_PROFILES[quality])
        deadline = time.monotonic() + timeout
        task_ids: list[str] = []
        if mode == "text":
            preview_payload = {"mode": "preview", "prompt": prompt.strip(), "model_type": "standard", **profile, "should_remesh": False, "target_formats": ["glb"]}
            preview = self._request("POST", self.text_endpoint, preview_payload)
            preview_id = preview.get("result")
            if not isinstance(preview_id, str) or not preview_id:
                raise ProviderError("Meshy preview did not return a task id")
            task_ids.append(preview_id)
            stages.append({"id": "preview", "status": "RUNNING", "task_id": preview_id})
            self._poll(self.text_endpoint, preview_id, deadline=deadline, poll_interval=poll_interval)
            stages[-1]["status"] = "PASS"
            refine_payload = {"mode": "refine", "preview_task_id": preview_id, "enable_pbr": profile["enable_pbr"], "texture_resolution": profile["texture_resolution"], "target_formats": ["glb"]}
            refine = self._request("POST", self.text_endpoint, refine_payload)
            refine_id = refine.get("result")
            if not isinstance(refine_id, str) or not refine_id:
                raise ProviderError("Meshy refine did not return a task id")
            task_ids.append(refine_id)
            stages.append({"id": "refine", "status": "RUNNING", "task_id": refine_id})
            final_status = self._poll(self.text_endpoint, refine_id, deadline=deadline, poll_interval=poll_interval)
            stages[-1]["status"] = "PASS"
        else:
            if mode == "image" and len(images) != 1:
                raise ProviderError("image mode requires exactly one image")
            if mode == "multi_image" and not 1 <= len(images) <= 4:
                raise ProviderError("multi_image mode requires one to four images")
            images = [_image_value(value) for value in images]
            payload = {"model_type": "standard", **profile, "should_texture": True, "should_remesh": False, "image_enhancement": True, "target_formats": ["glb"]}
            if profile["ai_model"] == "meshy-6":
                payload["remove_lighting"] = True
            endpoint = self.image_endpoint if mode == "image" else self.multi_image_endpoint
            payload["image_url" if mode == "image" else "image_urls"] = images[0] if mode == "image" else images
            task = self._request("POST", endpoint, payload)
            task_id = task.get("result")
            if not isinstance(task_id, str) or not task_id:
                raise ProviderError("Meshy image task did not return a task id")
            task_ids.append(task_id)
            stages.append({"id": mode, "status": "RUNNING", "task_id": task_id})
            final_status = self._poll(endpoint, task_id, deadline=deadline, poll_interval=poll_interval)
            stages[-1]["status"] = "PASS"

        glb = self._task_glb(final_status)
        candidate, normalized_glb = _provider_asset(glb, asset_id=asset_id.strip(), kind=kind)
        mutation = project.replace_generated_asset(candidate, normalized_glb, agent="meshy", prompt=prompt, run_id=f"meshy-{uuid.uuid4().hex[:20]}", workspace="meshy-pipeline", auto_fit_dimensions=False, source="meshy", operation_name="asset.provider_generate")
        stages.append({"id": "qa", "status": mutation["report"]["status"], "checks": mutation["report"].get("summary", {})})
        return {"status": mutation["status"], "provider": "meshy-pipeline", "mode": mode, "quality": quality, "task_ids": task_ids, "reference_generation": {key: value for key, value in (reference_generation or {}).items() if key != "data"} or None, "pipeline": stages, "mutation": mutation}
