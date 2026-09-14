# Resident OS web foundation

This is the Next.js 15 App Router foundation for the five public role surfaces:

| Route | Audience | Current boundary |
| --- | --- | --- |
| `/app` | Resident | Read-only route shell; ticket creation waits for a documented mutation contract. |
| `/manage` | Property manager | Evidence and decision-provenance component demonstration; no live dispatch. |
| `/owner` | Asset owner | No metrics until a reproducible evaluation defines them. |
| `/tech` | Maintenance technician | No active-job reads or work-status mutation. |
| `/v/[token]` | External vendor | Server-verified, expiring, no-account HMAC link. |

`/resident/sign-in` models resident magic-link access; `/staff/sign-in` models
password plus TOTP staff access. Both forms are deliberately disabled until the
identity-provider and API contracts include tenant membership validation, rate
limits, session handling, auditing, and recovery behaviour. They do not submit
credentials, send email, or create a session.

## Commands

Run these from the repository root:

```powershell
pnpm install
pnpm generate:api
pnpm typecheck:web
pnpm build:web
pnpm dev:web
```

The `web-quality.yml` workflow installs from `pnpm-lock.yaml`, audits production
dependencies at the high-severity threshold, verifies that OpenAPI generation is
current, type-checks, and builds the production bundle on every relevant pull
request and change to `main`.

## Vendor link contract

`lib/vendor-link.ts` accepts only the server-side format
`base64url(payload).base64url(HMAC-SHA-256(payload))`. Payload JSON must include
non-empty `workOrderId` and `vendorId` strings plus a future integer `expiresAt`
(Unix seconds). The verifier checks canonical base64url encodings, compares the
32-byte HMAC in timing-safe fashion, and fails closed if
`VENDOR_LINK_SIGNING_SECRET` is absent, invalid, tampered, or expired.

Only a future authorised dispatch service may create links. The vendor route never
creates a session and currently renders only the signed claim references. Do not
place the signing secret in `NEXT_PUBLIC_*`, browser code, logs, or a link.

## UI and data rules

- Use `@resident-os/shared-types` for all API-shaped types. Regenerate it from
  `docs/openapi.yaml`; never edit `api.generated.ts` by hand.
- Use `@resident-os/ui` for the status lamp, evidence rail, and decision marker.
  The status lamp and decision marker supply text as well as colour, and the
  evidence rail supports pointer and keyboard interaction in both directions.
- Use the existing shadcn primitives in `components/ui` for ordinary controls.
- Keep server-only code such as HMAC verification out of Client Components.
