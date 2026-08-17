# GLB preview format

Status: Accepted

## Decision

v0.1 uses glTF 2.0 binary GLB for portable preview/interchange and stores semantic part identity in `node.extras.open3d`.

## Consequence

Viewer and engine adapters share a stable artifact target; richer source/editable formats remain separate artifacts.
