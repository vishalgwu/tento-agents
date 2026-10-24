# Product delivery map

The main application is Tento Resident OS: one project overview and a shared entry point for four verified workspaces. See RELEASE-STATUS.md for deployment evidence and PRODUCT.md for the capability boundary.

## Current application

- Home: product purpose, live maintenance workflow and workspace sign-in choices.
- Resident: authorized residence selection, saved reports, history and agent results.
- Maintenance: read-only organization request queue and saved assessments.
- Owner: read-only maintenance overview over authorized organization records.
- Technical administrator: organization-scoped requests, agent outcomes and service readiness.

The API verifies account identity before issuing a workspace session. A workspace selector never grants roles. Existing tenant RLS remains authoritative. There is no self-service registration or role promotion.

## Remaining product work

Approved policy evidence is required before policy-backed work orders can be accepted. Repair assignment/status editing, owner finance, portfolio management, user provisioning, media, vendor scheduling and outbound notifications are not implemented. Add these only through explicit product scope, real APIs and permission checks; do not create pretend controls or demo dashboards.

## Removed misleading scaffolding

Unused vendor-link page and signing helper; unused shared decorative UI package; unused badge/separator components; redirects that disguised owner and maintenance pages as resident pages; obsolete vendor/media credential suggestions. Database history, applied migrations and functioning AI/safety/retrieval logic remain intact.
