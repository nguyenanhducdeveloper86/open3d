# Contributing

Open3D Artist is intentionally small. Start with an issue for protocol, security, licensing, or provider changes; small bug fixes and docs can go directly through a pull request.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q open3d_artist tests
python3 -m open3d_artist init /tmp/open3d-example --asset examples/watering-can/asset.yaml
python3 -m open3d_artist validate /tmp/open3d-example
```

Keep the core dependency-free. Optional YAML, DCC, engine, GPU, and remote-provider integrations belong behind explicit extras or separate packages. Do not add a generic executor to make an adapter convenient.

## Contract changes

Schema/protocol changes need an ADR under `docs/adr/`, a fixture update, and a compatibility note. IDs and error/check IDs are stable API surface. Additive fields should remain inside the published schema version; breaking changes require a major version.

## Pull requests

Every PR should explain the trust boundary, tests, license impact, and whether a checkpoint/rollback path is affected. Commits should include a DCO sign-off:

```text
Signed-off-by: Your Name <you@example.com>
```
