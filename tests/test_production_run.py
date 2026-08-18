import json
import threading
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path

from open3d_artist.production import run_production
from open3d_artist.project import Project
from open3d_artist.server import Open3DHTTPServer


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "examples/production-qualification/recipe.json"
BRIEF = json.loads((ROOT / "examples/production-qualification/brief.json").read_text(encoding="utf-8"))


class ProductionRunTest(unittest.TestCase):
    def test_run_project_state_and_viewer_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "qualification"
            result = run_production(BRIEF, output)
            self.assertEqual(result["receipt"]["brief"]["id"], BRIEF["brief_id"])
            self.assertEqual(result["receipt"]["recipe"]["id"], BRIEF["recipe_id"])
            self.assertEqual(result["receipt"]["views"]["local_qa"], "PASS")
            self.assertEqual(result["receipt"]["sandbox"]["network"], "DENIED")
            self.assertEqual(result["validation"]["status"], "PASS")
            self.assertEqual(result["promotion"]["state"], "LOCAL_ONLY_NOT_APPROVED")
            self.assertNotEqual(result["promotion"]["state"], "APPROVED")
            self.assertTrue(Project(output).validate()["status"] == "PASS")
            self.assertTrue(result["current"]["glb"].startswith("sha256:"))
            self.assertTrue(result["current"]["qa"].startswith("sha256:"))

            web = Path(directory) / "web"
            web.mkdir()
            (web / "index.html").write_text("viewer", encoding="utf-8")
            server = Open3DHTTPServer(("127.0.0.1", 0), Project(output), web)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/")
                self.assertEqual(connection.getresponse().status, 200)
                connection.request("GET", "/api/production/state")
                state = json.loads(connection.getresponse().read())
                self.assertEqual(state["promotion"]["state"], "LOCAL_ONLY_NOT_APPROVED")
                connection.request("GET", "/api/artifact/current")
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_rejects_unknown_recipe_and_injection_fields(self):
        with self.assertRaisesRegex(Exception, "unknown recipe_id"):
            run_production({**BRIEF, "recipe_id": "not-registered-v1"}, Path(tempfile.mkdtemp()))
        with self.assertRaisesRegex(Exception, "checked-in recipe ID"):
            run_production({**BRIEF, "recipe_id": "../../run-command-v1"}, Path(tempfile.mkdtemp()))
        with self.assertRaisesRegex(Exception, "unsupported fields"):
            run_production({**BRIEF, "command": "rm -rf /"}, Path(tempfile.mkdtemp()))
        with self.assertRaisesRegex(Exception, "must match"):
            run_production({**BRIEF, "reference": {**BRIEF["reference"], "path": "../../secret"}}, Path(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
