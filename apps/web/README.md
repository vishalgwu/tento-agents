# apps/web

Next.js 15 (App Router) — the single web app that hosts **all four role shells** for Resident OS.

## Role shells

| Shell | Route prefix | Primary user | Device |
|---|---|---|---|
| Resident | `/r` | Priya | Mobile web |
| Manager console | `/m` | Marcus | Desktop, keyboard-first |
| Owner dashboard | `/o` | Dana | Desktop |
| Tech | `/t` | Sam | Mobile, often gloved / offline |
| Vendor | `/v/{signed}` | Ravi | Signed link, no login |

## Boundaries

- **Server Components for reads**, Route Handlers as the BFF.
- The browser never holds a service key. A scoped, short-lived service token is minted server-side and forwarded to `services/api`.
- Types come from `packages/shared-types` (generated from `docs/openapi.yaml`) — never hand-written.

## Owner

Vishal. Solo build — see [PHASES.md §2](../../docs/PHASES.md) for the directory-contract rules that keep the code organized.

---
> Resident OS — the AI operations layer for apartment communities.
> Property management software records what happened. This is the layer that decides what to do next.
> Root: [README.md](../../README.md) · Vision: [docs/PRD.md](../../docs/PRD.md) · Architecture: [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)
