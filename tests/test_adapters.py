import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from open3d_artist.geometry import generate_glb
from open3d_artist.providers import ConsentRequired, MeshyImageTo3D
from open3d_artist.project import Project
from open3d_artist.unity import UnityValidator
from open3d_artist.workers import BlenderSandbox, WorkerUnavailable, run_limited


ASSET = {
    "schema_version": "0.1.0",
    "asset_id": "ADAPTER-001",
    "kind": "prop",
    "units": "m",
    "dimensions": {"width": 1, "depth": 1, "height": 1},
    "parts": [{"part_id": "body", "role": "body"}],
    "geometry": {"triangle_budget": {"max": 1000}, "primitives": [{"part_id": "body", "type": "box", "size": {"x": 1, "y": 1, "z": 1}}]},
}


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode()


class AdapterTest(unittest.TestCase):
    def project(self, root):
        (root / "asset.yaml").write_text(json.dumps(ASSET), encoding="utf-8")
        return Project.init(root, root / "asset.yaml")

    def test_worker_policy_and_unity_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "open3d"
            root.mkdir()
            project = self.project(root)
            blend = root / "scene.blend"
            blend.write_bytes(b"blend-fixture")
            sandbox = BlenderSandbox(root, blender=sys.executable, bwrap="missing-bwrap", sandbox_exec="missing-sandbox-exec")
            with self.assertRaises(WorkerUnavailable):
                sandbox.run({"operation": "inspect", "input_blend": "scene.blend"})
            with tempfile.TemporaryDirectory() as inputs, tempfile.TemporaryDirectory() as outputs:
                command = sandbox.build_command({"operation": "inspect", "input_blend": "scene.blend"}, input_dir=Path(inputs), output_dir=Path(outputs), sandboxed=False)
                self.assertIn("--disable-autoexec", command)
                self.assertIn("--factory-startup", command)
            unity_root = root / "unity"
            (unity_root / "Assets").mkdir(parents=True)
            (unity_root / "Assets/model.glb").write_bytes(project.store.read_bytes(project.current()["glb_artifact"]))
            command = UnityValidator(unity_root, unity="unity-editor").command("Assets/model.glb", ".open3d/report.json")
            self.assertIn("-batchmode", command)
            self.assertIn("Open3DValidator.Run", command)
            with self.assertRaises(ValueError):
                UnityValidator(unity_root).command("../outside.glb", ".open3d/report.json")

    def test_provider_requires_consent_and_stores_verified_glb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "open3d"
            root.mkdir()
            project = self.project(root)
            glb = project.store.read_bytes(project.current()["glb_artifact"])
            calls = []

            def opener(request, timeout=0):
                calls.append((request.method, request.full_url, timeout))
                if request.method == "POST":
                    return Response({"result": "task-1"})
                if request.full_url.endswith("/task-1"):
                    return Response({"status": "SUCCEEDED", "model_urls": {"glb": "https://cdn.example/model.glb"}})
                return Response(glb)

            provider = MeshyImageTo3D(api_key="test-key", opener=opener)
            with self.assertRaises(ConsentRequired):
                provider.generate(project, image_url="https://example.com/input.png", consent=False)
            result = provider.generate(project, image_url="https://example.com/input.png", consent=True, poll_interval=0)
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertTrue(project.store.read_bytes(result["artifact_id"]).startswith(b"glTF"))
            self.assertEqual(calls[0][0], "POST")

    def test_bounded_process_output(self):
        result = run_limited([sys.executable, "-c", "print('ok')"], cwd=Path.cwd(), timeout=2, max_output=64)
        self.assertEqual(result.status, "PASS")
        self.assertIn("ok", result.output)


if __name__ == "__main__":
    unittest.main()
