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
Each run also rasterizes only the checked-in SVG reference and `HERO_3Q.png`
with a fixed bounded ImageMagick command and records deterministic local
similarity evidence. This is local evidence only: the manifest remains
`UNAVAILABLE_REPAIR_REQUIRED`, scopes follow-up as `PACK_PENDING_FULL_6_VIEW`,
and repair is capped at three attempts without changing geometry.

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

Record evidence from an installed Codex or Claude Code CLI without allowing
edits:

```sh
python3 -m open3d_artist production-agent-receipt --agent codex --run "$RUN_DIR"
python3 -m open3d_artist production-agent-receipt --agent claude --run "$RUN_DIR"
```

The bridge uses fixed non-interactive read-only/plan argv, bounded timeout and
output, and writes only `agent_process_receipt.json`. Missing, unauthenticated,
or failed CLIs are recorded as `UNAVAILABLE` or `FAILED`; agent text cannot
change geometry, QA, promotion, approval, signing, or release state. A `PASS`
requires a parsed structured agent receipt tied to the exact production receipt
digest.

Promote a verified run with `production-promote --run <run> --project <project>`;
the equivalent HTTP route is `/api/production/promote`, and MCP exposes typed
`production.promote` and `production.release_verify`. Promotion copies the
receipt, blend, GLB, six renders, provenance, QA, evidence, and release proof
into CAS, preserving a rollback checkpoint. `PROMOTED_LOCAL_NOT_APPROVED` is
the only local promotion state: external visual QA and Unity remain unavailable.

Safety boundary: prompts, local references, views, catalog recipe IDs, repair IDs, and reference digests are validated;
arbitrary paths, commands, Python, providers, network, Unity, and unsandboxed
Blender execution are not permitted. External visual QA and Unity remain
`UNAVAILABLE`; never promote a local receipt to approval.
