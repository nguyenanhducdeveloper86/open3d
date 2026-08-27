import json
import tempfile
import unittest
from pathlib import Path

from open3d_artist.geometry import generate_glb
from open3d_artist.project import Project
from open3d_artist.qa import _glb_mesh_stats


ASSET = {
    "schema_version": "0.1.0",
    "asset_id": "TEST-PROP-001",
    "kind": "prop",
    "units": "m",
    "dimensions": {"width": 2, "depth": 2, "height": 2},
    "parts": [{"part_id": "body", "role": "body"}, {"part_id": "handle", "role": "functional"}],
    "geometry": {"triangle_budget": {"max": 1000}, "primitives": [
        {"part_id": "body", "type": "box", "size": {"x": 1, "y": 1, "z": 1}, "center": {"x": 0, "y": 0, "z": 0}, "color": "#4477aa"},
        {"part_id": "handle", "type": "box", "size": {"x": 0.2, "y": 0.8, "z": 0.8}, "center": {"x": 0.6, "y": 0, "z": 0}, "color": "#aaaaaa"},
    ]},
}


class CoreWorkflowTest(unittest.TestCase):
    def test_glb_bounds_include_node_transforms(self):
        gltf = {
            "accessors": [{"min": [-1, -2, -3], "max": [1, 2, 3], "count": 36}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 0}]}],
            "nodes": [{"mesh": 0, "translation": [10, 20, 30]}],
        }
        stats = _glb_mesh_stats(gltf)
        self.assertEqual(stats["bounds"]["min"], [9.0, 18.0, 27.0])
        self.assertEqual(stats["bounds"]["max"], [11.0, 22.0, 33.0])
        self.assertEqual(stats["bounds"]["size"], [2.0, 4.0, 6.0])
        blender_stats = _glb_mesh_stats({**gltf, "asset": {"generator": "Khronos glTF Blender I/O v5.2.39"}})
        self.assertEqual(blender_stats["bounds"]["size"], [2.0, 6.0, 4.0])

    def test_edit_validate_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "asset"
            root.mkdir()
            (root / "asset.yaml").write_text(json.dumps(ASSET), encoding="utf-8")
            project = Project.init(root, root / "asset.yaml")
            before = project.current()
            self.assertEqual(project.validate()["status"], "PASS")
            result = project.edit_part("handle", {"x": 1.1}, idempotency_key="test-edit")
            self.assertEqual(result["report"]["status"], "PASS")
            edited = project.current()
            self.assertNotEqual(edited["glb_artifact"], before["glb_artifact"])
            project.rollback(before["checkpoint_id"])
            self.assertEqual(project.current()["glb_artifact"], before["glb_artifact"])
            self.assertEqual(project.validate()["status"], "PASS")

    def test_asset_versions_and_undo_restore_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "asset"
            root.mkdir()
            (root / "asset.yaml").write_text(json.dumps(ASSET), encoding="utf-8")
            project = Project.init(root, root / "asset.yaml")
            before = project.current()
            initial = project.asset_versions()
            self.assertEqual(initial["current_version"], "v001")
            self.assertFalse(initial["can_undo"])

            project.edit_part("handle", {"x": 1.1}, idempotency_key="versioned-edit")
            edited = project.asset_versions()
            self.assertEqual([item["version_id"] for item in edited["versions"]], ["v001", "v002"])
            self.assertEqual(edited["current_version"], "v002")
            self.assertTrue(edited["can_undo"])

            undone = project.undo()
            self.assertEqual(undone["status"], "PASS")
            self.assertEqual(undone["restored_version"]["version_id"], "v001")
            self.assertEqual(project.current()["glb_artifact"], before["glb_artifact"])
            restored = project.asset_versions()
            self.assertEqual(restored["current_version"], "v001")
            self.assertFalse(restored["can_undo"])

            second_asset = json.loads(json.dumps(ASSET))
            second_asset["asset_id"] = "TEST-PROP-002"
            project.replace_generated_asset(second_asset, generate_glb(second_asset), agent="codex", prompt="new asset", run_id="test-run")
            self.assertEqual(project.asset_versions()["current_version"], "v001")
            self.assertFalse(project.asset_versions()["can_undo"])
            self.assertEqual(project.undo()["status"], "NOOP")
            catalog_versions = project.asset_versions(ASSET["asset_id"])
            self.assertEqual(catalog_versions["current_version"], "v001")
            self.assertFalse(catalog_versions["can_undo"])


if __name__ == "__main__":
    unittest.main()
