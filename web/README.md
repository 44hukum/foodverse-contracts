# web — admin UI for Contract Signing v1

React 18 + TypeScript (strict) + Vite. API types are generated from the
repo-root `openapi.yaml`; nothing is hand-modelled.

```bash
npm install
npm run dev          # real backend at VITE_API_BASE_URL (from the repo-root .env)
npm run dev:mock     # no backend: MSW intercepts the API in the browser
npm test             # vitest, single run
npm run lint
npm run typecheck
npm run generate:api # regenerate src/api/schema.d.ts after openapi.yaml changes
```

## Mock mode

`npm run dev:mock` starts Vite in mode `mock`, which boots the MSW service
worker (`public/mockServiceWorker.js`) with the handlers in `src/mocks/`.
The same handlers back the Vitest suite. Log in with the credentials in
`src/mocks/data.ts` (`admin@example.com`, `mock-only-password`); they exist
nowhere else. The mock issues a fresh random signing token on every send and
never persists it, mirroring the real API.

## Layout

```
src/
  api/        generated schema, typed fetch client, named aliases
  auth/       in-memory session (SPEC.md §4), provider, route guard
  components/ status badge, dual-timezone time, copy box, layout
  lib/        date formatting (Asia/Kathmandu + UTC), validation, errors
  mocks/      MSW handlers + fixture data (browser worker and node server)
  pages/      Login, ContractList, CreateContract, ContractDetail
  test/       vitest setup and render helpers
```

`src/sign/` (the signer-facing page) is a separate issue and is not part of
this app's routes yet.
