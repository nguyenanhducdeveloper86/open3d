"""Deterministic primitive meshes and a dependency-free GLB writer."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import asset_digest


@dataclass
class Mesh:
    part_id: str
    positions: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    indices: list[int]
    color: tuple[float, float, float, float]

    @property
    def triangles(self) -> int:
        return len(self.indices) // 3


def _vec(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not isinstance(value, dict):
        return default
    return tuple(float(value.get(axis, default[index])) for index, axis in enumerate(("x", "y", "z")))  # type: ignore[return-value]


def _color(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, str) and value.startswith("#") and len(value) in {7, 9}:
        raw = value[1:]
        if len(raw) == 6:
            raw += "ff"
        return tuple(int(raw[index : index + 2], 16) / 255 for index in range(0, 8, 2))  # type: ignore[return-value]
    if isinstance(value, (list, tuple)) and len(value) in {3, 4}:
        values = [float(item) for item in value]
        return tuple((values + [1.0])[:4])  # type: ignore[return-value]
    return (0.65, 0.65, 0.68, 1.0)


def _scale(primitive: dict[str, Any]) -> tuple[float, float, float]:
    value = _vec(primitive.get("scale"), (1.0, 1.0, 1.0))
    if min(value) <= 0 or not all(math.isfinite(item) for item in value):
        raise ValueError("primitive scale must contain positive finite values")
    return value


def _box(part_id: str, primitive: dict[str, Any]) -> Mesh:
    size = _vec(primitive.get("size"), (0.1, 0.1, 0.1))
    scale = _scale(primitive)
    size = tuple(size[index] * scale[index] for index in range(3))
    center = _vec(primitive.get("center"), (0.0, 0.0, 0.0))
    half = tuple(item / 2 for item in size)
    faces = [
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
        ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
        ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
        ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
    ]
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []
    for normal, corners in faces:
        start = len(positions)
        positions.extend(
            (
                center[0] + corner[0] * half[0],
                center[1] + corner[1] * half[1],
                center[2] + corner[2] * half[2],
            )
            for corner in corners
        )
        normals.extend([normal] * 4)
        indices.extend([start, start + 1, start + 2, start, start + 2, start + 3])
    return Mesh(part_id, positions, normals, indices, _color(primitive.get("color")))


def _axis_point(axis: str, x: float, y: float, z: float, center: tuple[float, float, float]) -> tuple[float, float, float]:
    if axis == "x":
        local = (z, x, y)
    elif axis == "y":
        local = (x, z, y)
    else:
        local = (x, y, z)
    return tuple(local[index] + center[index] for index in range(3))  # type: ignore[return-value]


def _axis_normal(axis: str, x: float, y: float, z: float) -> tuple[float, float, float]:
    if axis == "x":
        return (z, x, y)
    if axis == "y":
        return (x, z, y)
    return (x, y, z)


def _cylinder(part_id: str, primitive: dict[str, Any]) -> Mesh:
    radius = float(primitive.get("radius", 0.05))
    depth = float(primitive.get("depth", 0.2))
    segments = int(primitive.get("segments", 16))
    if radius <= 0 or depth <= 0 or segments < 3:
        raise ValueError("cylinder radius/depth must be positive and segments >= 3")
    scale = _scale(primitive)
    radius *= max(scale[0], scale[1])
    depth *= scale[2]
    axis = primitive.get("axis", "z")
    if axis not in {"x", "y", "z"}:
        raise ValueError("cylinder axis must be x, y, or z")
    center = _vec(primitive.get("center"), (0.0, 0.0, 0.0))
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []

    for index in range(segments):
        a0 = 2 * math.pi * index / segments
        a1 = 2 * math.pi * (index + 1) / segments
        for z, angle in ((-depth / 2, a0), (-depth / 2, a1), (depth / 2, a1), (depth / 2, a0)):
            positions.append(_axis_point(axis, radius * math.cos(angle), radius * math.sin(angle), z, center))
            normals.append(_axis_normal(axis, math.cos(angle), math.sin(angle), 0))
        start = len(positions) - 4
        indices.extend([start, start + 1, start + 2, start, start + 2, start + 3])

    for z, normal_sign in ((-depth / 2, -1), (depth / 2, 1)):
        center_index = len(positions)
        positions.append(_axis_point(axis, 0, 0, z, center))
        normals.append(_axis_normal(axis, 0, 0, normal_sign))
        for index in range(segments):
            a0 = 2 * math.pi * index / segments
            a1 = 2 * math.pi * (index + 1) / segments
            positions.extend(
                [
                    _axis_point(axis, radius * math.cos(a0), radius * math.sin(a0), z, center),
                    _axis_point(axis, radius * math.cos(a1), radius * math.sin(a1), z, center),
                ]
            )
            normals.extend([_axis_normal(axis, 0, 0, normal_sign)] * 2)
            ring = len(positions) - 2
            if normal_sign < 0:
                indices.extend([center_index, ring + 1, ring])
            else:
                indices.extend([center_index, ring, ring + 1])
    return Mesh(part_id, positions, normals, indices, _color(primitive.get("color")))


def meshes_for_asset(asset: dict[str, Any]) -> list[Mesh]:
    geometry = asset.get("geometry", {})
    primitives = geometry.get("primitives")
    if not primitives:
        dimensions = asset["dimensions"]
        primitives = [
            {
                "part_id": part["part_id"],
                "type": "box",
                "size": {
                    "x": dimensions["width"] * (0.8 if index == 0 else 0.2),
                    "y": dimensions["depth"] * (0.8 if index == 0 else 0.2),
                    "z": dimensions["height"] * (0.8 if index == 0 else 0.2),
                },
                "center": {"x": 0, "y": 0, "z": dimensions["height"] * (0.4 if index == 0 else 0.8)},
            }
            for index, part in enumerate(asset["parts"])
        ]
    meshes: list[Mesh] = []
    for primitive in primitives:
        if primitive.get("type", "box") == "cylinder":
            meshes.append(_cylinder(primitive["part_id"], primitive))
        else:
            meshes.append(_box(primitive["part_id"], primitive))
    return meshes


def mesh_stats(meshes: Iterable[Mesh]) -> dict[str, Any]:
    meshes = list(meshes)
    points = [point for mesh in meshes for point in mesh.positions]
    if not points:
        return {"triangles": 0, "parts": [], "bounds": None}
    mins = [min(point[index] for point in points) for index in range(3)]
    maxs = [max(point[index] for point in points) for index in range(3)]
    return {
        "triangles": sum(mesh.triangles for mesh in meshes),
        "parts": sorted({mesh.part_id for mesh in meshes}),
        "bounds": {"min": mins, "max": maxs, "size": [maxs[i] - mins[i] for i in range(3)]},
    }


def _append_floats(buffer: bytearray, values: Iterable[tuple[float, float, float]]) -> tuple[int, int]:
    while len(buffer) % 4:
        buffer.append(0)
    offset = len(buffer)
    flattened = [number for value in values for number in value]
    buffer.extend(struct.pack(f"<{len(flattened)}f", *flattened))
    return offset, len(flattened) // 3


def _append_indices(buffer: bytearray, values: list[int]) -> tuple[int, int]:
    while len(buffer) % 4:
        buffer.append(0)
    offset = len(buffer)
    buffer.extend(struct.pack(f"<{len(values)}I", *values))
    return offset, len(values)


def generate_glb(asset: dict[str, Any]) -> bytes:
    meshes = meshes_for_asset(asset)
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    quality_gate = metadata.get("quality_gate") if isinstance(metadata.get("quality_gate"), dict) else {}
    part_detail_tags = quality_gate.get("part_detail_tags") if isinstance(quality_gate.get("part_detail_tags"), dict) else {}
    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    mesh_defs: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []

    for mesh_index, mesh in enumerate(meshes):
        position_offset, position_count = _append_floats(binary, mesh.positions)
        position_view = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": position_offset, "byteLength": position_count * 12, "target": 34962})
        mins = [min(point[index] for point in mesh.positions) for index in range(3)]
        maxs = [max(point[index] for point in mesh.positions) for index in range(3)]
        position_accessor = len(accessors)
        accessors.append({"bufferView": position_view, "componentType": 5126, "count": position_count, "type": "VEC3", "min": mins, "max": maxs})

        normal_offset, normal_count = _append_floats(binary, mesh.normals)
        normal_view = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": normal_offset, "byteLength": normal_count * 12, "target": 34962})
        normal_accessor = len(accessors)
        accessors.append({"bufferView": normal_view, "componentType": 5126, "count": normal_count, "type": "VEC3"})

        index_offset, index_count = _append_indices(binary, mesh.indices)
        index_view = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": index_offset, "byteLength": index_count * 4, "target": 34963})
        index_accessor = len(accessors)
        accessors.append({"bufferView": index_view, "componentType": 5125, "count": index_count, "type": "SCALAR"})

        material_index = len(materials)
        materials.append(
            {
                "name": f"{mesh.part_id}.material",
                "pbrMetallicRoughness": {"baseColorFactor": list(mesh.color), "metallicFactor": 0.0, "roughnessFactor": 0.72},
            }
        )
        mesh_defs.append(
            {
                "name": f"{mesh.part_id}.mesh",
                "primitives": [{"attributes": {"NORMAL": normal_accessor, "POSITION": position_accessor}, "indices": index_accessor, "material": material_index}],
            }
        )
        tags = part_detail_tags.get(mesh.part_id, quality_gate.get("required_detail_tags", []))
        if isinstance(tags, list):
            tags = ",".join(item for item in tags if isinstance(item, str) and item.strip())
        extras = {"open3d": {"part_id": mesh.part_id, "part_role": "semantic"}}
        if isinstance(tags, str) and tags.strip():
            extras["open3d_detail_tags"] = tags
        nodes.append({"name": mesh.part_id, "mesh": mesh_index, "extras": extras})

    gltf = {
        "asset": {"generator": "Open3D Artist 0.1", "version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": mesh_defs,
        "materials": materials,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {"open3d": {"schema_version": "0.1.0", "asset_id": asset["asset_id"], "asset_digest": asset_digest(asset)}},
    }
    json_chunk = json.dumps(gltf, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    while len(json_chunk) % 4:
        json_chunk += b" "
    while len(binary) % 4:
        binary.append(0)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return b"glTF" + struct.pack("<II", 2, total_length) + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk + struct.pack("<I4s", len(binary), b"BIN\x00") + binary


def read_glb_json(data: bytes) -> dict[str, Any]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("invalid GLB header")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2 or total_length != len(data):
        raise ValueError("unsupported or truncated GLB")
    json_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON":
        raise ValueError("GLB JSON chunk missing")
    end = 20 + json_length
    if end > len(data):
        raise ValueError("GLB JSON chunk is truncated")
    return json.loads(data[20:end].decode("utf-8"))


def patch_glb_metadata(data: bytes, asset: dict[str, Any]) -> bytes:
    """Attach Open3D identity and semantic part metadata to a Blender GLB."""

    gltf = read_glb_json(data)
    extras = gltf.setdefault("extras", {})
    open3d = extras.setdefault("open3d", {})
    open3d.update({
        "schema_version": "0.1.0",
        "asset_id": asset["asset_id"],
        "asset_digest": asset_digest(asset),
    })
    part_roles = {part["part_id"]: part.get("role", "part") for part in asset["parts"]}
    found: set[str] = set()
    for node in gltf.get("nodes", []):
        if not isinstance(node, dict) or "mesh" not in node:
            continue
        node_extras = node.setdefault("extras", {})
        node_open3d = node_extras.setdefault("open3d", {})
        candidate = node_open3d.get("part_id") or node_extras.get("open3d_part_id") or node.get("name", "")
        candidate = str(candidate).split(".", 1)[0]
        if candidate not in part_roles:
            continue
        node_open3d.update({"part_id": candidate, "part_role": part_roles[candidate]})
        found.add(candidate)
    missing = sorted(set(part_roles) - found)
    if missing:
        raise ValueError(f"Blender GLB is missing semantic parts: {', '.join(missing)}")

    json_length = struct.unpack_from("<I", data, 12)[0]
    old_json_end = 20 + json_length
    rest = data[old_json_end:]
    json_chunk = json.dumps(gltf, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    while len(json_chunk) % 4:
        json_chunk += b" "
    total_length = 12 + 8 + len(json_chunk) + len(rest)
    return b"glTF" + struct.pack("<II", 2, total_length) + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk + rest
