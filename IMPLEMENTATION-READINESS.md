# Implementation readiness

Status: **public alpha foundation**

The repository is cloneable, licensed, tested, and has a working offline vertical slice. It is ready for public contributor feedback, not a claim that every six-month v0.1 production gate is complete.

| Area | Current evidence | Status |
|---|---|---|
| Contract/schema | `schemas/v0.1/`, semantic parser, JSON Schema test | ready |
| Artifact core | immutable SHA-256 CAS and integrity checks | ready |
| Checkpoint/edit | semantic scale edit, operation log, exact rollback | ready |
| GLB preview | deterministic dependency-free writer and `part_id` extras | ready |
| Deterministic QA | stable report/check IDs and blocking checks | ready |
| MCP | typed stdio inspect/validate/edit/rollback surface | experimental |
| Blender | launch/security boundary documented, worker not bundled | planned |
| Viewer | GLB contract documented, desktop viewer not bundled | planned |
| Unity | import policy documented, licensed validator not bundled | planned |
| Providers | license matrix and optional boundary documented | planned |
| Release signing/SBOM | policy documented, source-only alpha | planned |

The research report's large G2–G10 backlog remains intentionally visible in [BACKLOG.md](BACKLOG.md). The first public milestone is the deterministic baseline; no AI provider is allowed to hide a core pipeline defect.

