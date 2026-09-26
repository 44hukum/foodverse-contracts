# CLAUDE.md — rules for every agent working in foodverse-contracts

This repo is **Contract Signing v1**: a standalone Foodverse tool for sending
onboarding contracts (PDFs) to hotels and restaurants and collecting
e-signatures with a full audit trail. It is independent of every other
Foodverse service: own admin accounts, own database, own bucket, and SMTP as
the only outbound integration. Read `SPEC.md` for behaviour and
`openapi.yaml` for the HTTP contract before touching anything.

## Stack

| Layer     | Choice                                                            |
|-----------|-------------------------------------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy 2 (2.0-style, typed), Alembic    |
| Database  | PostgreSQL 16                                                     |
| Storage   | Two backends behind one interface, chosen by `STORAGE_BACKEND`: `local` (a private folder; default for dev and tests) and `s3` (S3-compatible; production) |
| Backend tests | pytest, pytest-asyncio, httpx `AsyncClient` against the app   |
| Frontend  | React 18, TypeScript (strict), Vite                               |
| Frontend tests | Vitest + React Testing Library                               |
| Auth      | Own `admins` table, argon2id passwords (`argon2-cffi`), HS256 JWT (`PyJWT`) |
| Email     | Plain SMTP via the standard library `smtplib` / `email`. No provider SDKs. |
| Tooling   | `uv` for Python deps and venvs, `npm` for the web app, Homebrew for native Postgres 16 and Mailpit. **No Docker anywhere in local dev.** |

Do not introduce another ORM, HTTP framework, state library, CSS framework,
or package manager without an issue that asks for it.

## Folder layout

```
.
├── SPEC.md            product and technical spec (source of truth for behaviour)
├── openapi.yaml       HTTP contract (source of truth for request/response shapes)
├── CLAUDE.md          this file
├── .env.example       every environment variable the system reads, with safe defaults
├── scripts/           worktree-init.sh, check.sh, hooks/ (shared dev tooling, bash only)
├── .github/workflows/ ci.yml (runs scripts/check.sh against a Postgres service container)
├── .claude/           settings.json (permissions + Stop hook) and skills/
├── api/               FastAPI backend
│   ├── app/           application package (routers, services, models, schemas, cli)
│   ├── alembic/       migrations
│   ├── tests/         pytest suite
│   └── pyproject.toml
├── web/               React + TypeScript + Vite frontend
│   ├── src/
│   └── package.json
└── docs/              ADRs, runbooks, diagrams. Anything longer than a code comment.
```

Backend code lives only under `api/`, frontend code only under `web/`. Shared
documentation goes in `docs/`. Nothing at the repo root except config, the
three spec files above, and the tooling folders (`scripts/`, `.github/`,
`.claude/`).

## How to run

These are the canonical commands. When you scaffold `api/` or `web/`, make
these exact commands work; do not invent alternatives.

```bash
# infrastructure: native services from Homebrew, no Docker
brew install postgresql@16 mailpit
brew services start postgresql@16          # Postgres on localhost:5432
brew services start mailpit                # SMTP on 1025, web UI on http://localhost:8025

# per-checkout setup (idempotent; safe to re-run). Copies .env, derives a
# per-branch database name and port offset, creates the database, points
# STORAGE_BACKEND=local at a per-worktree folder, installs deps, migrates.
scripts/worktree-init.sh
set -a; source .env; set +a                # export API_PORT / WEB_PORT etc. into your shell

# backend
cd api
uv sync                         # installs deps into api/.venv
uv run alembic upgrade head
uv run python -m app.cli create-admin --email you@example.com --name "You"   # prompts for password
uv run uvicorn app.main:app --reload --port "${API_PORT:-8000}"

# other admin CLI commands (never expose these as HTTP endpoints)
uv run python -m app.cli reset-admin-password --email you@example.com
uv run python -m app.cli deactivate-admin --email you@example.com
uv run python -m app.cli run-retention          # the daily job, runnable by hand

# frontend
cd web
npm install
npm run dev                     # http://localhost:${WEB_PORT:-5173}
```

Files uploaded in dev land in `LOCAL_STORAGE_DIR` (git-ignored, one folder
per worktree). Set `STORAGE_BACKEND=s3` and the `S3_*` variables only for a
production-like run; nothing in local dev needs it.

## How to test

```bash
# everything, exactly as CI runs it (skips api/ or web/ if that part has no code yet)
scripts/check.sh

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

Backend tests run against a real PostgreSQL (native, on localhost; a
service container in CI), not SQLite. Storage in tests uses the `local`
backend pointed at a throwaway temp folder, behind the same interface as
`s3` in production; the `s3` backend is unit-tested with a stub client and
never with a real bucket. SMTP is faked with an in-memory outbox; never hit
a network mail server from tests. The Stop hook in `.claude/settings.json`
runs `scripts/check.sh` before an agent can finish a turn, so a red suite
blocks the agent, not the reviewer.

## Rules

These are not suggestions. If an issue seems to require breaking one, stop
and say so in your PR or comment instead of breaking it.

1. **`contract_events` is append-only.** Never write an `UPDATE` or `DELETE`
   against it, in application code, in migrations, in tests, or in ad-hoc
   SQL. The app's database role has no update/delete grant on that table and
   a trigger rejects them; do not remove either. If an event was wrong, write
   a new event that says so. Personal data attached to an event (IP, user
   agent) lives in `contract_event_pii`, which only the retention job may
   delete from; that is how anonymization works without touching the log.
   Never put names, emails, IPs, or user agents into `metadata`.
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
   `.env.example`, `.gitignore`, `scripts/`, `.github/`, `.claude/`) are
   shared and changes to them must be called out explicitly in the PR
   description.
5. **`openapi.yaml` is the contract.** Backend routes and frontend clients
   are implemented to match it, not the other way round. If the work cannot
   be done without changing the contract, say so in the PR (what changes and
   why), make the change to `openapi.yaml` in its own clearly-labelled
   commit, and never let the implementation drift from the file silently.
   Run `npx --yes @redocly/cli lint openapi.yaml` after any edit.
6. **Signing tokens are never stored or logged.** Only `sha256(token)` is
   persisted. The raw token appears in exactly three places: the send
   response (once, never in list or get), the email to the signer, and the
   public URL path. Do not log request or response bodies on the send or
   public endpoints. The web app shows the link in a copy box, never as a
   clickable anchor, and never passes it to analytics.
7. **PDF bytes are never streamed by API endpoints.** Downloads go through
   short-lived signed URLs from the storage backend only. With `s3` that is
   a pre-signed bucket URL and the bucket is private. With `local` the
   backend itself mounts one HMAC-signed, expiring download route
   (SPEC.md §6, "Storage backends"); it is not an API endpoint, it refuses
   to start when `ENVIRONMENT=production`, and no other route may read from
   `LOCAL_STORAGE_DIR`. Never bypass the storage interface from a router.
8. **Status changes are conditional and evented.** Every transition uses
   `UPDATE ... WHERE status IN (...)` and writes exactly one
   `contract_events` row in the same transaction. Invalid transitions return
   `409 invalid_state`.
9. **Do not weaken security limits** (token length, expiry bounds, upload
   size, PNG validation, rate limits, argon2 parameters, JWT lifetime) to
   make a test pass. Fix the test.
10. **Keep `SPEC.md` honest.** If you discover the spec is wrong or
    ambiguous, open the question in the PR and update the spec in the same
    PR once resolved. Code that contradicts the spec is a bug in one of them.
11. **Admin accounts are created only by CLI.** No signup endpoint, no
    password-reset endpoint, no default admin baked into migrations or
    seeds. Passwords are read interactively, never from flags or env vars,
    and only ever stored as argon2id hashes.
12. **Email is plain SMTP.** Use `smtplib` behind the project's mailer
    interface. Do not add SendGrid, SES, Postmark, or any other provider
    SDK. Attach the signed PDF when it is at or under
    `EMAIL_MAX_ATTACHMENT_BYTES`; otherwise include a pre-signed link with
    `EMAIL_DOWNLOAD_LINK_TTL_HOURS`.
13. **Retention is deletion of PII, never of the audit log.** Signed
    contracts are never auto-deleted in v1. For unsigned contracts the
    retention job nulls signer name/email and deletes `contract_event_pii`
    rows after 90 days. Do not extend it to delete anything else without a
    spec change (see SPEC.md §9, framed on Nepal's Individual Privacy Act
    2075).
14. **Human-facing timestamps show Asia/Kathmandu and UTC.** Certificate
    page, emails, and admin UI render both. Storage and the API stay UTC.
15. **Legal text is versioned.** The consent text and certificate wording
    are `v0-draft`. Changing them means a new version string in config and
    a note in the PR; old versions stay recognisable in the audit trail.

## Conventions

- Python: `ruff` for lint and format, `mypy --strict` on `app/`. Type
  annotate everything. Async SQLAlchemy sessions. Pydantic v2 schemas
  mirror `openapi.yaml` names one-to-one (`ContractDetail`,
  `SubmitSignatureRequest`, ...).
- TypeScript: `strict: true`, no `any`. API types are generated from
  `openapi.yaml` (`npm run generate:api`), never hand-written.
- Timestamps are UTC `timestamptz` in the database and RFC 3339 strings on
  the wire. Never use naive datetimes. Convert to `DISPLAY_TIMEZONE` only at
  the rendering edge (PDF stamping, email templates, React components).
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
