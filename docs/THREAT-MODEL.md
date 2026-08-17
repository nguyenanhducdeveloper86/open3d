# Threat model

| Asset | Threat | Control |
|---|---|---|
| contract JSON/YAML | schema confusion or oversized values | version/semantic validation and triangle budget |
| artifact bytes | tampering or partial write | SHA-256 verification and atomic rename |
| project paths | traversal/symlink escape | resolve and boundary-check before worker mounts |
| worker skill | code execution/network abuse | separate process sandbox, deny-by-default permissions |
| MCP client | confused deputy or arbitrary execution | typed coarse tools and no raw executor |
| provider | unwanted upload or license violation | explicit consent, BYOK, manifest and license gate |

The bundled Blender adapter executes only three fixed operations through an OS boundary: bubblewrap on Linux or macOS `sandbox-exec` when available. It denies network, restricts writes to temporary output, caps process time/output, and refuses an unsandboxed run unless explicitly requested. Community skills and arbitrary Blender Python remain disabled.
