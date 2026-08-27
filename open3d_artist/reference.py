"""Small img2threejs-style reference intake gate for external Blender builds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import digest_json


IMG2THREEJS_PASSES = (
    "blockout",
    "structural-pass",
    "form-refinement",
    "material-pass",
    "surface-pass",
    "lighting-pass",
    "interaction-pass",
    "optimization-pass",
)
_LEVELS = {"macro", "meso", "micro"}
_EVIDENCE = {"visible", "inferred", "not_observed"}
_FAILURE_POLICIES = {"refine-spec", "refine-code", "request-input", "stop"}


def validate_reference_spec(path: str | Path, *, target_asset_id: str | None = None) -> dict[str, Any]:
    """Load and validate the bounded reference plan written by an external agent."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("reference_spec.json is missing")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("reference_spec.json is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("reference_spec.json must be an object")

    errors: list[str] = []
    if value.get("schema_version") != "0.1.0":
        errors.append("schema_version must be 0.1.0")
    if value.get("profile") != "img2threejs":
        errors.append("profile must be img2threejs")
    if target_asset_id is not None and value.get("target_asset_id") != target_asset_id:
        errors.append(f"target_asset_id must be {target_asset_id}")
    if value.get("suitability") not in {"pass", "conditional"}:
        errors.append("suitability must be pass or conditional")
    if not isinstance(value.get("subject"), str) or not value["subject"].strip():
        errors.append("subject must be a non-empty string")

    silhouette = value.get("silhouette")
    if not isinstance(silhouette, dict) or not isinstance(silhouette.get("primary"), str) or not silhouette["primary"].strip():
        errors.append("silhouette.primary must be a non-empty string")

    components = value.get("components")
    component_ids: set[str] = set()
    if not isinstance(components, list) or len(components) < 3:
        errors.append("components must contain at least 3 entries")
        components = []
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            errors.append(f"components[{index}] must be an object")
            continue
        component_id = component.get("id")
        if not isinstance(component_id, str) or not component_id.strip() or component_id in component_ids:
            errors.append(f"components[{index}].id must be unique and non-empty")
        else:
            component_ids.add(component_id)
        if not isinstance(component.get("role"), str) or not component["role"].strip():
            errors.append(f"components[{index}].role is required")
        if component.get("level") not in _LEVELS:
            errors.append(f"components[{index}].level must be macro, meso, or micro")
        features = component.get("visible_features")
        if not isinstance(features, list) or not features or not all(isinstance(item, str) and item.strip() for item in features):
            errors.append(f"components[{index}].visible_features must be a non-empty string list")

    details = value.get("detail_inventory")
    if not isinstance(details, list) or len(details) < 5:
        errors.append("detail_inventory must contain at least 5 entries")
        details = []
    detail_ids: set[str] = set()
    for index, detail in enumerate(details):
        if not isinstance(detail, dict):
            errors.append(f"detail_inventory[{index}] must be an object")
            continue
        detail_id = detail.get("id")
        if not isinstance(detail_id, str) or not detail_id.strip() or detail_id in detail_ids:
            errors.append(f"detail_inventory[{index}].id must be unique and non-empty")
        else:
            detail_ids.add(detail_id)
        if detail.get("component") not in component_ids:
            errors.append(f"detail_inventory[{index}].component must reference a component")
        for field in ("feature", "implementation"):
            if not isinstance(detail.get(field), str) or not detail[field].strip():
                errors.append(f"detail_inventory[{index}].{field} is required")
        if detail.get("evidence") not in _EVIDENCE:
            errors.append(f"detail_inventory[{index}].evidence is invalid")

    materials = value.get("materials")
    if not isinstance(materials, list) or len(materials) < 2:
        errors.append("materials must contain at least 2 entries")
        materials = []
    material_ids: set[str] = set()
    for index, material in enumerate(materials):
        if not isinstance(material, dict):
            errors.append(f"materials[{index}] must be an object")
            continue
        material_id = material.get("id")
        if not isinstance(material_id, str) or not material_id.strip() or material_id in material_ids:
            errors.append(f"materials[{index}].id must be unique and non-empty")
        else:
            material_ids.add(material_id)
        for field in ("region", "finish"):
            if not isinstance(material.get(field), str) or not material[field].strip():
                errors.append(f"materials[{index}].{field} is required")
        if material.get("evidence") not in _EVIDENCE:
            errors.append(f"materials[{index}].evidence is invalid")

    if value.get("build_passes") != list(IMG2THREEJS_PASSES):
        errors.append("build_passes must use the ordered img2threejs pass list")
    unseen = value.get("unseen_regions")
    if not isinstance(unseen, list) or not unseen or not all(isinstance(item, str) and item.strip() for item in unseen):
        errors.append("unseen_regions must acknowledge at least one uncertain or hidden region")

    review_policy = value.get("review_policy")
    if not isinstance(review_policy, dict):
        errors.append("review_policy is required")
    else:
        if review_policy.get("on_failure") not in _FAILURE_POLICIES:
            errors.append("review_policy.on_failure is invalid")
        if review_policy.get("require_side_by_side") is not True:
            errors.append("review_policy.require_side_by_side must be true")
        corrections = review_policy.get("max_corrections")
        if isinstance(corrections, bool) or not isinstance(corrections, int) or not 1 <= corrections <= 3:
            errors.append("review_policy.max_corrections must be an integer from 1 to 3")

    if errors:
        raise ValueError("reference_spec rejected: " + "; ".join(errors[:8]))
    return {
        "path": source.name,
        "digest": digest_json(value),
        "summary": {
            "profile": value["profile"],
            "subject": value["subject"],
            "components": len(components),
            "details": len(details),
            "materials": len(materials),
            "passes": list(IMG2THREEJS_PASSES),
            "unseen_regions": len(unseen),
        },
    }
