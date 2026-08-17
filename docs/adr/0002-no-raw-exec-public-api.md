# No raw execution public API

Status: Accepted

## Decision

The public CLI/MCP surface exposes typed asset operations only. It does not expose shell, arbitrary filesystem, or Blender Python execution.

## Consequence

New worker capabilities need a manifest, schema, permissions, validator, and explicit adapter boundary. Convenience is traded for a smaller security surface.
