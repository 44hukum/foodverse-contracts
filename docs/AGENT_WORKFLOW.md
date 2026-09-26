# Agent workflow

How a worker (human or agent) takes an FVR issue from ticket to merged PR in
this repo. One page; the rules themselves live in `CLAUDE.md`.

## The loop

```
issue -> worktree -> init -> implement -> check -> finish -> PR -> review -> merge
```

1. **Pick up an issue.** Every unit of work is an FVR ticket. The issue
   names the folders it may touch (`api/`, `web/`, or root/tooling). Work
   outside those folders is a separate issue.
2. **Branch in a worktree.** Branch name starts with the ticket id
   (`<user>/fvr-14-...`). Each worktree is isolated: its own `.env`, its own
   database, its own ports, its own `.local-storage/` folder.
3. **Initialise.** Run `scripts/worktree-init.sh` (Orca runs it as the
   post-create hook with `ORCA_ROOT_PATH` set). It copies `.env` from the
   root checkout, derives `foodverse_contracts_<branch>` and an `API_PORT`
   / `WEB_PORT` offset, creates the databases with `createdb` on native
   Postgres, installs deps, and migrates. Re-running is safe.
4. **Read before writing.** `CLAUDE.md` for rules, `SPEC.md` for behaviour,
   `openapi.yaml` for shapes. For an endpoint, use the `add-endpoint`
   skill.
5. **Implement with tests.** Every behaviour change ships with a test that
   fails before and passes after. Migrations ship with an upgrade/downgrade
   test.
6. **Check.** `scripts/check.sh` runs ruff, mypy, pytest, lint, typecheck,
   and vitest for whichever parts have code. It is the same command CI
   runs. The Stop hook in `.claude/settings.json` runs it whenever the
   agent tries to finish a turn and blocks with the failure output (exit 2)
   until it passes, so an agent cannot hand over a red suite. The hook
   honours `stop_hook_active` so it never loops on itself, and it is a
   no-op while `api/` and `web/` are empty.
7. **Finish.** Use the `finish-issue` skill: check every acceptance
   criterion against a test or command, confirm the rules checklist, write
   the summary, commit with an imperative subject, push, and open one PR
   titled `FVR-<n>: ...` whose body lists what changed, how it was tested,
   deviations from spec or contract, and new env vars.
8. **Review and merge.** CI (`.github/workflows/ci.yml`) runs
   `scripts/check.sh` against a Postgres 16 service container on GitHub's
   machines with uv and npm caches. A reviewer merges; the worker never
   merges their own PR.

## Guardrails the tooling enforces

| Guardrail                                     | Where                                   |
|-----------------------------------------------|-----------------------------------------|
| Cannot finish with failing tests or lint      | Stop hook -> `scripts/check.sh`         |
| Same checks locally and in CI                 | `scripts/check.sh` is the only entry    |
| Agent never reads `.env`, lockfiles, `node_modules`, `.venv`, `dist` | `permissions.deny` in `.claude/settings.json` |
| Routine commands run without prompts          | `permissions.allow` (pytest, ruff, uv, npm test/lint, alembic, createdb, git status/diff/add/commit/push, gh pr create) |
| One DB and port set per branch                | `scripts/worktree-init.sh`              |
| No Docker in local dev                        | native Postgres + Mailpit via Homebrew; `STORAGE_BACKEND=local` |

## When to stop and ask

- The issue needs a change to `openapi.yaml`, `SPEC.md`, or `CLAUDE.md`
  that it does not mention.
- Meeting a criterion would break a rule in `CLAUDE.md`.
- The work needs the other side (`api/` vs `web/`).
- A test can only pass by weakening a security limit.

Say what is blocked and why in the PR or comment, deliver the rest.
