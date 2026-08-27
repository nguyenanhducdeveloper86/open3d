# Implementation readiness

Status: **public alpha production slice**

The repository is cloneable, licensed, tested, and has a working offline vertical slice. It is ready for public contributor feedback, not a claim that every six-month v0.1 production gate is complete.

| Area | Current evidence | Status |
|---|---|---|
| Contract/schema | `schemas/v0.1/`, semantic parser, JSON Schema test | ready |
| Artifact core | immutable SHA-256 CAS and integrity checks | ready |
| Checkpoint/edit | semantic scale edit, operation log, exact rollback | ready |
| GLB preview | deterministic dependency-free writer and `part_id` extras | ready |
| Deterministic QA | stable report/check IDs and blocking checks | ready |
| MCP | typed stdio inspect/validate/edit/rollback surface | experimental |
| Blender | allowlisted standalone worker, watchdog, output cap, bubblewrap/macOS sandbox policy | adapter ready; host sandbox still required on unsupported OS |
| Viewer | local API, Three.js GLB viewer, semantic picking, edit/QA/history/provider views | ready |
| Unity | batch validator source adapter and bounded command builder | adapter ready; licensed Editor/importer required |
| Providers | opt-in Meshy text/image/multi-view pipeline with preview/refine, PBR quality profiles, semantic GLB normalization, plus Codex imagegen CLI and All2API-compatible reference adapters | adapter ready; provider keys required |
| Release signing/SBOM | tag workflow, checksums, CycloneDX inventory, OIDC provenance attestation | ready on tagged CI release |

The research report's large G2–G10 backlog remains intentionally visible in [BACKLOG.md](BACKLOG.md). The first public milestone is the deterministic baseline; no AI provider is allowed to hide a core pipeline defect.
