# Knowledge fixtures

These eleven Markdown documents are synthetic retrieval and safety test inputs. They are not live policy, contracts, legal advice, or emergency operating procedures. Keep `status: temporary_fixture` and `production_eligible: false`; never load them into production retrieval.

Each content file carries a stable identifier, immutable version, source URI, effective dates, jurisdiction, and authority. Authority values are `statute`, `lease`, `internal_sop`, and `vendor_contract`. Ingestion validates metadata, hashes content, retains source spans, and rejects ineligible sources.

Files cover plumbing, HVAC, electrical, appliances, emergency response, leases, two jurisdictions, community rules, vendor procedures, and resident FAQs. Evaluation expectations live under `evals/datasets/`.

Replace these fixtures with verified, property-specific source versions before connecting production retrieval. Preserve legal and safety applicability boundaries; generated text must never acquire source authority merely by being indexed.
