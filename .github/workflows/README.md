# .github/workflows

CI/CD pipelines.

## Planned pipelines

| File | Owner | Purpose |
|---|---|---|
| `ci.yml` | Track **B** | Lint, typecheck, unit tests on every push. Cross-tenant RLS suite runs here. |
| `evals.yml` | Track **A** | The eval gate — priority F1, groundedness, P0 recall, fair-housing red-team. Blocks merge on regression. |
| `deploy.yml` | Track **B** | Deploy `apps/web` → Vercel and `services/*` → Fly on `main`. |

## Rules

- Prompts are versioned artifacts. A prompt change without a matching eval run is a merge block.
- The evals CI job posts a delta comment on every PR: "P0 recall −0.02 vs main, groundedness +0.01, cost/ticket −$0.003."
- Secrets come from GitHub Environments, scoped to `staging` and `production`. No repo-wide secrets.

See [docs/PHASES.md](../../docs/PHASES.md) for ownership and [docs/04-execution-and-career.md](../../docs/04-execution-and-career.md) for the milestone schedule.

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
