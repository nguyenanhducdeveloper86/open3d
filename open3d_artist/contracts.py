"""Versioned asset contracts and canonical hashing.

The core intentionally accepts JSON without a runtime dependency. JSON is a
valid YAML 1.2 document, so the example ``asset.yaml`` files stay portable;
install ``open3d-artist[yaml]`` when human-authored YAML syntax is needed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1.0"
_PART_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_ASSET_KINDS = {"prop", "environment", "character", "material", "scene"}


class ContractError(ValueError):
    """Raised when an asset contract cannot be trusted."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json(value))


def _major(version: Any) -> int:
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ContractError("schema_version must use MAJOR.MINOR.PATCH, for example 0.1.0")
    return int(version.split(".", 1)[0])


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ContractError(f"{name} must be greater than zero")
    return float(value)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def normalize_asset(value: Any) -> dict[str, Any]:
    """Validate and normalize an asset contract into stable JSON."""

    asset = copy.deepcopy(_mapping(value, "asset contract"))
    version = asset.get("schema_version", SCHEMA_VERSION)
    if _major(version) != 0:
        raise ContractError(f"unsupported schema major: {version}")
    asset["schema_version"] = version

    asset_id = asset.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ContractError("asset_id must be a non-empty string")
    asset["asset_id"] = asset_id.strip()

    kind = asset.get("kind", "prop")
    if kind not in _ASSET_KINDS:
        raise ContractError(f"kind must be one of: {', '.join(sorted(_ASSET_KINDS))}")
    asset["kind"] = kind
    asset["units"] = asset.get("units", "m")
    if asset["units"] != "m":
        raise ContractError("v0.1 contracts use meters (units: m)")

    dimensions = _mapping(asset.get("dimensions"), "dimensions")
    for axis in ("width", "depth", "height"):
        dimensions[axis] = _number(dimensions.get(axis), f"dimensions.{axis}", positive=True)

    parts = asset.get("parts", [])
    if not isinstance(parts, list) or not parts:
        raise ContractError("parts must be a non-empty list")
    seen: set[str] = set()
    normalized_parts: list[dict[str, Any]] = []
    for part in parts:
        part = _mapping(part, "parts entry")
        part_id = part.get("part_id")
        if not isinstance(part_id, str) or not _PART_ID.fullmatch(part_id):
            raise ContractError("part_id must match ^[A-Za-z][A-Za-z0-9_.-]*$")
        if part_id in seen:
            raise ContractError(f"duplicate part_id: {part_id}")
        seen.add(part_id)
        normalized_parts.append(part)
    asset["parts"] = sorted(normalized_parts, key=lambda part: part["part_id"])

    geometry = _mapping(asset.get("geometry", {}), "geometry")
    budget = _mapping(geometry.get("triangle_budget", {}), "geometry.triangle_budget")
    budget["max"] = int(_number(budget.get("max", 100_000), "geometry.triangle_budget.max", positive=True))
    geometry["triangle_budget"] = budget
    primitives = geometry.get("primitives")
    if primitives is not None:
        if not isinstance(primitives, list) or not primitives:
            raise ContractError("geometry.primitives must be a non-empty list when provided")
        for primitive in primitives:
            primitive = _mapping(primitive, "geometry.primitives entry")
            if not isinstance(primitive.get("part_id"), str) or primitive.get("part_id") not in seen:
                raise ContractError(f"primitive references unknown part: {primitive.get('part_id')}")
            primitive_type = primitive.get("type", "box")
            if primitive_type not in {"box", "cylinder"}:
                raise ContractError("primitive type must be box or cylinder")
            for vector_name in ("center", "scale"):
                vector = primitive.get(vector_name)
                if vector is not None:
                    vector = _mapping(vector, f"primitive.{vector_name}")
                    for axis, value in vector.items():
                        if axis not in {"x", "y", "z"}:
                            raise ContractError(f"primitive.{vector_name} has unknown axis: {axis}")
                        _number(value, f"primitive.{vector_name}.{axis}", positive=vector_name == "scale")
            if primitive_type == "box" and primitive.get("size") is not None:
                size = _mapping(primitive["size"], "primitive.size")
                for axis in ("x", "y", "z"):
                    _number(size.get(axis), f"primitive.size.{axis}", positive=True)
            if primitive_type == "cylinder":
                _number(primitive.get("radius", 0.05), "primitive.radius", positive=True)
                _number(primitive.get("depth", 0.2), "primitive.depth", positive=True)
                segments = primitive.get("segments", 16)
                if isinstance(segments, bool) or not isinstance(segments, int) or segments < 3:
                    raise ContractError("primitive.segments must be an integer >= 3")
                if primitive.get("axis", "z") not in {"x", "y", "z"}:
                    raise ContractError("primitive.axis must be x, y, or z")
    asset["geometry"] = geometry

    outputs = _mapping(asset.get("outputs", {}), "outputs")
    outputs.setdefault("editable", "contract")
    outputs.setdefault("preview", "glb")
    asset["outputs"] = outputs
    return asset


def _load_payload(text: str, source: Path) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ContractError(
                f"{source} is not JSON; install YAML support with `pip install open3d-artist[yaml]`"
            ) from exc
        try:
            return yaml.safe_load(text)
        except Exception as yaml_error:  # pragma: no cover - depends on optional parser
            raise ContractError(f"cannot parse {source}: {yaml_error}") from json_error


def load_asset(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ContractError(f"asset contract not found: {source}")
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".md":
        match = re.search(r"\A\s*---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
        if not match:
            raise ContractError(f"{source} must start with YAML frontmatter")
        text = match.group(1)
    return normalize_asset(_load_payload(text, source))


def asset_bytes(asset: dict[str, Any]) -> bytes:
    return canonical_json(normalize_asset(asset))


def asset_digest(asset: dict[str, Any]) -> str:
    return digest_bytes(asset_bytes(asset))
