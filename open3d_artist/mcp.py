"""Small, typed stdio MCP surface for the local project.

This exposes typed project operations. Agent builds are staged, validated, and
run through the bounded Blender worker; there is no raw shell tool.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .agent_bridge import AGENTS, run_agent_build
from .project import Project, ProjectError
from .production import CATALOG, REPAIR_ID, catalog, promote_production, production_agent_receipt, production_state, repair_production, run_production, verify_release


PROTOCOL_VERSION = "2026-07-28"


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}


def _tools() -> list[dict[str, Any]]:
    recipe_ids = [entry["recipe_id"] for entry in catalog()] if CATALOG.is_file() else []
    return [
        _tool("asset.inspect", "Inspect the current asset contract and artifact refs.", {}, []),
        _tool("asset.validate", "Run deterministic QA against the current GLB.", {}, []),
        _tool("asset.edit_part", "Scale one semantic part and keep the change checkpointed.", {"part_id": {"type": "string"}, "scale_x": {"type": "number", "exclusiveMinimum": 0}, "scale_y": {"type": "number", "exclusiveMinimum": 0}, "scale_z": {"type": "number", "exclusiveMinimum": 0}, "idempotency_key": {"type": "string"}}, ["part_id"]),
        _tool("checkpoint.rollback", "Restore an exact prior checkpoint.", {"checkpoint_id": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}}, ["checkpoint_id"]),
        _tool("production.run", "Run a checked-in local production brief.", {"brief": {"type": "object", "additionalProperties": False, "properties": {"schema_version": {"type": "string", "const": "0.1.0"}, "brief_id": {"type": "string"}, "prompt": {"type": "string"}, "reference": {"type": "object"}, "recipe_id": {"type": "string", "enum": recipe_ids}, "views": {"type": "array", "items": {"type": "string"}}}, "required": ["brief_id", "prompt", "reference", "recipe_id", "views"]}, "output": {"type": "string"}}, ["brief", "output"]),
        _tool("production.promote", "Promote a verified run into this project with immutable artifacts and a checkpoint.", {"run": {"type": "string"}}, ["run"]),
        _tool("production.repair", "Run the one fixed geometry-changing local repair.", {"run": {"type": "string"}, "repair_id": {"type": "string", "enum": [REPAIR_ID]}}, ["run", "repair_id"]),
        _tool("production.release_verify", "Verify promoted production artifacts and release proof.", {}, []),
        _tool("production.agent_receipt", "Run a fixed read-only agent review and record evidence.", {"agent": {"type": "string", "enum": list(AGENTS)}, "run": {"type": "string"}, "output_root": {"type": "string"}}, ["agent", "run"]),
        _tool("agent.build", "Let Codex, Claude Code, or OpenCode author asset.json/build.py, then run the build in the Blender sandbox and adopt a passing GLB.", {"agent": {"type": "string", "enum": list(AGENTS)}, "prompt": {"type": "string", "maxLength": 16384}, "timeout": {"type": "number", "exclusiveMinimum": 0}}, ["agent", "prompt"]),
    ]


def _result(value: Any, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)}], "isError": error}


def _call(project: Project, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "asset.inspect":
        return project.inspect()
    if name == "asset.validate":
        return project.validate()
    if name == "asset.edit_part":
        scales = {axis: args[key] for axis, key in (("x", "scale_x"), ("y", "scale_y"), ("z", "scale_z")) if key in args}
        return project.edit_part(args["part_id"], scales, idempotency_key=args.get("idempotency_key"))
    if name == "checkpoint.rollback":
        return project.rollback(args["checkpoint_id"])
    if name == "production.run":
        return run_production(args["brief"], args["output"])
    if name == "production.promote":
        return promote_production(args["run"], project.root)
    if name == "production.repair":
        return repair_production(args["run"], args["repair_id"])
    if name == "production.release_verify":
        return {"state": production_state(project), "verification": verify_release(project)}
    if name == "production.agent_receipt":
        return production_agent_receipt(args["agent"], args["run"], output_root=args.get("output_root"))
    if name == "agent.build":
        return run_agent_build(args["agent"], args["prompt"], project.root, timeout=args.get("timeout", 900))
    raise ProjectError(f"unknown tool: {name}")


def _resource(project: Project, uri: str) -> Any:
    project_id = project.current()["project_id"]
    prefix = f"open3d://projects/{project_id}/"
    if uri == prefix + "asset":
        return project.inspect()
    if uri == prefix + "qa/latest":
        return project.store.read_json(project.current()["qa_artifact"])
    if uri == prefix + "history":
        if not project.operations.is_file():
            return []
        return [json.loads(line) for line in project.operations.read_text(encoding="utf-8").splitlines() if line]
    raise ProjectError("resource URI is not available")


def handle(project: Project, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    if method and method.startswith("notifications/"):
        return None
    request_id = request.get("id")
    try:
        if method == "initialize":
            value = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}}, "serverInfo": {"name": "open3d-artist", "version": "0.1.0a1"}}
        elif method == "ping":
            value = {}
        elif method == "tools/list":
            value = {"tools": _tools()}
        elif method == "tools/call":
            params = request.get("params", {})
            value = _call(project, params["name"], params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": request_id, "result": _result(value)}
        elif method == "resources/list":
            project_id = project.current()["project_id"]
            value = {"resources": [{"uri": f"open3d://projects/{project_id}/{name}", "name": name, "mimeType": "application/json"} for name in ("asset", "qa/latest", "history")]}
        elif method == "resources/read":
            value = {"contents": [{"uri": request["params"]["uri"], "mimeType": "application/json", "text": json.dumps(_resource(project, request["params"]["uri"]), ensure_ascii=False, sort_keys=True, indent=2)}]}
        else:
            raise ProjectError(f"unsupported MCP method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": value}
    except (KeyError, ProjectError, ValueError, TypeError) as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}


def serve_stdio(project: Project) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle(project, request)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
