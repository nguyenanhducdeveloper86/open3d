# Open3D Artist

Open3D Artist is a contract-first pipeline for building and validating small 3D assets. It is designed for artists and external LLM agents that need inspectable artifacts, semantic parts, deterministic checks, and safe rollback instead of an opaque mesh-generation demo.

The repository ships a runnable v0.1 local production slice:

- versioned asset contracts with canonical SHA-256 hashes;
- immutable `.open3d` content-addressed storage;
- deterministic primitive-to-GLB export with `extras.open3d.part_id`;
- geometry QA with stable check IDs;
- checkpointed semantic-part edits and exact rollback;
- a small typed MCP stdio surface with no raw shell or Python execution;
- bounded Blender and Unity worker adapters with explicit runtime boundaries;
- opt-in Meshy high-quality text/image/multi-view-to-3D integration with preview/refine, PBR textures, and verified GLB storage;
- optional Codex imagegen CLI or the local `/Users/ducna/mcp-all2api` browser bridge (ChatGPT/Flow/Grok) for reference images before Meshy;
- a Three.js desktop viewer served by the local API;
- checksums, SBOM generation, and GitHub OIDC release provenance;
- standard-library tests, viewer build, and a clean-room GitHub Actions check.

Blender, Unity, and remote providers remain optional runtime dependencies. No model weights, proprietary credentials, Blender binary, Unity Editor, or importer package is bundled.

## Alpha distribution

The `v0.1.0a1` release is a prerelease. Its wheel contains the Python core and CLI only. Use the `open3d-artist-app-v0.1.0a1.tar.gz` source bundle when you need the checked-in production recipes, fixture tool, Unity validator source, and built viewer; host runtimes such as Blender, bubblewrap/ImageMagick, and Unity are still installed separately. Verify downloaded files with `sha256sum -c SHA256SUMS`.

Distribution provenance attests what was built, not production-asset approval. Released production examples remain `LOCAL_ONLY_NOT_APPROVED`; the alpha does not imply external visual QA, Unity/provider validation, successful agent execution, or xFarm-quality parity.

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
# Agent-authored Blender build (requires Codex/Claude Code/OpenCode/Agy and Blender)
python -m open3d_artist agent-build examples/watering-can --agent codex --prompt "Build a stylized Scandinavian timber house"
# Meshy text-to-3D: preview -> refine -> PBR/4K GLB -> contract/QA/version
python -m open3d_artist meshy-generate examples/watering-can --asset-id PROP-SCANDI-HOUSE-001 --prompt "Production-quality stylized Scandinavian timber house" --quality high --consent

# Local mcp-all2api image -> authenticated external agent -> Blender -> GLB/QA
# Start mcp-all2api first (`npm start`, default http://127.0.0.1:3737), then use
# the Create 3D asset dialog and choose “All2API image → Agent Blender”.

npm ci --prefix web
npm run build --prefix web
python -m open3d_artist serve examples/watering-can
```

Open `http://127.0.0.1:8289` for the desktop viewer. The viewer reads the current GLB artifact, supports semantic picking and checkpointed edits, and sends build prompts only to authenticated Codex, Claude Code, OpenCode, or Agy agents.

The example `asset.yaml` uses JSON syntax, which is valid YAML 1.2, so the core has no runtime dependency. For normal YAML authoring install `pip install -e '.[yaml]'`.

External agent builds are staged under `.open3d/agent-runs/`: the selected agent writes `asset.json` and `build.py`, Open3D executes the script with Blender in the OS sandbox, then runs the fixed `blender-design-v1` pass. That pass preserves authored bevels, adds conservative form softness only to raw meshes, applies weighted normals/selective smooth shading, guarantees UVs, creates deterministic Principled surface variation embedded in the GLB, renders `HERO_3Q`, `FRONT`, `BACK`, `LEFT`, `RIGHT`, and `TOP`, and records `pipeline.json` plus the preview images before verifying semantic parts, triangle budget, dimensions, GLB identity, material/primitive breakup, normals, detail coverage, and long-thin roof-span artifacts. Agent entry points use this production gate; there is no local-agent fallback. These are deterministic Blender/structural checks, not a claim of human or external visual approval.

When a reference image is attached, the agent build also uses an img2threejs-style intake gate: it must write `reference_spec.json` with a silhouette, macro/meso/micro component inventory, detail implementation plan, materials, ordered build passes, and explicit unseen regions before Blender runs. This is a lightweight reference-to-procedural-Blender workflow for base Apple Silicon; it is not a neural image-to-3D model generator. The validated spec digest is kept in the agent receipt and asset history.

To route all three CLIs through one 9router-style token pool, copy `.env.example`, replace the token, export it, and start the server:

```bash
cp .env.example .env
set -a; . ./.env; set +a
python -m open3d_artist serve examples/watering-can
```

Open3D probes `${OPEN3D_AGENT_POOL_URL}/v1/models`; a failed pool probe blocks every agent instead of silently switching to direct credentials. Leave the pool variables unset to use each CLI's own authenticated session.

If OpenCode's saved config points to an unavailable model, set `OPEN3D_OPENCODE_MODEL` to a model available to that OpenCode credential; this override is ignored when the shared pool is configured. Agy uses `Claude Sonnet 4.6 (Thinking)` by default; set `OPEN3D_AGY_AGENT` to one of the names returned by `agy agents` to select another external agent. Agy must pass its own account eligibility check before Open3D marks it active.

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

This is an alpha production slice, not a finished DCC replacement. The procedural GLB generator remains the deterministic baseline. Blender sandboxing needs bubblewrap on Linux, macOS `sandbox-exec`, or an equivalent host policy; Unity needs a licensed Editor and a compatible importer; Meshy needs `MESHY_API_KEY` plus explicit consent. Meshy generation uses `meshy-7`/`latest`, Ultra geometry, PBR, and 4K/8K textures; use `draft` when latency or credits matter. Codex imagegen CLI additionally needs `OPENAI_API_KEY` and the imagegen CLI's `openai` dependency. The local All2API bridge uses `ALL2API_BASE` (default `http://127.0.0.1:3737`) and a connected browser worker; it does not need an API key. These boundaries are reported as unavailable rather than silently bypassed.

The implementation contract is captured in [the v0.1 specs](specs/v0.1/README.md) and the research-derived [architecture](docs/ARCHITECTURE.md). See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [PROVIDER-LICENSE-MATRIX.md](docs/PROVIDER-LICENSE-MATRIX.md) before adding a worker or provider.

Read [BOOTSTRAP.md](BOOTSTRAP.md) for a clean-room setup, [IMPLEMENTATION-READINESS.md](IMPLEMENTATION-READINESS.md) for the honest current boundary, and [BACKLOG.md](BACKLOG.md) for the remaining production gates.

## License

Core code and specifications are Apache-2.0. A future Blender-side package may need a separate GPL-compatible boundary; it is not silently mixed into this package. See [LICENSING.md](docs/LICENSING.md).
