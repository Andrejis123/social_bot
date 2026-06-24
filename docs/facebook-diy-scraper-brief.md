# Facebook DIY Scraper - Exploration Brief

> **What this is:** a self-contained handoff to make a *future* session faster.
> Paste it (or point the session at this path) when we either (a) brainstorm
> whether to commit to writing our own Facebook scraper, or (b) decide to go
> through with it. It captures our specific requirements plus the concrete
> learnings from the session that built the Apify-based Facebook Phase A, so the
> next session does not have to re-derive any of it.
>
> Distilled from: the shipped `src/social_bot/scrapers/facebook.py`, the plan
> file `~/.claude/plans/orient-yourself-in-the-modular-toast.md`, and memory
> (`project_facebook_expansion`, `tools_inventory`, `feedback_actor_pricing_models`,
> `project_media_storage_architecture`, `feedback_iteration_persistence`).

---

## 1. Why DIY is even on the table (the three drivers)

We do **not** want to build a scraper for fun. DIY only earns its keep against
one of these three problems, and the brainstorm should keep them separate
because they have different bars:

1. **Restricted / age-gated public Pages (the key unsolved function).** The ecig
   client's brands (`iqos_cz`, `ploom.cz`, `pulzeczech` FB) sit behind Meta's
   2019 age-gate, which walls them to logged-in 18+ viewers. **No commercial REST
   API sells behind-login Facebook** (ScrapeCreators is incognito-only; Bright
   Data and Decodo explicitly refuse logins). This is the same wall it took ages
   to solve on Instagram (solved there with HikerAPI) - and there is **no
   HikerAPI analog for Facebook**. This is the strongest DIY motivator.
2. **Apify reliability.** Actors go down intermittently, and we run posts on the
   free credit tier. If an actor is the only path and it is down, we are not
   scraping at all.
3. **Apify cost / overcharge.** Per-event pricing can hide surcharges; one
   careless run can wipe the EUR 5/month free cap and block *all* subsequent cron
   until reset (see `feedback_actor_pricing_models`). DIY trades a recurring
   per-result fee for proxy bandwidth + our maintenance time.

**Framing rule for the next session:** driver #1 is a *capability* gap (no money
buys it), drivers #2 and #3 are *economics/reliability* gaps (money might buy a
better actor). Treat them differently when deciding.

---

## 2. What "done" must look like - our concrete requirements

A DIY scraper is only useful if it drops into the existing pipeline unchanged.
The integration contract (already exercised by the Apify-based scraper) is:

- **Conform to the `Scraper` protocol** in `src/social_bot/scrapers/base.py`:
  implement `scrape_posts(...)` and `scrape_stories(...)` returning
  `ScrapedPost` / `ScrapedStory` / `ScrapedMedia` dataclasses. `platform = "facebook"`.
- **Field mapping is already settled** (copy from `facebook.py`, it is
  transport-agnostic): `platform_post_id`, `permalink` (prefer canonical
  `/posts/<id>`), `posted_at`, `caption`, `like_count` (reaction TOTAL),
  `comment_count`, `share_count`, `view_count` (video only), `play_count=None`,
  `save_count=None` (FB has no saves), `post_type`
  (`image`/`video`/`reel`/`carousel`/`text`), and `raw` = the full payload for
  reversibility.
- **Media handling matches Instagram reels:** a video post stores the playable
  mp4 at `slide_index = len(out)` **and** its cover image at
  `REEL_COVER_SLIDE_INDEX` (99). This is what lets the classifier/descriptor send
  the real `video/mp4` bytes to Gemini (see `project_media_storage_architecture`).
- **Plug-in points (all already exist, no changes needed):**
  - `scrapers/registry.py` -> `_REGISTRY["facebook"]`
  - `pipeline/ingest_posts.py` -> guarded by `supported_platforms()`
  - dedup on the unique `(platform, platform_post_id)`
  - platform-scoped storage paths (`<client>/<handle>/facebook/posts/...`)
  - `--platform` CLI filter already wired (handle `agapeslovensko` exists on both
    IG and FB, so platform scoping matters)
- **Cache the page numeric id** (`facebookId`) as
  `discovered_platform_account_id`, parity with the IG pk.

If DIY produces `ScrapedPost` objects with these fields, *nothing downstream
changes.*

---

## 3. What we verified this session (the facts that de-risk DIY)

These were established empirically (not assumed) and the next session should
trust them rather than re-test from scratch:

- **Normal public Pages do NOT need cookies.** `apify/facebook-posts-scraper`
  (official) returned **20 posts with full month history, per-reaction breakdown,
  and `viewsCount` anonymously** for Agape. The earlier "anonymous FB = 1 post,
  cookies required" conclusion was **wrong** - that 1-post wall is specific to
  `get-leads/all-in-one-facebook-scraper`'s anon mode, not Facebook in general.
  *Lesson:* test the specific actor/endpoint, do not generalize one tool's quirk.
- **Restricted pages are still unverified.** Whether a cookie'd actor (or DIY
  with cookies) actually beats the age-gate has **not** been tested. Do this
  *before* building anything (see Phase 0). Do not assume cookies are sufficient.
- **The real payload shapes** (ground truth, captured in
  `tests/fixtures/facebook_official_{agape,nasa}.json`):
  - top-level: `postId`, `url` (reel/pfbid link, less stable), `topLevelUrl`
    (canonical numeric `/posts/<id>`), `time` (ISO-8601 with trailing `Z`),
    `text`, `likes` (reaction total), `comments`, `shares`, `viewsCount`,
    `isVideo`, `facebookId` (page id), `media[]`.
  - `media[]` elements: `__typename` is `Video` or `Photo`; videos carry the mp4
    at **`videoDeliveryLegacyFields.browser_native_hd_url`** (HD, fall back to
    `browser_native_sd_url`), plus `playable_duration_in_ms`, `original_width/height`,
    and a cover at `thumbnailImage.uri` (or `thumbnail`); photos carry
    `photo_image.uri` (or `thumbnail`). Carousels can lead with a junk element
    (`__typename: None`, no URL) - filter it.
  - *Lesson learned the hard way:* the video URL is **nested**; a shallow grep
    missed it and we first shipped cover-only reels. Verify nested fields.
- **`mbasic.facebook.com` was retired in December 2024.** The easy mobile-HTML
  scraping path is dead. DIY therefore means parsing modern FB **GraphQL** (or
  rendered HTML) behind cookies - the brittle, high-maintenance path. This is the
  single biggest argument *against* DIY and the next session should weigh it
  heavily.

---

## 4. The DIY technical problem - what we would actually have to build

Roughly in dependency order:

1. **Auth.** One or more FB burner accounts (18+), capture session cookies
   (`c_user`, `xs`), plus refresh/rotation when they expire or get checkpointed.
2. **Transport.** Residential proxy (we already use `RESIDENTIAL_PROXY_URL` for
   the IG fallback - reuse the pattern), per-cookie rate ceilings, backoff.
3. **Fetch.** Hit FB's internal GraphQL endpoint(s) for Page posts (need the
   `doc_id` / persisted-query id + `variables`), handle pagination cursors. HTML
   rendering (Playwright) is the heavier fallback if GraphQL proves too guarded.
4. **Parse.** Map obfuscated/rotating GraphQL JSON to our `ScrapedPost` fields.
   This is the part that breaks when FB changes layout = the recurring tax.
5. **Media.** Resolve the video CDN URLs (same fields section 3 lists) and
   download via the existing media storage path.
6. **Anti-bot / reliability.** Detect checkpoints, captchas, and bans; alert
   (Telegram, like the rest of the pipeline) instead of silently failing.

---

## 5. Provider landscape recap (what is ruled out and why)

| Option | Public posts | Restricted? | Cost | Status |
|---|---|---|---|---|
| `apify/facebook-posts-scraper` (official) | yes, anon, full history | No (cookieless) | ~$2/1k, per-event | **Current Phase A** |
| `get-leads/all-in-one-facebook-scraper` | yes (1 post anon) | cookie-capable, **unverified vs age-gate** | ~$1.35/1k, per-result | Phase B candidate |
| Bright Data / Decodo | yes | No (refuse logins) | ~$1.50/1k | public-only dead-end |
| ScrapeCreators | yes (incognito) | No | ~$0.63/1k + EUR 47 upfront | **rejected** (can't do key function) |
| **DIY (GraphQL/cookies/proxy)** | yes | **yes (full control)** | proxy bandwidth only | the subject of this brief |

Engagement-loss myth, resolved: cookies do **not** strip engagement counts; full
reaction/ comment/ share numbers come back either way. (The "cookies omit likes"
claim was one actor's Pages-mode quirk.)

---

## 6. Decision criteria - commit to DIY only if ALL hold

1. A real ecig FB target confirms the **age-gate actually bites**, AND
2. A **cookie'd commercial actor** (official or get-leads, with our burner
   cookies) **cannot** read it either - i.e. money genuinely cannot buy the
   capability, AND
3. We accept the **ongoing maintenance burden** of tracking FB GraphQL changes.

For drivers #2/#3 (reliability/cost) alone, DIY is likely the wrong call: a
second commercial actor or Bright Data's free tier (5k records/mo, no card) is
cheaper than our engineering time. DIY's unique value is **only** the restricted
capability. See `feedback_iteration_persistence`: when a problem feels
"should-be-solvable," the blocker is usually tool-specific, not platform-level -
so exhaust the cookie'd-actor route before building.

---

## 7. Phased recipe / to-do (when/if we proceed)

**Phase 0 - de-risk before writing any code (do this first, cheap):**
- [ ] Point a cookie'd run (official actor and/or get-leads with burner cookies)
      at ONE restricted ecig Page. Does auth beat the age-gate? **If yes, DIY may
      be unnecessary - stop here and just use the cookie'd actor.**
- [ ] Measure real Apify cost at full cadence (all clients, posts+stories) and
      quantify observed downtime. Decide if #2/#3 are real problems or anxiety.

**Phase 1 - auth spike (smallest reproduction):**
- [ ] Create an 18+ FB burner; capture cookies. Add `FACEBOOK_COOKIES` config
      mirroring `INSTAGRAM_COOKIES`.
- [ ] Hand `curl`/`httpx` with cookies + residential proxy: can we fetch ONE
      restricted Page's posts payload at all? (No parsing yet - just "does FB
      return data to a scripted, authenticated, proxied request?")

**Phase 2 - parse spike (throwaway):**
- [ ] Identify the GraphQL endpoint + `doc_id` + `variables` for Page posts;
      find the pagination cursor.
- [ ] Write a throwaway parser -> map to `ScrapedPost`. **Validate against the
      existing `facebook_official_*.json` fixtures as ground truth** (the Apify
      output is our oracle for "correct" normalization).

**Phase 3 - productionize behind the protocol:**
- [ ] Decide architecture: a standalone DIY scraper, OR a DIY backend inside
      `FacebookScraper` with **automatic fallback to the Apify actor** (mirror
      the IG `hiker -> apify` tiering: DIY tier-1 for restricted, actor fallback
      for public). Recommended: the tiered version.
- [ ] TDD the normalizer with captured restricted-page fixtures, mirroring
      `tests/test_facebook_normalizer.py` (red -> green).
- [ ] Cookie/proxy config, retry/backoff (template: `_hiker_client.py`), ban/
      checkpoint detection, Telegram alerting.
- [ ] Keep `just check` green; deploy via `just deploy` (rebuild Docker image).

---

## 8. Reusable assets already in the repo (do not reinvent)

- **`src/social_bot/scrapers/facebook.py`** - the normalizer and helpers
  (`_normalize_post_facebook`, `_extract_media`, `_video_url`, `_ms_to_seconds`,
  `_classify_post_type`, `_parse_fb_time`, `_coerce_int`, `_profile_url`) are
  **transport-agnostic**: reuse them verbatim whether bytes come from Apify or
  DIY. Only the fetch layer changes.
- **`src/social_bot/scrapers/_hiker_client.py`** - a clean hand-written API
  client with retry/backoff and `retry_on_404`. This is the template for a DIY FB
  client.
- **`src/social_bot/scrapers/instagram.py`** - the cookie + residential-proxy
  fallback pattern; the auth/proxy template for FB.
- **`src/social_bot/scrapers/base.py`** - the shapes the DIY scraper must emit.
- **`tests/fixtures/facebook_official_{agape,nasa}.json`** - ground-truth payloads
  to validate DIY parsing against.
- **registry + `ingest_posts` + `--platform` filter** - integration points,
  unchanged by transport.

---

## 9. Open questions to resolve next session

- Does cookie auth actually defeat the age-gate, or does FB still block scripted
  access even when authenticated? (Phase 0 answers this.)
- How often does FB rotate GraphQL `doc_id`s / schemas - i.e. what is the real
  maintenance frequency?
- Burner account longevity: what is the ban rate at our scraping cadence?
- ToS / legal posture for cookie'd scraping of competitors - acceptable for our
  monitoring use case? Document the stance.
- Architecture: one DIY scraper, or DIY-with-actor-fallback? (Recommend the
  latter for resilience.)
- Stories: FB stories are still Phase B and untackled; DIY for stories is a
  separate, harder problem (ephemeral, even more auth-bound).

---

## 10. Cross-references

- **Memory:** `project_facebook_expansion`, `tools_inventory`,
  `feedback_actor_pricing_models`, `project_media_storage_architecture`,
  `feedback_iteration_persistence`, `project_uncategorized_policy`.
- **Plan file:** `~/.claude/plans/orient-yourself-in-the-modular-toast.md`
- **Code:** `src/social_bot/scrapers/{facebook.py,_hiker_client.py,instagram.py,base.py,registry.py}`,
  `src/social_bot/pipeline/ingest_posts.py`, `scripts/scrape_posts.py`
