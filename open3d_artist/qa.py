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


def validate_asset_and_glb(asset: dict[str, Any], glb: bytes, *, artifact_id: str | None = None, meshes: list[Mesh] | None = None) -> dict[str, Any]:
    asset = normalize_asset(asset)
    meshes = meshes or []
    checks: list[dict[str, Any]] = []
    try:
        gltf = read_glb_json(glb)
        checks.append(_check("artifact.glb_header", True, "glTF 2.0", gltf.get("asset", {}).get("version")))
        declared_digest = gltf.get("extras", {}).get("open3d", {}).get("asset_digest")
        checks.append(_check("artifact.contract_identity", declared_digest == asset_digest(asset), asset_digest(asset), declared_digest, hint="regenerate_glb"))
        node_parts = sorted(
            node.get("extras", {}).get("open3d", {}).get("part_id")
            for node in gltf.get("nodes", [])
            if node.get("extras", {}).get("open3d", {}).get("part_id")
        )
    except (ValueError, KeyError, TypeError) as exc:
        checks.append(_check("artifact.glb_header", False, "valid GLB", str(exc), hint="regenerate_glb"))
        node_parts = []

    expected_parts = sorted(part["part_id"] for part in asset["parts"])
    actual_parts = sorted(mesh.part_id for mesh in meshes) if meshes else node_parts
    checks.append(_check("geometry.part_identity", actual_parts == expected_parts, expected_parts, actual_parts, hint="restore_semantic_part_ids"))

    stats = mesh_stats(meshes)
    triangles = int(stats["triangles"])
    max_triangles = int(asset["geometry"]["triangle_budget"]["max"])
    checks.append(_check("geometry.triangle_budget", triangles <= max_triangles, {"max": max_triangles}, {"triangles": triangles}, hint="reduce_geometry"))

    finite = all(math.isfinite(number) for mesh in meshes for point in mesh.positions for number in point)
    checks.append(_check("geometry.finite", finite, True, finite, hint="remove_non_finite_vertices"))

    non_degenerate = all(len(mesh.indices) % 3 == 0 and mesh.triangles > 0 for mesh in meshes)
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
