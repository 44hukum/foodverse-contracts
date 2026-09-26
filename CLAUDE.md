# CLAUDE.md — rules for every agent working in foodverse-contracts

This repo is **Contract Signing v1**: an internal Foodverse tool for sending
onboarding contracts (PDFs) to hotels and restaurants and collecting
e-signatures with a full audit trail. Read `SPEC.md` for behaviour and
`openapi.yaml` for the HTTP contract before touching anything.

## Stack

| Layer     | Choice                                                            |
|-----------|-------------------------------------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy 2 (2.0-style, typed), Alembic    |
| Database  | PostgreSQL 16                                                     |
| Storage   | S3-compatible object storage (MinIO locally, S3 in production)    |
| Backend tests | pytest, pytest-asyncio, httpx `AsyncClient` against the app   |
| Frontend  | React 18, TypeScript (strict), Vite                               |
| Frontend tests | Vitest + React Testing Library                               |
| Tooling   | `uv` for Python deps and venvs, `npm` for the web app, `docker compose` for Postgres + MinIO |

Do not introduce another ORM, HTTP framework, state library, CSS framework,
or package manager without an issue that asks for it.

## Folder layout

```
.
├── SPEC.md            product and technical spec (source of truth for behaviour)
├── openapi.yaml       HTTP contract (source of truth for request/response shapes)
├── CLAUDE.md          this file
├── .env.example       every environment variable the system reads, with safe defaults
├── docker-compose.yml local Postgres + MinIO (to be added with the first api/ scaffold)
├── api/               FastAPI backend
│   ├── app/           application package (routers, services, models, schemas)
│   ├── alembic/       migrations
│   ├── tests/         pytest suite
│   └── pyproject.toml
├── web/               React + TypeScript + Vite frontend
│   ├── src/
│   └── package.json
└── docs/              ADRs, runbooks, diagrams. Anything longer than a code comment.
```

Backend code lives only under `api/`, frontend code only under `web/`. Shared
documentation goes in `docs/`. Nothing at the repo root except config and
the three spec files above.

## How to run

These are the canonical commands. When you scaffold `api/` or `web/`, make
these exact commands work; do not invent alternatives.

```bash
# infrastructure (Postgres on 5432, MinIO on 9000/9001)
cp .env.example .env            # first time only, then edit
docker compose up -d db minio

# backend
cd api
uv sync                         # installs deps into api/.venv
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# frontend
cd web
npm install
npm run dev                     # http://localhost:5173
```

## How to test

```bash
# backend — must pass before any PR
cd api
uv run pytest                   # full suite, uses a throwaway Postgres schema
uv run pytest -x -k "signing"   # focused run
uv run ruff check . && uv run ruff format --check . && uv run mypy app

# frontend — must pass before any PR
cd web
npm test                        # vitest, single run
npm run lint
npm run typecheck               # tsc --noEmit
```

Backend tests run against a real PostgreSQL (from `docker compose`), not
SQLite. Object storage is faked in tests with an in-memory implementation
behind the same interface used in production. Email is faked the same way.

## Rules

These are not suggestions. If an issue seems to require breaking one, stop
and say so in your PR or comment instead of breaking it.

1. **`contract_events` is append-only.** Never write an `UPDATE` or `DELETE`
   against it, in application code, in migrations, in tests, or in ad-hoc
   SQL. The app's database role has no update/delete grant on that table and
   a trigger rejects them; do not remove either. If an event was wrong, write
   a new event that says so.
2. **No secrets in code.** Credentials, API keys, signing keys, and hostnames
   that differ per environment come from environment variables. `.env` is
   git-ignored; `.env.example` must list every variable with a safe
   placeholder. If you add a variable, add it to `.env.example` in the same
   commit. Never commit a real `.env`, and never paste real values into
   tests, fixtures, or docs.
3. **Every change needs tests.** A behaviour change without a test that
   fails before and passes after is not done. Bug fixes include a regression
   test. Migrations include a test that upgrades and downgrades cleanly.
4. **Stay inside the folders your issue names.** If your issue is about
   `api/`, do not touch `web/`, and vice versa. If you need something from
   the other side, describe it in the PR and stop; a separate issue will
   cover it. Root-level files (`SPEC.md`, `openapi.yaml`, `CLAUDE.md`,
   `.env.example`, compose file) are shared and changes to them must be
   called out explicitly in the PR description.
5. **`openapi.yaml` is the contract.** Backend routes and frontend clients
   are implemented to match it, not the other way round. If the work cannot
   be done without changing the contract, say so in the PR (what changes and
   why), make the change to `openapi.yaml` in its own clearly-labelled
   commit, and never let the implementation drift from the file silently.
   Run `npx --yes @redocly/cli lint openapi.yaml` after any edit.
6. **Signing tokens are never stored, logged, or returned to admins.** Only
   `sha256(token)` is persisted. Tokens appear in exactly two places: the
   email to the signer and the public URL path.
7. **PDF bytes are never streamed by the API.** Downloads go through
   short-lived pre-signed storage URLs only. The bucket is private.
8. **Status changes are conditional and evented.** Every transition uses
   `UPDATE ... WHERE status IN (...)` and writes exactly one
   `contract_events` row in the same transaction. Invalid transitions return
   `409 invalid_state`.
9. **Do not weaken security limits** (token length, expiry bounds, upload
   size, PNG validation, rate limits) to make a test pass. Fix the test.
10. **Keep `SPEC.md` honest.** If you discover the spec is wrong or
    ambiguous, open the question in the PR and update the spec in the same
    PR once resolved. Code that contradicts the spec is a bug in one of them.

## Conventions

- Python: `ruff` for lint and format, `mypy --strict` on `app/`. Type
  annotate everything. Async SQLAlchemy sessions. Pydantic v2 schemas
  mirror `openapi.yaml` names one-to-one (`ContractDetail`,
  `SubmitSignatureRequest`, ...).
- TypeScript: `strict: true`, no `any`. API types are generated from
  `openapi.yaml` (`npm run generate:api`), never hand-written.
- Timestamps are UTC `timestamptz` in the database and RFC 3339 strings on
  the wire. Never use naive datetimes.
- IDs are UUIDv4 except `contract_events.id`, which is `bigserial`.
- Error responses always use the `Error` schema from `openapi.yaml`.
- Commits: imperative subject under 72 chars, body explains why. Branch
  names and PR titles start with the ticket id (`FVR-12: ...`).
- PR description must list: what changed, how it was tested, any deviation
  from `SPEC.md` or `openapi.yaml`, and any new environment variable.

## Definition of done for an issue

- [ ] Code only in the folders the issue names.
- [ ] Tests added or updated, whole suite green locally.
- [ ] Lint, format, and type checks green.
- [ ] `.env.example` updated if a variable was added.
- [ ] `openapi.yaml` unchanged, or changed in its own commit and called out.
- [ ] No token, secret, or PDF bytes in logs or test fixtures.
- [ ] PR description follows the template above.
