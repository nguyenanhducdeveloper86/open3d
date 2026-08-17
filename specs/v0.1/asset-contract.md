# Asset contract

The canonical asset is a JSON object accepted from `asset.yaml`, JSON, or YAML frontmatter in `ASSET.md`. It contains a version, stable asset ID, kind, meter dimensions, non-empty unique semantic parts, and a triangle budget.

`geometry.primitives` is the dependency-free alpha representation. A future Blender worker may produce richer source artifacts, but it must preserve the same asset ID and semantic part IDs.
