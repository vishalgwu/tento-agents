# knowledge

The Resident OS **knowledge base**. Markdown-only, front-matter-typed, versioned in git — retrieval reads from here, not from a CMS.

## Layout

```
knowledge/
├── sops/            # Standard operating procedures (SOP-PLM-04, SOP-HVAC-11, ...)
├── policy/          # Lease clauses, chargeback rules, quiet hours, pet policy
├── habitability/    # Per-jurisdiction habitability SLAs (US-VA, US-CA, US-NY, US-TX, US-IL, ...)
├── fair-housing/    # Protected-class guidance, ADA reasonable accommodation, redlined phrases
└── vendor/          # Vendor SOPs, trade skill matrix, warranty databases
```

Every document has front matter:

```yaml
---
id: SOP-PLM-04
title: Recurring drain failure — escalation to trap replacement
version: 3
effective_from: 2026-01-01
jurisdictions: [US-*]
tags: [plumbing, drain, chargeback]
---
```

## Why markdown-in-git

- Retrieval provenance survives PR review — you can `git blame` a citation.
- No embedding blob is ever authoritative for a policy. The chunk in the vector store points back to a versioned document ID.
- Effective dates + jurisdictions are structured columns on ingest, not a summarizer's guess.

## Owner

Track **A** per [PHASES.md](../../docs/PHASES.md). The MVP target is 12 real SOP/policy documents by end of Week 2.

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../README.md)
