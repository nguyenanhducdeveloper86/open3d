import io
import json
import sys
import tempfile
import unittest
import base64
from pathlib import Path

from open3d_artist.geometry import generate_glb
from open3d_artist.providers import All2ApiImageGenerator, ConsentRequired, MeshyImageTo3D, MeshyPipeline, OpenAICompatibleImageGenerator
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
                if sys.platform == "darwin":
                    self.assertEqual(command[command.index("--gpu-backend") + 1], "metal")
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

    def test_meshy_pipeline_refines_and_adopts_provider_glb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "open3d"
            root.mkdir()
            project = self.project(root)
            glb = project.store.read_bytes(project.current()["glb_artifact"])
            calls = []

            def opener(request, timeout=0):
                calls.append((request.method, request.full_url, json.loads(request.data.decode()) if request.data else None))
                if request.method == "POST" and request.full_url.endswith("/text-to-3d"):
                    return Response({"result": "preview-1" if calls[-1][2]["mode"] == "preview" else "refine-1"})
                if request.full_url.endswith("/preview-1"):
                    return Response({"status": "SUCCEEDED"})
                if request.full_url.endswith("/refine-1"):
                    return Response({"status": "SUCCEEDED", "model_urls": {"glb": "https://cdn.example/model.glb"}})
                return Response(glb)

            result = MeshyPipeline(api_key="test-key", text_endpoint="https://mesh.example/v2/text-to-3d", opener=opener).run(
                project, asset_id="PROP-CABIN-001", prompt="a production-quality cabin", consent=True, quality="high", poll_interval=0
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["mode"], "text")
            self.assertEqual(result["task_ids"], ["preview-1", "refine-1"])
            self.assertEqual(project.current()["asset_id"], "PROP-CABIN-001")
            self.assertEqual(project.current()["geometry_source"], "meshy")
            self.assertEqual(project.history()[-1]["name"], "asset.provider_generate")
            self.assertEqual(calls[0][2]["ai_model"], "meshy-7")
            self.assertTrue(calls[0][2]["ultra_mode"])
            self.assertEqual(calls[1][0], "GET")

    def test_openai_compatible_image_generator_returns_data_uri(self):
        png = b"\x89PNG\r\n\x1a\n" + b"open3d-image-fixture"

        def opener(request, timeout=0):
            self.assertEqual(request.method, "POST")
            payload = json.loads(request.data.decode())
            self.assertEqual(payload["model"], "test-image")
            return Response({"data": [{"b64_json": base64.b64encode(png).decode()}]})

        result = OpenAICompatibleImageGenerator(provider_id="all2api-image", api_key="test-key", base_url="https://all2api.example/v1", model="test-image", opener=opener).generate(prompt="a cabin", quality="high")
        self.assertEqual(result["provider"], "all2api-image")
        self.assertTrue(result["data"].startswith("data:image/png;base64,"))

    def test_all2api_bridge_generates_reference_image_from_browser_worker(self):
        png = b"\x89PNG\r\n\x1a\nall2api-image-fixture"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            image = output / "reference.png"
            image.write_bytes(png)
            calls = []

            def opener(request, timeout=0):
                calls.append((request.method, request.full_url, json.loads(request.data.decode()) if request.data else None))
                if request.method == "GET" and request.full_url.endswith("/api/health"):
                    return Response({"ok": True, "outputDir": str(output)})
                if request.method == "POST":
                    self.assertEqual(calls[-1][2]["tool"], "chatgpt")
                    self.assertEqual(calls[-1][2]["model"], "High")
                    return Response({"jobId": "job-1", "status": "pending"})
                return Response({"jobId": "job-1", "status": "done", "savedPath": str(image)})

            result = All2ApiImageGenerator(base_url="http://all2api.test", opener=opener).generate(prompt="a production cabin", quality="high", timeout=10)
            self.assertEqual(result["provider"], "all2api-image")
            self.assertTrue(result["data"].startswith("data:image/png;base64,"))
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
