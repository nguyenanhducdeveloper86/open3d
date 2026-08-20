"""Deterministic, non-mutating asset quality checks."""

from __future__ import annotations

import math
from typing import Any

from .contracts import asset_digest, canonical_json, digest_bytes, normalize_asset
from .geometry import Mesh, mesh_stats, read_glb_json


def _check(check_id: str, passed: bool, expected: Any, actual: Any, *, affected: list[str] | None = None, hint: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "severity": "blocking" if not passed else "info",
        "expected": expected,
        "actual": actual,
    }
    if affected:
        result["affected_parts"] = affected
    if hint and not passed:
        result["repair_hint"] = hint
    return result


def _glb_mesh_stats(gltf: dict[str, Any]) -> dict[str, Any]:
    """Read bounded geometry stats from glTF accessors without decoding mesh data."""

    accessors = gltf.get("accessors", [])
    meshes = gltf.get("meshes", [])
    parts: set[str] = set()
    triangles = 0
    mins: list[float] | None = None
    maxs: list[float] | None = None
    for node in gltf.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(node.get("mesh"), int):
            continue
        node_extras = node.get("extras", {}) if isinstance(node.get("extras", {}), dict) else {}
        node_open3d = node_extras.get("open3d", {}) if isinstance(node_extras.get("open3d", {}), dict) else {}
        part_id = node_open3d.get("part_id") or node_extras.get("open3d_part_id")
        if isinstance(part_id, str):
            parts.add(part_id)
        mesh_index = node["mesh"]
        if mesh_index >= len(meshes) or not isinstance(meshes[mesh_index], dict):
            continue
        for primitive in meshes[mesh_index].get("primitives", []):
            if not isinstance(primitive, dict):
                continue
            position_index = primitive.get("attributes", {}).get("POSITION") if isinstance(primitive.get("attributes"), dict) else None
            if isinstance(position_index, int) and position_index < len(accessors):
                position = accessors[position_index]
                if isinstance(position, dict) and isinstance(position.get("min"), list) and isinstance(position.get("max"), list):
                    values_min = [float(value) for value in position["min"][:3]]
                    values_max = [float(value) for value in position["max"][:3]]
                    mins = values_min if mins is None else [min(left, right) for left, right in zip(mins, values_min)]
                    maxs = values_max if maxs is None else [max(left, right) for left, right in zip(maxs, values_max)]
            index = primitive.get("indices")
            if isinstance(index, int) and index < len(accessors) and isinstance(accessors[index], dict):
                triangles += int(accessors[index].get("count", 0)) // 3
            elif isinstance(position_index, int) and position_index < len(accessors):
                triangles += int(accessors[position_index].get("count", 0)) // 3
    bounds = None
    if mins is not None and maxs is not None:
        bounds = {"min": mins, "max": maxs, "size": [maxs[index] - mins[index] for index in range(3)]}
    return {"triangles": triangles, "parts": sorted(parts), "bounds": bounds}


def validate_asset_and_glb(asset: dict[str, Any], glb: bytes, *, artifact_id: str | None = None, meshes: list[Mesh] | None = None) -> dict[str, Any]:
    asset = normalize_asset(asset)
    checks: list[dict[str, Any]] = []
    gltf = None
    try:
        gltf = read_glb_json(glb)
        checks.append(_check("artifact.glb_header", True, "glTF 2.0", gltf.get("asset", {}).get("version")))
        declared_digest = gltf.get("extras", {}).get("open3d", {}).get("asset_digest")
        checks.append(_check("artifact.contract_identity", declared_digest == asset_digest(asset), asset_digest(asset), declared_digest, hint="regenerate_glb"))
    except (ValueError, KeyError, TypeError) as exc:
        checks.append(_check("artifact.glb_header", False, "valid GLB", str(exc), hint="regenerate_glb"))

    expected_parts = sorted(part["part_id"] for part in asset["parts"])
    if meshes is None:
        stats = _glb_mesh_stats(gltf or {})
        actual_parts = stats["parts"]
    else:
        stats = mesh_stats(meshes)
        actual_parts = sorted(mesh.part_id for mesh in meshes)
    checks.append(_check("geometry.part_identity", actual_parts == expected_parts, expected_parts, actual_parts, hint="restore_semantic_part_ids"))

    triangles = int(stats["triangles"])
    max_triangles = int(asset["geometry"]["triangle_budget"]["max"])
    checks.append(_check("geometry.triangle_budget", triangles <= max_triangles, {"max": max_triangles}, {"triangles": triangles}, hint="reduce_geometry"))

    if meshes is None:
        bounds_values = [value for bound in (stats.get("bounds") or {}).values() if isinstance(bound, list) for value in bound]
        finite = bool(bounds_values) and all(math.isfinite(float(number)) for number in bounds_values)
    else:
        finite = all(math.isfinite(number) for mesh in meshes for point in mesh.positions for number in point)
    checks.append(_check("geometry.finite", finite, True, finite, hint="remove_non_finite_vertices"))

    non_degenerate = triangles > 0 if meshes is None else all(len(mesh.indices) % 3 == 0 and mesh.triangles > 0 for mesh in meshes)
    checks.append(_check("geometry.non_degenerate", non_degenerate, True, non_degenerate, hint="repair_mesh"))

    dimensions = asset["dimensions"]
    bounds = stats.get("bounds")
    size = bounds["size"] if bounds else [0, 0, 0]
    expected_size = [dimensions["width"], dimensions["depth"], dimensions["height"]]
    tolerance = 1e-6
    fits = all(size[index] <= expected_size[index] + tolerance for index in range(3))
    checks.append(_check("geometry.dimensions", fits, expected_size, size, hint="adjust_dimensions_or_primitives"))

    passed = all(check["status"] == "PASS" for check in checks)
    report_without_id = {
        "schema_version": "0.1.0",
        "asset_id": asset["asset_id"],
        "artifact_id": artifact_id,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {"blocking_failures": sum(check["status"] == "FAIL" for check in checks)},
    }
    report_without_id = {key: value for key, value in report_without_id.items() if value is not None}
    report_without_id["report_id"] = digest_bytes(canonical_json(report_without_id))
    return report_without_id
