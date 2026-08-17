# Open3D Artist

Open3D Artist is a local-first, contract-first pipeline for building and validating small 3D assets. It is designed for artists and agents that need inspectable artifacts, semantic parts, deterministic checks, and safe rollback instead of an opaque mesh-generation demo.

The repository ships a runnable v0.1 local production slice:

- versioned asset contracts with canonical SHA-256 hashes;
- immutable `.open3d` content-addressed storage;
- deterministic primitive-to-GLB export with `extras.open3d.part_id`;
- geometry QA with stable check IDs;
- checkpointed semantic-part edits and exact rollback;
- a small typed MCP stdio surface with no raw shell or Python execution;
- bounded Blender and Unity worker adapters with explicit runtime boundaries;
- opt-in Meshy image-to-3D integration with consent and verified GLB storage;
- a Three.js desktop viewer served by the local API;
- checksums, SBOM generation, and GitHub OIDC release provenance;
- standard-library tests, viewer build, and a clean-room GitHub Actions check.

Blender, Unity, and remote providers remain optional runtime dependencies. No model weights, proprietary credentials, Blender binary, Unity Editor, or importer package is bundled.

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

npm ci --prefix web
npm run build --prefix web
python -m open3d_artist serve examples/watering-can
```

Open `http://127.0.0.1:8289` for the local desktop viewer. The viewer reads the current GLB artifact, supports semantic picking and checkpointed scale edits, and exposes QA, history, and provider status.

The example `asset.yaml` uses JSON syntax, which is valid YAML 1.2, so the core has no runtime dependency. For normal YAML authoring install `pip install -e '.[yaml]'`.

## Repository map

```text
open3d_artist/       Python core and CLI
schemas/v0.1/        Published JSON Schema contracts
specs/v0.1/          Normative protocol notes
examples/             Golden, dependency-free asset fixture
tests/                Small standard-library regression suite
docs/                 Architecture, security, compatibility, and OSS policy
web/                  Vite + Three.js local desktop viewer
workers/              Blender and Unity adapter boundaries
scripts/              Release/SBOM helper
```

## Status and scope

This is an alpha production slice, not a finished DCC replacement. The procedural GLB generator remains the deterministic baseline. Blender sandboxing needs bubblewrap on Linux, macOS `sandbox-exec`, or an equivalent host policy; Unity needs a licensed Editor and a compatible importer; Meshy needs `MESHY_API_KEY` plus explicit consent. These boundaries are reported as unavailable rather than silently bypassed.

The implementation contract is captured in [the v0.1 specs](specs/v0.1/README.md) and the research-derived [architecture](docs/ARCHITECTURE.md). See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [PROVIDER-LICENSE-MATRIX.md](docs/PROVIDER-LICENSE-MATRIX.md) before adding a worker or provider.

Read [BOOTSTRAP.md](BOOTSTRAP.md) for a clean-room setup, [IMPLEMENTATION-READINESS.md](IMPLEMENTATION-READINESS.md) for the honest current boundary, and [BACKLOG.md](BACKLOG.md) for the remaining production gates.

## License

Core code and specifications are Apache-2.0. A future Blender-side package may need a separate GPL-compatible boundary; it is not silently mixed into this package. See [LICENSING.md](docs/LICENSING.md).
