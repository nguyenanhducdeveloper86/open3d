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

from .contracts import digest_json
from .project import ProjectError

MAX_OUTPUT = 16 * 1024
MAX_TIMEOUT = 60.0
AGENTS = ("codex", "claude")


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


def run_production_agent(agent: str, run: str | Path, *, output_root: str | Path | None = None,
                         timeout: float = 30, runner: Callable[..., Any] = subprocess.run,
                         which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    if agent not in AGENTS:
        raise ProjectError("agent must be codex or claude")
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
    else:
        argv = ["claude", "-p", "--bare", "--no-session-persistence", "--permission-mode", "plan",
                "--disallowed-tools", "Edit,Write,NotebookEdit,Bash", "--output-format", "json"]
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
