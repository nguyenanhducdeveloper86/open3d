"""Project lifecycle: CAS, references, checkpoints, operations, and edits."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .contracts import asset_bytes, canonical_json, load_asset, normalize_asset
from .geometry import generate_glb, meshes_for_asset
from .qa import validate_asset_and_glb
from .store import ArtifactStore


class ProjectError(ValueError):
    pass


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.state = self.root / ".open3d"
        if not self.state.is_dir():
            raise ProjectError(f"not an Open3D project: {self.root}")
        self.store = ArtifactStore(self.state)
        self.refs = self.state / "refs"
        self.checkpoints = self.refs / "checkpoints"
        self.operations = self.state / "operations" / "operations.jsonl"

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
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

    @classmethod
    def init(cls, root: str | Path, asset_path: str | Path) -> "Project":
        root = Path(root).resolve()
        state = root / ".open3d"
        if state.exists():
            raise ProjectError(f"project already exists: {root}")
        root.mkdir(parents=True, exist_ok=True)
        source = Path(asset_path)
        if not source.is_absolute():
            source = root / source
        asset = load_asset(source)
        meshes = meshes_for_asset(asset)
        glb = generate_glb(asset)
        state.mkdir()
        project = cls.__new__(cls)
        project.root = root
        project.state = state
        project.store = ArtifactStore(state)
        project.refs = state / "refs"
        project.checkpoints = project.refs / "checkpoints"
        project.operations = state / "operations" / "operations.jsonl"
        project.refs.mkdir(parents=True, exist_ok=True)
        project.checkpoints.mkdir(parents=True, exist_ok=True)
        project.operations.parent.mkdir(parents=True, exist_ok=True)

        contract_id = project.store.put_bytes(asset_bytes(asset), kind="asset-contract", metadata={"asset_id": asset["asset_id"]})
        glb_id = project.store.put_bytes(glb, kind="glb", metadata={"asset_id": asset["asset_id"], "contract_artifact": contract_id})
        report = validate_asset_and_glb(asset, glb, artifact_id=glb_id, meshes=meshes)
        qa_id = project.store.put_json(report, kind="qa-report", metadata={"asset_id": asset["asset_id"], "input_artifact_id": glb_id})
        current = {
            "schema_version": "0.1.0",
            "project_id": _project_id(root),
            "asset_id": asset["asset_id"],
            "contract_artifact": contract_id,
            "glb_artifact": glb_id,
            "qa_artifact": qa_id,
            "qa_status": report["status"],
            "checkpoint_id": None,
        }
        project._write_atomic(project.refs / "current.json", canonical_json(current))
        project._write_atomic(project.root / "project.json", canonical_json({"schema_version": "0.1.0", "project_id": current["project_id"], "asset_id": asset["asset_id"], "current_ref": ".open3d/refs/current.json"}))
        project._create_checkpoint(current, parent=None, operation_id="op_init", note="initial project state")
        return project

    def _current_path(self) -> Path:
        return self.refs / "current.json"

    def current(self) -> dict[str, Any]:
        try:
            return json.loads(self._current_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ProjectError("current project reference is missing or corrupt") from exc

    def _write_current(self, value: dict[str, Any]) -> None:
        self._write_atomic(self._current_path(), canonical_json(value))

    def _append_operation(self, operation: dict[str, Any]) -> None:
        self.operations.parent.mkdir(parents=True, exist_ok=True)
        with self.operations.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(operation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _create_checkpoint(self, ref: dict[str, Any], *, parent: str | None, operation_id: str, note: str) -> str:
        snapshot = {key: value for key, value in ref.items() if key != "checkpoint_id"}
        identity = {"schema_version": "0.1.0", "project_id": ref["project_id"], "parent_checkpoint": parent, "operation_id": operation_id, "note": note, "ref": snapshot}
        from .contracts import digest_json

        checkpoint_id = digest_json(identity)
        record = {**identity, "checkpoint_id": checkpoint_id}
        self._write_atomic(self.checkpoints / f"{checkpoint_id[7:]}.json", canonical_json(record))
        current = dict(ref)
        current["checkpoint_id"] = checkpoint_id
        self._write_current(current)
        return checkpoint_id

    def checkpoint(self, note: str = "manual checkpoint") -> str:
        current = self.current()
        return self._create_checkpoint(current, parent=current.get("checkpoint_id"), operation_id=_operation_id(), note=note)

    def _checkpoint_record(self, checkpoint_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", checkpoint_id):
            raise ProjectError("invalid checkpoint id")
        path = self.checkpoints / f"{checkpoint_id[7:]}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ProjectError(f"checkpoint not found: {checkpoint_id}") from exc
        if record.get("checkpoint_id") != checkpoint_id:
            raise ProjectError("checkpoint integrity check failed")
        return record

    def rollback(self, checkpoint_id: str) -> dict[str, Any]:
        record = self._checkpoint_record(checkpoint_id)
        previous = self.current()
        restored = dict(record["ref"])
        restored["checkpoint_id"] = checkpoint_id
        self._write_current(restored)
        self._append_operation({"schema_version": "0.1.0", "operation_id": _operation_id(), "name": "checkpoint.rollback", "version": "0.1", "input_checkpoint": previous.get("checkpoint_id"), "result_checkpoint": checkpoint_id, "mutates": [], "invalidates": []})
        return restored

    def load_current_asset(self) -> dict[str, Any]:
        return normalize_asset(self.store.read_json(self.current()["contract_artifact"]))

    def inspect(self) -> dict[str, Any]:
        current = self.current()
        return {"project": json.loads((self.root / "project.json").read_text(encoding="utf-8")), "current": current, "contract": self.load_current_asset(), "artifacts": {key: self.store.metadata_for(current[key]) for key in ("contract_artifact", "glb_artifact", "qa_artifact")}}

    def history(self) -> list[dict[str, Any]]:
        if not self.operations.is_file():
            return []
        return [json.loads(line) for line in self.operations.read_text(encoding="utf-8").splitlines() if line]

    def validate(self) -> dict[str, Any]:
        current = self.current()
        asset = self.load_current_asset()
        glb = self.store.read_bytes(current["glb_artifact"])
        report = validate_asset_and_glb(asset, glb, artifact_id=current["glb_artifact"], meshes=meshes_for_asset(asset))
        qa_id = self.store.put_json(report, kind="qa-report", metadata={"asset_id": asset["asset_id"], "input_artifact_id": current["glb_artifact"]})
        current["qa_artifact"] = qa_id
        current["qa_status"] = report["status"]
        self._write_current(current)
        return report

    def edit_part(self, part_id: str, scales: dict[str, float], *, idempotency_key: str | None = None) -> dict[str, Any]:
        current = self.current()
        idempotency_key = idempotency_key or _operation_id()
        existing = self._find_idempotency(idempotency_key)
        if existing:
            return {"replayed": True, "operation": existing, "current": self.current()}
        operation_id = _operation_id()
        asset = self.load_current_asset()
        if part_id not in {part["part_id"] for part in asset["parts"]}:
            raise ProjectError(f"unknown part_id: {part_id}")
        if not scales or any(axis not in {"x", "y", "z"} for axis in scales):
            raise ProjectError("scales must contain at least one of x, y, z")
        if any(not isinstance(value, (int, float)) or value <= 0 for value in scales.values()):
            raise ProjectError("scale values must be positive numbers")
        candidate = normalize_asset(asset)
        changed = False
        for primitive in candidate["geometry"].get("primitives", []):
            if primitive["part_id"] != part_id:
                continue
            primitive.setdefault("scale", {"x": 1.0, "y": 1.0, "z": 1.0})
            for axis, factor in scales.items():
                primitive["scale"][axis] = float(primitive["scale"].get(axis, 1.0)) * float(factor)
            changed = True
        if not changed:
            raise ProjectError(f"part has no editable primitive: {part_id}")
        before_checkpoint = self._create_checkpoint(current, parent=current.get("checkpoint_id"), operation_id=operation_id, note=f"before edit {part_id}")

        contract_id = self.store.put_bytes(asset_bytes(candidate), kind="asset-contract", metadata={"asset_id": candidate["asset_id"], "parent_contract": current["contract_artifact"]})
        meshes = meshes_for_asset(candidate)
        glb = generate_glb(candidate)
        glb_id = self.store.put_bytes(glb, kind="glb", metadata={"asset_id": candidate["asset_id"], "contract_artifact": contract_id})
        report = validate_asset_and_glb(candidate, glb, artifact_id=glb_id, meshes=meshes)
        qa_id = self.store.put_json(report, kind="qa-report", metadata={"asset_id": candidate["asset_id"], "input_artifact_id": glb_id})
        operation = {"schema_version": "0.1.0", "operation_id": operation_id, "name": "asset.edit_part", "version": "0.1", "idempotency_key": idempotency_key, "input_checkpoint": before_checkpoint, "mutates": [f"part:{part_id}"], "invalidates": ["qa.geometry", "qa.viewer"], "result_checkpoint": None, "status": report["status"]}
        if report["status"] != "PASS":
            operation["result_checkpoint"] = before_checkpoint
            self._append_operation(operation)
            return {"operation": operation, "report": report, "rolled_back_to": before_checkpoint}

        next_ref = {**current, "contract_artifact": contract_id, "glb_artifact": glb_id, "qa_artifact": qa_id, "qa_status": report["status"], "checkpoint_id": before_checkpoint}
        result_checkpoint = self._create_checkpoint(next_ref, parent=before_checkpoint, operation_id=operation_id, note=f"after edit {part_id}")
        operation["result_checkpoint"] = result_checkpoint
        self._append_operation(operation)
        return {"operation": operation, "report": report, "current": self.current()}

    def _find_idempotency(self, key: str) -> dict[str, Any] | None:
        if not self.operations.is_file():
            return None
        for line in self.operations.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            operation = json.loads(line)
            if operation.get("idempotency_key") == key:
                return operation
        return None

    def export_glb(self, output: str | Path) -> Path:
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(destination, self.store.read_bytes(self.current()["glb_artifact"]))
        return destination


def _project_id(root: Path) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-")
    return value or "open3d-project"


def _operation_id() -> str:
    return f"op_{uuid.uuid4().hex[:20]}"
