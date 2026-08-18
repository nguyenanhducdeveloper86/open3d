import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from open3d_artist.agent_bridge import run_production_agent
from open3d_artist.contracts import digest_json
from open3d_artist.project import ProjectError


class FakeRunner:
    def __init__(self, output="{}\n", returncode=0):
        self.output, self.returncode, self.calls = output, returncode, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=b"fake 1\n", stderr=b"")
        return SimpleNamespace(returncode=self.returncode, stdout=self.output.encode(), stderr=b"fake error")


def completed_run(root):
    receipt = {"schema_version": "0.2.0", "status": "PASS", "brief_id": "fixture"}
    (root / "run_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return receipt


class ProductionAgentReceiptTests(unittest.TestCase):
    def test_fixed_read_only_bridge_writes_digest_linked_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); receipt = completed_run(root)
            digest = digest_json(receipt)
            fake = FakeRunner(json.dumps({"agent_receipt": {"production_receipt_digest": digest}}))
            result = run_production_agent("codex", root, runner=fake, which=lambda _: "/bin/fake")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["production_receipt_digest"], digest)
            self.assertEqual(fake.calls[1][1:4], ["exec", "--sandbox", "read-only"])
            self.assertTrue((root / "agent_process_receipt.json").is_file())

    def test_rejects_unsafe_inputs_and_agent_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); completed_run(root)
            with self.assertRaises(ProjectError): run_production_agent("shell", root)
            with self.assertRaises(ProjectError): run_production_agent("codex", root, output_root=root / "other")
            fake = FakeRunner(json.dumps({"agent_receipt": {"production_receipt_digest": "sha256:bad"}}))
            result = run_production_agent("codex", root, runner=fake, which=lambda _: "/bin/fake")
            self.assertEqual(result["reason"], "RECEIPT_DIGEST_MISMATCH")

    def test_missing_and_failed_cli_are_truthful_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); completed_run(root)
            missing = run_production_agent("claude", root, which=lambda _: None)
            self.assertEqual(missing["status"], "UNAVAILABLE")
            fake = FakeRunner("x" * 100000, returncode=1)
            failed = run_production_agent("codex", root, runner=fake, which=lambda _: "/bin/fake")
            self.assertEqual(failed["status"], "FAILED")
            self.assertLessEqual(len(failed["stdout"]), 16 * 1024 + len("...[truncated]"))


if __name__ == "__main__":
    unittest.main()
