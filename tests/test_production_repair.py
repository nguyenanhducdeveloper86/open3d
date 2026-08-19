import json
import os
import tempfile
import unittest
from pathlib import Path

from open3d_artist.production import REQUIRED_VIEWS, repair_production, run_production
from open3d_artist.project import ProjectError


ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/production-qualification/brief.json").read_text())


class ProductionRepairTest(unittest.TestCase):
    def test_fixed_repair_mutates_artifacts_and_regenerates_views(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run_production(BRIEF, run)
            before = (run / "PROP-CAMP-LANTERN-001.glb").read_bytes()
            result = repair_production(run, "fixture-repair-v1")
            repair = result["repair"]
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(repair["geometry_mutated"])
            self.assertNotEqual(before, (run / "PROP-CAMP-LANTERN-001.glb").read_bytes())
            self.assertEqual(repair["attempts"], 1)
            self.assertLessEqual(repair["attempts"], 3)
            self.assertEqual(repair["BEST_VERSION"], "v002")
            self.assertTrue(repair["rollback"]["available"])
            self.assertEqual(set(REQUIRED_VIEWS), {path.stem for path in run.glob("*.png")})
            manifest = json.loads((run / "reference_manifest.json").read_text())
            self.assertEqual(manifest["approval"], "LOCAL_ONLY_NOT_APPROVED")
            self.assertEqual(manifest["visual_qa"]["status"], "UNAVAILABLE_REPAIR_REQUIRED")
            with self.assertRaisesRegex(ProjectError, "repair attempt cap"):
                repair_production(run, "fixture-repair-v1")

    def test_rejects_invalid_id_and_symlink_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            with self.assertRaisesRegex(ProjectError, "unknown repair_id"):
                repair_production(run, "not-allowlisted-v1")
            target = Path(directory) / "target"
            target.mkdir()
            link = Path(directory) / "link"
            os.symlink(target, link)
            with self.assertRaisesRegex(ProjectError, "run must be a directory"):
                repair_production(link, "fixture-repair-v1")


if __name__ == "__main__":
    unittest.main()
