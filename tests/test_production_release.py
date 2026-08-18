import json
import tempfile
import unittest
from pathlib import Path

from open3d_artist.production import promote_production, run_production, verify_release
from open3d_artist.project import Project, ProjectError


ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/production-qualification/brief.json").read_text())


class ProductionReleaseTest(unittest.TestCase):
    def test_promotes_immutable_release_and_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run_production(BRIEF, run)
            project = Path(directory) / "project"
            result = promote_production(run, project)
            self.assertEqual(result["promotion"]["state"], "PROMOTED_LOCAL_NOT_APPROVED")
            self.assertEqual(result["promotion"]["external_visual_qa"], "UNAVAILABLE")
            self.assertEqual(verify_release(Project(project))["status"], "PASS")
            self.assertEqual(len(Project(project).current()["production_artifacts"]["renders"]), 6)

    def test_rejects_tampered_digest_and_unsafe_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run_production(BRIEF, run)
            with self.assertRaisesRegex(ProjectError, "separate from run"):
                promote_production(run, run / "nested")
            receipt_path = run / "run_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["artifacts_manifest"]["files"][0]["sha256"] = "sha256:" + "0" * 64
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ProjectError, "digest mismatch"):
                promote_production(run, Path(directory) / "project")
            with self.assertRaisesRegex(ProjectError, "digest mismatch"):
                promote_production(run, Path(directory) / "project-2")

    def test_rejects_false_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            result = run_production(BRIEF, run)
            self.assertNotEqual(result["promotion"]["state"], "APPROVED")
            receipt = json.loads((run / "run_receipt.json").read_text())
            receipt["promotion"]["state"] = "APPROVED"
            (run / "run_receipt.json").write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ProjectError, "cannot be APPROVED"):
                promote_production(run, Path(directory) / "project")


if __name__ == "__main__":
    unittest.main()
