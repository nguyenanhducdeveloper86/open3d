# Checkpoint and operation protocol

A checkpoint records a complete project reference before or after a mutation. The reference includes the contract, GLB, QA report, and parent checkpoint IDs. Rollback replaces the current reference with the checkpoint snapshot and does not delete artifacts.

Operation names and versions are stable. A repeated idempotency key replays the existing operation rather than applying a second mutation.
