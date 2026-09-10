# Resident OS Domain Vocabulary

## Status

This document freezes the enum wire values used by database migrations, API
contracts, agent schemas, SSE payloads, fixtures, and evaluation data.

Requirements: FR-201, FR-401, FR-501, FR-701, SR-003, SR-005, QR-003.

The values below are lowercase ASCII `snake_case` strings. They are serialized
exactly as shown: consumers must not use title case, spaces, hyphens, numeric
codes, aliases, or display labels in place of these values. User-facing copy is
an application concern and never changes a wire value.

`infra/migrations/0001_init.sql` is the database implementation of this
contract. Changes to either artifact require one atomic change to the migration,
API/event contracts, generated types, fixtures, tests, and this document.

## `priority`

Database type: `priority`.

| Value | Operational meaning |
| --- | --- |
| `p0` | Life safety; follows the deterministic P0 human-paging protocol immediately. |
| `p1` | Habitability issue; the applicable statutory response window controls. |
| `p2` | Urgent maintenance issue. |
| `p3` | Routine maintenance issue. |

`p0` detection is deterministic and must run before model processing. Priority
is always displayed with a text label; colour is never the sole signal.

## `ticket_status`

Database type: `ticket_status`.

| Value | Meaning |
| --- | --- |
| `submitted` | The report has been persisted. |
| `acknowledged` | A ticket number has been returned to the resident. |
| `triaging` | Deterministic safety and decision processing is in progress. |
| `awaiting_approval` | A proposed decision requires a human action. |
| `approved` | The required approval record permits the next authorised action. |
| `rejected` | A human rejected the proposal. |
| `dispatched` | An authorised work order or vendor dispatch was initiated. |
| `in_progress` | Work is actively being performed. |
| `resolved` | Work is reported complete and awaits any closing checks. |
| `closed` | The ticket lifecycle is complete. |
| `escalated` | The workflow requires human intervention outside the normal path. |
| `cancelled` | The ticket was ended without resolution. |

## `responsible_party`

Database type: `responsible_party`.

| Value | Meaning |
| --- | --- |
| `owner` | The property owner or operator is responsible for the outcome or cost. |
| `resident` | The resident is the proposed responsible party. |
| `vendor` | An external vendor is the proposed responsible party. |
| `undetermined` | Evidence is insufficient to assign responsibility. |

## `trade`

Database type: `trade`.

| Value | Meaning |
| --- | --- |
| `general_maintenance` | General maintenance work. |
| `plumbing` | Plumbing work. |
| `electrical` | Electrical work. |
| `hvac` | Heating, ventilation, and air-conditioning work. |
| `appliance` | Appliance work. |
| `pest_control` | Pest-control work. |
| `restoration` | Damage-restoration work. |
| `roofing` | Roofing work. |
| `locksmith` | Lock and access work. |
| `other` | A trade outside the enumerated set; requires an explicit explanation. |

## `reject_reason`

Database type: `reject_reason`.

| Value | Meaning |
| --- | --- |
| `insufficient_evidence` | The proposal lacks adequate supported evidence. |
| `incorrect_priority` | The proposed priority is incorrect. |
| `incorrect_routing` | The proposed trade, vendor, or routing is incorrect. |
| `cost_or_scope` | The proposed cost or scope is unsuitable. |
| `policy_conflict` | The proposal conflicts with controlling policy. |
| `other` | A reason outside this taxonomy; accompanying free-text rationale is required. |

## `decision_mode`

Database type: `decision_mode`.

| Value | Meaning |
| --- | --- |
| `auto` | Deterministic validation permits the configured automatic path. |
| `approval_required` | A human approval is required before any side effect. |
| `abstain` | The system cannot make a supported proposal. |
| `escalate` | The outcome must be routed to a human or safety path. |

`auto` never grants an agent write authority. Only the orchestrator may execute
an approved, scoped action.

## `guardrail`

Database type: `guardrail_kind`.

| Value | Meaning |
| --- | --- |
| `tenant_authorisation` | Tenant scope or principal authorisation check. |
| `rate_limit` | Request-rate or quota check. |
| `payload_size` | Request or attachment size check. |
| `pii_redaction` | PII detection and redaction check. |
| `prompt_injection` | Untrusted-content instruction-injection check. |
| `content_safety` | Harmful or abusive-content check. |
| `schema_validation` | Typed input or output schema check. |
| `citation_verification` | Citation existence and source-span check. |
| `numeric_sanity` | Numeric range, unit, or arithmetic check. |
| `policy_compliance` | Deterministic policy-precedence check. |
| `fair_housing` | Housing-equity and accessibility policy check. |
| `output_pii` | Outbound PII exposure check. |
| `grant_scope` | Server-side tool-grant and approval-token scope check. |
| `idempotency` | Mutation replay-protection check. |
| `cost_budget` | Model or organisation cost-budget check. |
| `latency_budget` | Request or workflow latency-budget check. |

Guardrail stage and outcome are separate database types (`guardrail_stage` and
`guardrail_outcome`); they are not substitutes for a `guardrail` value.

## `notification_tier`

Database type: `notification_tier`.

| Value | Meaning |
| --- | --- |
| `u0` | Notification tier zero. |
| `u1` | Notification tier one. |
| `u2` | Notification tier two. |
| `u3` | Notification tier three. |

The deterministic notification state machine will define eligibility, timing,
channel, retry, and escalation semantics in Phase 4. A model never selects a
notification tier or initiates delivery.

## `role`

Database type: `app_role`.

| Value | Meaning |
| --- | --- |
| `resident` | Apartment resident. |
| `property_manager` | Property-management staff member. |
| `maintenance_technician` | In-house maintenance staff member. |
| `vendor_contact` | External vendor contact. |
| `asset_owner` | Owner-side operational stakeholder. |
| `operations_admin` | Restricted operations and ML-administration user. |

Roles do not replace route-level authorisation or Postgres RLS. The `roles.scope`
field separately specifies organisation or property scope.

## `authority`

Database type: `authority`.

| Value | Precedence |
| --- | --- |
| `statute` | 1 — highest |
| `lease` | 2 |
| `internal_sop` | 3 |
| `vendor_contract` | 4 — lowest |

This precedence is deterministic: `statute` > `lease` > `internal_sop` >
`vendor_contract`.

## `failure_kind`

Database type: `failure_kind`.

| Value | Meaning |
| --- | --- |
| `schema_violation` | Typed-schema validation failed. |
| `citation_failure` | Citation verification failed. |
| `retrieval_miss` | Required evidence was not retrieved. |
| `provider_failure` | An external model or integration provider failed. |
| `timeout` | A bounded operation exceeded its time limit. |
| `budget_breach` | A configured cost or resource budget was exceeded. |
| `tool_failure` | A narrow internal tool failed. |
| `guardrail_block` | A guardrail blocked the operation. |
| `authorisation_failure` | Principal, tenant, grant, or approval authorisation failed. |
| `idempotency_conflict` | A repeated mutation conflicts with its original request. |
| `unexpected_error` | An uncategorised internal failure occurred. |

## Change control

Additive enum values require an approved forward migration and a compatibility
review. Existing values are immutable: do not rename, delete, or repurpose them.
During the Phase-0 contract freeze, every vocabulary change must update the
database migration, this document, API and SSE contracts, typed schemas,
fixtures, tests, and release evidence in one change set.
