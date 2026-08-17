# Compatibility

| Component | v0.1 baseline | Policy |
|---|---|---|
| Python | 3.11+ | stdlib core; test current supported Python versions in CI |
| Contract | JSON Schema draft 2020-12 shape | reject unknown major versions |
| Preview | glTF 2.0 / GLB | semantic metadata in `extras.open3d` |
| MCP | 2026-07-28 target | transport adapter may evolve independently |
| Blender | optional, not required by core | pin a worker version when introduced |
| Unity | optional, not required by core | licensed runner only |

Minor additions should be backward compatible. Breaking schema or operation semantics require a new major version and migration note.
