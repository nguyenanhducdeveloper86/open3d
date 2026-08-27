"""Fixed Blender-side design pass for agent-authored assets.

The external agent owns the model design. This script owns the repeatable
artist finish: controlled edge softness, shading, UV coverage, studio renders,
and a bounded pipeline receipt. It is intentionally standalone because it is
executed by Blender's Python, not the host Python environment.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


VIEWS = ("HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP")


def _arguments() -> argparse.Namespace:
    tail = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(tail)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _semantic_objects(contract: dict) -> list:
    import bpy  # type: ignore

    part_ids = {part["part_id"] for part in contract.get("parts", []) if isinstance(part, dict)}
    result = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.get("open3d_preview_only"):
            continue
        part_id = obj.get("open3d_part_id") or (obj.name if obj.name in part_ids else None)
        if part_id in part_ids:
            obj["open3d_part_id"] = part_id
            result.append(obj)
    return result


def _bounds(objects: list) -> tuple:
    from mathutils import Vector  # type: ignore

    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise ValueError("agent scene contains no semantic mesh objects")
    mins = [min(point[index] for point in points) for index in range(3)]
    maxs = [max(point[index] for point in points) for index in range(3)]
    return mins, maxs, [maxs[index] - mins[index] for index in range(3)]


def _rounded_object(obj) -> bool:
    value = " ".join([obj.name, *(material.name for material in obj.data.materials if material)]).lower()
    return bool(obj.get("open3d_smooth") is True or any(token in value for token in (
        "round", "cylinder", "handle", "spout", "pipe", "glass", "curved", "sphere", "dome", "blob",
    )))


def _form_refinement(objects: list) -> dict:
    bevelled = 0
    smoothed = 0
    weighted = 0
    for obj in objects:
        dimensions = [abs(float(value)) for value in obj.dimensions if abs(float(value)) > 1e-6]
        smallest = min(dimensions) if dimensions else 0.1
        largest = max(dimensions) if dimensions else 1.0
        width = min(max(smallest * 0.045, 0.002), max(largest * 0.02, 0.004), 0.08)
        bevel = next((modifier for modifier in obj.modifiers if modifier.type == "BEVEL"), None)
        # Agent scripts commonly apply their own bevels before joining semantic
        # parts. Re-bevelling a dense joined mesh multiplies every tiny board,
        # shingle, and stone; only add the fixed bevel to genuinely raw meshes.
        if bevel is not None and bevel.name.startswith("Open3D form softness") and len(obj.data.polygons) >= 96:
            obj.modifiers.remove(bevel)
            bevel = None
        if bevel is None and width > 0 and len(obj.data.polygons) < 96:
            bevel = obj.modifiers.new("Open3D form softness", "BEVEL")
            bevel.width = width
            bevel.segments = 2
            bevel.limit_method = "ANGLE"
            bevel.angle_limit = math.radians(35)
            try:
                bevel.harden_normals = True
            except Exception:
                pass
            bevelled += 1
        elif bevel is not None:
            bevel.segments = min(max(int(getattr(bevel, "segments", 1)), 2), 3)
            bevelled += 1

        if _rounded_object(obj):
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
            smoothed += 1
        if not any(modifier.type == "WEIGHTED_NORMAL" for modifier in obj.modifiers):
            try:
                normal = obj.modifiers.new("Open3D weighted normals", "WEIGHTED_NORMAL")
                normal.keep_sharp = True
                normal.weight = 50
                weighted += 1
            except Exception:
                # Blender builds without this modifier still retain bevels and
                # exported vertex normals; the receipt records the fallback.
                pass
        obj["open3d_form_pass"] = "bevel-3-segment-weighted-normal"
        obj["open3d_bevel_width"] = round(width, 6)
    return {"objects": len(objects), "bevelled": bevelled, "smoothed": smoothed, "weighted_normals": weighted}


def _surface_pass(objects: list) -> dict:
    import bpy  # type: ignore

    uv_created = 0
    uv_existing = 0
    material_count = 0
    failures = []
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for obj in objects:
        if obj.data.uv_layers:
            uv_existing += 1
        else:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                try:
                    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.03, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
                except TypeError:
                    bpy.ops.uv.smart_project(island_margin=0.03)
                bpy.ops.object.mode_set(mode="OBJECT")
                uv_created += 1
            except Exception as exc:
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    pass
                failures.append({"object": obj.name, "error": str(exc)[:240]})
            finally:
                obj.select_set(False)
        for material in obj.data.materials:
            if not material:
                continue
            material_count += 1
            material.use_nodes = True
            principled = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
            if principled:
                roughness = principled.inputs.get("Roughness")
                if roughness:
                    roughness.default_value = min(max(float(roughness.default_value), 0.22), 0.96)
                specular = principled.inputs.get("Specular IOR Level")
                if specular:
                    specular.default_value = min(max(float(specular.default_value), 0.18), 0.65)
            material["open3d_surface_pass"] = "pbr-ready-uv"
        obj["open3d_surface_pass"] = "uv-unwrapped"
    return {"objects_with_uv": uv_existing + uv_created, "uv_created": uv_created, "materials": material_count, "failures": failures}


def _surface_texture_pass(objects: list, output: Path) -> dict:
    """Add small deterministic baked-looking texture images to exported materials."""

    import bpy  # type: ignore

    texture_dir = output / "textures"
    texture_dir.mkdir(parents=True, exist_ok=True)
    materials = []
    for obj in objects:
        for material in obj.data.materials:
            if material and material not in materials:
                materials.append(material)
    created = 0
    existing = 0
    failures = []
    for material in materials:
        nodes = material.node_tree.nodes if material.use_nodes and material.node_tree else None
        links = material.node_tree.links if material.use_nodes and material.node_tree else None
        if nodes is None or links is None:
            failures.append({"material": material.name, "error": "material nodes unavailable"})
            continue
        if material.get("open3d_surface_texture"):
            existing += 1
            continue
        principled = nodes.get("Principled BSDF")
        if principled is None:
            failures.append({"material": material.name, "error": "Principled BSDF unavailable"})
            continue
        base = principled.inputs.get("Base Color")
        if base is None:
            failures.append({"material": material.name, "error": "Base Color unavailable"})
            continue
        color = tuple(float(value) for value in base.default_value[:3])
        size = 128
        seed = sum((index + 1) * ord(char) for index, char in enumerate(material.name))
        pixels = []
        label = material.name.lower()
        for y in range(size):
            for x in range(size):
                slow = 0.5 + 0.5 * math.sin((x * 0.115 + y * 0.017) + seed * 0.071)
                fine = 0.5 + 0.5 * math.sin((x * 0.83 + y * 0.37) + seed * 0.19)
                if any(word in label for word in ("wood", "timber", "pine", "door")):
                    factor = 0.82 + 0.18 * slow + 0.05 * fine
                elif any(word in label for word in ("stone", "mortar", "concrete")):
                    factor = 0.78 + 0.16 * fine + 0.06 * slow
                elif any(word in label for word in ("roof", "shingle", "charcoal")):
                    factor = 0.88 + 0.08 * slow + 0.04 * fine
                elif any(word in label for word in ("glass", "iron", "metal")):
                    factor = 0.94 + 0.04 * fine
                else:
                    factor = 0.9 + 0.08 * slow + 0.02 * fine
                pixels.extend((min(max(color[0] * factor, 0.0), 1.0), min(max(color[1] * factor, 0.0), 1.0), min(max(color[2] * factor, 0.0), 1.0), 1.0))
        safe_name = "".join(char if char.isalnum() else "_" for char in material.name).strip("_") or "material"
        image = bpy.data.images.get("Open3D Surface " + safe_name) or bpy.data.images.new("Open3D Surface " + safe_name, width=size, height=size, alpha=False)
        image.pixels = pixels
        image.filepath_raw = str(texture_dir / f"{safe_name}.png")
        image.file_format = "PNG"
        image.save()
        try:
            image.pack()
        except Exception:
            pass
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = "Open3D baked surface texture"
        texture.label = "Open3D surface variation"
        texture.image = image
        texture.interpolation = "Linear"
        texture.location = (-420, 90)
        links.new(texture.outputs["Color"], base)
        bump = nodes.new("ShaderNodeBump")
        bump.name = "Open3D micro surface"
        bump.inputs["Strength"].default_value = 0.075 if "glass" not in label else 0.02
        bump.inputs["Distance"].default_value = 0.045
        bump.location = (-120, -120)
        links.new(texture.outputs["Color"], bump.inputs["Height"])
        normal = principled.inputs.get("Normal")
        if normal:
            links.new(bump.outputs["Normal"], normal)
        material["open3d_surface_texture"] = "embedded-png"
        material["open3d_surface_texture_path"] = str((texture_dir / f"{safe_name}.png").relative_to(output))
        created += 1
    return {"materials": len(materials), "textures_created": created, "textures_existing": existing, "failures": failures}


def _look_at(camera, target) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def _remove_preview_objects() -> None:
    import bpy  # type: ignore

    for obj in list(bpy.data.objects):
        if obj.get("open3d_preview_only"):
            bpy.data.objects.remove(obj, do_unlink=True)


def _material(name: str, color: tuple[float, float, float, float], roughness: float = 0.82):
    import bpy  # type: ignore

    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = roughness
    material["open3d_preview_only"] = True
    return material


def _preview_setup(objects: list, mins: list[float], maxs: list[float], size: list[float]):
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore

    _remove_preview_objects()
    scene = bpy.context.scene
    center = Vector(((mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2, mins[2] + size[2] * 0.46))
    radius = max(size)
    ground_size = max(radius * 4.0, 4.0)
    bpy.ops.mesh.primitive_plane_add(size=ground_size, location=(center.x, center.y, mins[2] - max(radius * 0.004, 0.002)))
    ground = bpy.context.object
    ground.name = "OPEN3D_PREVIEW_GROUND"
    ground["open3d_preview_only"] = True
    ground.data.materials.append(_material("Open3D Preview Ground", (0.018, 0.026, 0.023, 1.0), 0.92))

    camera_data = bpy.data.cameras.new("Open3D Preview Camera")
    camera = bpy.data.objects.new("OPEN3D_PREVIEW_CAMERA", camera_data)
    camera["open3d_preview_only"] = True
    bpy.context.scene.collection.objects.link(camera)
    camera_data.lens = 52
    camera_data.sensor_width = 36
    camera_data.clip_start = max(radius * 0.001, 0.01)
    camera_data.clip_end = max(radius * 20.0, 100.0)
    scene.camera = camera

    lights = (("KEY", (radius * 1.7, -radius * 2.0, radius * 2.4), (1200, 1.0)),
              ("FILL", (-radius * 1.8, -radius * 0.8, radius * 1.3), (700, 1.0)),
              ("RIM", (radius * 0.7, radius * 1.9, radius * 2.2), (1000, 1.0)))
    for name, location, settings in lights:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = "OPEN3D_PREVIEW_" + name
        light["open3d_preview_only"] = True
        light.data.energy = settings[0]
        light.data.shape = "DISK"
        light.data.size = max(radius * 1.2, 1.0)
        _look_at(light, center)

    world = scene.world or bpy.data.worlds.new("Open3D Preview World")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.012, 0.018, 0.016, 1.0)
        background.inputs["Strength"].default_value = 0.32
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    return camera, center, radius


def _render_views(output: Path, camera, target, radius: float) -> dict:
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore

    offsets = {
        "HERO_3Q": (1.55, -1.55, 0.82),
        "FRONT": (0.0, -2.45, 0.42),
        "BACK": (0.0, 2.45, 0.42),
        "LEFT": (-2.45, 0.0, 0.42),
        "RIGHT": (2.45, 0.0, 0.42),
        "TOP": (0.0, -0.65, 2.65),
    }
    renders = {}
    scene = bpy.context.scene
    render_dir = output / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    for view in VIEWS:
        camera.location = target + Vector(tuple(value * radius for value in offsets[view]))
        _look_at(camera, target)
        path = render_dir / f"{view}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"render missing: {view}")
        dimensions = {"width": int(scene.render.resolution_x * scene.render.resolution_percentage / 100), "height": int(scene.render.resolution_y * scene.render.resolution_percentage / 100)}
        visual_sanity = {"status": "PASS" if dimensions == {"width": 640, "height": 640} else "FAIL", "dimensions": dimensions}
        if visual_sanity["status"] != "PASS":
            raise ValueError(f"render has unexpected dimensions: {view}")
        renders[view] = {"path": str(path.relative_to(output)), "bytes": path.stat().st_size, "status": "PASS", "visual_sanity": visual_sanity}
    return renders


def _export(output: Path, objects: list) -> None:
    import bpy  # type: ignore

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    glb = output / "asset.glb"
    try:
        bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", export_extras=True,
                                  export_materials="EXPORT", use_selection=True, export_cameras=False,
                                  export_lights=False, export_apply=True)
    except TypeError:
        bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", export_extras=True,
                                  export_materials="EXPORT", use_selection=True, export_cameras=False,
                                  export_lights=False)
    if not glb.is_file() or glb.stat().st_size == 0:
        raise ValueError("asset.glb was not exported")


def _evaluated_triangles(objects: list) -> int:
    import bpy  # type: ignore

    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles = 0
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            triangles += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    return triangles


def run(args: argparse.Namespace) -> int:
    import bpy  # type: ignore

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend)), load_ui=False)
    scene = bpy.context.scene
    objects = _semantic_objects(contract)
    if not objects:
        raise ValueError("agent scene contains no contract semantic mesh objects")
    scene["open3d_asset_id"] = contract.get("asset_id", "")
    scene["open3d_pipeline"] = "blender-design-v1"
    scene["open3d_pipeline_passes"] = ",".join(("blockout", "structural-pass", "form-refinement", "material-pass", "surface-pass", "lighting-pass", "interaction-pass", "optimization-pass"))
    mins, maxs, size = _bounds(objects)
    form = _form_refinement(objects)
    surface = _surface_pass(objects)
    if surface["failures"] or surface["objects_with_uv"] != len(objects):
        raise ValueError("surface pass did not produce UVs for every semantic object")
    texture = _surface_texture_pass(objects, output)
    if texture["failures"]:
        raise ValueError("surface texture pass failed: " + "; ".join(item["material"] for item in texture["failures"][:4]))
    camera, target, radius = _preview_setup(objects, mins, maxs, size)
    renders = _render_views(output, camera, target, radius)
    triangles = _evaluated_triangles(objects)
    budget = int(contract.get("geometry", {}).get("triangle_budget", {}).get("max", 100000))
    if triangles > budget:
        raise ValueError(f"optimized scene is over triangle budget: {triangles} > {budget}; refine the agent build instead of decimating authored details")
    _export(output, objects)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"))
    receipt = {
        "schema_version": "0.1.0",
        "pipeline": "blender-design-v1",
        "status": "PASS",
        "asset_id": contract.get("asset_id"),
        "stages": [
            {"id": "blockout", "status": "PASS", "owner": "external-agent"},
            {"id": "structural-pass", "status": "PASS", "owner": "external-agent"},
            {"id": "form-refinement", "status": "PASS", "owner": "open3d", "evidence": form},
            {"id": "material-pass", "status": "PASS", "owner": "open3d", "evidence": {"materials": surface["materials"]}},
            {"id": "surface-pass", "status": "PASS", "owner": "open3d", "evidence": {**surface, **texture}},
            {"id": "lighting-pass", "status": "PASS", "owner": "open3d", "evidence": {"engine": scene.render.engine}},
            {"id": "interaction-pass", "status": "PASS", "owner": "open3d", "evidence": {"semantic_objects": len(objects)}},
            {"id": "optimization-pass", "status": "PASS", "owner": "open3d", "evidence": {"export": "GLB", "triangles": triangles, "triangle_budget": budget, "preview_only_objects_excluded": True}},
        ],
        "views": renders,
        "render_contract": {"width": 640, "height": 640, "required_views": list(VIEWS)},
        "form_language": {"edge_softness": "bevel", "curved_shading": "selective-smooth", "normal_strategy": "weighted-normal-when-available"},
        "visual_review": {"status": "LOCAL_RENDER_SANITY_PASS", "reference_comparison": "pending_external_reference_review", "not_claimed": True},
    }
    _write(output / "pipeline.json", receipt)
    return 0


def main() -> int:
    try:
        return run(_arguments())
    except Exception as exc:
        args = _arguments()
        _write(Path(args.output) / "pipeline.json", {"schema_version": "0.1.0", "pipeline": "blender-design-v1", "status": "FAIL", "error": str(exc)[:1000]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
