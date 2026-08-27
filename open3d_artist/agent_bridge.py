"""Evidence-only bridge to installed Codex and Claude Code CLIs."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .contracts import digest_json, load_asset
from .project import Project, ProjectError

MAX_OUTPUT = 16 * 1024
MAX_TIMEOUT = 60.0
MAX_PLAN_PROMPT = 8 * 1024
MAX_BUILD_TIMEOUT = 900.0
MAX_BUILD_PROMPT = 16 * 1024
# Generated All2API references can be larger than browser uploads; the HTTP
# request body remains bounded separately by the local server.
MAX_REFERENCE_IMAGE_BYTES = 4 * 1024 * 1024
MAX_REFERENCED_ASSETS = 16
AGENTS = ("codex", "claude", "opencode")
POOL_URL_ENV = "OPEN3D_AGENT_POOL_URL"
POOL_TOKEN_ENV = "OPEN3D_AGENT_POOL_TOKEN"
POOL_MODEL_ENV = "OPEN3D_AGENT_POOL_MODEL"
OPENCODE_MODEL_ENV = "OPEN3D_OPENCODE_MODEL"


def _agent_label(agent: str) -> str:
    return {"codex": "Codex", "claude": "Claude Code", "opencode": "OpenCode"}.get(agent, agent)


def _bounded(value: bytes | str) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    return text[:MAX_OUTPUT] + ("...[truncated]" if len(text) > MAX_OUTPUT else "")


def _pool_config() -> dict[str, str]:
    return {
        "url": os.environ.get(POOL_URL_ENV, "").strip().rstrip("/"),
        "token": os.environ.get(POOL_TOKEN_ENV, "").strip(),
        "model": os.environ.get(POOL_MODEL_ENV, "auto").strip() or "auto",
    }


def _opencode_model() -> str:
    return os.environ.get(OPENCODE_MODEL_ENV, "").strip()


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _pool_v1_url(url: str) -> str:
    return url if url.endswith("/v1") else f"{url}/v1"


def agent_pool_status(*, opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """Report the optional shared OpenAI-compatible LLM pool without exposing its token."""

    config = _pool_config()
    if not config["url"] and not config["token"]:
        return {"mode": "DIRECT_CLI", "status": "NOT_CONFIGURED", "reason": "DIRECT_CLI_AUTH"}
    if not config["url"]:
        return {"mode": "SHARED_POOL", "status": "CONFIG_ERROR", "reason": "POOL_URL_REQUIRED"}
    if not config["token"]:
        return {"mode": "SHARED_POOL", "status": "AUTH_REQUIRED", "reason": "POOL_TOKEN_REQUIRED", "url": _safe_url(config["url"])}
    request = urllib.request.Request(
        f"{_pool_v1_url(config['url'])}/models",
        headers={"Authorization": f"Bearer {config['token']}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=2) as response:
            status_code = int(getattr(response, "status", 200))
        if status_code >= 400:
            reason = "POOL_AUTH_REQUIRED" if status_code in (401, 403) else "POOL_HTTP_ERROR"
            return {"mode": "SHARED_POOL", "status": "AUTH_REQUIRED" if status_code in (401, 403) else "UNAVAILABLE", "reason": reason, "http_status": status_code, "url": _safe_url(config["url"]), "model": config["model"]}
    except urllib.error.HTTPError as exc:
        reason = "POOL_AUTH_REQUIRED" if exc.code in (401, 403) else "POOL_HTTP_ERROR"
        return {"mode": "SHARED_POOL", "status": "AUTH_REQUIRED" if exc.code in (401, 403) else "UNAVAILABLE", "reason": reason, "http_status": exc.code, "url": _safe_url(config["url"]), "model": config["model"]}
    except (OSError, urllib.error.URLError, TimeoutError):
        return {"mode": "SHARED_POOL", "status": "UNAVAILABLE", "reason": "POOL_UNREACHABLE", "url": _safe_url(config["url"]), "model": config["model"]}
    return {"mode": "SHARED_POOL", "status": "ACTIVE", "reason": "POOL_AUTHENTICATED", "url": _safe_url(config["url"]), "model": config["model"]}


def _agent_environment(agent: str, executable: str, *, build: bool) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = os.path.dirname(executable) + os.pathsep + environment.get("PATH", "")
    environment["LANG"] = "C.UTF-8" if build else "C"
    environment["LC_ALL"] = environment["LANG"]
    config = _pool_config()
    if config["url"]:
        # 9router's Codex integration uses the gateway root; Anthropic/OpenCode use /v1.
        environment["OPENAI_BASE_URL"] = config["url"]
        environment["OPENAI_API_KEY"] = config["token"]
        environment["ANTHROPIC_BASE_URL"] = _pool_v1_url(config["url"])
        environment["ANTHROPIC_API_KEY"] = config["token"]
        environment["ANTHROPIC_AUTH_TOKEN"] = config["token"]
        if agent == "opencode":
            environment["OPENCODE_CONFIG_CONTENT"] = json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "model": f"open3d-pool/{config['model']}",
                "provider": {
                    "open3d-pool": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "Open3D shared LLM pool",
                        "options": {
                            "baseURL": _pool_v1_url(config["url"]),
                            "apiKey": "{env:OPEN3D_AGENT_POOL_TOKEN}",
                        },
                        "models": {config["model"]: {"name": config["model"]}},
                    }
                },
            })
    return environment


def _auth_probe(agent: str, executable: str, *, runner: Callable[..., Any]) -> dict[str, str]:
    command = {
        "codex": [executable, "login", "status"],
        "claude": [executable, "auth", "status", "--json"],
        "opencode": [executable, "auth", "list"],
    }[agent]
    try:
        result = runner(command, cwd=os.getcwd(), input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, env=_agent_environment(agent, executable, build=False), check=False)
    except (OSError, subprocess.SubprocessError):
        return {"status": "AUTH_REQUIRED", "reason": "AUTH_CHECK_FAILED"}
    output = _bounded((getattr(result, "stdout", b"") or getattr(result, "stderr", b"")) or b"").strip()
    if getattr(result, "returncode", 1) != 0:
        return {"status": "AUTH_REQUIRED", "reason": "AUTH_CHECK_FAILED"}
    lowered = output.lower()
    authenticated = False
    if agent == "codex":
        authenticated = "logged in" in lowered or "authenticated" in lowered
    elif agent == "claude":
        try:
            authenticated = bool(json.loads(output).get("loggedIn"))
        except (json.JSONDecodeError, AttributeError):
            authenticated = "loggedin" in lowered and "true" in lowered
    else:
        authenticated = "credentials" in lowered and "0 credentials" not in lowered
    return {"status": "ACTIVE" if authenticated else "AUTH_REQUIRED", "reason": "AUTHENTICATED" if authenticated else "AUTH_REQUIRED"}


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


def _run_command(command: list[str], *, prompt: str, cwd: Path, timeout: float, runner: Callable[..., Any], environment: dict[str, str] | None = None) -> Any:
    environment = environment or {"PATH": os.path.dirname(command[0]), "LANG": "C", "LC_ALL": "C"}
    return runner(command, cwd=str(cwd), input=prompt.encode("utf-8"), stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, timeout=timeout, env=environment, check=False)


def _agent_command(agent: str, executable: str, *, build: bool = False, cwd: Path | None = None) -> list[str]:
    if agent == "codex":
        command = [executable, "exec", "--sandbox", "workspace-write" if build else "read-only", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config"]
        if build and cwd is not None:
            command.extend(["--cd", str(cwd)])
        return command
    if agent == "claude":
        command = [executable, "-p", "--no-session-persistence", "--permission-mode", "acceptEdits" if build else "plan"]
        if build:
            command.extend(["--allowed-tools", "Read,Edit,Write", "--disallowed-tools", "Bash,WebFetch,WebSearch"])
        else:
            command.extend(["--disallowed-tools", "Edit,Write,NotebookEdit,Bash"])
        return [*command, "--output-format", "text"]
    return [executable, "run", "--format", "default", "--auto"]


def _run_agent_command(agent: str, executable: str, prompt: str, *, cwd: Path, timeout: float,
                       runner: Callable[..., Any], build: bool = False) -> Any:
    if agent == "opencode":
        command = [executable, "run", "--dir", str(cwd), "--format", "default", "--auto"]
        pool = _pool_config()
        if pool["url"]:
            command.extend(["--model", f"open3d-pool/{pool['model']}"])
        elif _opencode_model():
            command.extend(["--model", _opencode_model()])
        command.append(prompt)
        input_value = b""
    else:
        command = _agent_command(agent, executable, build=build, cwd=cwd)
        pool = _pool_config()
        if pool["url"] and agent in ("codex", "claude"):
            command.extend(["--model", pool["model"]])
        if agent == "codex":
            command.append("-")
        elif agent == "claude" and build:
            command.extend(["--add-dir", str(cwd)])
        input_value = prompt.encode("utf-8")
    environment = _agent_environment(agent, executable, build=build)
    return runner(command, cwd=str(cwd), input=input_value, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  timeout=timeout, env=environment, check=False)


def agent_catalog(*, runner: Callable[..., Any] = subprocess.run,
                  which: Callable[[str], str | None] = shutil.which) -> list[dict[str, Any]]:
    pool = agent_pool_status()
    result = []
    for agent in AGENTS:
        executable = which(agent)
        if executable is None:
            result.append({"agent_id": agent, "label": _agent_label(agent), "status": "UNAVAILABLE", "reason": "CLI_NOT_INSTALLED", "version": None})
            continue
        try:
            value = runner([executable, "--version"], cwd=os.getcwd(), input=b"", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=10, env={"PATH": os.path.dirname(executable), "LANG": "C", "LC_ALL": "C"}, check=False)
            output = _bounded((getattr(value, "stdout", b"") or getattr(value, "stderr", b"")) or b"").strip()
            status = "CLI_READY" if getattr(value, "returncode", 1) == 0 else "UNAVAILABLE"
            reason = "CLI_AVAILABLE" if status == "CLI_READY" else "CLI_VERSION_FAILED"
        except (OSError, subprocess.SubprocessError):
            output, status, reason = "", "UNAVAILABLE", "CLI_UNAVAILABLE"
        item = {"agent_id": agent, "label": _agent_label(agent), "status": status, "reason": reason, "version": output or None}
        if status == "CLI_READY":
            auth = ({"status": pool["status"], "reason": pool["reason"]}
                    if pool["mode"] == "SHARED_POOL"
                    else _auth_probe(agent, executable, runner=runner))
            if auth["status"] == "ACTIVE":
                item.update(status="ACTIVE", reason=auth["reason"], execution="READY")
            elif pool["mode"] == "SHARED_POOL":
                item.update(status="AUTH_REQUIRED", reason=auth["reason"], execution="BLOCKED")
            else:
                item.update(status=auth["status"], reason=auth["reason"], execution="BLOCKED")
        result.append(item)
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
    pool = agent_pool_status()
    if pool["mode"] == "SHARED_POOL" and pool["status"] != "ACTIVE":
        return {"status": "UNAVAILABLE", "agent": agent, "reason": pool["reason"], "pool": pool, "output": ""}
    instruction = ("Read-only Open3D asset planning request. Inspect the current contract, semantic parts, and QA state in this project. "
                   "Return a concise plan and, if useful, a proposed allowlisted edit. Do not edit files, run commands, or claim that a mutation happened.\n\n"
                   f"User request: {prompt.strip()}")
    started = time.time()
    completed = None
    try:
        completed = _run_agent_command(agent, executable, instruction, cwd=project_path, timeout=float(timeout), runner=runner)
        status = "PASS" if completed.returncode == 0 else "FAILED"
        reason = "PLAN_COMPLETE" if status == "PASS" else _cli_failure_reason(completed)
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


def _stage_reference_image(reference_image: Any, workspace: Path) -> dict[str, Any] | None:
    if reference_image is None:
        return None
    if not isinstance(reference_image, dict):
        raise ProjectError("reference_image must be an object")
    mime_type = str(reference_image.get("mime_type", "")).lower()
    mime_aliases = {"image/jpg": "image/jpeg"}
    mime_type = mime_aliases.get(mime_type, mime_type)
    extensions = {"image/png": ("png", b"\x89PNG\r\n\x1a\n"), "image/jpeg": ("jpg", b"\xff\xd8"), "image/webp": ("webp", b"RIFF")}
    if mime_type not in extensions:
        raise ProjectError("reference_image must be PNG, JPEG, or WebP")
    data_url = reference_image.get("data")
    prefix = f"data:{mime_type};base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ProjectError("reference_image data must be a base64 data URL")
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ProjectError("reference_image data is not valid base64") from exc
    extension, magic = extensions[mime_type]
    if not raw or len(raw) > MAX_REFERENCE_IMAGE_BYTES or not raw.startswith(magic):
        raise ProjectError("reference_image is empty, too large, or has the wrong file signature")
    if mime_type == "image/webp" and b"WEBP" not in raw[:16]:
        raise ProjectError("reference_image is not a valid WebP file")
    path = workspace / f"reference-image.{extension}"
    path.write_bytes(raw)
    return {"name": str(reference_image.get("name") or path.name)[:128], "mime_type": mime_type,
            "bytes": len(raw), "path": str(path.name)}


def _agent_build_instruction(prompt: str, reference_path: str | None = None, referenced_assets_path: str | None = None) -> str:
    reference_note = (f"\nA user reference image is staged at `{reference_path}`. Inspect it with the available agent tools and use it as visual guidance; do not copy hidden metadata or claim image-to-mesh reconstruction.\n"
                      if reference_path else "")
    assets_note = (f"\nReferenced workspace asset contracts are staged at `{referenced_assets_path}`. Use them as context for @asset mentions. The first mentioned asset is the build target; keep other referenced assets unchanged unless explicitly requested.\n"
                   if referenced_assets_path else "")
    return f"""You are the Open3D Blender asset builder. Work only in the current workspace.

Open3D will execute your build.py with Blender after you finish. The user request is:
{prompt.strip()}
{reference_note}{assets_note}

Required files in the current workspace:
1. asset.json — a valid Open3D v0.1 asset contract. Use the exact schema_version string `0.1.0`, a supported kind (`prop`, `environment`, `character`, `material`, or `scene`), `dimensions.width/depth/height`, a `parts` array (not `semantic_parts`), `geometry.triangle_budget.max`, `outputs`, and this production gate in metadata:
   metadata.quality_gate = {{"profile":"production", "minimum_materials":6, "minimum_primitives_per_part":2, "required_detail_tags":["primary_form","surface_breakup","edge_treatment","material_breakup"], "part_detail_tags":{{<every part_id>: [all four required tags]}}}}.
2. build.py — a Blender Python script that parses the named arguments after Blender's `--`: `--contract <contract path> --output <output directory>`, creates or edits the requested model with bpy, and writes both `asset.glb` and `scene.blend` into the supplied output directory.

Build rules:
- Use only bpy, math, json, pathlib, and the Python standard library. Do not use network, subprocess, shell commands, or external downloads.
- Name every semantic mesh object exactly with its part_id and set object custom properties open3d_part_id and open3d_part_role.
- Set every semantic mesh object's `open3d_detail_tags` custom property to the four required tags from the quality gate. The tags must describe actual modeled geometry, not text-only claims.
- Set the scene custom properties open3d_asset_id and open3d_asset_digest from the contract.
- Export a real GLB with bpy.ops.export_scene.gltf(filepath=..., export_format='GLB', export_extras=True).
- Do not assume the contract path is the first positional argument; read the `--contract` and `--output` values exactly.
- Target the installed Blender 5.2 LTS: use `scene.render.engine = 'BLENDER_EEVEE'` (or a try/except fallback), not enum introspection through bpy.types.
- Keep the model inside the contract dimensions and triangle budget. For a new asset request, treat current_asset.json as context only: choose dimensions that bound the final model with a small margin instead of reusing unrelated dimensions. For an edit request, preserve existing dimensions unless the user asks to resize. Prefer separate editable semantic parts and production-quality bevels/materials when the prompt requests them.
- Production-detail bar: model the reference's recognizable silhouette and major secondary forms. For architectural props, this normally means a clean roof with two planes/ridge/eaves (no dangling or floating roof bars), wall/cladding and trim, door slab/frame/hardware, window glass/frames/mullions, chimney masonry/cap/flue, foundation/plinth/stone breakup, and porch/treads/rails when present. Use material separation and restrained bevels to make these details readable at game-view distance.
- Before finishing, inspect the generated scene from a three-quarter view and remove accidental intersections, detached geometry, oversized rods, duplicate subjects, hidden placeholder blocks, and details that extend beyond the intended silhouette. Do not call a generic box with a few strips production quality.
- Do not claim success in text unless asset.json, build.py, asset.glb, and scene.blend are actually present.

The file current_asset.json contains the current asset contract. If previous_build.py exists, use it as the editable source for an edit request. Preserve existing semantic part IDs where possible and change only what the user asked for. You may replace the previous build with a better one, but write the two required files before finishing."""


def _cli_failure_reason(completed: Any) -> str:
    output = _bounded(getattr(completed, "stdout", b"") or b"") + "\n" + _bounded(getattr(completed, "stderr", b"") or b"")
    lowered = output.lower()
    if any(marker in lowered for marker in ("not logged in", "authentication", "unauthorized", "api key", "login required", '"loggedin": false')):
        return "AUTH_REQUIRED"
    return "CLI_FAILED"


def run_agent_build(agent: str, prompt: str, project: str | Path, *, timeout: float = 900,
                    runner: Callable[..., Any] = subprocess.run,
                    which: Callable[[str], str | None] = shutil.which,
                    worker: Any | None = None,
                    reference_image: dict[str, Any] | None = None,
                    target_asset_id: str | None = None,
                    referenced_asset_ids: list[str] | None = None,
                    create_asset: bool = False,
                    quality_profile: str | None = None) -> dict[str, Any]:
    """Let an external agent author a Blender build, then execute and adopt it."""

    if agent not in AGENTS:
        raise ProjectError("agent must be codex, claude, or opencode")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_BUILD_PROMPT:
        raise ProjectError(f"prompt must be non-empty and no larger than {MAX_BUILD_PROMPT} bytes")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > MAX_BUILD_TIMEOUT:
        raise ProjectError(f"timeout must be between 0 and {MAX_BUILD_TIMEOUT} seconds")
    if not isinstance(create_asset, bool):
        raise ProjectError("create_asset must be a boolean")
    if quality_profile not in {None, "production"}:
        raise ProjectError("quality_profile must be production or null")
    if referenced_asset_ids is not None and (not isinstance(referenced_asset_ids, list) or len(referenced_asset_ids) > MAX_REFERENCED_ASSETS):
        raise ProjectError(f"referenced_asset_ids must be a list of at most {MAX_REFERENCED_ASSETS} assets")
    requested_reference_ids = []
    for asset_id in referenced_asset_ids or []:
        if not isinstance(asset_id, str) or not asset_id.strip() or len(asset_id) > 64:
            raise ProjectError("referenced_asset_ids must contain non-empty asset IDs")
        if asset_id.casefold() not in {item.casefold() for item in requested_reference_ids}:
            requested_reference_ids.append(asset_id)
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
    pool = agent_pool_status()
    if pool["mode"] == "SHARED_POOL" and pool["status"] != "ACTIVE":
        return {"status": "UNAVAILABLE", "agent": agent, "reason": pool["reason"], "pool": pool, "project_state_unchanged": True, "output": ""}

    agent_root = project_path / ".open3d" / "agent-runs"
    if agent_root.is_symlink():
        raise ProjectError("agent run directory must not be a symlink")
    agent_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="build-", dir=agent_root))
    workspace = run_dir / "workspace"
    output = run_dir / "output"
    workspace.mkdir()
    output.mkdir()
    staged_reference = _stage_reference_image(reference_image, workspace)
    project_obj = Project(project_path)
    current_ref = project_obj.current()
    target_ref = current_ref
    target_asset = project_obj.load_current_asset()
    if target_asset_id and target_asset_id != current_ref.get("asset_id"):
        catalog_asset = project_obj.workspace_asset(target_asset_id)
        target_ref = {**current_ref, **{key: catalog_asset[key] for key in ("asset_id", "contract_artifact", "glb_artifact", "qa_artifact", "qa_status", "geometry_source", "agent_build") if key in catalog_asset}}
        target_asset = project_obj.store.read_json(catalog_asset["contract_artifact"])
    (workspace / "current_asset.json").write_text(json.dumps(target_asset, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    previous_workspace = target_ref.get("agent_build", {}).get("workspace") if isinstance(target_ref.get("agent_build"), dict) else None
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
    referenced_assets = []
    for asset_id in requested_reference_ids:
        catalog_asset = project_obj.workspace_asset(asset_id)
        referenced_assets.append({"asset_id": catalog_asset["asset_id"], "name": catalog_asset.get("name"), "kind": catalog_asset.get("kind"), "contract": catalog_asset["contract"]})
    if referenced_assets:
        (workspace / "referenced_assets.json").write_text(json.dumps(referenced_assets, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (workspace / "request.json").write_text(json.dumps({"schema_version": "0.1.0", "agent": agent, "prompt": prompt.strip(), "reference_image": staged_reference, "target_asset_id": None if create_asset else target_asset_id or current_ref.get("asset_id"), "referenced_asset_ids": [asset["asset_id"] for asset in referenced_assets], "create_asset": create_asset}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    instruction = _agent_build_instruction(prompt, staged_reference["path"] if staged_reference else None, "referenced_assets.json" if referenced_assets else None)
    completed = None
    try:
        completed = _run_agent_command(agent, executable, instruction, cwd=workspace, timeout=float(timeout), runner=runner, build=True)
        cli_status = "PASS" if completed.returncode == 0 else "FAILED"
        cli_reason = "BUILD_FILES_READY" if cli_status == "PASS" else _cli_failure_reason(completed)
    except subprocess.TimeoutExpired as exc:
        cli_status, cli_reason, completed = "FAILED", "CLI_TIMEOUT", exc
    except (OSError, subprocess.SubprocessError) as exc:
        cli_status, cli_reason, completed = "UNAVAILABLE", "CLI_UNAVAILABLE", exc
    stdout = _bounded(getattr(completed, "stdout", b"") or b"")
    stderr = _bounded(getattr(completed, "stderr", b"") or b"")
    common = {
        "schema_version": "0.1.0", "agent": agent, "run": str(run_dir.relative_to(project_path)),
        "workspace": str(workspace.relative_to(project_path)), "prompt": prompt.strip(),
        "reference_image": staged_reference,
        "create_asset": create_asset,
        "quality_profile": quality_profile,
        "pool": pool,
        "cli": {"status": cli_status, "reason": cli_reason, "executable": executable, "stdout": stdout, "stderr": stderr,
                "exit_status": getattr(completed, "returncode", None)},
        "started_at": started, "ended_at": time.time(), "mutations": "NONE", "project_state_unchanged": True,
    }
    required = (workspace / "asset.json", workspace / "build.py")
    if cli_status != "PASS" or any(not path.is_file() or path.is_symlink() for path in required):
        result = {**common, "status": "FAILED", "reason": cli_reason if cli_status != "PASS" else "BUILD_FILES_MISSING"}
        (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    try:
        staged_asset = load_asset(workspace / "asset.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {**common, "status": "FAILED", "reason": "CONTRACT_REJECTED", "error": str(exc)}
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
        asset = staged_asset
        if not create_asset and target_asset_id and asset["asset_id"] != target_asset_id:
            result = {**common, "status": "FAILED", "reason": "TARGET_ASSET_MISMATCH", "error": f"Agent returned {asset['asset_id']} but the edit target is {target_asset_id}", "blender": blender_result}
            (run_dir / "agent_build_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return result
        glb_path, blend_path = output / "asset.glb", output / "scene.blend"
        if glb_path.stat().st_size > 512 * 1024 * 1024 or blend_path.stat().st_size > 1024 * 1024 * 1024:
            raise ProjectError("agent build artifact is too large")
        adopted = project_obj.replace_generated_asset(asset, glb_path.read_bytes(), blend=blend_path.read_bytes(), agent=agent, prompt=prompt.strip(), run_id=run_dir.name, workspace=str(workspace.relative_to(project_path)), auto_fit_dimensions=True, quality_profile=quality_profile)
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
        argv = ["claude", "-p", "--no-session-persistence", "--permission-mode", "plan",
                "--disallowed-tools", "Edit,Write,NotebookEdit,Bash", "--output-format", "json"]
    else:
        argv = ["opencode", "run", "--dir", str(run_path), "--format", "default", "--auto"]
    command = [executable, *argv[1:]] if executable else [agent, *argv[1:]]
    if agent == "opencode" and not _pool_config()["url"] and _opencode_model():
        command.extend(["--model", _opencode_model()])
    status, reason, completed = "UNAVAILABLE", "CLI_NOT_INSTALLED", None
    version = None
    try:
        if executable is None:
            raise FileNotFoundError(agent)
        pool = agent_pool_status()
        if pool["mode"] == "SHARED_POOL" and pool["status"] != "ACTIVE":
            result = {"schema_version": "0.1.0", "status": "UNAVAILABLE", "agent": agent, "reason": pool["reason"],
                      "production_receipt_digest": receipt_digest, "run": str(run_path), "pool": pool,
                      "mutations": "NONE", "production_state_unchanged": True}
            (run_path / "agent_process_receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return result
        version_result = runner([executable, "--version"], cwd=str(run_path), input=b"",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                                env={"PATH": os.path.dirname(executable), "LANG": "C", "LC_ALL": "C"}, check=False)
        version = _bounded(getattr(version_result, "stdout", b"") or getattr(version_result, "stderr", b"") or b"").strip()
        if agent == "opencode":
            completed = runner(command + [prompt], cwd=str(run_path), input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=float(timeout), env=_agent_environment(agent, executable, build=False), check=False)
        else:
            completed = _run_command(command, prompt=prompt, cwd=run_path, timeout=float(timeout), runner=runner,
                                     environment=_agent_environment(agent, executable, build=False))
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
