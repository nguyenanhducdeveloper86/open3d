import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from open3d_artist.project import Project
from open3d_artist.server import Open3DHTTPServer


ASSET = {
    "schema_version": "0.1.0",
    "asset_id": "TEST-WORKSPACE-001",
    "kind": "prop",
    "units": "m",
    "dimensions": {"width": 2, "depth": 2, "height": 2},
    "parts": [{"part_id": "body", "role": "body"}],
    "geometry": {"triangle_budget": {"max": 1000}, "primitives": [{"part_id": "body", "type": "box", "size": {"x": 1, "y": 1, "z": 1}}]},
}


class WorkspaceTest(unittest.TestCase):
    def test_catalog_scene_and_http_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            (root / "asset.yaml").write_text(json.dumps(ASSET), encoding="utf-8")
            project = Project.init(root, root / "asset.yaml")
            workspace = project.workspace()
            self.assertEqual(len(workspace["assets"]), 1)
            self.assertEqual(len(workspace["scene"]["instances"]), 1)
            preview = project.store.put_bytes(b"fake-png", kind="preview-render", metadata={"view": "HERO_3Q"})
            current = project.current()
            current["preview_artifacts"] = {"HERO_3Q": preview}
            project._write_current(current)
            instance = project.add_scene_instance(ASSET["asset_id"], {"position": {"x": 2, "z": -1}})
            self.assertEqual(instance["position"]["x"], 2.0)
            self.assertEqual(len(project.workspace()["scene"]["instances"]), 2)

            web = Path(directory) / "web"
            web.mkdir()
            (web / "index.html").write_text("viewer", encoding="utf-8")
            server = Open3DHTTPServer(("127.0.0.1", 0), project, web)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/api/workspace")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(len(json.loads(response.read())["assets"]), 1)
                connection.request("GET", "/api/versions")
                response = connection.getresponse()
                versions = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(versions["current_version"], "v001")
                self.assertFalse(versions["can_undo"])
                connection.request("GET", f"/api/assets/{ASSET['asset_id']}")
                self.assertEqual(connection.getresponse().status, 200)
                connection.request("GET", f"/api/assets/{ASSET['asset_id']}/artifact")
                self.assertEqual(connection.getresponse().status, 200)
                connection.request("GET", "/api/preview/HERO_3Q")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b"fake-png")
                payload = json.dumps({"asset_id": ASSET["asset_id"], "transform": {"position": {"x": 4}}}).encode()
                connection.request("POST", "/api/scene/instances", body=payload, headers={"Content-Type": "application/json"})
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
