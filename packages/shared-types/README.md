# Shared API types

`src/api.generated.ts` is generated from the repository's canonical
[`docs/openapi.yaml`](../../docs/openapi.yaml) contract with
[openapi-typescript](https://openapi-ts.dev/). It is checked into source control
so consumers can build from a reproducible contract snapshot.

From the repository root, run:

```powershell
pnpm generate:api
```

Do not edit `src/api.generated.ts` or create a second handwritten interface that
mirrors a backend model. Change `docs/openapi.yaml`, regenerate, review the diff,
and update the consuming code in the same change. `src/index.ts` is the stable
public package entry point.
