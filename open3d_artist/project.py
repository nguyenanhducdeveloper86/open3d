"""Project lifecycle: CAS, references, checkpoints, operations, and edits."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .contracts import asset_bytes, canonical_json, load_asset, normalize_asset
from .geometry import generate_glb, meshes_for_asset, patch_glb_metadata
from .qa import validate_asset_and_glb
from .store import ArtifactStore


class ProjectError(ValueError):
    pass


_WORKSPACE_SCHEMA = "0.1.0"
_INSTANCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


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
        self.workspace_path = self.state / "workspace.json"

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
        project.workspace_path = state / "workspace.json"
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
        project._write_workspace(project._new_workspace(project.current(), asset))
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

    def _write_project_metadata(self, ref: dict[str, Any]) -> None:
        self._write_atomic(
            self.root / "project.json",
            canonical_json({
                "schema_version": "0.1.0",
                "project_id": ref["project_id"],
                "asset_id": ref["asset_id"],
                "current_ref": ".open3d/refs/current.json",
            }),
        )

    @staticmethod
    def _identity_transform() -> dict[str, dict[str, float]]:
        return {
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        }

    @staticmethod
    def _transform(value: Any) -> dict[str, dict[str, float]]:
        if value is None:
            return Project._identity_transform()
        if not isinstance(value, dict):
            raise ProjectError("scene transform must be an object")
        result = Project._identity_transform()
        for name in result:
            source = value.get(name, {})
            if not isinstance(source, dict):
                raise ProjectError(f"scene transform.{name} must be an object")
            for axis in result[name]:
                number = source.get(axis, result[name][axis])
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                    raise ProjectError(f"scene transform.{name}.{axis} must be finite")
                if name == "scale" and number <= 0:
                    raise ProjectError(f"scene transform.scale.{axis} must be positive")
                result[name][axis] = float(number)
        return result

    def _workspace_entry(self, ref: dict[str, Any], asset: dict[str, Any] | None = None) -> dict[str, Any]:
        asset = normalize_asset(asset if asset is not None else self.store.read_json(ref["contract_artifact"]))
        return {
            "asset_id": asset["asset_id"],
            "name": asset.get("name") or asset["asset_id"],
            "kind": asset["kind"],
            "units": asset["units"],
            "dimensions": asset["dimensions"],
            "parts": asset["parts"],
            "contract": asset,
            "contract_artifact": ref["contract_artifact"],
            "glb_artifact": ref["glb_artifact"],
            "qa_artifact": ref.get("qa_artifact"),
            "blend_artifact": ref.get("blend_artifact"),
            "qa_status": ref.get("qa_status", "UNKNOWN"),
            "geometry_source": ref.get("geometry_source", "contract"),
            "agent_build": ref.get("agent_build"),
        }

    def _new_workspace(self, ref: dict[str, Any], asset: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = self._workspace_entry(ref, asset)
        instance_id = f"instance-{uuid.uuid4().hex[:12]}"
        return {
            "schema_version": _WORKSPACE_SCHEMA,
            "project_id": ref["project_id"],
            "assets": [entry],
            "scene": {
                "schema_version": _WORKSPACE_SCHEMA,
                "instances": [{"instance_id": instance_id, "asset_id": entry["asset_id"], **self._identity_transform()}],
            },
        }

    def _read_workspace(self) -> tuple[dict[str, Any], bool]:
        if not self.workspace_path.is_file():
            return self._new_workspace(self.current()), True
        try:
            value = json.loads(self.workspace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError("workspace state is missing or corrupt") from exc
        if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
            raise ProjectError("workspace state must contain an assets list")
        scene = value.get("scene")
        if not isinstance(scene, dict) or not isinstance(scene.get("instances"), list):
            raise ProjectError("workspace state must contain scene instances")
        return value, False

    def _write_workspace(self, value: dict[str, Any]) -> None:
        self._write_atomic(self.workspace_path, canonical_json(value))

    def _upsert_workspace_asset(self, ref: dict[str, Any], asset: dict[str, Any] | None = None) -> dict[str, Any]:
        value, _ = self._read_workspace()
        entry = self._workspace_entry(ref, asset)
        assets = value.setdefault("assets", [])
        for index, existing in enumerate(assets):
            if existing.get("asset_id") == entry["asset_id"]:
                assets[index] = entry
                break
        else:
            assets.append(entry)
        value["schema_version"] = _WORKSPACE_SCHEMA
        value["project_id"] = ref["project_id"]
        value.setdefault("scene", {"schema_version": _WORKSPACE_SCHEMA, "instances": []})["schema_version"] = _WORKSPACE_SCHEMA
        self._write_workspace(value)
        return entry

    def workspace(self) -> dict[str, Any]:
        value, missing = self._read_workspace()
        current = self.current()
        current_entry = self._workspace_entry(current)
        assets = value.setdefault("assets", [])
        changed = missing
        for index, existing in enumerate(assets):
            if existing.get("asset_id") == current_entry["asset_id"]:
                if existing.get("glb_artifact") != current_entry["glb_artifact"] or existing.get("qa_artifact") != current_entry.get("qa_artifact") or existing.get("blend_artifact") != current_entry.get("blend_artifact"):
                    assets[index] = current_entry
                    changed = True
                break
        else:
            assets.append(current_entry)
            changed = True
        value.setdefault("scene", {"schema_version": _WORKSPACE_SCHEMA, "instances": []})
        value["scene"].setdefault("instances", [])
        if not value["scene"]["instances"]:
            value["scene"]["instances"].append({"instance_id": f"instance-{uuid.uuid4().hex[:12]}", "asset_id": current_entry["asset_id"], **self._identity_transform()})
            changed = True
        if changed:
            value["schema_version"] = _WORKSPACE_SCHEMA
            value["project_id"] = current["project_id"]
            value["scene"]["schema_version"] = _WORKSPACE_SCHEMA
            self._write_workspace(value)
        return value

    def workspace_asset(self, asset_id: str) -> dict[str, Any]:
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ProjectError("asset_id must be a non-empty string")
        for asset in self.workspace()["assets"]:
            if asset.get("asset_id") == asset_id:
                return asset
        raise ProjectError(f"workspace asset not found: {asset_id}")

    def add_scene_instance(self, asset_id: str, transform: dict[str, Any] | None = None, *, instance_id: str | None = None) -> dict[str, Any]:
        asset = self.workspace_asset(asset_id)
        value = self.workspace()
        instance_id = instance_id or f"instance-{uuid.uuid4().hex[:12]}"
        if not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id):
            raise ProjectError("instance_id must match ^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
        if any(item.get("instance_id") == instance_id for item in value["scene"]["instances"]):
            raise ProjectError(f"scene instance already exists: {instance_id}")
        instance = {"instance_id": instance_id, "asset_id": asset["asset_id"], **self._transform(transform)}
        value["scene"]["instances"].append(instance)
        self._write_workspace(value)
        return instance

    def update_scene_instance(self, instance_id: str, transform: dict[str, Any]) -> dict[str, Any]:
        value = self.workspace()
        for instance in value["scene"]["instances"]:
            if instance.get("instance_id") == instance_id:
                instance.update(self._transform(transform))
                self._write_workspace(value)
                return instance
        raise ProjectError(f"scene instance not found: {instance_id}")

    def remove_scene_instance(self, instance_id: str) -> dict[str, Any]:
        value = self.workspace()
        before = len(value["scene"]["instances"])
        value["scene"]["instances"] = [item for item in value["scene"]["instances"] if item.get("instance_id") != instance_id]
        if len(value["scene"]["instances"]) == before:
            raise ProjectError(f"scene instance not found: {instance_id}")
        self._write_workspace(value)
        return {"instance_id": instance_id, "removed": True}

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
        self._write_project_metadata(restored)
        self._upsert_workspace_asset(restored)
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

    @staticmethod
    def _version_signature(ref: dict[str, Any]) -> tuple[Any, ...]:
        # QA reports are refreshable metadata; a validation run must not create a new asset version.
        return tuple(ref.get(key) for key in ("asset_id", "contract_artifact", "glb_artifact"))

    def _checkpoint_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        if not self.checkpoints.is_dir():
            return records
        for path in self.checkpoints.glob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            checkpoint_id = record.get("checkpoint_id")
            if re.fullmatch(r"sha256:[0-9a-f]{64}", str(checkpoint_id)) and isinstance(record.get("ref"), dict):
                records[checkpoint_id] = record
        return records

    def asset_versions(self, asset_id: str | None = None) -> dict[str, Any]:
        """Return distinct immutable asset states in their operation order."""

        if asset_id is not None and (not isinstance(asset_id, str) or not asset_id.strip()):
            raise ProjectError("asset_id must be a non-empty string")
        current = self.current()
        reference = current
        if asset_id is not None and asset_id != current.get("asset_id"):
            reference = self.workspace_asset(asset_id)
        records = self._checkpoint_records()
        versions: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        next_numbers: dict[str, int] = {}

        def add(checkpoint_id: Any, operation: dict[str, Any] | None = None) -> None:
            if not isinstance(checkpoint_id, str) or checkpoint_id not in records:
                return
            record = records[checkpoint_id]
            ref = record["ref"]
            ref_asset_id = ref.get("asset_id")
            if asset_id is not None and ref_asset_id != asset_id:
                return
            signature = self._version_signature(ref)
            if signature in seen:
                return
            seen.add(signature)
            number = next_numbers.get(str(ref_asset_id), 0) + 1
            next_numbers[str(ref_asset_id)] = number
            versions.append({
                "version_id": f"v{number:03d}",
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint": record.get("parent_checkpoint"),
                "asset_id": ref_asset_id,
                "contract_artifact": ref.get("contract_artifact"),
                "glb_artifact": ref.get("glb_artifact"),
                "qa_artifact": ref.get("qa_artifact"),
                "blend_artifact": ref.get("blend_artifact"),
                "qa_status": ref.get("qa_status", "UNKNOWN"),
                "geometry_source": ref.get("geometry_source", "contract"),
                "operation_id": (operation or {}).get("operation_id") or record.get("operation_id"),
                "operation": (operation or {}).get("name") or record.get("operation_id"),
                "note": (operation or {}).get("note") or record.get("note") or "saved asset version",
                "current": False,
            })

        for record in records.values():
            if record.get("operation_id") == "op_init":
                add(record.get("checkpoint_id"))
                break
        for operation in self.history():
            add(operation.get("result_checkpoint"), operation)
        add(reference.get("checkpoint_id"))
        if not versions:
            add(current.get("checkpoint_id"))

        current_signature = self._version_signature(reference)
        current_version = None
        current_asset_index = -1
        for index, version in enumerate(versions):
            version["current"] = self._version_signature(version) == current_signature
            if version["current"]:
                current_version = version
                current_asset_index = sum(1 for previous in versions[:index] if previous.get("asset_id") == reference.get("asset_id"))
        current_checkpoint = current_version["checkpoint_id"] if current_version else reference.get("checkpoint_id")
        return {
            "schema_version": "0.1.0",
            "current_checkpoint": current_checkpoint,
            "current_version": current_version["version_id"] if current_version else None,
            "can_undo": reference is current and current_asset_index > 0,
            "versions": versions,
        }

    def undo(self) -> dict[str, Any]:
        """Restore the distinct asset version immediately before the current one."""

        current = self.current()
        listing = self.asset_versions(current.get("asset_id"))
        current_index = next((index for index, version in enumerate(listing["versions"]) if version["current"]), -1)
        if current_index <= 0:
            return {"status": "NOOP", "reason": "NO_PREVIOUS_VERSION", "current": self.current(), "versions": listing}
        current_version = listing["versions"][current_index]
        previous_version = listing["versions"][current_index - 1]
        restored = self.rollback(previous_version["checkpoint_id"])
        return {
            "status": "PASS",
            "action": "undo",
            "undone_version": current_version,
            "restored_version": previous_version,
            "current": restored,
        }

    def validate(self) -> dict[str, Any]:
        current = self.current()
        asset = self.load_current_asset()
        glb = self.store.read_bytes(current["glb_artifact"])
        meshes = None if current.get("geometry_source", "contract") != "contract" else meshes_for_asset(asset)
        agent_build = current.get("agent_build") if isinstance(current.get("agent_build"), dict) else {}
        quality_profile = "production" if agent_build.get("quality_profile") == "production" else None
        report = validate_asset_and_glb(asset, glb, artifact_id=current["glb_artifact"], meshes=meshes, quality_profile=quality_profile)
        qa_id = self.store.put_json(report, kind="qa-report", metadata={"asset_id": asset["asset_id"], "input_artifact_id": current["glb_artifact"]})
        current["qa_artifact"] = qa_id
        current["qa_status"] = report["status"]
        self._write_current(current)
        self._upsert_workspace_asset(current, asset)
        return report

    def edit_part(self, part_id: str, scales: dict[str, float], *, idempotency_key: str | None = None) -> dict[str, Any]:
        current = self.current()
        if current.get("geometry_source", "contract") != "contract":
            raise ProjectError("Generated assets must be edited through an agent build prompt")
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
        self._upsert_workspace_asset(self.current(), candidate)
        return {"operation": operation, "report": report, "current": self.current()}

    def replace_generated_asset(self, asset: dict[str, Any], glb: bytes, *, blend: bytes | None = None,
                                agent: str, prompt: str, run_id: str, workspace: str | None = None,
                                auto_fit_dimensions: bool = False, source: str = "blender",
                                operation_name: str = "asset.agent_build", quality_profile: str | None = None) -> dict[str, Any]:
        """Adopt a generated asset after contract and GLB validation."""

        candidate = normalize_asset(asset)
        report = validate_asset_and_glb(candidate, glb, meshes=None, quality_profile=quality_profile)
        fitted_dimensions = None
        if auto_fit_dimensions and report["status"] != "PASS" and all(
            check["status"] == "PASS" or check["check_id"] == "geometry.dimensions" for check in report["checks"]
        ):
            dimensions_check = next(check for check in report["checks"] if check["check_id"] == "geometry.dimensions")
            actual = dimensions_check.get("actual")
            if isinstance(actual, list) and len(actual) == 3 and all(isinstance(value, (int, float)) and value > 0 for value in actual):
                fitted_dimensions = {axis: round(float(value) * 1.02, 6) for axis, value in zip(("width", "depth", "height"), actual)}
                candidate["dimensions"] = fitted_dimensions
                glb = patch_glb_metadata(glb, candidate)
                report = validate_asset_and_glb(candidate, glb, meshes=None, quality_profile=quality_profile)
        if report["status"] != "PASS":
            return {"status": "FAIL", "report": report, "mutated": False}
        current = self.current()
        operation_id = _operation_id()
        source_label = source.replace("-", " ")
        before_checkpoint = self._create_checkpoint(current, parent=current.get("checkpoint_id"), operation_id=operation_id, note=f"before {source_label} generation")
        contract_id = self.store.put_bytes(asset_bytes(candidate), kind="asset-contract", metadata={"asset_id": candidate["asset_id"], "source": source})
        glb_id = self.store.put_bytes(glb, kind="glb", metadata={"asset_id": candidate["asset_id"], "contract_artifact": contract_id, "source": source})
        qa_id = self.store.put_json({**report, "artifact_id": glb_id}, kind="qa-report", metadata={"asset_id": candidate["asset_id"], "input_artifact_id": glb_id})
        blend_id = self.store.put_bytes(blend, kind="blend", metadata={"asset_id": candidate["asset_id"], "source": "blender-agent"}) if blend is not None else None
        agent_build = {"agent": agent, "run_id": run_id, "prompt": prompt}
        if workspace:
            agent_build["workspace"] = workspace
        if quality_profile:
            agent_build["quality_profile"] = quality_profile
        next_ref = {
            **current,
            "asset_id": candidate["asset_id"],
            "contract_artifact": contract_id,
            "glb_artifact": glb_id,
            "qa_artifact": qa_id,
            "qa_status": report["status"],
            "geometry_source": source,
            "agent_build": agent_build,
            "checkpoint_id": before_checkpoint,
        }
        if blend_id:
            next_ref["blend_artifact"] = blend_id
        result_checkpoint = self._create_checkpoint(next_ref, parent=before_checkpoint, operation_id=operation_id, note=f"after {source_label} generation")
        operation = {
            "schema_version": "0.1.0",
            "operation_id": operation_id,
            "name": operation_name,
            "version": "0.1",
            "agent": agent,
            "run_id": run_id,
            "input_checkpoint": before_checkpoint,
            "mutates": ["asset:contract", "artifact:glb", "artifact:blend" if blend_id else "artifact:glb"],
            "invalidates": [],
            "result_checkpoint": result_checkpoint,
            "status": "PASS",
        }
        self._append_operation(operation)
        self._write_atomic(self.root / "asset.yaml", asset_bytes(candidate))
        self._write_project_metadata(self.current())
        self._upsert_workspace_asset(current)
        self._upsert_workspace_asset(self.current(), candidate)
        result = {"status": "PASS", "mutated": True, "operation": operation, "report": report, "current": self.current()}
        if fitted_dimensions:
            result["dimensions_autofit"] = fitted_dimensions
        return result

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
