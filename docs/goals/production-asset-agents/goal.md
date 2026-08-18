# Open3D Production Asset Agents

## Objective

Turn Open3D into a production asset system that can turn a prompt or reference into a high-quality Blender asset, validate it through multi-view QA, and expose the workflow through a desktop viewer and Codex/Claude Code-compatible agent interface.

## Original Request

“Open3D có thể gen các asset tương tự các production asset của xFarm với chất lượng cao, có thể tích hợp sử dụng các agent như Codex, Claude Code như OpenDesign.”

## Intake Summary

- Input shape: `open_ended`
- Audience: the Open3D operator and asset-production team
- Authority: `requested`
- Proof type: `artifact`
- Completion proof: A local prompt/reference run produces a deterministic `.blend`, `.glb`, six production renders, machine-readable QA/provenance evidence, and a viewer-loaded approved artifact; the same run is callable from Codex and Claude Code adapters.
- Goal oracle: Run the documented end-to-end fixture workflow from a clean checkout and inspect the generated asset, six-view evidence, QA result, agent receipt, and release metadata.
- Likely misfire: Build a chat box or one-shot mesh API while missing xFarm’s real quality loop: locked asset spec, deterministic Blender recipe, six-view renders, visual QA, bounded repair, evidence, and promotion.
- Blind spots considered: Blender availability and sandbox policy, external xFarm paths, provider credentials/cost, Codex/Claude CLI availability and permissions, deterministic output, visual QA quality, artifact promotion, and signed-release trust.
- Existing plan facts: Preserve the current Blender sandbox, Unity validator, desktop viewer, AI-provider adapters, signed-release workflow, and GSAP dark design system; use `/Users/ducna/Desktop/xFarm` as the compatibility reference; keep the implementation simple.

## Goal Oracle

The oracle for this goal is:

`python -m open3d_artist ...` can execute one checked-in production fixture from prompt/reference through Blender generation, six-view QA, approval, viewer load, and signed artifact metadata, with an agent receipt callable by Codex and Claude Code.

The PM must keep comparing task receipts to this oracle. Planning, discovery, a passing tiny slice, or a clean-looking board is not enough. The goal finishes only when a final Judge/PM audit maps receipts and verification back to this oracle and records `full_outcome_complete: true`.

## Goal Kind

`open_ended`

## Current Tranche

Discover enough evidence, implement the largest reversible production slice, verify it locally, then continue through agent integration, QA/promotion, viewer, and release until the full oracle is demonstrated.

## Non-Negotiable Constraints

- Do not claim AI generation is production-ready without a reproducible artifact and QA evidence.
- Keep Blender execution sandboxed and allowlisted; never silently execute arbitrary agent code.
- Preserve existing user changes and the current GSAP visual language.
- Prefer stdlib/native tooling and the smallest useful implementation.
- Provider credentials and external CLIs remain explicit operator configuration, never committed.
- After every verified Worker package, commit the completed work and push it to `origin/main`; record the resulting commit in the handoff.

## Stop Rule

Stop only when a final audit proves the full original outcome is complete.

Do not stop after planning, discovery, or Judge selection if a safe Worker task can be activated.

Do not stop after a single verified Worker package when the broader outcome still has safe local follow-up work.

## Slice Sizing

Workers should implement vertical, reversible slices that move the end-to-end oracle forward. Repeated provider, QA, or agent work belongs in one coherent package rather than many wrapper-only tasks.

## Board Health

The PM owns board health. `state.yaml` is authoritative; `notes/` stores long receipts and evidence summaries.

## Canonical Board

Machine truth lives at:

`docs/goals/production-asset-agents/state.yaml`

## Run Command

```text
/goal Follow docs/goals/production-asset-agents/goal.md.
```

## PM Loop

On every continuation, read this charter and `state.yaml`, run the GoalBuddy checker, work only on the active task, record a receipt, activate the next safe task, and run the stop gate before ending.
