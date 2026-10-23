# Domain vocabulary

The database wire enums are defined in `infra/migrations/0001_init.sql`. Agent handoff enums are in `services/brain/src/brain/graph/state.py`. Public payloads are documented in `docs/openapi.yaml`; regenerate TypeScript consumers after changes.

The direct intake endpoint returns `completed`, `abstained`, or `emergency`. A completed response means intake finished, not that a repair was scheduled. Safety outcomes are deterministic. Unsupported or invalid outcomes terminate with abstention.

Priority wire values are `p0`, `p1`, `p2`, and `p3`. These are routing categories, not statutory deadlines. Keep database, agent, API, event, and generated consumer contracts consistent when changing any wire value.
