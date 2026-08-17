# Checkpoint before mutation

Status: Accepted

## Decision

Every mutating operation records a checkpoint containing the complete current reference before and after the operation. Rollback restores the reference without deleting reachable artifacts.
