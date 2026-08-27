# Compatibility

| Component | v0.1 baseline | Policy |
|---|---|---|
| Python | 3.11+ | stdlib core; test current supported Python versions in CI |
| Contract | JSON Schema draft 2020-12 shape | reject unknown major versions |
| Preview | glTF 2.0 / GLB | semantic metadata in `extras.open3d` |
| MCP | 2026-07-28 target | transport adapter may evolve independently |
| Blender | optional, bundled worker adapter | Blender 5.x plus bubblewrap or macOS sandbox policy |
| Unity | optional validator source adapter | licensed Editor plus a compatible GLTF importer |
| Viewer | local HTTP desktop-style viewer | current Chromium/WebGL2-class browser |
| Meshy | optional remote text/image/multi-view provider | `MESHY_API_KEY`, HTTPS, explicit consent; high profile uses Meshy 7 Ultra + PBR |
| Codex imagegen CLI | optional reference-image provider | bundled `imagegen` CLI, `OPENAI_API_KEY`, and its `openai` dependency |
| All2API | optional local mcp-all2api browser-bridge reference-image provider | `ALL2API_BASE` (default `http://127.0.0.1:3737`), connected ChatGPT/Flow/Grok worker, explicit consent; no API key |

Minor additions should be backward compatible. Breaking schema or operation semantics require a new major version and migration note.
