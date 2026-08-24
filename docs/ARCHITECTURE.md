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

The dependency-free procedural generator supplies a deterministic baseline for fixtures, not an agent fallback. Its GLB nodes carry `extras.open3d.part_id`, allowing a viewer or engine adapter to resolve semantic parts without parsing arbitrary names. The MCP server maps to typed inspect, validate, edit-part, rollback, and agent-build operations. `agent.build` gives an authenticated external agent a staging workspace for `asset.json` and `build.py`, then the parent process runs Blender with output-only writes and validates the GLB; raw shell remains absent from the public API. An optional 9router-style OpenAI-compatible pool is probed before execution and is fail-closed.
