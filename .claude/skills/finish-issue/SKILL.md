---
name: finish-issue
description: Finish an FVR issue end to end - verify tests and lint, check every acceptance criterion, write the summary, commit, and open the PR titled "FVR-__: ...". Use when the work for an issue is implemented and the agent is about to hand it over.
---

# finish-issue

Run this before declaring any FVR issue done. Do the steps in order; stop and
report instead of skipping one.

## 1. Everything green

```bash
scripts/check.sh
```

It must exit 0. If it fails, fix the code or the test that is wrong. Never
weaken a security limit, delete a failing test, or mark it skipped to get
green (CLAUDE.md rule 9). If `api/` or `web/` has code, run its focused
commands too so warnings are visible:

```bash
cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
cd web && npm run lint && npm run typecheck && npm test
```

## 2. Acceptance criteria

Re-read the issue text. For each acceptance criterion write one line:
`[x] criterion - how it is verified (test name, command, or file)`. A
criterion with no test or command behind it is not met. If a criterion
cannot be met inside the folders the issue names, say so; do not touch the
other side (rule 4).

## 3. Rules check

Confirm, and say so explicitly in the summary:

- `contract_events` has no UPDATE/DELETE anywhere in the diff (rule 1).
- No secrets, tokens, real emails, or PDF bytes in code, tests, fixtures, or logs (rules 2, 6).
- Every new env var is in `.env.example` (rule 2).
- `openapi.yaml` unchanged, or changed in its own commit that says why (rule 5).
- `SPEC.md` still true; if the work revealed a spec gap, the spec is updated in this PR (rule 10).
- Migrations, if any, have an upgrade/downgrade test (rule 3).

## 4. Summary

Write the PR body in this shape (it is also the final message to the user):

```
## What changed
- ...

## How it was tested
- scripts/check.sh: pass (api: N tests, web: M tests)
- ...

## Deviations from SPEC.md / openapi.yaml
- none | describe

## New environment variables
- none | NAME=placeholder (added to .env.example)

## Acceptance criteria
- [x] ... - verified by ...
```

## 5. Commit and PR

```bash
git status                              # only intended files; no .env, no lockfile noise you did not mean
git add <files>
git commit -m "FVR-<n>: <imperative subject under 72 chars>" -m "<why, not what>"
git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
gh pr create --title "FVR-<n>: <subject>" --body-file <summary file>
```

The branch name and the PR title both start with the ticket id. One PR per
issue. If the issue id is unknown, ask rather than inventing one.
