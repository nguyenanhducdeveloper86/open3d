# Bootstrap Open3D Artist

This is the shortest clean-room path from clone to a passing artifact:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m unittest discover -s tests -v
python -m open3d_artist init /tmp/open3d-watering-can --asset "$PWD/examples/watering-can/asset.yaml"
python -m open3d_artist validate /tmp/open3d-watering-can
python -m open3d_artist edit-part /tmp/open3d-watering-can spout --scale-x 1.2
python -m open3d_artist export /tmp/open3d-watering-can /tmp/watering-can.glb
```

Optional checks:

```bash
pip install -e '.[dev,yaml]'
python -m unittest discover -s tests -v
```

The core does not need Blender, Unity, a GPU, network access, or provider credentials. Keep `.open3d/` project state out of Git; the repository `.gitignore` already does this.

