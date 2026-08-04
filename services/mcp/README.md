# services/mcp

Three Model Context Protocol servers that expose narrow, testable tool surfaces to the orchestrator.

## The three servers

| Server | Exposes | Notes |
|---|---|---|
| `kb-mcp/` | `search_knowledge`, `get_citation`, `list_sops` | Read-only; hits the hybrid retriever |
| `ops-mcp/` | `get_unit_history`, `get_asset`, `get_vendor_availability`, `create_work_order`, `notify_resident` | The **only** write tools in the system live here, and only the orchestrator holds credentials to call them |
| `policy-mcp/` | `get_lease_clause`, `get_habitability_sla`, `run_fair_housing_check` | Deterministic policy retrieval + guardrails; no LLM inside |

## Rule

Every tool is a pure function of its inputs and the DB snapshot at call time. Tool schemas are checked into this package; the orchestrator imports them, no dynamic discovery.

## Owner

Vishal. See [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
