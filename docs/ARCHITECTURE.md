# Architecture

```text
asset.yaml / ASSET.md
        |
        v
contract validation + canonical SHA-256
        |
        v
immutable artifact store (.open3d/objects)
        |
        +--> deterministic GLB + semantic node metadata
        +--> structured QA report
        +--> checkpoint before each mutation
        |
        v
typed CLI/MCP operations
```

The filesystem is the source of truth. SQLite, a desktop shell, Blender, Unity, and remote providers can index or consume the same artifacts later; they are not allowed to become a second, hidden project database.

## Trust zones

The Python contract/CAS/QA core is trusted local code. GLB/contract input is untrusted data and must stay schema-validated. Future Blender skills and provider outputs are constrained/untrusted workers. Remote providers are explicit, opt-in adapters and must never receive an asset without consent.

## Current implementation boundary

The dependency-free procedural generator supplies a deterministic baseline. Its GLB nodes carry `extras.open3d.part_id`, allowing a viewer or engine adapter to resolve semantic parts without parsing arbitrary names. The MCP server maps only to inspect, validate, edit-part, and rollback operations; raw shell, arbitrary path, and Python execution are intentionally absent.
