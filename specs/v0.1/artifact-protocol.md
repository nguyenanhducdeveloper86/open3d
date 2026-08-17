# Artifact protocol

An artifact is stored at `.open3d/objects/sha256/<first-two>/<digest>`. Its ID is the SHA-256 digest of exact bytes. A write uses a temporary file, flush/fsync, and atomic rename. Readers verify the digest before returning bytes.

Metadata is descriptive and may be rebuilt; bytes and project references are authoritative.
