# Open3D Artist

Open3D Artist is a local-first, contract-first pipeline for building and validating small 3D assets. It is designed for artists and agents that need inspectable artifacts, semantic parts, deterministic checks, and safe rollback instead of an opaque mesh-generation demo.

The repository currently ships a runnable v0.1 vertical slice:

- versioned asset contracts with canonical SHA-256 hashes;
- immutable `.open3d` content-addressed storage;
- deterministic primitive-to-GLB export with `extras.open3d.part_id`;
- geometry QA with stable check IDs;
- checkpointed semantic-part edits and exact rollback;
- a small typed MCP stdio surface with no raw shell or Python execution;
- standard-library tests and a clean-room GitHub Actions check.

Blender, Unity, GPU providers, remote APIs, and a desktop viewer are extension boundaries, not core runtime dependencies. No model weights or proprietary credentials are bundled.

## Quick start

Requires Python 3.11+.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m unittest discover -s tests -v

python -m open3d_artist init examples/watering-can --asset asset.yaml
python -m open3d_artist validate examples/watering-can
python -m open3d_artist inspect examples/watering-can
python -m open3d_artist edit-part examples/watering-can spout --scale-x 1.2
python -m open3d_artist export examples/watering-can /tmp/watering-can.glb
```

The example `asset.yaml` uses JSON syntax, which is valid YAML 1.2, so the core has no runtime dependency. For normal YAML authoring install `pip install -e '.[yaml]'`.

## Repository map

```text
open3d_artist/       Python core and CLI
schemas/v0.1/        Published JSON Schema contracts
specs/v0.1/          Normative protocol notes
examples/             Golden, dependency-free asset fixture
tests/                Small standard-library regression suite
docs/                 Architecture, security, compatibility, and OSS policy
workers/               Optional worker boundary documentation
```

## Status and scope

This is an alpha foundation, not a finished DCC replacement. The procedural GLB generator is the deterministic baseline. Blender headless execution, Unity import validation, six-view rendering, provider adapters, signed packages, and a full desktop viewer are planned adapters and are deliberately not hidden behind fake “production-ready” claims.

The implementation contract is captured in [the v0.1 specs](specs/v0.1/README.md) and the research-derived [architecture](docs/ARCHITECTURE.md). See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [PROVIDER-LICENSE-MATRIX.md](docs/PROVIDER-LICENSE-MATRIX.md) before adding a worker or provider.

## License

Core code and specifications are Apache-2.0. A future Blender-side package may need a separate GPL-compatible boundary; it is not silently mixed into this package. See [LICENSING.md](docs/LICENSING.md).
