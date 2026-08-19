"""Generate the local, deterministic production qualification fixture."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from open3d_artist.contracts import asset_bytes, canonical_json, digest_bytes, load_asset  # noqa: E402
from open3d_artist.geometry import generate_glb, meshes_for_asset  # noqa: E402
from open3d_artist.qa import validate_asset_and_glb  # noqa: E402
from open3d_artist.store import ArtifactStore  # noqa: E402


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repair-id")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def repaired_asset(recipe: dict) -> dict:
    if recipe.get("repair_id") != "fixture-repair-v1":
        raise ValueError("unsupported repair id")
    asset = copy.deepcopy(recipe["asset"])
    handle = next(item for item in asset["geometry"]["primitives"] if item["part_id"] == "handle")
    handle["size"]["y"] = 0.54
    return asset


def material(name: str, color: str):
    value = tuple(int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*value, 1.0)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*value, 1.0)
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.72
    return mat


def look_at(camera, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def build_scene(asset: dict, recipe: dict) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

    collection = bpy.data.collections.new("FIXTURE_ASSET")
    bpy.context.scene.collection.children.link(collection)
    materials = {}
    for primitive in asset["geometry"]["primitives"]:
        part_id = primitive["part_id"]
        center = primitive.get("center", {"x": 0, "y": 0, "z": 0})
        location = (center["x"], center["y"], center["z"])
        if primitive.get("type", "box") == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(vertices=primitive.get("segments", 16), radius=primitive["radius"], depth=primitive["depth"], location=location)
            obj = bpy.context.object
            axis = primitive.get("axis", "z")
            if axis == "x":
                obj.rotation_euler[1] = math.pi / 2
            elif axis == "y":
                obj.rotation_euler[0] = math.pi / 2
        else:
            size = primitive["size"]
            bpy.ops.mesh.primitive_cube_add(size=1, location=location)
            obj = bpy.context.object
            obj.dimensions = (size["x"], size["y"], size["z"])
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.name = part_id
        obj["open3d_part_id"] = part_id
        obj["open3d_part_role"] = next(part.get("role", "part") for part in asset["parts"] if part["part_id"] == part_id)
        bpy.context.collection.objects.unlink(obj)
        collection.objects.link(obj)
        color = primitive.get("color", "#8796A5")
        materials.setdefault(color, material(f"fixture_{color[1:]}", color))
        obj.data.materials.append(materials[color])

    camera_data = bpy.data.cameras.new("QualificationCamera")
    camera = bpy.data.objects.new("QualificationCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    camera_data.lens = 52
    light_data = bpy.data.lights.new("Key", type="AREA")
    light_data.energy = 850
    light_data.shape = "DISK"
    light_data.size = 4
    light = bpy.data.objects.new("Key", light_data)
    light.location = (2.5, -3.5, 4.5)
    bpy.context.scene.collection.objects.link(light)
    look_at(light, Vector((0, 0, 0.35)))
    fill_data = bpy.data.lights.new("Fill", type="AREA")
    fill_data.energy = 450
    fill_data.size = 3
    fill = bpy.data.objects.new("Fill", fill_data)
    fill.location = (-3, 2, 2.5)
    bpy.context.scene.collection.objects.link(fill)
    look_at(fill, Vector((0, 0, 0.35)))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.025, 0.035, 0.05)
    scene["open3d_asset_id"] = asset["asset_id"]
    scene["qualification_recipe"] = recipe["recipe_id"]

    target = Vector((0, 0, 0.35))
    views = {
        "HERO_3Q": (2.4, -3.2, 2.0),
        "FRONT": (0, -4.0, 0.8),
        "BACK": (0, 4.0, 0.8),
        "LEFT": (-4.0, 0, 0.8),
        "RIGHT": (4.0, 0, 0.8),
        "TOP": (0, 0, 4.8),
    }
    scene["qualification_views"] = json.dumps(list(views))
    scene["_fixture_views"] = views


def write_project(output: Path, asset: dict, recipe: dict, glb: bytes) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    (output / "asset.yaml").write_bytes(asset_bytes(asset))
    (output / "recipe.json").write_bytes(canonical_json(recipe))
    state = output / ".open3d"
    store = ArtifactStore(state)
    contract_id = store.put_bytes(asset_bytes(asset), kind="asset-contract", metadata={"asset_id": asset["asset_id"]})
    glb_id = store.put_bytes(glb, kind="glb", metadata={"asset_id": asset["asset_id"], "contract_artifact": contract_id})
    report = validate_asset_and_glb(asset, glb, artifact_id=glb_id, meshes=meshes_for_asset(asset))
    qa_id = store.put_json(report, kind="qa-report", metadata={"asset_id": asset["asset_id"], "input_artifact_id": glb_id})
    current = {"schema_version": "0.1.0", "project_id": output.name, "asset_id": asset["asset_id"], "contract_artifact": contract_id, "glb_artifact": glb_id, "qa_artifact": qa_id, "qa_status": report["status"], "checkpoint_id": None}
    refs = state / "refs"
    (refs / "checkpoints").mkdir(parents=True, exist_ok=True)
    (refs / "current.json").write_bytes(canonical_json(current))
    (output / "project.json").write_bytes(canonical_json({"schema_version": "0.1.0", "project_id": output.name, "asset_id": asset["asset_id"], "current_ref": ".open3d/refs/current.json"}))
    return report


def main() -> None:
    options = args()
    recipe = json.loads(options.recipe.read_text(encoding="utf-8"))
    if options.repair_id is not None:
        if options.repair_id != "fixture-repair-v1":
            raise ValueError("unsupported repair id")
        recipe = copy.deepcopy(recipe)
        recipe["repair_id"] = options.repair_id
        asset = repaired_asset(recipe)
    else:
        asset = recipe["asset"]
    output = options.output.resolve()
    build_scene(asset, recipe)
    scene = bpy.context.scene
    views = json.loads(scene["qualification_views"])
    positions = {"HERO_3Q": (2.4, -3.2, 2.0), "FRONT": (0, -4.0, 0.8), "BACK": (0, 4.0, 0.8), "LEFT": (-4.0, 0, 0.8), "RIGHT": (4.0, 0, 0.8), "TOP": (0, 0, 4.8)}
    output.mkdir(parents=True, exist_ok=True)
    for view in views:
        scene.camera.location = positions[view]
        look_at(scene.camera, Vector((0, 0, 0.35)))
        scene.render.filepath = str(output / f"{view}.png")
        bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / f"{asset['asset_id']}.blend"))
    glb = generate_glb(asset)
    (output / f"{asset['asset_id']}.glb").write_bytes(glb)
    report = write_project(output, asset, recipe, glb)
    provenance = {"schema_version": "0.1.0", "asset_id": asset["asset_id"], "recipe_id": recipe["recipe_id"], "prompt": recipe["prompt"], "reference": recipe["reference"], "generator": "Blender Python API + Open3D deterministic GLB writer", "network": False, "external_inference": False, "glb_sha256": digest_bytes(glb)}
    qa = {"schema_version": "0.1.0", "asset_id": asset["asset_id"], "local_geometry": report, "renders": {view: {"status": "PASS", "path": f"{view}.png"} for view in views}, "external_visual_qa": {"status": "UNAVAILABLE_REPAIR_REQUIRED", "reason": "No external reference-first visual QA provider is configured for this local fixture."}, "local_technical_status": "PASS", "approval": "LOCAL_ONLY_NOT_APPROVED"}
    evidence = {"schema_version": "0.1.0", "asset_id": asset["asset_id"], "required_views": views, "artifacts": [f"{asset['asset_id']}.blend", f"{asset['asset_id']}.glb"], "qa": "qa.json", "provenance": "provenance.json", "deterministic": True}
    (output / "provenance.json").write_bytes(canonical_json(provenance))
    (output / "qa.json").write_bytes(canonical_json(qa))
    (output / "evidence.json").write_bytes(canonical_json(evidence))


if __name__ == "__main__":
    main()
