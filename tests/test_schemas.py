import json
import unittest
from pathlib import Path


class PublishedSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
        except ImportError:
            cls.jsonschema = None
        else:
            cls.jsonschema = jsonschema

    def test_schemas_and_golden_asset(self):
        if self.jsonschema is None:
            self.skipTest("install open3d-artist[dev] for JSON Schema conformance")
        root = Path(__file__).parents[1]
        schemas = list((root / "schemas/v0.1").glob("*.json"))
        self.assertEqual(len(schemas), 12)
        for schema_path in schemas:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.jsonschema.Draft202012Validator.check_schema(schema)
        asset_schema = json.loads((root / "schemas/v0.1/asset.schema.json").read_text(encoding="utf-8"))
        asset = json.loads((root / "examples/watering-can/asset.yaml").read_text(encoding="utf-8"))
        self.jsonschema.Draft202012Validator(asset_schema).validate(asset)


if __name__ == "__main__":
    unittest.main()
