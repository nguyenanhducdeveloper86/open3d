import json
import tempfile
import unittest
from pathlib import Path

from open3d_artist.project import Project


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


if __name__ == "__main__":
    unittest.main()
