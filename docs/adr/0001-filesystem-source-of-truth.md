# Filesystem source of truth

Status: Accepted

## Decision

Project references, immutable artifacts, checkpoints, and the operation log live under `.open3d/`. Indexes and UIs may be rebuilt from these files.

## Consequence

Projects remain inspectable, portable, and recoverable without a daemon database. Concurrent writers are not supported by the alpha CLI; add locking when multi-process editing becomes a real requirement.
