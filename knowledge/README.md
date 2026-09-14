# Resident OS temporary knowledge-fixture register

> **Status: evaluation-only project content.** This directory is a temporary
> corpus for product development, retrieval experiments, and tests. It is not
> an approved policy library, signed contract set, legal advice, emergency
> playbook, or source of live operational deadlines. No document in this
> directory may be used to make a resident-, vendor-, or owner-affecting
> decision until its accountable owner has replaced it with verified source
> material and recorded approval in the production knowledge register.

## Why this corpus exists

The project needs stable, realistic-looking documents while the knowledge
ingestion, retrieval, citation, and authorization boundaries are built. These
fixtures let those components be tested without presenting generated text as
truth. They intentionally contain no production approval and must remain
excluded from any live retrieval index.

## Required metadata

Every content file begins with YAML front matter containing the contract fields
below. The ingestion worker must reject a document that omits a required field
or whose `status` is not explicitly eligible for the target environment.

| Field | Purpose |
| --- | --- |
| `id` | Stable human and citation identifier. |
| `version` | Immutable source version, never overwritten in place. |
| `effective_from` / `effective_to` | Period in which that version may be considered. |
| `jurisdiction` | Retrieval filter; it is not a claim that the text is legally complete. |
| `authority` | One of `statute`, `lease`, `internal_sop`, or `vendor_contract`. |
| `status` | Lifecycle gate. All current documents are `temporary_fixture`. |
| `production_eligible` | Must be `false` until a named owner approves a verified replacement. |
| `source_uri` | Traceable source location or explicitly temporary project URI. |

Additional metadata such as `source_owner`, `reviewed_by`, and `reviewed_at`
captures provenance; a `null` review value means **not reviewed**, never
“implicitly approved.”

## Current register

| ID | File | Accountable replacement owner | Intended authority | Current status |
| --- | --- | --- | --- | --- |
| SOP-PLM-04 | `sops/SOP-PLM-04.md` | Maintenance Operations Lead | internal SOP | Temporary fixture |
| SOP-HVAC-01 | `sops/SOP-HVAC-01.md` | HVAC Program Owner | internal SOP | Temporary fixture |
| SOP-ELEC-01 | `sops/SOP-ELEC-01.md` | Electrical Safety Owner | internal SOP | Temporary fixture |
| SOP-APP-01 | `sops/SOP-APP-01.md` | Appliance Program Owner | internal SOP | Temporary fixture |
| SOP-EMG-01 | `emergency/emergency-response.md` | Safety & Incident Lead | internal SOP | Temporary fixture |
| LEASE-VA-2025 | `leases/lease-template.md` | Legal Counsel / Lease Owner | lease | Temporary fixture |
| JUR-VA-STAT-01 | `jurisdiction/us-va-habitability.md` | Virginia Legal Counsel | statute | Temporary research fixture |
| JUR-MD-STAT-01 | `jurisdiction/us-md-habitability.md` | Maryland Legal Counsel | statute | Temporary research fixture |
| POL-COMM-01 | `community/community-rules.md` | Community Operations Owner | internal SOP | Temporary fixture |
| VND-PROC-01 | `vendors/vendor-procedures.md` | Vendor Management Owner | vendor contract | Temporary fixture |
| FAQ-RES-01 | `resident/resident-faq.md` | Resident Communications Owner | internal SOP | Temporary fixture |

The original build brief labels this set “twelve” documents but enumerates
eleven content categories/files. This register intentionally preserves the
eleven requested fixtures. A product owner must define and source any twelfth
document rather than adding plausible content solely to meet a count.

## Responsibilities and handoff

| Role | Accountabilities | Explicit limits |
| --- | --- | --- |
| Knowledge steward | Validates metadata/schema, hashes/version-registers accepted sources, runs injection screening, and retains source spans. | Cannot approve policy, law, lease, vendor terms, or operational actions. |
| Policy owner | Replaces and approves operational SOPs and community policy with a review date. | Cannot convert legal research into legal advice. |
| Legal counsel / lease owner | Supplies current jurisdictional materials and executed lease excerpts; validates applicability and effective dates. | Must not approve a synthetic summary as a legal source. |
| Safety & incident lead | Approves emergency language and escalation boundaries. | Must not turn this app into an emergency dispatcher without a separately approved process. |
| Vendor manager | Supplies signed vendor obligations and contact/access procedures. | Must not expose credentials, keys, IDs, or unnecessary resident data. |
| Retrieval worker | Filters by tenant, status, jurisdiction, authority, and effective date; returns spans with citations and abstains on missing evidence. | Cannot send messages, open tickets, approve work, or invoke tools. |
| Orchestrator / authorized human | Reviews an evidence-backed proposal and records authorization before any side effect. | Must block all real outbound transport in demo mode. |

## Production promotion checklist

Before a replacement can be indexed outside evaluation:

1. The accountable owner supplies an authoritative source, a stable source URI,
   and the complete applicable text or licensed record.
2. Legal and safety material receives the required domain review; a project
   developer review is not enough.
3. The steward assigns a new immutable version, content hash, effective window,
   jurisdiction, authority, and reviewer record. The temporary file stays
   retained for test reproducibility.
4. Retrieval evaluates provenance, scope, citation spans, conflict precedence
   (`statute` > `lease` > `internal_sop` > `vendor_contract`), and abstention.
5. A human authorizes the production-index change. Fixture documents remain
   excluded from production regardless of retrieval score.
