# Blender worker boundary

The Python package now includes an allowlisted worker at `open3d_artist/blender_worker.py`. The parent launcher is `open3d_artist.workers.BlenderSandbox` and the CLI entry point is:

```bash
open3d blender-run /path/to/open3d-project job.json
```

Jobs are limited to `inspect`, `validate`, and `export_glb`; they can only open a `.blend` inside the project root. The launcher uses bubblewrap on Linux or macOS `sandbox-exec` when available, and refuses an unsandboxed run unless `--allow-unsafe` is explicit.

The fixed Blender command is:

```bash
blender --background --factory-startup --disable-autoexec \
  --python worker_bootstrap.py \
  --job /job/input/job.json --result /job/output/result.json
```

The parent daemon owns the watchdog, mounts only declared project/output paths, denies network under bubblewrap, caps runtime/output, and verifies GLB output before putting it in the CAS. Community skills remain disabled; only the bundled worker is executable.

No `.blend`, model weight, API key, or arbitrary Python executor belongs in the core package.
