# Viewer contract

GLB is glTF 2.0. A semantic node carries:

```json
{"extras": {"open3d": {"part_id": "spout", "part_role": "semantic"}}}
```

`artifact_id` is the cache key. A viewer must dispose its old scene/resources before loading a new digest and must expose stale QA state rather than silently retaining a previous PASS.
