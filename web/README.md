# web — admin UI for Contract Signing v1

React 18 + TypeScript (strict) + Vite. API types are generated from the
repo-root `openapi.yaml`; nothing is hand-modelled.

```bash
npm install
npm run dev          # real backend at VITE_API_BASE_URL (from the repo-root .env)
npm run dev:mock     # no backend: MSW intercepts the API in the browser
npm test             # vitest, single run
npm run test:e2e     # playwright happy path against the MSW mocks (needs `npx playwright install chromium`)
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
  util/       date formatting (Asia/Kathmandu + UTC), validation, errors
  mocks/      MSW handlers + fixture data (browser worker and node server)
  pages/      Login, ContractList, CreateContract, ContractDetail
  sign/       public /sign/:token page: PDF review, signature pad, consent, error states
  test/       vitest setup and render helpers
e2e/          Playwright happy path for the signing page (375px viewport, MSW mocks)
```

## Signing page in mock mode

The mock resolves the fixture tokens in `src/sign/mocks/data.ts` (one per
contract state) and any token issued by the mock send endpoint during the
same session. Open `/sign/<token>` in `npm run dev:mock` to see each state.
No PDF bytes are served in mock mode; the preview frame shows a placeholder.
