# Deep-Audit Prompt — Social_Bot

Paste everything below the line into Fable.

---

**Before doing anything else, orient yourself thoroughly in this project.** Do a
proper deep exploration pass first (spawn sub-agents / parallel exploration as
needed, and take the time it needs) so you actually understand the system before
you write a word. Read broadly across the WHOLE repository — every file under
`src/social_bot/`, `scripts/`, `tests/`, `config/`, `migrations/`, `docker/`,
plus `README.md`, `CLAUDE.md`, `justfile`, `pyproject.toml`, `uv.lock`, and the
`research/` and `docs/` notes. Do not sample one folder.

**Also read the latest Claude insights document in the `docs/` folder** (read
whichever insights file is present there) and factor its findings into your
audit.

You are doing a deep, unbiased audit of **Social_Bot**, a Python system that
scrapes Instagram + Facebook, runs an AI classify/describe pipeline, stores
time-series engagement, and renders monthly `.pptx` client reports. Verify every
claim against the code — the README may lag reality. Form your own conclusions
from what you find; do not assume any answer is already known. Where a design
choice is debatable, ask "what is actually best for this project?" and argue it
from the evidence rather than defaulting to generic best practice.

Some files worth understanding (pointers, not conclusions — judge them yourself):

- `src/social_bot/scrapers/` — Instagram (HikerAPI in `_hiker_client.py`, Apify
  fallback) and Facebook. Assess the error/retry/fallback handling and the cost
  implications of how these are called.
- `src/social_bot/ai/`, `src/social_bot/pipeline/` — Gemini/OpenAI classify +
  describe + report synthesis. Assess parsing robustness, retries, idempotency,
  and LLM-call cost.
- `src/social_bot/db/` — the Supabase data layer. Judge whether the intended
  boundary (this being the only module that knows column names) actually holds.
- `scripts/archive_and_purge.py`, `scripts/restore_from_bundle.py`, and the
  hiker-dedup migration/backfill scripts — assess data-safety and dedup.
- `scripts/` generally — a mix of live cron drivers and `_spike_*.py`
  experiments. Judge which are which and whether that is a problem.
- `docker/`, `justfile`, `.env` / `.env.example` / `credentials.json` — judge
  the deploy model and secret handling.

Produce TWO separate markdown documents.

===== DOCUMENT 1: CODEBASE AUDIT (write to AUDIT_CODEBASE.md) =====
Cover, each as its own section:
1. **Architecture overview** — how the pieces actually fit, drawn from the code
   (not assumptions). Trace at least one real end-to-end flow. Note where the
   README/structure diverges from what the code implies.
2. **Correctness & reliability risks** — bugs, race conditions, unhandled
   failures, and rate-limit / API-error handling for the social platforms and
   LLM providers this bot targets.
3. **Security & secrets** — token handling, auth, injection surfaces, and
   anything logged/sent/stored that shouldn't be.
4. **Data & state** — persistence, idempotency, duplicate-post / replay risk,
   and archive/purge/restore safety.
5. **Performance & cost** — hot paths and wasteful API/LLM/scraper calls (this
   system spends real money per scrape and per LLM call), N+1 patterns.
6. **Testing gaps** — what's untested that would hurt most if it broke. Point at
   the specific `tests/test_*.py` that should exist or expand.
7. **Maintainability** — coupling, dead code, naming, dependency health.

For EVERY finding give: `file:line` reference, severity
(Critical/High/Med/Low), why it matters, and a concrete fix. Rank ALL findings
in one table at the top, most severe first. If you're uncertain, say so — do
not invent.

===== DOCUMENT 2: WORKFLOW & PROCESS INSIGHTS (write to AUDIT_WORKFLOW.md) =====
Based on what the repo reveals about how this developer builds — commit patterns
and messages, branch strategy, CI presence/absence, test discipline, doc habits,
TODO/FIXME density, folder conventions, the `_spike_*.py` experiment pattern,
the pre-commit hooks, `CLAUDE.md` operating notes, and tooling — give honest,
direct insight (no flattery). Cover:
1. What is being done well and should be kept.
2. Where the process is costing time or causing bugs.
3. Concrete workflow upgrades — tooling, automation, CI steps, review habits,
   folder/convention changes — ranked by effort-to-payoff.
4. A suggested 30-day improvement plan, sequenced.

Rules for both docs:
- Evidence over opinion. Cite specific files/lines/commits.
- Prioritize ruthlessly — surface the top 20% that gives 80% of the value.
- Be direct about weaknesses. No flattery.
- End each doc with a short "if you only do 3 things" list.

Start by listing the files you read, then produce both documents.
