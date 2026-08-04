# packages/shared-types

**Generated code. Do not hand-edit.**

TypeScript types produced from `docs/openapi.yaml` and the SSE event catalogue. This is the mechanic that keeps `apps/web` (Track B) and `services/api` (Track A) from drifting — one contract, two consumers, zero duplicated definitions.

## Regenerate

```bash
pnpm run gen:types
```

Any PR that changes API shapes must regenerate this package in the same commit. See the contract-change protocol in [docs/PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
