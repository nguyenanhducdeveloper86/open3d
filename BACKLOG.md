# Backlog

This is the implementation queue derived from the research report. “Ready” means the repository has a tested slice, not that every production adapter exists.

## P0

| Gate | Work | Status |
|---|---|---|
| G1 | contract parser, CAS, checkpoints, operation log | **ready**; GC/concurrency hardening remains |
| G2 | constrained Blender launcher and worker | planned |
| G3 | GLB viewer, semantic picking, resource disposal | planned; GLB contract ready |
| G4 | deterministic geometry QA and golden fixtures | **ready** for primitive baseline; broader mesh corpus remains |
| G5 | semantic edit, invalidation DAG, bounded repair | **partial**; scale edit/rollback ready |
| G6 | locked six-view renderer and visual evidence | planned |
| G7 | licensed Unity batch validator | planned |
| G8 | MCP typed operations and conformance | **experimental**; local stdio surface ready |
| G9 | provider SDK, consent, license gates | planned |
| G10 | packaging, provenance, release hardening | **partial**; OSS policy/CI ready, signed binaries remain |

## P1/P2

UV/PBR/baking, LOD/colliders, GPU providers, Godot validation, benchmark lanes, characters/rigging, physics metadata, scene assembly, distributed workers, and a signed public registry come after the core contracts prove stable.

## Rules

- procedural baseline before model provider;
- deterministic QA before visual/AI QA;
- checkpoint before mutation;
- no raw shell/Python execution in public APIs;
- every provider declares license, upload behavior, permissions, and resource needs.

