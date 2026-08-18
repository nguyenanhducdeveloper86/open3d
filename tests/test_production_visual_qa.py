import json
import tempfile
import unittest
from pathlib import Path

from open3d_artist.production import run_production


ROOT = Path(__file__).resolve().parents[1]
BRIEF = json.loads((ROOT / "examples/production-qualification/brief.json").read_text(encoding="utf-8"))


class ProductionVisualQATest(unittest.TestCase):
    def test_local_report_is_bounded_and_truthful(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_production(BRIEF, Path(directory) / "run")["receipt"]["reference_manifest"]
        qa = manifest["visual_qa"]
        self.assertEqual(qa["method"], "LOCAL_IMAGEMAGICK_RGB_MAE")
        self.assertEqual(qa["dimensions"], {"width": 256, "height": 256, "channels": 3})
        self.assertGreaterEqual(qa["similarity"], 0)
        self.assertLessEqual(qa["similarity"], 1)
        self.assertTrue(qa["matched_components"])
        self.assertIn("next_action", qa)
        self.assertEqual(qa["scope"], "PACK_PENDING_FULL_6_VIEW")
        self.assertEqual(manifest["repair"]["max_attempts"], 3)
        self.assertEqual(manifest["repair"]["attempts"], 0)
        self.assertEqual(manifest["approval"], "LOCAL_ONLY_NOT_APPROVED")


if __name__ == "__main__":
    unittest.main()
