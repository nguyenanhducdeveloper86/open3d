---
name: open3d-production-asset
description: Run Open3D's checked-in, sandboxed production asset brief locally.
---

# Open3D production asset

Use the repository's fixed local protocol. It accepts a JSON brief, selects only
one of the checked-in catalog recipes (`lantern`, `watering-can`, or
`wood-crate`), and returns a
stable receipt with six-view QA, artifact references, sandbox/network facts,
unavailable external gates, and `LOCAL_ONLY_NOT_APPROVED` promotion.

Codex or Claude Code invocation:

```sh
python3 -m open3d_artist production-run \
  --brief examples/production-qualification/brief.json --output "$RUN_DIR"
python3 -m open3d_artist validate "$RUN_DIR"
```

The HTTP equivalent is `POST /api/production/run` with `{"brief": <object>,
"output": "<run directory>"}`. MCP exposes the typed `production.run` tool.
These are local adapters; this package does not claim to execute an external
Codex or Claude process.

Promote a verified run with `production-promote --run <run> --project <project>`;
the equivalent HTTP route is `/api/production/promote`, and MCP exposes typed
`production.promote` and `production.release_verify`. Promotion copies the
receipt, blend, GLB, six renders, provenance, QA, evidence, and release proof
into CAS, preserving a rollback checkpoint. `PROMOTED_LOCAL_NOT_APPROVED` is
the only local promotion state: external visual QA and Unity remain unavailable.

Safety boundary: prompts, local references, views, catalog recipe IDs, and reference digests are validated;
arbitrary paths, commands, Python, providers, network, Unity, and unsandboxed
Blender execution are not permitted. External visual QA and Unity remain
`UNAVAILABLE`; never promote a local receipt to approval.
