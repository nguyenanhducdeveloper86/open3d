"""Bounded external-worker execution with an explicit sandbox policy."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .project import Project, ProjectError
from .geometry import read_glb_json


class WorkerError(RuntimeError):
    pass


class WorkerUnavailable(WorkerError):
    pass


@dataclass(frozen=True)
class ProcessResult:
    status: str
    returncode: int | None
    output: str
    duration_ms: int


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def run_limited(command: Sequence[str], *, cwd: Path, timeout: float, max_output: int = 64 * 1024, env: dict[str, str] | None = None) -> ProcessResult:
    """Run a fixed argv command with timeout and output caps."""

    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
        env=env,
    )
    output = bytearray()
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    status = "PASS"
    while selector.get_map() or process.poll() is None:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            status = "TIMEOUT"
            _kill_process(process)
            break
        for key, _ in selector.select(min(remaining, 0.2)):
            chunk = key.fileobj.read1(8192)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            output.extend(chunk)
            if len(output) > max_output:
                status = "OUTPUT_LIMIT"
                _kill_process(process)
                selector.unregister(key.fileobj)
                break
        if status != "PASS":
            break
    selector.close()
    if process.poll() is None:
        process.wait(timeout=2)
    if process.stdout is not None:
        process.stdout.close()
    duration_ms = int((time.monotonic() - started) * 1000)
    return ProcessResult(status, process.returncode, output[:max_output].decode("utf-8", errors="replace"), duration_ms)


def _inside(root: Path, value: str | Path, *, label: str, must_exist: bool = False) -> Path:
    candidate = Path(value)
    resolved = (root / candidate if not candidate.is_absolute() else candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ProjectError(f"{label} must stay inside the project") from exc
    if must_exist and not resolved.is_file():
        raise ProjectError(f"{label} does not exist: {resolved}")
    return resolved


class BlenderSandbox:
    """Launch the bundled allowlisted Blender worker, never arbitrary Python."""

    OPERATIONS = {"inspect", "validate", "export_glb"}

    def __init__(self, project_root: str | Path, *, blender: str = "blender", bwrap: str = "bwrap", sandbox_exec: str = "sandbox-exec", worker_script: str | Path | None = None):
        self.root = Path(project_root).resolve()
        self.blender = blender
        self.bwrap = bwrap
        self.sandbox_exec = sandbox_exec
        self.worker_script = Path(worker_script or Path(__file__).with_name("blender_worker.py")).resolve()

    def _sandbox_kind(self) -> str | None:
        if shutil.which(self.bwrap) or Path(self.bwrap).is_file():
            return "bubblewrap"
        if shutil.which(self.sandbox_exec) or Path(self.sandbox_exec).is_file():
            return "macos-sandbox"
        return None

    def _blender_path(self) -> Path:
        found = shutil.which(self.blender)
        if found:
            return Path(found).resolve()
        candidate = Path(self.blender).resolve()
        if candidate.is_file():
            return candidate
        raise WorkerUnavailable(f"Blender executable not found: {self.blender}")

    def _job_paths(self, job: dict[str, Any]) -> tuple[str, Path | None]:
        if not isinstance(job, dict) or set(job) - {"schema_version", "operation", "input_blend"}:
            raise ProjectError("Blender job contains unsupported fields")
        if job.get("schema_version", "0.1.0") != "0.1.0":
            raise ProjectError("unsupported Blender job schema")
        operation = job.get("operation")
        if operation not in self.OPERATIONS:
            raise ProjectError(f"unsupported Blender operation: {operation}")
        input_blend = _inside(self.root, job.get("input_blend", ""), label="input_blend", must_exist=True)
        if input_blend.suffix.lower() != ".blend":
            raise ProjectError("input_blend must be a .blend file")
        return operation, input_blend

    def build_command(self, job: dict[str, Any], *, input_dir: Path, output_dir: Path, sandboxed: bool, sandbox_kind: str | None = None) -> list[str]:
        operation, input_blend = self._job_paths(job)
        if not self.worker_script.is_file():
            raise WorkerUnavailable(f"Blender worker script is missing: {self.worker_script}")
        blender_path = self._blender_path()
        job_file = input_dir / "job.json"
        result_file = output_dir / "result.json"
        output_glb = output_dir / "export.glb"
        kind = sandbox_kind or ("bubblewrap" if sandboxed else "unsafe")
        if kind == "bubblewrap":
            project_input = Path("/project") / input_blend.relative_to(self.root)
            job_value = {"schema_version": "0.1.0", "operation": operation, "input_blend": str(project_input), "output_glb": "/output/export.glb"}
            command = [
                self.bwrap,
                "--die-with-parent",
                "--unshare-net",
            ]
            for runtime_path in (Path("/usr"), Path("/lib"), Path("/lib64"), Path("/bin"), Path("/etc"), Path("/opt")):
                if runtime_path.exists():
                    command.extend(["--ro-bind", str(runtime_path), str(runtime_path)])
            command.extend([
                "--ro-bind", str(self.root), "/project",
                "--ro-bind", str(self.worker_script.parent), "/worker",
                "--ro-bind", str(input_dir), "/input",
                "--bind", str(output_dir), "/output",
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--chdir", "/project",
                str(blender_path),
                "--background", "--factory-startup", "--disable-autoexec",
                "--python", "/worker/blender_worker.py",
                "--job", "/input/job.json", "--result", "/output/result.json",
            ])
        elif kind == "macos-sandbox":
            job_value = {"schema_version": "0.1.0", "operation": operation, "input_blend": str(input_blend), "output_glb": str(output_glb)}
            profile = self._macos_profile(input_dir, output_dir)
            command = [
                self.sandbox_exec, "-p", profile,
                str(blender_path),
                "--background", "--factory-startup", "--disable-autoexec",
                "--python", str(self.worker_script),
                "--job", str(job_file), "--result", str(result_file),
            ]
        else:
            job_value = {"schema_version": "0.1.0", "operation": operation, "input_blend": str(input_blend), "output_glb": str(output_glb)}
            command = [
                str(blender_path),
                "--background", "--factory-startup", "--disable-autoexec",
                "--python", str(self.worker_script),
                "--job", str(job_file), "--result", str(result_file),
            ]
        job_file.write_text(json.dumps(job_value, sort_keys=True), encoding="utf-8")
        return command

    @staticmethod
    def _sandbox_path(path: Path) -> str:
        return str(path).replace("\\", "\\\\").replace('"', '\\"')

    def _macos_profile(self, input_dir: Path, output_dir: Path) -> str:
        # macOS sandbox-exec needs Blender's signed runtime services to start.
        # Keep that native baseline, then deny network and all writes except
        # the declared output/temp directories.
        writable = (output_dir, Path(tempfile.gettempdir()), Path("/tmp"))
        lines = ["(version 1)", "(allow default)", "(deny network*)", "(deny file-write*)"]
        lines.extend(f'(allow file-write* (subpath "{self._sandbox_path(path)}"))' for path in writable)
        return " ".join(lines)

    def run(self, job: dict[str, Any], *, timeout: float = 300, allow_unsafe: bool = False) -> dict[str, Any]:
        self._blender_path()
        sandbox_kind = self._sandbox_kind()
        if sandbox_kind is None and not allow_unsafe:
            raise WorkerUnavailable("real sandbox unavailable; install bubblewrap or explicitly pass allow_unsafe")
        operation, _ = self._job_paths(job)
        with tempfile.TemporaryDirectory(prefix="open3d-blender-input-") as input_name, tempfile.TemporaryDirectory(prefix="open3d-blender-output-") as output_name:
            input_dir, output_dir = Path(input_name), Path(output_name)
            command = self.build_command(job, input_dir=input_dir, output_dir=output_dir, sandboxed=sandbox_kind is not None, sandbox_kind=sandbox_kind or "unsafe")
            clean_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(output_dir), "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
            result = run_limited(command, cwd=self.root, timeout=timeout, env=clean_env)
            result_path = output_dir / "result.json"
            worker_result: dict[str, Any] = {}
            if result_path.is_file():
                try:
                    worker_result = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    worker_result = {"status": "FAIL", "error": "worker result is invalid JSON"}
            response: dict[str, Any] = {
                "worker": "blender",
                "operation": operation,
                "sandbox": sandbox_kind or "unsafe-explicit",
                "process": {"status": result.status if result.status != "PASS" else ("PASS" if result.returncode == 0 else "FAIL"), "returncode": result.returncode, "duration_ms": result.duration_ms, "output": result.output},
                "result": worker_result,
            }
            if operation == "export_glb" and result.returncode == 0 and (output_dir / "export.glb").is_file():
                glb = (output_dir / "export.glb").read_bytes()
                read_glb_json(glb)
                response["artifact"] = self._store_glb(glb)
            return response

    def _store_glb(self, data: bytes) -> str:
        project = Project(self.root)
        return project.store.put_bytes(data, kind="blender-glb", metadata={"source": "blender-worker"})
