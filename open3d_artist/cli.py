"""Command-line entry point for the local-first Open3D pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .mcp import serve_stdio
from .project import Project, ProjectError


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

    export = commands.add_parser("export", help="copy the current GLB")
    export.add_argument("project", type=Path)
    export.add_argument("output", type=Path)

    mcp = commands.add_parser("mcp", help="serve the typed MCP surface over stdio")
    mcp.add_argument("project", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            project = args.project.resolve()
            asset = args.asset if args.asset.is_absolute() else project / args.asset
            _json(Project.init(project, asset).inspect())
            return 0
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
        elif args.command == "export":
            _json({"artifact": project.current()["glb_artifact"], "output": str(project.export_glb(args.output))})
        elif args.command == "mcp":
            serve_stdio(project)
        return 0
    except (ProjectError, ValueError, OSError) as exc:
        print(f"open3d: {exc}", file=sys.stderr)
        return 2
