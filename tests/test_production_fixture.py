import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "examples/production-qualification/recipe.json"
VIEWS = {"HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"}


class ProductionFixtureTest(unittest.TestCase):
    def test_fixture_is_reproducible_and_truthful(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "qualification"
            subprocess.run(["blender", "--background", "--factory-startup", "--python", str(ROOT / "tools/production_fixture/generate_fixture.py"), "--", "--recipe", str(RECIPE), "--output", str(output)], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            files = {path.name for path in output.iterdir()}
            self.assertTrue(any(name.endswith(".blend") for name in files))
            self.assertTrue(any(name.endswith(".glb") for name in files))
            self.assertTrue(VIEWS <= {name[:-4] for name in files if name.endswith(".png")})
            evidence = json.loads((output / "evidence.json").read_text())
            qa = json.loads((output / "qa.json").read_text())
            self.assertEqual(evidence["required_views"], sorted(VIEWS, key=["HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"].index))
            self.assertEqual(qa["external_visual_qa"]["status"], "UNAVAILABLE_REPAIR_REQUIRED")
            self.assertNotEqual(qa["approval"], "APPROVED")
            validation = subprocess.run(["python3", "-m", "open3d_artist", "validate", str(output)], cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE)
            self.assertIn('"status": "PASS"', validation.stdout)


if __name__ == "__main__":
    unittest.main()
