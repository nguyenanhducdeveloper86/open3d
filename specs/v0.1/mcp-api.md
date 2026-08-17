# MCP API

The experimental stdio adapter targets MCP protocol revision `2026-07-28` and exposes:

| Tool | Purpose |
|---|---|
| `asset.inspect` | current contract and artifact refs |
| `asset.validate` | deterministic QA |
| `asset.edit_part` | checkpointed semantic scale edit |
| `checkpoint.rollback` | exact restore |

Resources are limited to `open3d://projects/{project_id}/asset`, `/qa/latest`, and `/history`. No public tool executes a shell, reads an arbitrary path, or evaluates Blender Python.
