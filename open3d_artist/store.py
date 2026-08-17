"""Immutable, content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .contracts import canonical_json, digest_bytes


class ArtifactError(ValueError):
    pass


class ArtifactStore:
    def __init__(self, state_dir: str | Path):
        self.root = Path(state_dir)
        self.objects = self.root / "objects" / "sha256"
        self.metadata = self.root / "artifacts"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.metadata.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_id: str) -> Path:
        if not artifact_id.startswith("sha256:") or len(artifact_id) != 71:
            raise ArtifactError("artifact id must be sha256:<64 hex characters>")
        value = artifact_id[7:]
        try:
            int(value, 16)
        except ValueError as exc:
            raise ArtifactError("artifact id must be sha256:<64 hex characters>") from exc
        return self.objects / value[:2] / value

    def _write_atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def put_bytes(self, data: bytes, *, kind: str, metadata: dict[str, Any] | None = None) -> str:
        artifact_id = digest_bytes(data)
        path = self._path(artifact_id)
        if path.exists():
            if self.read_bytes(artifact_id) != data:
                raise ArtifactError(f"digest collision or corrupt artifact: {artifact_id}")
        else:
            self._write_atomic(path, data)
        # Keep identity fields owned by the store; producer metadata cannot lie about them.
        record = {**(metadata or {}), "artifact_id": artifact_id, "kind": kind, "bytes": len(data)}
        self._write_atomic(self.metadata / f"{artifact_id[7:]}.json", canonical_json(record))
        return artifact_id

    def put_json(self, value: Any, *, kind: str, metadata: dict[str, Any] | None = None) -> str:
        return self.put_bytes(canonical_json(value), kind=kind, metadata=metadata)

    def read_bytes(self, artifact_id: str) -> bytes:
        path = self._path(artifact_id)
        if not path.is_file():
            raise ArtifactError(f"artifact not found: {artifact_id}")
        data = path.read_bytes()
        if digest_bytes(data) != artifact_id:
            raise ArtifactError(f"artifact failed integrity check: {artifact_id}")
        return data

    def read_json(self, artifact_id: str) -> Any:
        try:
            return json.loads(self.read_bytes(artifact_id))
        except json.JSONDecodeError as exc:
            raise ArtifactError(f"artifact is not JSON: {artifact_id}") from exc

    def metadata_for(self, artifact_id: str) -> dict[str, Any]:
        path = self.metadata / f"{artifact_id[7:]}.json"
        if not path.is_file():
            data = self.read_bytes(artifact_id)
            return {"artifact_id": artifact_id, "bytes": len(data)}
        return json.loads(path.read_text(encoding="utf-8"))
