---
name: add-endpoint
description: Add or change a FastAPI endpoint in api/ so that it matches openapi.yaml exactly - schema names, status codes, error shape, events, and tests. Use when an issue asks for a new route or a change to an existing one.
---

# add-endpoint

`openapi.yaml` is the contract (CLAUDE.md rule 5). The endpoint is
implemented to match it, never the other way round.

## 1. Read the contract first

```bash
grep -n "<path>" openapi.yaml            # find the operation
```

Note the operationId, path and query parameters, request schema, every
response code, the `Error` schema, and the security scheme (admin bearer or
public token). If the operation is not in `openapi.yaml`, stop: either the
issue expects a contract change (see step 5) or the endpoint should not
exist.

## 2. Implement to the contract

- Router in `api/app/routers/`, one module per tag. Business logic in
  `api/app/services/`; routers stay thin.
- Pydantic v2 schemas in `api/app/schemas/` named one-to-one with the
  contract (`ContractDetail`, `SubmitSignatureRequest`, ...). Do not invent
  extra fields, do not drop required ones.
- Errors always use the `Error` schema with the codes the contract lists.
  Invalid state transitions return `409 invalid_state` (rule 8).
- Status changes use `UPDATE ... WHERE status IN (...)` and write exactly
  one `contract_events` row in the same transaction (rules 1, 8). Never put
  names, emails, IPs, or user agents into `metadata`; IP and user agent go
  to `contract_event_pii`.
- No token, request body, or response body in logs on send or public
  endpoints (rule 6). No PDF bytes through the API; hand out
  `signed_download_url` from the storage backend (rule 7).
- Everything typed; `mypy --strict` must pass.

## 3. Tests (required)

In `api/tests/`, with httpx `AsyncClient` against the app and the real test
database:

- the happy path, asserting the response shape matches the contract schema;
- each documented error code (401/403/404/409/422 as listed);
- the event row(s) written, and that no forbidden PII landed in `metadata`;
- for state changes, a test that the wrong starting status yields
  `409 invalid_state`.

Run `scripts/check.sh` until green.

## 4. Verify against the contract

Fetch `/openapi.json` from the running app in a test (or compare the
generated schema in a test) and assert the operation's path, method,
status codes, and schema names match `openapi.yaml`. Any mismatch is a bug
in the implementation, not in the file.

## 5. If the contract must change

Say so in the PR description (what changes and why). Make the change to
`openapi.yaml` in its own commit titled `FVR-<n>: openapi: <change>`, run
`npx --yes @redocly/cli lint openapi.yaml`, then implement to the new
contract. Never let the implementation drift from the file silently. If
the change also affects `web/`, describe it in the PR and stop; a separate
issue covers the frontend (rule 4).

## 6. Finish

Use the `finish-issue` skill.
