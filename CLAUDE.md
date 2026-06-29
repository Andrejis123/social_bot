# CLAUDE.md

Agent operating notes. The **README.md** and **justfile** are the canonical
sources of truth for how this repo runs and deploys — consult them (and the
recipes in `just --list`) *before* exploring or before trusting memory for an
operational procedure. This file adds agent-specific context only; keep it lean
and don't duplicate what README/justfile already state.

## Working style — align before building, verify after

For any multi-step or ambiguous task, lock scope and architecture with me
*before* writing code: batch your open questions into a **single** round
(AskUserQuestion), propose the design/tradeoffs, and start only once you're ~95%
sure what I want. Small or clearly-specified tasks: just do them — don't
manufacture questions or turn this into an interrogation.

Before marking anything done: exercise the code with **real data**, confirm the
ROOT CAUSE rather than patching a symptom, and show the verification output.
"Tests pass" is not "prod behavior is fixed" — for pipeline/deploy work prefer an
actual run (and `just deploy-check` after a deploy).

**Bug-fix protocol:** investigate and establish root cause first — do not write
code yet. Once root cause is confirmed, invoke `/write-tests` with a description
of the bug and its cause, wait for the subagent to produce a failing test, then
write the fix. Fix only after the failing test exists.

## Deploy — this is routine, I do it directly

I have SSH access to the VPS (key authorized) and run deploys myself. Do **not**
punt the pull/rebuild back to the user.

The VPS cron runs each job from the **built Docker image** `social-bot:latest`
(`docker run ... social-bot python -m scripts.<x>`), so a `git pull` alone does
**not** update running code — **the image must be rebuilt.** Only `config/` is
volume-mounted (YAML/prompt edits need no rebuild); `src/`, `scripts/`,
`assets/`, `migrations/` are baked into the image.

```bash
git push origin main      # from Mac
just deploy               # ssh + git pull + docker compose build on the VPS
just deploy-check         # confirm the new code is actually in the image
```

VPS host + path live in the `deploy` recipe (justfile) and in memory
(`tools_inventory`). Repo path on the VPS is `/opt/social-bot/`.

## Running tooling

- Run Python via `uv run ...` or the project venv `.venv/bin/python` — the
  package isn't on system Python. (`uv run` may warn about a stale
  `Claude_Social/.venv` VIRTUAL_ENV; it still works.)
- `just check` = ruff + mypy + pytest. Lint is green — keep it green.
- Pre-commit hook runs `/security-review` + `/simplify` automatically. Never
  skip with `--no-verify`; fix the underlying issue instead.

## Conventions

- **No Claude branding** on user-visible surfaces (README, pyproject, docs,
  commit messages); omit Co-Authored-By by default. (This file is agent config,
  not a user-visible surface.)
- **No em-dashes** in rendered reports or in synthesis prompts.
- The report-subject brand renders as a verbatim `@handle` in synthesis prose
  and in notifications — never the client name/slug.
- **Date format**: Drive folder names and any other user-visible date strings use
  European convention `DD-MM-YYYY` (e.g. `28-06-2026`), not ISO `YYYY-MM-DD`.

## Memory & todos

- **Todos**: Notion DB `31ff3868-b444-8054-aa56-e3f8db6d8720` (Project = Social_Bot)
  is the canonical task list. Query it directly — do not maintain a parallel list in memory files.
- **Notion API key**: `NOTION_API_TOKEN` in `.env` (loaded via `python-dotenv`).
- **Memory files** (5 total): `project_journal.md` (live state, cron, decisions, session log),
  `feedback.md` (style rules + working preferences), `tools_inventory.md` (APIs + infra),
  `user_profile.md`, `todos.md`.
- **End of session**: update `project_journal.md` (decisions made, files changed); mark
  completed Notion tasks Done via API (token in `.env` as `NOTION_API_TOKEN`).
- **Subagents doing web search/fetch**: prefer `model: haiku` to save tokens.
