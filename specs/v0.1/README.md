# Open3D Artist Core Specification v0.1

This is the narrow contract that the current repository implements. The schemas are machine-readable; these notes define identity and lifecycle rules.

## Invariants

1. Core objects carry `schema_version`.
2. Unknown major versions are rejected.
3. Artifact IDs are SHA-256 of exact bytes and artifacts are immutable.
4. `part_id` is stable within an asset and is never reused for a different semantic part.
5. Every mutation has an idempotency key and a checkpoint before the mutation.
6. Deterministic QA is the blocking authority; model/VLM/provider suggestions are not.
7. Public operations are typed; raw process, shell, and arbitrary path execution are out of scope.

## Documents

- [asset contract](asset-contract.md)
- [artifact protocol](artifact-protocol.md)
- [checkpoint and operation protocol](checkpoint-protocol.md)
- [QA protocol](qa-protocol.md)
- [skill boundary](skill-protocol.md)
- [MCP API](mcp-api.md)
- [viewer contract](viewer-contract.md)
