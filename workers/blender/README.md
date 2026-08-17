# Blender worker boundary

This directory is deliberately documentation-only in the alpha. A future worker should launch Blender with a fixed policy equivalent to:

```bash
blender --background --factory-startup --disable-autoexec \
  --python worker_bootstrap.py -- \
  --job /job/input/job.json --result /job/output/result.json
```

The parent daemon must own the watchdog, mount only declared project/output paths, deny network by default, cap CPU/memory/PIDs/output size, and verify every output before putting it in the CAS. Community skills remain disabled until the host platform provides a real process/container sandbox.

No `.blend`, model weight, API key, or arbitrary Python executor belongs in the core package.
