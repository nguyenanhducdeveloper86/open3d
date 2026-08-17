# v0.1 PRD

## User outcome

Clone the repository, define a small stylized prop, generate a portable GLB, inspect deterministic QA, edit one semantic part, and roll back exactly without a service account or GPU.

## Non-goals

Character rigging, marketplace features, arbitrary code execution, hidden cloud upload, Unity redistribution, and native installer packaging remain out of scope. The foundation release now includes a local desktop-style viewer, bounded worker adapters, and opt-in provider integration.

## Acceptance

The golden watering-can fixture passes QA, its GLB contains semantic part IDs, an edit changes a new artifact/checkpoint, and rollback restores the previous artifact digest. The same path runs in a clean Python environment.
