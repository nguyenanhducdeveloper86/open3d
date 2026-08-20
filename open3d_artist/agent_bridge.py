"""Evidence-only bridge to installed Codex and Claude Code CLIs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .contracts import digest_json, load_asset
from .project import Project, ProjectError

MAX_OUTPUT = 16 * 1024
MAX_TIMEOUT = 60.0
MAX_PLAN_PROMPT = 8 * 1024
MAX_BUILD_TIMEOUT = 900.0
MAX_BUILD_PROMPT = 16 * 1024
AGENTS = ("codex", "claude", "opencode")


def _agent_label(agent: str) -> str:
    return {"codex": "Codex", "claude": "Claude Code", "opencode": "OpenCode"}.get(agent, agent)


def _bounded(value: bytes | str) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    return text[:MAX_OUTPUT] + ("...[truncated]" if len(text) > MAX_OUTPUT else "")


def _receipt_from_output(output: str) -> Any:
    candidates = [output.strip()]
    candidates.extend(line.strip() for line in output.splitlines() if line.strip().startswith("{"))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and ("agent_receipt" in value or "goalbuddy_receipt_v1" in value):
            return value
    return None


def _reported_digest(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("production_receipt_digest", "receipt_digest"):
            if isinstance(value.get(key), str):
                return value[key]
        for child in value.values():
            found = _reported_digest(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _reported_digest(child)
            if found:
                return found
    return None


def _run_command(command: list[str], *, prompt: str, cwd: Path, timeout: float, runner: Callable[..., Any]) -> Any:
    environment = {"PATH": os.path.dirname(command[0]), "LANG": "C", "LC_ALL": "C"}
    return runner(command, cwd=str(cwd), input=prompt.encode("utf-8"), stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, timeout=timeout, env=environment, check=False)


def _agent_command(agent: str, executable: str) -> list[str]:
    if agent == "codex":
        return [executable, "exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "-"]
    if agent == "claude":
        return [executable, "-p", "--bare", "--no-session-persistence", "--permission-mode", "plan", "--disallowed-tools", "Edit,Write,NotebookEdit,Bash", "--output-format", "text"]
    return [executable, "run", "--format", "default", "--auto"]


def _run_agent_command(agent: str, executable: str, prompt: str, *, cwd: Path, timeout: float,
                       runner: Callable[..., Any], build: bool = False) -> Any:
    if agent == "opencode":
        command = [executable, "run", "--dir", str(cwd), "--format", "default", "--auto", prompt]
        input_value = b""
    else:
        command = _agent_command(agent, executable)
        if build:
            if agent == "codex":
                command = [executable, "exec", "--sandbox", "workspace-write", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--cd", str(cwd), "-"]
            else:
                command = [executable, "-p", "--bare", "--no-session-persistence", "--permission-mode", "acceptEdits", "--allowed-tools", "Read,Edit,Write", "--disallowed-tools", "Bash,WebFetch,WebSearch", "--add-dir", str(cwd), "--output-format", "text"]
        input_value = prompt.encode("utf-8")
    environment = os.environ.copy() if build else {"PATH": os.path.dirname(executable), "LANG": "C", "LC_ALL": "C"}
    if build:
        environment["PATH"] = os.path.dirname(executable) + os.pathsep + os.environ.get("PATH", "")
        environment["LANG"] = "C.UTF-8"
        environment["LC_ALL"] = "C.UTF-8"
    return runner(command, cwd=str(cwd), input=input_value, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  timeout=timeout, env=environment, check=False)


def agent_catalog(*, runner: Callable[..., Any] = subprocess.run,
                  which: Callable[[str], str | None] = shutil.which) -> list[dict[str, Any]]:
    result = [{"agent_id": "local", "label": "Local agent", "status": "READY", "reason": "ALLOWLISTED_LOCAL", "version": "Open3D"}]
    for agent in AGENTS:
        executable = which(agent)
        if executable is None:
            result.append({"agent_id": agent, "label": _agent_label(agent), "status": "UNAVAILABLE", "reason": "CLI_NOT_INSTALLED", "version": None})
            continue
        try:
            value = runner([executable, "--version"], cwd=os.getcwd(), input=b"", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=10, env={"PATH": os.path.dirname(executable), "LANG": "C", "LC_ALL": "C"}, check=False)
            output = _bounded((getattr(value, "stdout", b"") or getattr(value, "stderr", b"")) or b"").strip()
            status = "READY" if getattr(value, "returncode", 1) == 0 else "UNAVAILABLE"
            reason = "CLI_AVAILABLE" if status == "READY" else "CLI_VERSION_FAILED"
        except (OSError, subprocess.SubprocessError):
            output, status, reason = "", "UNAVAILABLE", "CLI_UNAVAILABLE"
        result.append({"agent_id": agent, "label": _agent_label(agent), "status": status, "reason": reason, "version": output or None})
    return result


def run_agent_plan(agent: str, prompt: str, project: str | Path, *, timeout: float = 30,
                   runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    if agent not in AGENTS:
        raise ProjectError("agent must be codex, claude, or opencode")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PLAN_PROMPT:
        raise ProjectError(f"prompt must be non-empty and no larger than {MAX_PLAN_PROMPT} bytes")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > MAX_TIMEOUT:
        raise ProjectError(f"timeout must be between 0 and {MAX_TIMEOUT} seconds")
    raw_project = Path(project).expanduser()
    if raw_project.is_symlink() or not raw_project.is_dir():
        raise ProjectError("agent project must be a real directory")
    project_path = raw_project.resolve()
    if not (project_path / ".open3d").is_dir():
        raise ProjectError("agent project is not an Open3D project")
    executable = which(agent)
    if executable is None:
        return {"status": "UNAVAILABLE", "agent": agent, "reason": "CLI_NOT_INSTALLED", "output": ""}
    instruction = ("Read-only Open3D asset planning request. Inspect the current contract, semantic parts, and QA state in this project. "
                   "Return a concise plan and, if useful, a proposed allowlisted edit. Do not edit files, run commands, or claim that a mutation happened.\n\n"
                   f"User request: {prompt.strip()}")
    started = time.time()
    completed = None
    try:
        completed = _run_agent_command(agent, executable, instruction, cwd=project_path, timeout=float(timeout), runner=runner)
        status = "PASS" if completed.returncode == 0 else "FAILED"
        reason = "PLAN_COMPLETE" if status == "PASS" else "CLI_FAILED"
    except subprocess.TimeoutExpired as exc:
        status, reason, completed = "FAILED", "CLI_TIMEOUT", exc
    except (OSError, subprocess.SubprocessError) as exc:
        status, reason, completed = "UNAVAILABLE", "CLI_UNAVAILABLE", exc
    stdout = getattr(completed, "stdout", b"") or b""
    stderr = getattr(completed, "stderr", b"") or b""
    output = _bounded(stdout or stderr)
    return {"status": status, "agent": agent, "reason": reason, "output": output, "version": None,
            "started_at": started, "ended_at": time.time(), "duration_seconds": round(time.time() - started, 6),
            "exit_status": getattr(completed, "returncode", None), "mutations": "NONE", "project_state_unchanged": True}


def _agent_build_instruction(prompt: str) -> str:
    return f"""You are the Open3D Blender asset builder. Work only in the current workspace.

Open3D will execute your build.py with Blender after you finish. The user request is:
{prompt.strip()}

Required files in the current workspace:
1. asset.json — a valid Open3D v0.1 asset contract. It must contain schema_version, asset_id, kind, units=m, positive dimensions, non-empty semantic parts, geometry.triangle_budget.max, and outputs.
2. build.py — a Blender Python script that parses the named arguments after Blender's `--`: `--contract <contract path> --output <output directory>`, creates or edits the requested model with bpy, and writes both `asset.glb` and `scene.blend` into the supplied output directory.

Build rules:
- Use only bpy, math, json, pathlib, and the Python standard library. Do not use network, subprocess, shell commands, or external downloads.
- Name every semantic mesh object exactly with its part_id and set object custom properties open3d_part_id and open3d_part_role.
- Set the scene custom properties open3d_asset_id and open3d_asset_digest from the contract.
- Export a real GLB with bpy.ops.export_scene.gltf(filepath=..., export_format='GLB', export_extras=True).
- Do not assume the contract path is the first positional argument; read the `--contract` and `--output` values exactly.
- Target the installed Blender 5.2 LTS: use `scene.render.engine = 'BLENDER_EEVEE'` (or a try/except fallback), not enum introspection through bpy.types.
- Keep the model inside the contract dimensions and triangle budget. For a new asset request, treat current_asset.json as context only: choose dimensions that bound the final model with a small margin instead of reusing unrelated dimensions. For an edit request, preserve existing dimensions unless the user asks to resize. Prefer separate editable semantic parts and production-quality bevels/materials when the prompt requests them.
- Do not claim success in text unless asset.json, build.py, asset.glb, and scene.blend are actually present.

The file current_asset.json contains the current asset contract. If previous_build.py exists, use it as the editable source for an edit request. Preserve existing semantic part IDs where possible and change only what the user asked for. You may replace the previous build with a better one, but write the two required files before finishing."""


def run_agent_build(agent: str, prompt: str, project: str | Path, *, timeout: float = 900,
                    runner: Callable[..., Any] = subprocess.run,
                    which: Callable[[str], str | None] = shutil.which,
                    worker: Any | None = None) -> dict[str, Any]:
    """Let an external agent author a Blender build, then execute and adopt it."""

    if agent not in AGENTS:
        raise ProjectError("agent must be codex, claude, or opencode")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_BUILD_PROMPT:
        raise ProjectError(f"prompt must be non-empty and no larger than {MAX_BUILD_PROMPT} bytes")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > MAX_BUILD_TIMEOUT:
        raise ProjectError(f"timeout must be between 0 and {MAX_BUILD_TIMEOUT} seconds")
    raw_project = Path(project).expanduser()
    if raw_project.is_symlink() or not raw_project.is_dir():
        raise ProjectError("agent project must be a real directory")
    project_path = raw_project.resolve()
    if not (project_path / ".open3d").is_dir():
        raise ProjectError("agent project is not an Open3D project")
    executable = which(agent)
    started = time.time()
    if executable is None:
        return {"status": "UNAVAILABLE", "agent": agent, "reason": "CLI_NOT_INSTALLED", "project_state_unchanged": True, "output": ""}

    agent_root = project_path / ".open3d" / "agent-runs"
    if agent_root.is_symlink():
        raise ProjectError("agent run directory must not be a symlink")
    agent_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="build-", dir=agent_root))
    workspace = run_dir / "workspace"
    output = run_dir / "output"
    workspace.mkdir()
    output.mkdir()
    project_obj = Project(project_path)
    current_ref = project_obj.current()
    (workspace / "current_asset.json").write_text(json.dumps(project_obj.load_current_asset(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    previous_workspace = current_ref.get("agent_build", {}).get("workspace") if isinstance(current_ref.get("agent_build"), dict) else None
    if isinstance(previous_workspace, str):
        previous_path = (project_path / previous_workspace).resolve()
        try:
            previous_path.relative_to(project_path)
        except ValueError:
            previous_path = None
        if previous_path and previous_path.is_dir() and not previous_path.is_symlink():
            for source_name, target_name in (("asset.json", "previous_asset.json"), ("build.py", "previous_build.py")):
                source = previous_path / source_name
                if source.is_file() and not source.is_symlink():
                    shutil.copy2(source, workspace / target_name)
    (workspace / "request.json").write_text(json.dumps({"schema_version": "0.1.0", "agent": agent, "prompt": prompt.strip()}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    instruction = _agent_build_instruction(prompt)
    completed = None
    try:
        completed = _run_agent_command(agent, executable, instruction, cwd=workspace, timeout=float(timeout), runner=runner, build=True)
        cli_status = "PASS" if completed.returncode == 0 else "FAILED"
        cli_reason = "BUILD_FILES_READY" if cli_status == "PASS" else "CLI_FAILED"
    except subprocess.TimeoutExpired as exc:
        cli_status, cli_reason, completed = "FAILED", "CLI_TIMEOUT", exc
    except (OSError, subprocess.SubprocessError) as exc:
        cli_status, cli_reason, completed = "UNAVAILABLE", "CLI_UNAVAILABLE", exc
    stdout = _bounded(getattr(completed, "stdout", b"") or b"")
    stderr = _bounded(getattr(completed, "stderr", b"") or b"")
    common = {
        "schema_version": "0.1.0", "agent": agent, "run": str(run_dir.relative_to(project_path)),
        "workspace": str(workspace.relative_to(project_path)), "prompt": prompt.strip(),
        "cli": {"status": cli_status, "reason": cli_reason, "executable": executable, "stdout": stdout, "stderr": stderr,
                "exit_status": getattr(completed, "returncode", None)},
        "started_at": started, "ended_at": time.time(), "mutations": "NONE", "project_state_unchanged": True,
    }
    required = (workspace / "asset.json", workspace / "build.py")
    if cli_status != "PASS" or any(not path.is_file() or path.is_symlink() for path in required):
        result = {**common, "status": "FAILED", "reason": cli_reason if cli_status != "PASS" else "BUILD_FILES_MISSING"}
        (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    if worker is None:
        from .workers import BlenderSandbox
        worker = BlenderSandbox(project_path)
    blender_result = worker.run_agent_build(workspace / "build.py", workspace / "asset.json", output, timeout=float(timeout))
    if blender_result.get("process", {}).get("status") != "PASS":
        result = {**common, "status": "FAILED", "reason": "BLENDER_BUILD_FAILED", "blender": blender_result}
        (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    try:
        asset = load_asset(workspace / "asset.json")
        glb_path, blend_path = output / "asset.glb", output / "scene.blend"
        if glb_path.stat().st_size > 512 * 1024 * 1024 or blend_path.stat().st_size > 1024 * 1024 * 1024:
            raise ProjectError("agent build artifact is too large")
        adopted = project_obj.replace_generated_asset(asset, glb_path.read_bytes(), blend=blend_path.read_bytes(), agent=agent, prompt=prompt.strip(), run_id=run_dir.name, workspace=str(workspace.relative_to(project_path)), auto_fit_dimensions=True)
    except (OSError, ValueError, ProjectError) as exc:
        result = {**common, "status": "FAILED", "reason": "OUTPUT_REJECTED", "error": str(exc), "blender": blender_result}
        (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result
    if adopted.get("status") != "PASS":
        result = {**common, "status": "FAILED", "reason": "QA_REJECTED", "report": adopted.get("report"), "blender": blender_result}
        (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result
    result = {**common, "status": "PASS", "reason": "BLENDER_BUILD_COMPLETE", "blender": blender_result,
              "mutation": adopted, "project_state_unchanged": False, "ended_at": time.time()}
    (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def run_production_agent(agent: str, run: str | Path, *, output_root: str | Path | None = None,
                         timeout: float = 30, runner: Callable[..., Any] = subprocess.run,
                         which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    if agent not in AGENTS:
        raise ProjectError("agent must be codex, claude, or opencode")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > MAX_TIMEOUT:
        raise ProjectError(f"timeout must be between 0 and {MAX_TIMEOUT} seconds")
    raw_run_path = Path(run).expanduser()
    raw_root = Path(output_root).expanduser() if output_root is not None else raw_run_path.parent
    if raw_run_path.is_symlink() or raw_root.is_symlink():
        raise ProjectError("production run and output root must be real directories")
    run_path, root = raw_run_path.resolve(), raw_root.resolve()
    if not run_path.is_dir() or not root.is_dir():
        raise ProjectError("production run and output root must be real directories")
    try:
        run_path.relative_to(root)
    except ValueError as exc:
        raise ProjectError("production run must stay inside the output root") from exc
    receipt_path = run_path / "run_receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ProjectError("completed production receipt is missing")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError("completed production receipt is invalid") from exc
    if not isinstance(receipt, dict) or receipt.get("status") != "PASS":
        raise ProjectError("production receipt is not completed")
    receipt_digest = digest_json(receipt)
    executable = which(agent)
    started = time.time()
    prompt = ("Read-only evidence review. Inspect only this completed Open3D production run directory: "
              f"{run_path}. Read run_receipt.json and report a structured agent receipt linked to "
              f"production_receipt_digest={receipt_digest}. Do not edit files, run commands, or claim "
              "QA, promotion, approval, signing, provider, Unity, or release success.\n")
    if agent == "codex":
        argv = ["codex", "exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check",
                "--ignore-user-config", "-"]
    elif agent == "claude":
        argv = ["claude", "-p", "--bare", "--no-session-persistence", "--permission-mode", "plan",
                "--disallowed-tools", "Edit,Write,NotebookEdit,Bash", "--output-format", "json"]
    else:
        argv = ["opencode", "run", "--dir", str(run_path), "--format", "default", "--auto"]
    command = [executable, *argv[1:]] if executable else [agent, *argv[1:]]
    status, reason, completed = "UNAVAILABLE", "CLI_NOT_INSTALLED", None
    version = None
    try:
        if executable is None:
            raise FileNotFoundError(agent)
        version_result = runner([executable, "--version"], cwd=str(run_path), input=b"",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                                env={"PATH": os.path.dirname(executable), "LANG": "C", "LC_ALL": "C"}, check=False)
        version = _bounded(getattr(version_result, "stdout", b"") or getattr(version_result, "stderr", b"") or b"").strip()
        if agent == "opencode":
            completed = runner(command + [prompt], cwd=str(run_path), input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=float(timeout), env=os.environ.copy(), check=False)
        else:
            completed = _run_command(command, prompt=prompt, cwd=run_path, timeout=float(timeout), runner=runner)
        status = "FAILED" if completed.returncode != 0 else "UNAVAILABLE"
        reason = "CLI_FAILED" if completed.returncode != 0 else "STRUCTURED_RECEIPT_MISSING"
    except subprocess.TimeoutExpired as exc:
        status, reason = "FAILED", "CLI_TIMEOUT"
        completed = exc
    except (OSError, subprocess.SubprocessError) as exc:
        status, reason = "UNAVAILABLE", "CLI_UNAVAILABLE"
        completed = exc
    stdout = _bounded(getattr(completed, "stdout", b"") or b"")
    stderr = _bounded(getattr(completed, "stderr", b"") or b"")
    structured = _receipt_from_output(stdout)
    if status == "UNAVAILABLE" and structured is not None:
        status, reason = "PASS", "STRUCTURED_RECEIPT"
    if structured is not None and _reported_digest(structured) not in (None, receipt_digest):
        status, reason = "FAILED", "RECEIPT_DIGEST_MISMATCH"
    finished = time.time()
    result = {
        "schema_version": "0.1.0", "status": status, "agent": agent,
        "reason": reason, "production_receipt_digest": receipt_digest,
        "run": str(run_path), "argv": command[1:], "executable": executable,
        "version": version, "started_at": started, "ended_at": finished,
        "duration_seconds": round(finished - started, 6),
        "exit_status": getattr(completed, "returncode", None),
        "stdout": stdout, "stderr": stderr, "agent_receipt": structured,
        "mutations": "NONE", "production_state_unchanged": True,
    }
    (run_path / "agent_process_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


production_agent_receipt = run_production_agent
