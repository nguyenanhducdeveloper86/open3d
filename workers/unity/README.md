# Unity validator

`Editor/Open3DValidator.cs` is a source adapter for a user-owned Unity project. Copy it into `Assets/Editor/`, install the project's glTF importer (for example glTFast when importing GLB), then run:

```bash
open3d unity-validate /path/to/unity-project Assets/Model.glb
```

The adapter launches Unity with `-batchmode -nographics -quit`, refreshes the asset database, checks that an importer and mesh/object exist, and reports normals/scale/material checks as JSON. Unity Editor, its license, and any GLTF importer remain external dependencies and are not redistributed by Open3D.
