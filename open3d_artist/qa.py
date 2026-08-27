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


def _matrix_multiply(left: list[float], right: list[float]) -> list[float]:
    return [sum(left[row * 4 + index] * right[index * 4 + column] for index in range(4)) for row in range(4) for column in range(4)]


def _node_matrix(node: dict[str, Any]) -> list[float]:
    matrix = node.get("matrix")
    if isinstance(matrix, list) and len(matrix) == 16:
        return [float(matrix[column * 4 + row]) for row in range(4) for column in range(4)]
    translation = node.get("translation", [0.0, 0.0, 0.0])
    scale = node.get("scale", [1.0, 1.0, 1.0])
    rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    tx, ty, tz = (float(value) for value in translation)
    sx, sy, sz = (float(value) for value in scale)
    x, y, z, w = (float(value) for value in rotation)
    return [
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y - z * w)) * sy, (2 * (x * z + y * w)) * sz, tx,
        (2 * (x * y + z * w)) * sx, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z - x * w)) * sz, ty,
        (2 * (x * z - y * w)) * sx, (2 * (y * z + x * w)) * sy, (1 - 2 * (x * x + y * y)) * sz, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def _transform_point(matrix: list[float], point: list[float]) -> list[float]:
    return [sum(matrix[row * 4 + index] * (point[index] if index < 3 else 1.0) for index in range(4)) for row in range(3)]


def _glb_mesh_stats(gltf: dict[str, Any]) -> dict[str, Any]:
    """Read bounded geometry stats from glTF accessors without decoding mesh data."""

    accessors = gltf.get("accessors", [])
    meshes = gltf.get("meshes", [])
    parts: set[str] = set()
    triangles = 0
    mins: list[float] | None = None
    maxs: list[float] | None = None
    nodes = gltf.get("nodes", [])
    parents: dict[int, int] = {}
    for parent_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        for child_index in node.get("children", []):
            if isinstance(child_index, int):
                parents[child_index] = parent_index

    world_matrices: dict[int, list[float]] = {}

    def world_matrix(index: int) -> list[float]:
        if index in world_matrices:
            return world_matrices[index]
        node = nodes[index] if 0 <= index < len(nodes) and isinstance(nodes[index], dict) else {}
        local = _node_matrix(node)
        parent = parents.get(index)
        result = _matrix_multiply(world_matrix(parent), local) if parent is not None and parent != index else local
        world_matrices[index] = result
        return result

    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("mesh"), int):
            continue
        matrix = world_matrix(node_index)
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
                    corners = [[x, y, z] for x in (values_min[0], values_max[0]) for y in (values_min[1], values_max[1]) for z in (values_min[2], values_max[2])]
                    transformed = [_transform_point(matrix, corner) for corner in corners]
                    values_min = [min(point[index] for point in transformed) for index in range(3)]
                    values_max = [max(point[index] for point in transformed) for index in range(3)]
                    mins = values_min if mins is None else [min(left, right) for left, right in zip(mins, values_min)]
                    maxs = values_max if maxs is None else [max(left, right) for left, right in zip(maxs, values_max)]
            index = primitive.get("indices")
            if isinstance(index, int) and index < len(accessors) and isinstance(accessors[index], dict):
                triangles += int(accessors[index].get("count", 0)) // 3
            elif isinstance(position_index, int) and position_index < len(accessors):
                triangles += int(accessors[position_index].get("count", 0)) // 3
    bounds = None
    if mins is not None and maxs is not None:
        generator = str(gltf.get("asset", {}).get("generator", "")).lower()
        if "blender" in generator:
            # Blender exports Z-up scenes as glTF Y-up: x, -z, y is Open3D's x, y, z.
            mins, maxs = [mins[0], -maxs[2], mins[1]], [maxs[0], -mins[2], maxs[1]]
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
