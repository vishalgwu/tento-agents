# Resume and interview evidence

Use the [copy-ready project bullets](../README.md#resume-ready-project-bullets) as the primary source. Choose three or four that fit the role; keep sample size and workload scope beside measured percentages or latency. Describe this as a deployed project demo, not commercial customer impact.

## How to discuss the engineering

- **Guardrails:** deterministic emergency screening runs before ordinary models. Four recorded emergency scenarios stopped without model calls. Source membership and independent policy checks withhold unsupported plans.
- **Prompt injection and PII:** 40 synthetic input-boundary cases span resident text, vendor replies, PDF layers, image captions and marketplace listings. Tests reject write-capable untrusted contexts for every case, including inputs without scanner pattern matches. PII redaction and role/tenant controls remain separate defenses. This is a measured boundary test, not proof of immunity to every attack.
- **Typed orchestration:** four specialist model stages exchange Pydantic-validated data. Model-facing JSON schemas expose bracketed citation patterns, and deterministic validators check allowed source membership. Next.js uses generated OpenAPI TypeScript contracts.
- **RAG:** maintenance data uses tenant-scoped PostgreSQL lexical retrieval. The fictional demo uses a separate SQLite FTS5/BM25 index. Its 14 source-labeled development queries measured Recall@3 90.5% and Precision@3 57.1%; do not describe those as production or held-out accuracy.
- **Performance:** warm embedding-cache lookup p95 fell 96.0% in 20 paired synthetic inputs. Intake p95 was 0.876s over 30 synthetic runs; the maximum was 9.734s. These workloads do not measure whole-ticket repair time.
- **MCP:** no application MCP transport is integrated. The repository has a separately tested tool-authorizer module; development connector usage is not an application runtime integration. Do not claim MCP delivery, an MCP server, or MCP-related impact on a resume for this release.

Every quantitative claim links to the raw report or relevant test in README.md. Do not invent cost-reduction percentages, business resolution-time gains, production reliability improvements or semantic faithfulness scores.
