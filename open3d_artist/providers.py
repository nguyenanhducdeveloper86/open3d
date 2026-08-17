"""Opt-in provider adapters. Secrets never enter project state or browser payloads."""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .geometry import read_glb_json
from .project import Project, ProjectError


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


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {"provider_id": "procedural", "label": "Open3D procedural", "configured": True, "requires_consent": False, "network": False, "license": "Apache-2.0"},
        {"provider_id": "meshy-image-to-3d", "label": "Meshy Image to 3D", "configured": bool(os.environ.get("MESHY_API_KEY")), "requires_consent": True, "network": True, "license": "provider terms"},
    ]


def _image_value(value: str) -> str:
    if value.startswith("data:image/"):
        try:
            base64.b64decode(value.split(",", 1)[1], validate=True)
        except (IndexError, ValueError) as exc:
            raise ProviderError("image data URI is invalid") from exc
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProviderError("image_url must be HTTPS or a base64 image data URI")
    return value


class MeshyImageTo3D:
    """Meshy image-to-3D v1 adapter with bounded polling and GLB verification."""

    def __init__(self, *, api_key: str | None = None, endpoint: str = "https://api.meshy.ai/openapi/v1/image-to-3d", opener: Callable[..., Any] = urlopen):
        self.api_key = api_key or os.environ.get("MESHY_API_KEY")
        self.endpoint = endpoint.rstrip("/")
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

    def generate(self, project: Project, *, image_url: str, consent: bool, timeout: float = 900, poll_interval: float = 3) -> dict[str, Any]:
        if not consent:
            raise ConsentRequired("remote image upload requires explicit consent")
        if not self.api_key:
            raise ProviderError("MESHY_API_KEY is not configured")
        image = _image_value(image_url)
        task = self._request("POST", self.endpoint, {"image_url": image, "enable_pbr": False, "should_texture": True, "target_formats": ["glb"]})
        task_id = task.get("result")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError("Meshy did not return a task id")
        deadline = time.monotonic() + timeout
        while True:
            status = self._request("GET", f"{self.endpoint}/{task_id}")
            state = status.get("status")
            if state == "SUCCEEDED":
                model_url = ((status.get("model_urls") or {}).get("glb"))
                if not isinstance(model_url, str) or not model_url.startswith("https://"):
                    raise ProviderError("Meshy succeeded without an HTTPS GLB URL")
                glb = self._download(model_url)
                read_glb_json(glb)
                artifact_id = project.store.put_bytes(glb, kind="provider-glb", metadata={"provider": "meshy-image-to-3d", "task_id": task_id})
                return {"provider": "meshy-image-to-3d", "status": state, "task_id": task_id, "artifact_id": artifact_id}
            if state in {"FAILED", "CANCELED"}:
                raise ProviderError(f"Meshy task {state.lower()}: {status.get('task_error') or status.get('message') or 'unknown error'}")
            if time.monotonic() >= deadline:
                raise ProviderError("Meshy task polling timed out")
            time.sleep(max(0, poll_interval))

    def _download(self, url: str) -> bytes:
        request = Request(url, method="GET", headers={"Accept": "model/gltf-binary"})
        try:
            with self.opener(request, timeout=60) as response:
                data = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"Meshy GLB download failed: {exc}") from exc
        if len(data) < 20 or len(data) > 512 * 1024 * 1024:
            raise ProviderError("Meshy GLB size is outside the supported range")
        return data
