import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open3d_artist import mcp


class MCPTests(unittest.TestCase):
    def test_tools_list_loads_recipe_ids_lazily(self):
        expected = [entry["recipe_id"] for entry in mcp.catalog()]
        response = mcp.handle(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertIn("asset.inspect", tools)
        self.assertEqual(expected, tools["production.run"]["inputSchema"]["properties"]["brief"]["properties"]["recipe_id"]["enum"])

        with tempfile.TemporaryDirectory() as directory, patch.object(mcp, "CATALOG", Path(directory) / "missing.json"):
            response = mcp.handle(None, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertIn("asset.inspect", tools)
        self.assertEqual([], tools["production.run"]["inputSchema"]["properties"]["brief"]["properties"]["recipe_id"]["enum"])


if __name__ == "__main__":
    unittest.main()
