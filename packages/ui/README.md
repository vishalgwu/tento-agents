# packages/ui

Shared component library consumed by `apps/web`. Design system tokens, primitives, and shell-agnostic components (approval cards, trace viewer, retrieval inspector, cost bar, streaming step list, evidence citations).

## Rules

- Nothing here talks to the network. Components take data as props; fetching is `apps/web`'s job.
- Types are imported from `packages/shared-types` only. No hand-typed API shapes.
- Design tokens follow [docs/DESIGN.md](../../docs/DESIGN.md).

## Owner

Track **B** per [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
