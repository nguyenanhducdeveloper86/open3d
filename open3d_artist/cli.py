"""Command-line entry point for the local-first Open3D pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent_bridge import run_agent_build
from .mcp import serve_stdio
from .providers import MeshyImageTo3D, MeshyPipeline, ProviderError, provider_catalog
from .production import promote_production, production_agent_receipt, repair_production, run_production, verify_release
from .project import Project, ProjectError
from .server import serve
from .unity import UnityValidator
from .workers import BlenderSandbox, WorkerError, WorkerUnavailable


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open3d", description="Open3D Artist local asset pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a project from an asset contract")
    init.add_argument("project", type=Path)
    init.add_argument("--asset", default="asset.yaml", type=Path)

    for name, help_text in (("inspect", "inspect the current project"), ("validate", "run deterministic QA")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("project", type=Path)

    edit = commands.add_parser("edit-part", help="scale one semantic part")
    edit.add_argument("project", type=Path)
    edit.add_argument("part_id")
    edit.add_argument("--scale-x", type=float)
    edit.add_argument("--scale-y", type=float)
    edit.add_argument("--scale-z", type=float)
    edit.add_argument("--idempotency-key")

    rollback = commands.add_parser("rollback", help="restore an exact checkpoint")
    rollback.add_argument("project", type=Path)
    rollback.add_argument("checkpoint_id")

    versions = commands.add_parser("versions", help="list immutable asset versions")
    versions.add_argument("project", type=Path)

    undo = commands.add_parser("undo", help="restore the previous asset version")
    undo.add_argument("project", type=Path)

    export = commands.add_parser("export", help="copy the current GLB")
    export.add_argument("project", type=Path)
    export.add_argument("output", type=Path)

    mcp = commands.add_parser("mcp", help="serve the typed MCP surface over stdio")
    mcp.add_argument("project", type=Path)

    http = commands.add_parser("serve", help="serve the local API and desktop viewer")
    http.add_argument("project", type=Path)
    http.add_argument("--host", default="127.0.0.1")
    http.add_argument("--port", default=8289, type=int)
    http.add_argument("--web-root", type=Path)

    worker = commands.add_parser("blender-run", help="run an allowlisted Blender job")
    worker.add_argument("project", type=Path)
    worker.add_argument("job", type=Path, help="JSON job envelope")
    worker.add_argument("--blender", default="blender")
    worker.add_argument("--bwrap", default="bwrap")
    worker.add_argument("--sandbox-exec", default="sandbox-exec")
    worker.add_argument("--timeout", type=float, default=300)
    worker.add_argument("--allow-unsafe", action="store_true", help="explicitly allow execution without a real OS sandbox")

    unity = commands.add_parser("unity-validate", help="run the supplied Unity Editor validator")
    unity.add_argument("unity_project", type=Path)
    unity.add_argument("input_asset", type=Path)
    unity.add_argument("--output", default=".open3d/unity-report.json", type=Path)
    unity.add_argument("--unity", default="unity-editor")
    unity.add_argument("--timeout", type=float, default=600)

    commands.add_parser("providers", help="list configured provider adapters")

    provider = commands.add_parser("provider-run", help="run the opt-in Meshy image-to-3D provider")
    provider.add_argument("project", type=Path)
    provider.add_argument("image_url")
    provider.add_argument("--consent", action="store_true", required=True, help="confirm that the image may be uploaded to Meshy")
    provider.add_argument("--timeout", type=float, default=900)

    generation = commands.add_parser("meshy-generate", help="run the high-quality Meshy text/image pipeline and adopt the GLB")
    generation.add_argument("project", type=Path)
    generation.add_argument("--asset-id", required=True)
    generation.add_argument("--prompt", required=True)
    generation.add_argument("--mode", choices=("text", "image", "multi_image"), default="text")
    generation.add_argument("--image-url", action="append", dest="image_urls", help="HTTPS or data image URL; repeat for multi_image")
    generation.add_argument("--kind", choices=("prop", "environment", "character", "material", "scene"), default="prop")
    generation.add_argument("--quality", choices=("draft", "high", "hero"), default="high")
    generation.add_argument("--reference-provider", choices=("codex-cli", "all2api", "openai"))
    generation.add_argument("--consent", action="store_true", required=True, help="confirm that prompt/images may be sent to remote providers")
    generation.add_argument("--timeout", type=float, default=900)

    production = commands.add_parser("production-run", help="run a checked-in local production brief")
    production.add_argument("--brief", required=True, type=Path)
    production.add_argument("--output", required=True, type=Path)
    production.add_argument("--timeout", type=float, default=300)
    repair = commands.add_parser("production-repair", help="run the fixed local production repair")
    repair.add_argument("--run", required=True, type=Path)
    repair.add_argument("--repair-id", required=True)
    repair.add_argument("--timeout", type=float, default=300)
    promote = commands.add_parser("production-promote", help="promote a verified local production run")
    promote.add_argument("--run", required=True, type=Path)
    promote.add_argument("--project", required=True, type=Path)
    release = commands.add_parser("production-release-verify", help="verify promoted release artifacts")
    release.add_argument("project", type=Path)
    agent = commands.add_parser("production-agent-receipt", help="record a read-only Codex or Claude run receipt")
    agent.add_argument("--agent", choices=("codex", "claude", "opencode"), required=True)
    agent.add_argument("--run", required=True, type=Path)
    agent.add_argument("--output-root", type=Path)
    agent.add_argument("--timeout", type=float, default=30)
    build = commands.add_parser("agent-build", help="let an agent author and run a Blender asset build")
    build.add_argument("project", type=Path)
    build.add_argument("--agent", choices=("codex", "claude", "opencode"), required=True)
    build.add_argument("--prompt", required=True)
    build.add_argument("--timeout", type=float, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            project = args.project.resolve()
            asset = args.asset if args.asset.is_absolute() else project / args.asset
            _json(Project.init(project, asset).inspect())
            return 0
        if args.command == "providers":
            _json(provider_catalog())
            return 0
        if args.command == "production-run":
            _json(run_production(json.loads(args.brief.read_text(encoding="utf-8")), args.output, timeout=args.timeout))
            return 0
        if args.command == "production-repair":
            _json(repair_production(args.run, args.repair_id, timeout=args.timeout))
            return 0
        if args.command == "production-promote":
            _json(promote_production(args.run, args.project))
            return 0
        if args.command == "production-release-verify":
            value = verify_release(Project(args.project))
            _json(value)
            return 0 if value["status"] == "PASS" else 1
        if args.command == "production-agent-receipt":
            _json(production_agent_receipt(args.agent, args.run, output_root=args.output_root, timeout=args.timeout))
            return 0
        if args.command == "unity-validate":
            value = UnityValidator(args.unity_project, unity=args.unity).run(args.input_asset, args.output, timeout=args.timeout)
            _json(value)
            return 0 if value["status"] == "PASS" else 1
        project = Project(args.project)
        if args.command == "inspect":
            _json(project.inspect())
        elif args.command == "validate":
            report = project.validate()
            _json(report)
            return 0 if report["status"] == "PASS" else 1
        elif args.command == "edit-part":
            scales = {axis: value for axis, value in (("x", args.scale_x), ("y", args.scale_y), ("z", args.scale_z)) if value is not None}
            _json(project.edit_part(args.part_id, scales, idempotency_key=args.idempotency_key))
        elif args.command == "rollback":
            _json(project.rollback(args.checkpoint_id))
        elif args.command == "versions":
            _json(project.asset_versions())
        elif args.command == "undo":
            _json(project.undo())
        elif args.command == "export":
            _json({"artifact": project.current()["glb_artifact"], "output": str(project.export_glb(args.output))})
        elif args.command == "mcp":
            serve_stdio(project)
        elif args.command == "serve":
            serve(project, host=args.host, port=args.port, web_root=args.web_root)
        elif args.command == "blender-run":
            job = json.loads(args.job.read_text(encoding="utf-8"))
            _json(BlenderSandbox(project.root, blender=args.blender, bwrap=args.bwrap, sandbox_exec=args.sandbox_exec).run(job, timeout=args.timeout, allow_unsafe=args.allow_unsafe))
        elif args.command == "provider-run":
            _json(MeshyImageTo3D().generate(project, image_url=args.image_url, consent=args.consent, timeout=args.timeout))
        elif args.command == "meshy-generate":
            _json(MeshyPipeline().run(project, asset_id=args.asset_id, prompt=args.prompt, mode=args.mode, kind=args.kind, image_urls=args.image_urls, consent=args.consent, quality=args.quality, reference_provider=args.reference_provider, timeout=args.timeout))
        elif args.command == "agent-build":
            _json(run_agent_build(args.agent, args.prompt, project.root, timeout=args.timeout, quality_profile="production"))
        return 0
    except (ProjectError, ProviderError, WorkerError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"open3d: {exc}", file=sys.stderr)
        return 2
