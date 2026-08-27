"""Deterministic, non-mutating asset quality checks."""

from __future__ import annotations

import math
import struct
from typing import Any

from .contracts import asset_digest, canonical_json, digest_bytes, normalize_asset
from .geometry import Mesh, mesh_stats, read_glb_json


PRODUCTION_REQUIRED_DETAIL_TAGS = (
    "primary_form",
    "surface_breakup",
    "edge_treatment",
    "material_breakup",
)


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


def _detail_tags(value: Any) -> set[str]:
    if isinstance(value, str):
        return {item.strip() for item in value.replace(";", ",").replace("|", ",").split(",") if item.strip()}
    if isinstance(value, list):
        return {item.strip() for item in value if isinstance(item, str) and item.strip()}
    return set()


def _glb_binary(data: bytes) -> bytes | None:
    if len(data) < 20 or data[:4] != b"glTF":
        return None
    json_length = struct.unpack_from("<I", data, 12)[0]
    offset = 20 + json_length
    while offset + 8 <= len(data):
        length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start, end = offset + 8, offset + 8 + length
        if end > len(data):
            return None
        if chunk_type == b"BIN\x00":
            return data[start:end]
        offset = end
    return None


def _glb_values(gltf: dict[str, Any], binary: bytes, accessor_index: int, *, vector: bool) -> list[Any] | None:
    accessors = gltf.get("accessors", [])
    views = gltf.get("bufferViews", [])
    if not isinstance(accessor_index, int) or accessor_index >= len(accessors):
        return None
    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict) or not isinstance(accessor.get("bufferView"), int):
        return None
    view_index = accessor["bufferView"]
    if view_index >= len(views) or not isinstance(views[view_index], dict):
        return None
    view = views[view_index]
    component_type = accessor.get("componentType")
    expected = (5126, "<3f", 12) if vector else ({5121: (5121, "<B", 1), 5123: (5123, "<H", 2), 5125: (5125, "<I", 4)}.get(component_type) or (0, "", 0))
    if vector:
        if component_type != expected[0] or accessor.get("type") != "VEC3":
            return None
        _, fmt, item_size = expected
    else:
        if expected[0] == 0 or accessor.get("type") != "SCALAR":
            return None
        _, fmt, item_size = expected
    count = accessor.get("count")
    if not isinstance(count, int) or count < 1 or count > 2_000_000:
        return None
    stride = int(view.get("byteStride", item_size))
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    if stride < item_size or start < 0 or start + (count - 1) * stride + item_size > len(binary):
        return None
    try:
        return [struct.unpack_from(fmt, binary, start + index * stride) for index in range(count)]
    except struct.error:
        return None


def _glb_thin_spans(gltf: dict[str, Any], data: bytes) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    binary = _glb_binary(data)
    if binary is None:
        return "UNAVAILABLE", {}
    nodes = gltf.get("nodes", [])
    meshes = gltf.get("meshes", [])
    result: dict[str, list[dict[str, Any]]] = {}
    components_by_part: dict[str, list[dict[str, Any]]] = {}
    try:
        for node in nodes:
            if not isinstance(node, dict) or not isinstance(node.get("mesh"), int):
                continue
            extras = node.get("extras", {}) if isinstance(node.get("extras", {}), dict) else {}
            open3d = extras.get("open3d", {}) if isinstance(extras.get("open3d", {}), dict) else {}
            part_id = open3d.get("part_id") or extras.get("open3d_part_id")
            mesh_index = node["mesh"]
            if not isinstance(part_id, str) or mesh_index >= len(meshes) or not isinstance(meshes[mesh_index], dict):
                continue
            matrix = _node_matrix(node)
            for primitive in meshes[mesh_index].get("primitives", []):
                if not isinstance(primitive, dict):
                    continue
                attributes = primitive.get("attributes") if isinstance(primitive.get("attributes"), dict) else {}
                positions = _glb_values(gltf, binary, attributes.get("POSITION"), vector=True)
                if not positions:
                    return "UNAVAILABLE", {}
                indices = _glb_values(gltf, binary, primitive.get("indices"), vector=False) if primitive.get("indices") is not None else [(index,) for index in range(len(positions))]
                if not indices or len(indices) % 3:
                    return "UNAVAILABLE", {}
                welded: dict[tuple[float, float, float], int] = {}
                world_positions: list[tuple[float, float, float]] = []
                vertex_ids: list[int] = []
                for position in positions:
                    world = tuple(_transform_point(matrix, list(position)))
                    key = tuple(round(value, 5) for value in world)
                    vertex_ids.append(welded.setdefault(key, len(welded)))
                    if len(world_positions) < len(welded):
                        world_positions.append(world)
                parent = list(range(len(welded)))

                def find(value: int) -> int:
                    while parent[value] != value:
                        parent[value] = parent[parent[value]]
                        value = parent[value]
                    return value

                def union(left: int, right: int) -> None:
                    left, right = find(left), find(right)
                    if left != right:
                        parent[right] = left

                triangle_ids: list[tuple[int, int, int]] = []
                for offset in range(0, len(indices), 3):
                    triangle = tuple(vertex_ids[int(indices[offset + item][0])] for item in range(3))
                    triangle_ids.append(triangle)
                    union(triangle[0], triangle[1])
                    union(triangle[1], triangle[2])
                components: dict[int, dict[str, Any]] = {}
                for triangle in triangle_ids:
                    root = find(triangle[0])
                    component = components.setdefault(root, {"triangles": 0, "min": [float("inf")] * 3, "max": [float("-inf")] * 3})
                    component["triangles"] += 1
                    for vertex in triangle:
                        point = world_positions[vertex]
                        for axis in range(3):
                            component["min"][axis] = min(component["min"][axis], point[axis])
                            component["max"][axis] = max(component["max"][axis], point[axis])
                for component in components.values():
                    dimensions = [round(component["max"][axis] - component["min"][axis], 5) for axis in range(3)]
                    components_by_part.setdefault(part_id, []).append({"triangles": component["triangles"], "dimensions": dimensions, "min": component["min"], "max": component["max"]})
        for part_id, part_components in components_by_part.items():
            for component in part_components:
                dimensions = component["dimensions"]
                longest, middle, shortest = sorted(dimensions, reverse=True)
                if longest < 2.0 or middle > 0.18 or shortest > 0.18:
                    continue
                # A fascia/eave is allowed when it overlaps a broad roof mass;
                # an isolated long rod is the artifact this check is meant to
                # catch. The old check rejected legitimate supported trim.
                supported = False
                for other in part_components:
                    if other is component:
                        continue
                    other_dimensions = other["dimensions"]
                    other_longest, other_middle, _ = sorted(other_dimensions, reverse=True)
                    if other_longest < longest * 0.65 or other_middle <= 0.3:
                        continue
                    if all(
                        min(component["max"][axis], other["max"][axis]) + 0.08 >= max(component["min"][axis], other["min"][axis])
                        for axis in range(3)
                    ):
                        supported = True
                        break
                if not supported:
                    result.setdefault(part_id, []).append({"triangles": component["triangles"], "dimensions": dimensions})
    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
        return "UNAVAILABLE", {}
    return "PASS", result


def _glb_mesh_stats(gltf: dict[str, Any], data: bytes | None = None) -> dict[str, Any]:
    """Read bounded geometry stats from glTF accessors without decoding mesh data."""

    accessors = gltf.get("accessors", [])
    meshes = gltf.get("meshes", [])
    parts: set[str] = set()
    triangles = 0
    mins: list[float] | None = None
    maxs: list[float] | None = None
    part_stats: dict[str, dict[str, Any]] = {}
    part_node_counts: dict[str, int] = {}
    mesh_nodes = 0
    unlabeled_mesh_nodes = 0
    primitives_without_normals = 0
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
        mesh_nodes += 1
        matrix = world_matrix(node_index)
        node_extras = node.get("extras", {}) if isinstance(node.get("extras", {}), dict) else {}
        node_open3d = node_extras.get("open3d", {}) if isinstance(node_extras.get("open3d", {}), dict) else {}
        part_id = node_open3d.get("part_id") or node_extras.get("open3d_part_id")
        if isinstance(part_id, str):
            parts.add(part_id)
            part_stat = part_stats.setdefault(part_id, {"triangles": 0, "primitives": 0, "materials": set(), "detail_tags": set()})
            part_node_counts[part_id] = part_node_counts.get(part_id, 0) + 1
            part_stat["detail_tags"].update(_detail_tags(node_extras.get("open3d_detail_tags")))
            part_stat["detail_tags"].update(_detail_tags(node_open3d.get("detail_tags")))
        else:
            part_stat = None
            unlabeled_mesh_nodes += 1
        mesh_index = node["mesh"]
        if mesh_index >= len(meshes) or not isinstance(meshes[mesh_index], dict):
            continue
        for primitive in meshes[mesh_index].get("primitives", []):
            if not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes") if isinstance(primitive.get("attributes"), dict) else {}
            if not isinstance(attributes.get("NORMAL"), int):
                primitives_without_normals += 1
            if part_stat is not None:
                part_stat["primitives"] += 1
                material = primitive.get("material")
                if isinstance(material, int):
                    part_stat["materials"].add(material)
            position_index = attributes.get("POSITION")
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
            primitive_triangles = 0
            if isinstance(index, int) and index < len(accessors) and isinstance(accessors[index], dict):
                primitive_triangles = int(accessors[index].get("count", 0)) // 3
            elif isinstance(position_index, int) and position_index < len(accessors):
                primitive_triangles = int(accessors[position_index].get("count", 0)) // 3
            triangles += primitive_triangles
            if part_stat is not None:
                part_stat["triangles"] += primitive_triangles
    bounds = None
    if mins is not None and maxs is not None:
        generator = str(gltf.get("asset", {}).get("generator", "")).lower()
        if "blender" in generator:
            # Blender exports Z-up scenes as glTF Y-up: x, -z, y is Open3D's x, y, z.
            mins, maxs = [mins[0], -maxs[2], mins[1]], [maxs[0], -mins[2], maxs[1]]
        bounds = {"min": mins, "max": maxs, "size": [maxs[index] - mins[index] for index in range(3)]}
    return {
        "triangles": triangles,
        "parts": sorted(parts),
        "bounds": bounds,
        "mesh_nodes": mesh_nodes,
        "unlabeled_mesh_nodes": unlabeled_mesh_nodes,
        "primitives_without_normals": primitives_without_normals,
        "part_node_counts": part_node_counts,
        "component_analysis": "NOT_RUN",
        "thin_spans": {},
        "part_stats": {
            part_id: {
                **value,
                "materials": sorted(value["materials"]),
                "detail_tags": sorted(value["detail_tags"]),
            }
            for part_id, value in sorted(part_stats.items())
        },
    }


def _add_component_analysis(stats: dict[str, Any], gltf: dict[str, Any], data: bytes) -> dict[str, Any]:
    status, thin_spans = _glb_thin_spans(gltf, data)
    stats["component_analysis"], stats["thin_spans"] = status, thin_spans
    return stats


def _production_quality_checks(asset: dict[str, Any], gltf: dict[str, Any] | None, stats: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    spec = metadata.get("quality_gate") if isinstance(metadata.get("quality_gate"), dict) else {}
    expected_parts = sorted(part["part_id"] for part in asset["parts"])
    required_tags = set(PRODUCTION_REQUIRED_DETAIL_TAGS)
    declared_tags = set(spec.get("required_detail_tags", [])) if isinstance(spec.get("required_detail_tags"), list) else set()
    part_detail_tags = spec.get("part_detail_tags") if isinstance(spec.get("part_detail_tags"), dict) else {}
    missing_spec_parts = [
        part_id for part_id in expected_parts
        if not required_tags.issubset(_detail_tags(part_detail_tags.get(part_id)))
    ]
    spec_ok = spec.get("profile") == "production" and required_tags.issubset(declared_tags) and not missing_spec_parts
    checks = [_check(
        "quality.production_spec",
        spec_ok,
        {"profile": "production", "required_detail_tags": list(PRODUCTION_REQUIRED_DETAIL_TAGS), "part_detail_tags": "all semantic parts"},
        {"profile": spec.get("profile"), "required_detail_tags": sorted(declared_tags), "missing_parts": missing_spec_parts},
        hint="add_production_quality_gate",
    )]
    if gltf is None:
        return checks + [
            _check("quality.material_coverage", False, {"minimum": 6}, {"materials": 0}, hint="export_materials"),
            _check("quality.part_breakup", False, {"minimum_primitives_per_part": 2, "minimum_materials_per_part": 2}, {}, hint="add_secondary_detail"),
            _check("quality.detail_coverage", False, list(PRODUCTION_REQUIRED_DETAIL_TAGS), {}, hint="tag_production_details"),
            _check("quality.mesh_node_coverage", False, {"unlabeled_mesh_nodes": 0}, {}, hint="tag_all_mesh_nodes"),
            _check("quality.normals", False, True, False, hint="export_normals"),
            _check("quality.geometry_analysis", False, "PASS", "UNAVAILABLE", hint="export_triangle_mesh"),
        ]

    try:
        declared_min_materials = int(spec.get("minimum_materials", 6))
    except (TypeError, ValueError):
        declared_min_materials = 6
    try:
        declared_min_primitives = int(spec.get("minimum_primitives_per_part", 2))
    except (TypeError, ValueError):
        declared_min_primitives = 2
    minimum_materials = max(6, declared_min_materials)
    minimum_primitives = max(2, declared_min_primitives)
    checks.append(_check(
        "quality.material_coverage",
        len(gltf.get("materials", [])) >= minimum_materials,
        {"minimum": minimum_materials},
        {"materials": len(gltf.get("materials", []))},
        hint="add_material_variation",
    ))
    part_stats = stats.get("part_stats", {})
    weak_parts = [
        part_id for part_id in expected_parts
        if not isinstance(part_stats.get(part_id), dict)
        or int(part_stats[part_id].get("primitives", 0)) < minimum_primitives
        or len(part_stats[part_id].get("materials", [])) < 2
    ]
    checks.append(_check(
        "quality.part_breakup",
        not weak_parts,
        {"minimum_primitives_per_part": minimum_primitives, "minimum_materials_per_part": 2},
        {"weak_parts": weak_parts},
        affected=weak_parts,
        hint="add_secondary_detail",
    ))
    missing_details = {
        part_id: sorted(required_tags - set(part_stats.get(part_id, {}).get("detail_tags", [])))
        for part_id in expected_parts
        if required_tags - set(part_stats.get(part_id, {}).get("detail_tags", []))
    }
    checks.append(_check(
        "quality.detail_coverage",
        not missing_details,
        list(PRODUCTION_REQUIRED_DETAIL_TAGS),
        missing_details,
        affected=sorted(missing_details),
        hint="tag_production_details",
    ))
    checks.append(_check(
        "quality.mesh_node_coverage",
        int(stats.get("unlabeled_mesh_nodes", 0)) == 0
        and int(stats.get("mesh_nodes", 0)) >= len(expected_parts)
        and all(int(stats.get("part_node_counts", {}).get(part_id, 0)) >= 1 for part_id in expected_parts),
        {"mesh_nodes": f">={len(expected_parts)}", "unlabeled_mesh_nodes": 0, "every_part_labeled": True},
        {"mesh_nodes": stats.get("mesh_nodes", 0), "unlabeled_mesh_nodes": stats.get("unlabeled_mesh_nodes", 0), "part_node_counts": stats.get("part_node_counts", {})},
        hint="tag_all_mesh_nodes",
    ))
    checks.append(_check(
        "quality.normals",
        int(stats.get("primitives_without_normals", 0)) == 0,
        True,
        int(stats.get("primitives_without_normals", 0)) == 0,
        hint="export_normals",
    ))
    checks.append(_check(
        "quality.geometry_analysis",
        stats.get("component_analysis") == "PASS",
        "PASS",
        stats.get("component_analysis"),
        hint="export_triangle_mesh",
    ))
    roof_parts = [part_id for part_id in expected_parts if part_id.casefold() == "roof" or "roof" in str(next(part.get("role", "") for part in asset["parts"] if part["part_id"] == part_id)).casefold()]
    thin_roof_spans = {part_id: stats.get("thin_spans", {}).get(part_id, []) for part_id in roof_parts if stats.get("thin_spans", {}).get(part_id)}
    checks.append(_check(
        "quality.silhouette_integrity",
        not thin_roof_spans,
        {"long_thin_roof_spans": 0},
        thin_roof_spans,
        affected=sorted(thin_roof_spans),
        hint="remove_floating_roof_bars",
    ))
    return checks


def validate_asset_and_glb(asset: dict[str, Any], glb: bytes, *, artifact_id: str | None = None, meshes: list[Mesh] | None = None, quality_profile: str | None = None) -> dict[str, Any]:
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
        stats = _glb_mesh_stats(gltf or {}, glb if quality_profile == "production" else None)
        if quality_profile == "production" and gltf is not None:
            stats = _add_component_analysis(stats, gltf, glb)
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

    if quality_profile == "production":
        checks.extend(_production_quality_checks(asset, gltf, stats))

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
