"""Allowlisted Blender worker entry point.

This file is intentionally standalone so Blender can execute it without the
Open3D package being installed into Blender's Python environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _scene_report(operation: str, blend_path: Path) -> dict[str, Any]:
    import bpy  # type: ignore

    bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    objects = list(bpy.data.objects)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    triangles = sum(len(mesh.data.loop_triangles) for mesh in meshes)
    return {
        "schema_version": "0.1.0",
        "status": "PASS",
        "operation": operation,
        "checks": [
            {"check_id": "blender.scene_loaded", "status": "PASS", "message": str(blend_path.name)},
            {"check_id": "blender.meshes_present", "status": "PASS" if meshes else "WARN", "message": f"{len(meshes)} mesh objects"},
        ],
        "scene": {"objects": len(objects), "meshes": len(meshes), "triangles": triangles},
    }


def run(job_path: Path, result_path: Path) -> int:
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if set(job) - {"schema_version", "operation", "input_blend", "output_glb"}:
            raise ValueError("unsupported job fields")
        if job.get("schema_version") != "0.1.0":
            raise ValueError("unsupported job schema")
        operation = job.get("operation")
        if operation not in {"inspect", "validate", "export_glb"}:
            raise ValueError("unsupported operation")
        blend_path = Path(job["input_blend"])
        report = _scene_report(operation, blend_path)
        if operation == "export_glb":
            import bpy  # type: ignore

            output = Path(job["output_glb"])
            output.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", export_materials="EXPORT", use_selection=False)
            report["output_glb"] = str(output)
        _write(result_path, report)
        return 0
    except Exception as exc:  # Blender exceptions must cross the JSON boundary.
        _write(result_path, {"schema_version": "0.1.0", "status": "FAIL", "error": str(exc)})
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    # Blender prepends its own argv. Keep only the two fixed worker arguments.
    try:
        start = sys.argv.index("--job")
        args = parser.parse_args(sys.argv[start : start + 4])
    except ValueError:
        args = parser.parse_args()
    return run(args.job, args.result)


if __name__ == "__main__":
    raise SystemExit(main())
