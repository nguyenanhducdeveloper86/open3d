# Job protocol

The future Blender/Unity worker job carries a version, job ID, idempotency key, input artifact IDs, operation, skill digest, declared limits, and output references. The parent process owns timeout/cancel policy and verifies outputs before registration.
