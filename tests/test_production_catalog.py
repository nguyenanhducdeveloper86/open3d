import json
import tempfile
import unittest
from pathlib import Path

from open3d_artist.production import REQUIRED_VIEWS, catalog, run_production
from open3d_artist.project import ProjectError

ROOT = Path(__file__).resolve().parents[1]


class ProductionCatalogTest(unittest.TestCase):
    def test_every_catalog_entry_emits_ordered_reference_manifest(self):
        brief_names = {"production-qualification-lantern-v1": "brief.json", "production-qualification-watering-can-v1": "brief-watering-can.json", "production-qualification-wood-crate-v1": "brief-wood-crate.json"}
        for entry in catalog():
            brief = json.loads((ROOT / "examples/production-qualification" / brief_names[entry["recipe_id"]]).read_text())
            with tempfile.TemporaryDirectory() as directory:
                result = run_production(brief, Path(directory) / "run")
                self.assertEqual(result["validation"]["status"], "PASS")
                manifest = result["receipt"]["reference_manifest"]
                self.assertEqual(manifest["required_views"], REQUIRED_VIEWS)
                self.assertEqual([item["role"] for item in manifest["attachments"][:2]], ["REFERENCE_SAMPLE", "CANDIDATE"])
                self.assertEqual([item["view"] for item in manifest["attachments"][1:]], REQUIRED_VIEWS)
                self.assertEqual(manifest["visual_qa"]["status"], "UNAVAILABLE_REPAIR_REQUIRED")
                self.assertEqual(manifest["visual_qa"]["scope"], "PACK_PENDING_FULL_6_VIEW")
                self.assertTrue(manifest["visual_qa"]["matched_components"])
                self.assertIn("next_action", manifest["visual_qa"])
                self.assertEqual(manifest["repair"]["max_attempts"], 3)
                self.assertEqual(manifest["repair"]["attempts"], 0)
                self.assertEqual(manifest["repair"]["BEST_VERSION"], "v001")
                self.assertEqual(manifest["approval"], "LOCAL_ONLY_NOT_APPROVED")

    def test_unknown_catalog_recipe_is_rejected(self):
        brief = json.loads((ROOT / "examples/production-qualification/brief.json").read_text())
        brief["recipe_id"] = "unknown-v1"
        with self.assertRaisesRegex(ProjectError, "unknown recipe_id"):
            run_production(brief, tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
