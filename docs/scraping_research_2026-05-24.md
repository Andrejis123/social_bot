# Scraping reliability research — 2026-05-24

**Goal:** Find a scraping path that successfully fetches posts from the restricted handles currently pulled from cron (pulzeczech, ploom.cz, iluminatecz) without burning the IE burner cookie.

**Blocker recap:** The current fallback (`get-leads/all-in-one-instagram-scraper`) is anonymous-first by design — it calls `web_profile_info` first, gives up before sending cookies, and `cookieStatus: unknown` proves it. IPRoyal residential proxy + cookies are wired and verified working at the network layer; the remaining variable is the actor's auth-routing behavior.

---

## TL;DR — top-1 recommendation

**Switch the fallback path to HikerAPI** (`hikerapi.com`), the managed SaaS built by the author of the `instagrapi` Python library.

- Cheapest viable option ($0.60 / 1000 requests, 100 free)
- Strongest theoretical fit — it's a hosted wrapper over `instagrapi`'s mobile **private** API (`_v1` endpoints), which is auth-first by construction, not anonymous-first
- Their cookie pool + proxies, not ours — zero cookie-burn risk during dev iteration
- 100 free requests is enough to verify on pulzeczech before any spend
- Vendor-risk hedged: if HikerAPI ever goes away, the underlying `instagrapi` library is MIT-licensed and self-hostable (see "Post-v1 strategic" below)

**Verified backup:** `crawlerbros/instagram-downloader-api` on Apify ($20 / 1000 results). Mandatory cookies pattern (`sessionid`+`ds_user_id`+`csrftoken`), 26× 5-star reviews, internal cookie pool. If HikerAPI ambiguates or fails, this is the immediate next swing.

**First actions on your return (~15 min total):**
1. Run HikerAPI free-tier test on pulzeczech (see § "Test plan" below)
2. If success → write the new scraper integration, swap fallback, re-enable restricted accounts
3. If failure → run the crawlerbros $0.02 test as fallback evidence

---

## Candidate matrix

Surveyed 13 Apify actors + 2 GitHub libraries + 1 SaaS. Only the 3 below pass the discriminator: *"can plausibly fetch posts from a public-but-anti-scrape Instagram profile via an authenticated-first code path."*

| # | Path | $/month @ our volume | Cookie burn risk | Setup effort | Restricted-profile signal | Vendor lock-in |
|---|---|---|---|---|---|---|
| **1** | **HikerAPI SaaS** | ~$0.10 | None (theirs) | ~2h (HTTP integration + new normalizer) | Strong (mobile private API, `instagrapi` author) | Low (instagrapi MIT fallback) |
| **2** | **crawlerbros/instagram-downloader-api** | ~$1.80 | None (theirs) | ~1h (swap actor id + new normalizer) | Medium (mandatory-cookie design + reviews, but closed-source) | High (no fallback) |
| **3** | **Self-host instagrapi on VPS** | $0 + IPRoyal | High (our IE burner) | ~6-8h (new Scraper class, session mgmt, ban handling) | Strong (direct `_v1` calls) | None |

> Volume math: ~3 restricted accounts × 30 posts/month = ~90 posts/month. Adjusted up for retries → ~100–200 requests/month.

### Why all the other Apify actors got rejected

Empirical signal from each actor's input schema + description:

| Actor | Verdict | Reason |
|---|---|---|
| `crawlerbros/instagram-profile-scraper` | ❌ | "Leave cookies field empty, works out of the box" — anonymous-first signature, same family as get-leads |
| `apidojo/instagram-scraper-api` | ❌ | "No login, no cookies" — explicit public-only |
| `sones/instagram-posts-scraper-lowcost` | ❌ for restricted (but ⭐ for primary, see Cost-optimization below) | Public-only; $0.30/1k makes it the cheapest primary scraper |
| `apify/instagram-api-scraper` | ❌ | Public-only, no auth input |
| `automation-lab/instagram-scraper` | ❌ | `sessionCookie` field exists but doc says "private accounts return no data at all" — cookie used only for hashtag/mentions modes |
| `cryptosignals/instagram-profile-scraper` | ❌ | "Public profiles only — private accounts are skipped" |
| `red.cars/instagram-scraper-pro` | ❌ | "Cannot extract from private accounts without following"; no custom proxy URLs |
| `futurizerush/instagram-user-post-scraper-api` | ❌ | sessionId required but "post list not accessible for private accounts" |
| `truefetch/instagram-profile-post` | ❌ | Public-only |
| `lisenser/ig-profile-scraper` | ❌ | Public-only, $16.99/mo + usage |
| `get-leads/all-in-one-instagram-scraper` (current) | ❌ | Anonymous-first, already empirically falsified |

---

## Test plan (run on return, in order — stop at first success)

### Test 1: HikerAPI free-tier (~5 min, $0)

1. Sign up at https://hikerapi.com — email + balance pre-pay (skip the pre-pay for now, 100 free requests are auto-granted)
2. Get API key from dashboard
3. Quick `curl` test:
   ```bash
   curl -H "x-access-key: $HIKER_KEY" \
     "https://api.hikerapi.com/v1/user/by/username?username=pulzeczech"
   ```
   Expect: JSON with `id`, `username`, `media_count`, etc. Saves us the user_id we need for the medias call.
4. Fetch medias:
   ```bash
   curl -H "x-access-key: $HIKER_KEY" \
     "https://api.hikerapi.com/v1/user/medias?user_id=<id>&amount=5"
   ```
   Success criteria: ≥1 media item with `code` (= shortCode), `caption_text`, `like_count`, `comment_count`, and `image_versions2` or `video_versions` URLs.

### Test 2: crawlerbros (~5 min, ~$0.02 of your Apify credits)

Only run if Test 1 fails or returns ambiguous data.

1. From `apify.com/crawlerbros/instagram-downloader-api`, click "Try for free" with the input:
   ```json
   {
     "usernames": ["pulzeczech"],
     "maxPosts_per_username": 5,
     "cookies": "<paste your INSTAGRAM_COOKIES JSON>"
   }
   ```
2. Run, inspect dataset. Same success criteria as above.

### Test 3 (only if BOTH above fail)
Bring findings back, reconsider. Self-host instagrapi becomes the path; budget 1-2 days engineering for the new Scraper class + cookie hygiene + ban-handling.

---

## Integration sketches (do AFTER tests verify)

### If HikerAPI wins

New file `src/claude_social/scrapers/_instagram_hiker.py`:

```python
# Pseudocode shape — verify against actual HikerAPI response schema after test
class HikerInstagramFallback:
    def __init__(self, api_key: str):
        self._key = api_key
        self._session = requests.Session()
        self._session.headers["x-access-key"] = api_key

    def fetch_posts(self, handle: str, limit: int = 30):
        user = self._session.get(
            "https://api.hikerapi.com/v1/user/by/username",
            params={"username": handle.lstrip("@")},
            timeout=30,
        ).json()
        medias = self._session.get(
            "https://api.hikerapi.com/v1/user/medias",
            params={"user_id": user["id"], "amount": limit},
            timeout=60,
        ).json()
        return [_normalize_hiker_media(m) for m in medias.get("items", [])]
```

Then in `InstagramScraper._scrape_posts_fallback`, wrap this behind the same trigger logic. New env var: `HIKER_API_KEY`. Drop `INSTAGRAM_COOKIES` dependency on the fallback path (still keep it for now — primary actor doesn't need it either, so the var becomes vestigial; can clean up next pass).

Note: HikerAPI's media schema is `instagrapi`-flavored (uses `code`, `caption_text`, `image_versions2`, `carousel_media`, `play_count`, etc.) — different from both the primary actor and the current fallback. Write a new `_normalize_post_hiker()` in `scrapers/instagram.py`, parallel to the existing `_normalize_post_fallback()`. Don't delete the old fallback yet — keep it as a third tier until HikerAPI proven over 2+ weeks of cron runs.

### If crawlerbros wins

Much smaller change:
1. Set `APIFY_INSTAGRAM_FALLBACK_ACTOR=crawlerbros/instagram-downloader-api` in `.env`
2. Adjust input shape in `_call_fallback_actor` — replace `scrapeMode`/`profiles`/`maxPostsPerProfile` with crawlerbros's `usernames`/`maxPosts_per_username`/`cookies` (JSON-formatted, not the raw string format `get-leads` accepts).
3. Add a new `_normalize_post_crawlerbros()` — output shape unknown until test, will need to inspect actual dataset items.
4. IPRoyal proxy URL not needed (crawlerbros uses internal proxy pool) — set `proxyTier: "none"` for this actor.

---

## Why other paths were dropped

### Custom Apify actor wrapping `instagrapi` — DROP

The user asked us to evaluate this; the honest answer is no. It combines the worst of both worlds: still own the cookie/ban risk (same as self-hosting on VPS), but adds Apify wrapper complexity (Dockerfile, Apify SDK, push pipeline, $0.30/CU compute) for infrastructure (queue, retry, dataset) that we already have via cron + Docker on the VPS. The only scenario this beats self-host-on-VPS is if we wanted to **sell** the actor to other Apify customers — out of scope.

### Self-host instagrapi — POST-v1 strategic

Listed in `future_possibilities.md` already. Deferred because:
- Each dev iteration sends fingerprintable requests through our burner cookie. Tuning + debugging is operationally expensive.
- Author's own README says: "private API automation is fragile in production… a hosted provider such as HikerAPI may be a better fit." That's the maintainer telling you to use the SaaS.
- Becomes attractive only when (a) volume is so high that $0.60/1k matters, or (b) we want full ownership for ToS-edge use cases. Neither applies at v1.

If/when revisited: instagrapi `v2.7.10` (May 21 2026), Python 3.10+, MIT. Use `client.user_medias_v1(user_id)` directly — bypasses the public-first fallback chain that's the same trap as get-leads. Configure `client.set_proxy("http://user:pass@host:port")` with IPRoyal URL. Persist session via `dump_settings`/`load_settings`. Keep one proxy IP per account stable (sticky IPRoyal already does this).

---

## Parallel cost-optimization (separate workstream, do not block on this)

Not the main blocker, but flagged because the user spotted it:

**Story actor swap:** `datavoyantlab/advanced-instagram-stories-scraper` is ~10× cheaper than current `igview-owner/instagram-story-viewer`. Same restricted-access limitation as current (no auth, no help for restricted profiles), so it's a pure cost play. Worth a test on agapeslovensko stories before swapping. Added to todos.md.

**Primary post actor potentially cheaper:** `sones/instagram-posts-scraper-lowcost` at $0.30/1000 vs ~$2.30/1000 for current `apify/instagram-scraper`. Public profiles only (matches current primary's role). Could trim primary cost ~7×. Lower priority than the restricted-profile fix.

---

## Open questions / things to verify after the test

1. **HikerAPI response schema** — exact field names for: media URL on carousels (children?), reel-vs-video discrimination, comment count nullability. Cannot finalize `_normalize_post_hiker()` until we see a real response.
2. **crawlerbros input cookie format** — JSON array? JSON object keyed by name? Single sessionid string? Their docs are vague; would clarify on test.
3. **Whether the new path solves iluminatecz** — handle status was "unavailable in incognito" — might be deactivated entirely, not restricted. Test it under HikerAPI's `/v1/user/by/username` to confirm.
4. **Stories pipeline for pulzeczech** — separate failing-cron issue noted in todos.md. The same SaaS likely has a stories endpoint — verify if test passes on posts.

---

## Cost summary (if we go HikerAPI + keep current primary)

| Item | Cost/month |
|---|---|
| Apify (primary actor on 7 accounts × ~30 posts) | ~$1-2 (current) |
| HikerAPI fallback (restricted accounts only) | ~$0.10 |
| IPRoyal residential | ~$1-3 depending on bandwidth (can potentially drop entirely if all paths use managed proxies — save for future review) |
| **Total** | **~$3/month** |

Well under the $30/month budget ceiling. If costs creep, the post-v1 self-host path becomes attractive.

---

## What I did NOT do (and why)

Per the unattended-execution commitment I gave you before you stepped away:
- **Did not run any Apify test** (even cheap, even on someone else's cookie pool). Advisor pushed back, saying the crawlerbros test is cookie-safe and $0.02 — they're right, but the call to spend your Apify credits without check-back felt like overreach.
- **Did not sign up for HikerAPI** — needs your email/payment details. The 100 free requests + signup form are step 1 of the test plan above.
- **Did not edit `instagram.py`, `.env`, cron, or anything in `src/`** — all integration waits for your verification.

---

## ADDENDUM — actual test results after user authorized (2026-05-24, 09:05-09:10 UTC)

User came back, provided HikerAPI key, granted full permission to test crawlerbros and HikerAPI.

### Test result 1: HikerAPI — BLOCKED (account needs top-up)
`GET /v2/user/by/username?username=agapeslovensko` returned:
```json
{"state": false, "error": "Top up your account at https://hikerapi.com/billing", "exc_type": "InsufficientFunds"}
```
The advertised "100 free requests" appears to require an initial balance to activate. **Action for user: deposit minimum (likely $1) at hikerapi.com/billing to unlock testing.**

### Test result 2: crawlerbros/instagram-downloader-api — WRONG SHAPE + EXPENSIVE
Run succeeded on agapeslovensko. Key findings:
- ✅ **Internal cookie pool confirmed:** logs show `MongoDB: 13 total cookies (12 active, 1 failed)` and selected cookie `amad6191@gmail.com` (2269 prior successful uses). Our `INSTAGRAM_COOKIES` were passed but ignored. **Their managed pool — zero burn risk on our IE burner.**
- ✅ Extracted profile data correctly (followers=4970, posts=1760, full_name="Agapé Slovensko")
- ✅ Extracted 3 reel URLs, processed each
- ❌ **Output is a media downloader, not a metadata scraper.** Every dataset item has shape `{post_url, filename, download_url, type, storage_key, video_meta: {width, height, codec, ...}}` — NO caption, NO like_count, NO comment_count, NO timestamp. Files get downloaded to Apify KV store.
- ❌ **Pricing was misadvertised.** Listed at "$20 / 1000 results"; actual charge was **$5.06 of `PAID_ACTORS_PER_EVENT` for 3 posts** — ~$1.70/post. Per-event prices are not transparent in the store listing.

### Test result 3: crawlerbros/instagram-profile-scraper (sibling) — BLOCKED
After the downloader's $5.06 charge, Apify returned `Monthly usage hard limit exceeded`. Free tier is $5/month, exhausted in one test.

### Apify account status
- Plan: FREE ($5/month credits)
- Current billing cycle: **2026-05-10 → 2026-06-09**
- Status: hard limit reached — no further actor runs possible until reset
- **🔥 IMPACT ON EXISTING CRON:**
  - Daily stories cron (every day 09:00-10:15 UTC): **WILL FAIL** starting tomorrow 2026-05-25
  - Weekly posts cron (Monday 06:00-07:55 UTC): **WILL FAIL** on 2026-05-31, 2026-06-07
  - Resumes on or after 2026-06-10 when free tier resets

### Recommended actions (in order)

1. **Restore service NOW** — top up Apify either with a one-off prepaid balance or upgrade to a paid plan. Even $5-10 prepaid via the Apify billing page restores the existing cron immediately. Otherwise client scraping stops for 16 days.

2. **Top up HikerAPI ($1 min)** — unlocks the test that we haven't been able to run yet. At $0.60/1000 requests, $1 = ~1600 requests = plenty for verification + several weeks of cron once integrated. This is still the long-term plan.

3. **Re-test on agapeslovensko + pulzeczech** via HikerAPI directly — no Apify dependency for this test, so the $5 cap doesn't matter. Bypasses the entire issue.

4. **If HikerAPI confirms it works on pulzeczech:** swap fallback to HikerAPI as planned. **Consider also moving primary** (currently `apify/instagram-scraper`) off Apify long-term — the $5/month free tier has shown it can be wiped out by a single expensive run. HikerAPI at $0.60/1000 for our full ~7-account-monthly volume = pennies/month. This is a bigger architectural change but addresses the brittleness root cause.

5. **Update the actor listing in your mental model:** `crawlerbros/instagram-downloader-api` is dropped (wrong product). `crawlerbros/instagram-profile-scraper` (the sibling) is the candidate that **wasn't** tested due to the cap — still unknown.

### My mistakes here
- Underweighted the warning "actor pricing model uses per-event charges, not headline result rate" — should have done a cost-bound dry-run before a full run. Will set a `maxItems` and read run cost projections upfront next time.
- Conflated "advertised pricing" with "actual cost." Two different things on Apify Store.
- Ran the wrong actor first: I picked `downloader-api` based on its "cookies required" signal, but the name "downloader" should have been a stronger negative signal that the product downloads files, not scrapes metadata.
