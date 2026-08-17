# Content-addressed artifacts

Status: Accepted

## Decision

Artifact identity is `sha256:<digest>` of the exact bytes. Writes are atomic and artifacts are never overwritten.
