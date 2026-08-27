import unittest

from open3d_artist.geometry import generate_glb
from open3d_artist.qa import PRODUCTION_REQUIRED_DETAIL_TAGS, validate_asset_and_glb


def quality_asset():
    tags = list(PRODUCTION_REQUIRED_DETAIL_TAGS)
    parts = [{"part_id": part_id, "role": part_id} for part_id in ("body", "trim", "hardware")]
    primitives = []
    for index, part in enumerate(parts):
        for detail in range(2):
            primitives.append({
                "part_id": part["part_id"],
                "type": "box",
                "size": {"x": 0.4, "y": 0.4, "z": 0.4},
                "center": {"x": index * 0.6, "y": detail * 0.5, "z": 0.2},
                "color": [0.2 + index * 0.2, 0.2 + detail * 0.2, 0.4, 1.0],
            })
    return {
        "schema_version": "0.1.0",
        "asset_id": "QUALITY-PROP-001",
        "kind": "prop",
        "units": "m",
        "dimensions": {"width": 2, "depth": 2, "height": 2},
        "parts": parts,
        "geometry": {"triangle_budget": {"max": 1000}, "primitives": primitives},
        "metadata": {"quality_gate": {
            "profile": "production",
            "minimum_materials": 6,
            "minimum_primitives_per_part": 2,
            "required_detail_tags": tags,
            "part_detail_tags": {part["part_id"]: tags for part in parts},
        }},
    }


class ProductionQualityTest(unittest.TestCase):
    def test_production_gate_accepts_material_and_detail_coverage(self):
        asset = quality_asset()
        report = validate_asset_and_glb(asset, generate_glb(asset), quality_profile="production")
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))

    def test_production_gate_rejects_placeholder_without_quality_spec(self):
        asset = quality_asset()
        asset.pop("metadata")
        report = validate_asset_and_glb(asset, generate_glb(asset), quality_profile="production")
        self.assertEqual(report["status"], "FAIL")
        failed = {check["check_id"] for check in report["checks"] if check["status"] == "FAIL"}
        self.assertIn("quality.production_spec", failed)
        self.assertIn("quality.detail_coverage", failed)

    def test_production_gate_rejects_long_thin_roof_spans(self):
        asset = quality_asset()
        asset["dimensions"]["width"] = 4
        asset["parts"].append({"part_id": "roof", "role": "roof"})
        tags = list(PRODUCTION_REQUIRED_DETAIL_TAGS)
        asset["metadata"]["quality_gate"]["part_detail_tags"]["roof"] = tags
        asset["geometry"]["primitives"].extend([
            {"part_id": "roof", "type": "box", "size": {"x": 3, "y": 0.1, "z": 0.1}, "center": {"x": 0, "y": 0, "z": 1.4}, "color": "#111111"},
            {"part_id": "roof", "type": "box", "size": {"x": 3, "y": 0.1, "z": 0.1}, "center": {"x": 0, "y": 0, "z": 1.6}, "color": "#222222"},
        ])
        report = validate_asset_and_glb(asset, generate_glb(asset), quality_profile="production")
        self.assertEqual(report["status"], "FAIL")
        silhouette = next(check for check in report["checks"] if check["check_id"] == "quality.silhouette_integrity")
        self.assertEqual(silhouette["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
