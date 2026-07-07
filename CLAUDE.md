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
  package isn't on system Python. (`VIRTUAL_ENV` is pinned to the project
  `.venv` in `.claude/settings.json`, so the stale-`Claude_Social/.venv`
  warning is gone from new sessions.)
- `just check` = ruff + mypy + pytest. Lint is green — keep it green.
- Commits go through `/commit-session` (git-guard blocks raw `git commit`); its
  `full` level runs `/code-review medium --fix` + `/security-review`. Never
  skip with `--no-verify`; fix the underlying issue instead.
- **When a protocol calls for a skill (`/security-review`, `/code-review`,
  `/write-tests`), you MUST invoke the actual Skill tool** — the one that spawns
  its sub-agents. Never hand-write the analysis inline and present it as if the
  skill ran. Faking a skill step is a serious integrity failure, worse than the
  shortcut itself. If a skill genuinely can't run, say so; don't fabricate output.

## Conventions

- **No Claude branding** on user-visible surfaces (README, pyproject, docs,
  commit messages); omit Co-Authored-By by default. (This file is agent config,
  not a user-visible surface.)
- **No em-dashes** in rendered reports or in synthesis prompts.
- The report-subject brand renders as a verbatim `@handle` in synthesis prose
  and in notifications — never the client name/slug.
- **Date format**: Drive folder names and any other user-visible date strings use
  European convention `DD-MM-YYYY` (e.g. `28-06-2026`), not ISO `YYYY-MM-DD`.

## Deleting scraped content — storage-first, then sweep (data-integrity invariant)

Supabase Storage has **no FK cascade from Postgres**: deleting a `media`/`story_media`/
`posts`/`stories` row does **not** delete its bucket object. Because every row-driven
cleanup tool discovers files by walking rows (`account → posts → media.storage_path`),
any row deleted before its bytes are removed becomes a **permanent orphan** ("ghost")
that no row-driven tool can ever rediscover. This is exactly how agape Facebook + old-
month files survived multiple purges (root-caused 2026-07-04).

Rules, non-negotiable:
1. **Never raw-delete content rows without deleting their `storage_path` objects first.**
   Use `storage.media.delete_from_storage(paths)` (storage) *before* the row `.delete()`.
   `scripts/_cleanup_stale_junk.py` (`collect` + `apply_delete`) already does this order —
   reuse it for targeted client/account wipes rather than hand-rolling deletes.
2. **After ANY bulk row deletion or purge, run the orphan sweep as the mandatory net:**
   `python -m scripts.cleanup_storage_orphans [--prefix <client>] --apply`. It lists the
   real bucket and deletes objects with no DB row — the *only* tool that reaches ghosts.
   Dry-run (no `--apply`) first to eyeball the count; it aborts an apply if the global
   tracked set is empty (guards against a failed query nuking the bucket).
3. Mirror on the Drive side with `scripts/cleanup_drive_orphans.py` after Drive-touching
   purges. Verify a wipe with a dry-run root sweep: `orphans: 0` means no ghosts remain.
4. **`restore_from_bundle` only recovers *tombstoned* rows** (it uploads bytes, then
   PATCHes rows where `storage_path IS NULL AND archive_drive_id=<zip>`). Once the rows
   are **hard-deleted**, it uploads 40 objects and matches 0 rows → creates fresh orphans
   (watch its `unmatched=` counter). So after a full row wipe, a Drive zip is cold storage:
   recovery is a **re-ingest**, not `restore_from_bundle`.

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
