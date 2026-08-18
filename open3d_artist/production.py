"""Harness-neutral, local-only production-agent protocol."""

from __future__ import annotations

import json
import hashlib
import hmac
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .contracts import canonical_json, digest_bytes, digest_json
from .project import Project, ProjectError
from .workers import BlenderSandbox

REQUIRED_VIEWS = ["HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"]
ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples/production-qualification/catalog.json"
FIXTURE = ROOT / "tools/production_fixture/generate_fixture.py"
_RECIPE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+$")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ProjectError(f"invalid production artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ProjectError(f"production artifact must be an object: {path}")
    return value


def catalog() -> list[dict[str, Any]]:
    value = _read(CATALOG)
    entries = value.get("recipes")
    if value.get("schema_version") != "0.1.0" or not isinstance(entries, list) or not entries:
        raise ProjectError("production catalog is invalid")
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"recipe_id", "recipe", "asset_id"}:
            raise ProjectError("production catalog entry is invalid")
        recipe_id, recipe_name = entry["recipe_id"], entry["recipe"]
        if not isinstance(recipe_id, str) or not _RECIPE_ID.fullmatch(recipe_id) or not isinstance(recipe_name, str) or Path(recipe_name).name != recipe_name:
            raise ProjectError("production catalog entry is not allowlisted")
        path = (CATALOG.parent / recipe_name).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ProjectError("production catalog recipe must stay inside the repository") from exc
        recipe = _read(path)
        if recipe.get("recipe_id") != recipe_id or recipe.get("asset", {}).get("asset_id") != entry["asset_id"]:
            raise ProjectError("production catalog recipe metadata does not match")
        result.append({"recipe_id": recipe_id, "recipe": path, "asset_id": entry["asset_id"]})
    return result


def _recipe_for(recipe_id: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(recipe_id, str) or not _RECIPE_ID.fullmatch(recipe_id):
        raise ProjectError("recipe_id must be a checked-in recipe ID")
    entry = next((item for item in catalog() if item["recipe_id"] == recipe_id), None)
    if entry is None:
        raise ProjectError(f"unknown recipe_id: {recipe_id}")
    path = entry["recipe"]
    recipe = _read(path)
    if recipe.get("recipe_id") != recipe_id or not isinstance(recipe.get("prompt"), str) or not recipe["prompt"].strip():
        raise ProjectError("recipe prompt metadata is required")
    reference = recipe.get("reference")
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        raise ProjectError("recipe reference metadata is required")
    reference_path = (path.parent / reference["path"]).resolve()
    try:
        reference_path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ProjectError("recipe reference must stay inside the repository") from exc
    if not reference_path.is_file() or reference.get("sha256") != digest_bytes(reference_path.read_bytes())[7:]:
        raise ProjectError("recipe reference is missing or has the wrong sha256")
    if recipe.get("views") != REQUIRED_VIEWS:
        raise ProjectError(f"recipe views must be exactly {REQUIRED_VIEWS}")
    return path, recipe


def validate_brief(brief: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    if not isinstance(brief, dict):
        raise ProjectError("brief must be an object")
    allowed = {"schema_version", "brief_id", "prompt", "reference", "recipe_id", "views"}
    if set(brief) - allowed:
        raise ProjectError("brief contains unsupported fields")
    if brief.get("schema_version", "0.1.0") != "0.1.0" or not isinstance(brief.get("brief_id"), str) or not brief["brief_id"].strip():
        raise ProjectError("brief schema_version and brief_id are required")
    if not isinstance(brief.get("prompt"), str) or not brief["prompt"].strip():
        raise ProjectError("brief prompt metadata is required")
    if brief.get("views") != REQUIRED_VIEWS:
        raise ProjectError(f"brief views must be exactly {REQUIRED_VIEWS}")
    reference = brief.get("reference")
    if not isinstance(reference, dict) or set(reference) - {"path", "kind", "sha256"} or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str):
        raise ProjectError("brief reference metadata is required")
    recipe_path, recipe = _recipe_for(brief.get("recipe_id"))
    if brief["prompt"] != recipe["prompt"] or reference != recipe["reference"]:
        raise ProjectError("brief prompt/reference must match the checked-in recipe")
    return recipe_path, recipe


def run_production(brief: dict[str, Any], output: str | Path, *, timeout: float = 300) -> dict[str, Any]:
    recipe_path, recipe = validate_brief(brief)
    if not FIXTURE.is_file():
        raise ProjectError("production fixture is missing")
    output_path = Path(output).resolve()
    worker_result = BlenderSandbox(ROOT).run_production_fixture(recipe_path, output_path, timeout=timeout)
    if worker_result["process"]["status"] != "PASS":
        raise ProjectError(f"production fixture failed: {worker_result['process']['output'][-1000:]}")
    evidence, qa = _read(output_path / "evidence.json"), _read(output_path / "qa.json")
    if evidence.get("required_views") != REQUIRED_VIEWS or set(qa.get("renders", {})) != set(REQUIRED_VIEWS):
        raise ProjectError("production fixture did not emit all required views")
    project = Project(output_path)
    validation, current = project.validate(), project.current()
    reference_manifest = _reference_manifest(output_path, recipe)
    (output_path / "reference_manifest.json").write_bytes(canonical_json(reference_manifest))
    promotion = {"state": "LOCAL_ONLY_NOT_APPROVED", "external_visual_qa": "UNAVAILABLE", "unity_evidence": "UNAVAILABLE"}
    (output_path / "promotion.json").write_text(json.dumps(promotion, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": "0.2.0", "status": "PASS", "brief_id": brief["brief_id"], "recipe_id": recipe["recipe_id"],
        "brief": {"id": brief["brief_id"], "prompt": brief["prompt"], "reference": brief["reference"]},
        "recipe": {"id": recipe["recipe_id"], "source": "checked-in-registry"}, "views": {"required": REQUIRED_VIEWS, "local_qa": "PASS"},
        "artifacts": {"blend": f"{recipe['asset']['asset_id']}.blend", "glb": current["glb_artifact"], "renders": [f"{view}.png" for view in REQUIRED_VIEWS], "qa": current["qa_artifact"], "evidence": "evidence.json", "reference_manifest": "reference_manifest.json"},
        "artifact_refs": {"glb": current["glb_artifact"], "qa": current["qa_artifact"], "evidence": "evidence.json"},
        "sandbox": {"kind": worker_result["sandbox"], "network": "DENIED"}, "network_denied": True, "external_gates": {"visual_qa": "UNAVAILABLE", "unity": "UNAVAILABLE"}, "promotion": promotion,
    }
    receipt["adapter_availability"] = {"provider": "UNAVAILABLE", "reference": "AVAILABLE", "visual_qa": "UNAVAILABLE", "unity": "UNAVAILABLE"}
    receipt["reference_manifest"] = reference_manifest
    receipt["artifacts_manifest"] = _manifest(output_path, recipe["asset"]["asset_id"])
    receipt["release"] = release_metadata(receipt)
    (output_path / "run_receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "receipt": receipt, "run_receipt": receipt, "promotion": promotion, "validation": validation, "current": {"glb": current["glb_artifact"], "qa": current["qa_artifact"]}, "viewer": {"route": "/", "artifact_route": "/api/artifact/current"}}


def _manifest(root: Path, asset_id: str) -> dict[str, Any]:
    names = [f"{asset_id}.blend", f"{asset_id}.glb", "asset.yaml", "recipe.json", "provenance.json", "qa.json", "evidence.json", "reference.svg", "reference_manifest.json"] + [f"{view}.png" for view in REQUIRED_VIEWS]
    files = []
    for name in names:
        raw_path = root / name
        path = raw_path.resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ProjectError("production artifact path escapes run") from exc
        if not path.is_file() or raw_path.is_symlink():
            raise ProjectError(f"production artifact is missing: {name}")
        files.append({"path": name, "sha256": digest_bytes(path.read_bytes())})
    return {"schema_version": "0.1.0", "files": files}


def _reference_manifest(root: Path, recipe: dict[str, Any]) -> dict[str, Any]:
    reference = recipe["reference"]
    source = (ROOT / "examples/production-qualification" / Path(reference["path"]).name).resolve()
    if not source.is_file() or digest_bytes(source.read_bytes())[7:] != reference["sha256"]:
        raise ProjectError("checked-in reference is missing or has the wrong sha256")
    target = root / "reference.svg"
    target.write_bytes(source.read_bytes())
    attachments = [{"role": "REFERENCE_SAMPLE", "path": "reference.svg", "sha256": digest_bytes(target.read_bytes())}]
    attachments.extend({"role": "CANDIDATE", "view": view, "path": f"{view}.png", "sha256": digest_bytes((root / f"{view}.png").read_bytes())} for view in REQUIRED_VIEWS)
    visual_qa = _local_visual_qa(root, target, root / "HERO_3Q.png")
    return {"schema_version": "0.1.0", "asset_id": recipe["asset"]["asset_id"], "required_views": REQUIRED_VIEWS, "attachments": attachments, "reference": {"status": "AVAILABLE", "kind": reference["kind"]}, "candidate": {"status": "LOCAL_TECHNICAL_PASS"}, "visual_qa": visual_qa, "repair": {"status": "UNAVAILABLE_REPAIR_REQUIRED", "max_attempts": 3, "attempts": 0, "BEST_VERSION": "v001", "best_version": "v001", "rollback": {"available": True, "version": "v001", "geometry_mutated": False, "reason": "No geometry-changing repair was run."}}, "approval": "LOCAL_ONLY_NOT_APPROVED"}


def _safe_raster_source(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ProjectError("visual QA source must stay inside the run") from exc
    if path.is_symlink() or not path.is_file() or resolved.stat().st_size > 10 * 1024 * 1024:
        raise ProjectError("visual QA source is unsafe")
    return resolved


def _rasterize(path: Path, output: Path, root: Path) -> bytes:
    source = _safe_raster_source(path, root)
    # Fixed, bounded invocation; inputs never contribute options or commands.
    command = ["convert", "-font", "/System/Library/Fonts/Helvetica.ttc", str(source), "-background", "#ffffff", "-alpha", "remove", "-alpha", "off", "-resize", "256x256!", "-depth", "8", f"RGB:{output}"]
    try:
        subprocess.run(command, cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProjectError("local ImageMagick visual QA failed") from exc
    raw = output.read_bytes()
    if len(raw) != 256 * 256 * 3:
        raise ProjectError("local visual QA raster has unexpected dimensions")
    return raw


def _local_visual_qa(root: Path, reference: Path, candidate: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="open3d-visual-qa-") as directory:
        work = Path(directory)
        reference_pixels = _rasterize(reference, work / "reference.rgb", root)
        candidate_pixels = _rasterize(candidate, work / "candidate.rgb", root)
    differences = [abs(left - right) for left, right in zip(reference_pixels, candidate_pixels)]
    mean_absolute_error = sum(differences) / len(differences)
    similarity = round(1.0 - mean_absolute_error / 255.0, 6)
    matched = ["REFERENCE_RASTER", "HERO_3Q_CANDIDATE", "RASTER_DIMENSIONS"]
    mismatched = []
    if similarity < 0.9:
        mismatched.append("HERO_3Q_VISUAL_SIMILARITY")
    else:
        matched.append("HERO_3Q_VISUAL_SIMILARITY")
    return {"status": "UNAVAILABLE_REPAIR_REQUIRED", "approval": "LOCAL_ONLY_NOT_APPROVED", "method": "LOCAL_IMAGEMAGICK_RGB_MAE", "command": "convert -font /System/Library/Fonts/Helvetica.ttc <checked-in-path> -background #ffffff -alpha remove -alpha off -resize 256x256! -depth 8 RGB:<temporary-path>", "dimensions": {"width": 256, "height": 256, "channels": 3}, "reference_digest": digest_bytes(reference.read_bytes()), "candidate_digest": digest_bytes(candidate.read_bytes()), "similarity": similarity, "mean_absolute_error": round(mean_absolute_error, 6), "differing_bytes": sum(value != 0 for value in differences), "matched_components": matched, "mismatched_components": mismatched, "next_action": "REPAIR_REQUIRED_BEFORE_APPROVAL", "scope": "PACK_PENDING_FULL_6_VIEW"}


def release_metadata(receipt: dict[str, Any]) -> dict[str, Any]:
    value = {"schema_version": "0.1.0", "receipt_digest": digest_json(receipt), "approval": "LOCAL_ONLY_NOT_APPROVED", "external_visual_qa": "UNAVAILABLE", "unity": "UNAVAILABLE"}
    key = __import__("os").environ.get("OPEN3D_RELEASE_SIGNING_KEY")
    if key:
        value["signature"] = hmac.new(key.encode(), canonical_json(value), hashlib.sha256).hexdigest()
    return value


def _validate_manifest(root: Path, receipt: dict[str, Any]) -> dict[str, Path]:
    manifest = receipt.get("artifacts_manifest", {})
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list) or len(files) != 15:
        raise ProjectError("production artifact manifest is incomplete")
    result = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", entry["path"]):
            raise ProjectError("unsafe production artifact path")
        raw_path = root / entry["path"]
        path = raw_path.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ProjectError("production artifact path escapes run") from exc
        if not path.is_file() or raw_path.is_symlink() or entry.get("sha256") != digest_bytes(path.read_bytes()):
            raise ProjectError(f"production artifact digest mismatch: {entry.get('path')}")
        result[entry["path"]] = path
    return result


def promote_production(run: str | Path, project: str | Path) -> dict[str, Any]:
    run_root = Path(run).resolve()
    if not run_root.is_dir() or run_root.is_symlink():
        raise ProjectError("run must be a directory")
    receipt = _read(run_root / "run_receipt.json")
    files = _validate_manifest(run_root, receipt)
    if receipt.get("promotion", {}).get("state") == "APPROVED":
        raise ProjectError("local production runs cannot be APPROVED")
    destination = Path(project).resolve()
    if destination == run_root or run_root in destination.parents:
        raise ProjectError("project destination must be separate from run")
    destination.mkdir(parents=True, exist_ok=True)
    project_obj = Project.init(destination, files["asset.yaml"])
    before = project_obj.current()
    checkpoint = project_obj.checkpoint("before production promotion")
    refs = {"renders": {}, "source": {}, "provenance": None, "evidence": None, "qa": None, "blend": None}
    for name, path in files.items():
        artifact = project_obj.store.put_bytes(path.read_bytes(), kind="production-" + path.suffix.lstrip("."), metadata={"source_path": name})
        refs["source"][name] = artifact
        if name.endswith(".png"):
            refs["renders"][Path(name).stem] = artifact
        elif name == "provenance.json": refs["provenance"] = artifact
        elif name == "evidence.json": refs["evidence"] = artifact
        elif name == "qa.json": refs["qa"] = artifact
        elif name.endswith(".blend"): refs["blend"] = artifact
    current = {**before, "production_receipt": project_obj.store.put_json(receipt, kind="production-receipt"), "production_artifacts": refs, "promotion_checkpoint": checkpoint, "release": project_obj.store.put_json(receipt["release"], kind="release-metadata")}
    result_checkpoint = project_obj._create_checkpoint(current, parent=checkpoint, operation_id="production_promote", note="production release promotion")
    current["checkpoint_id"] = result_checkpoint
    project_obj._write_current(current)
    promotion = {"state": "PROMOTED_LOCAL_NOT_APPROVED", "checkpoint": checkpoint, "result_checkpoint": result_checkpoint, "external_visual_qa": "UNAVAILABLE", "unity_evidence": "UNAVAILABLE", "release_verified": verify_release(project_obj)}
    (destination / "run_receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (destination / "release.json").write_text(json.dumps(receipt["release"], sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (destination / "promotion.json").write_text(json.dumps(promotion, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "promotion": promotion, "release": receipt["release"], "current": current, "receipt": receipt}


def verify_release(project: Project) -> dict[str, Any]:
    current = project.current()
    refs = current.get("production_artifacts")
    if not isinstance(refs, dict): return {"status": "UNAVAILABLE", "reason": "no production promotion"}
    checked = []
    for artifact in refs.get("source", {}).values():
        project.store.read_bytes(artifact); checked.append(artifact)
    receipt = project.store.read_json(current["production_receipt"])
    release = project.store.read_json(current["release"])
    unsigned = dict(receipt); unsigned.pop("release", None)
    if release.get("receipt_digest") != digest_json(unsigned):
        raise ProjectError("release receipt digest mismatch")
    key = __import__("os").environ.get("OPEN3D_RELEASE_SIGNING_KEY")
    signature = "UNAVAILABLE"
    if key:
        signed = dict(release); supplied = signed.pop("signature", None)
        signature = "PASS" if supplied == hmac.new(key.encode(), canonical_json(signed), hashlib.sha256).hexdigest() else "FAIL"
        if signature == "FAIL": raise ProjectError("release signature mismatch")
    return {"status": "PASS", "artifacts": len(checked), "approval": "LOCAL_ONLY_NOT_APPROVED", "external_visual_qa": "UNAVAILABLE", "unity": "UNAVAILABLE", "signature": signature}


def production_state(project: Project) -> dict[str, Any]:
    root = project.root
    receipt = _read(root / "run_receipt.json")
    current = project.current()
    artifacts = current.get("production_artifacts", {})
    return {"receipt": receipt, "run_receipt": receipt, "promotion": _read(root / "promotion.json"), "release": _read(root / "release.json") if (root / "release.json").is_file() else receipt.get("release", {}), "release_verification": verify_release(project), "renders": {view: f"/api/production/render/{view}" for view in REQUIRED_VIEWS if view in artifacts.get("renders", {})}, "adapters": receipt.get("adapter_availability", {}), "validation": project.validate(), "current": current, "viewer": {"route": "/", "artifact_route": "/api/artifact/current"}}
