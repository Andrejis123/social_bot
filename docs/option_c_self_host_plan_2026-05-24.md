# Option C — Self-host `subzeroid/instagrapi` on the VPS

**Date:** 2026-05-24
**Status:** Designed, awaiting confirmation. Code-complete deliverable would replace the Apify *fallback* tier; primary actor stays. Restricted-account re-enablement is gated behind a successful 1-week soak on pulzeczech.

## 1. Executive summary

We add a third scraper tier — a self-hosted `instagrapi` client living in the existing Docker container on the VPS at `161.35.170.254`. It calls Instagram's authenticated mobile private API (`_v1`) directly through our IE burner cookie and the IPRoyal sticky-IE proxy already wired in. The primary `apify/instagram-scraper` actor keeps doing the cheap public scrapes for the 3 active public accounts. The Apify fallback (`get-leads/all-in-one-instagram-scraper`) stays in place as the middle tier for 2+ weeks while we soak instagrapi behind a feature flag. Estimated effort: **12–18h** across four rollout stages, spread over ~2 weeks of calendar time. Operational ceiling: the IE burner becomes a single point of failure for the restricted accounts — we mitigate with Telegram alerting on challenge/login-required errors and a documented runbook for cookie replacement.

## 2. Architecture

### New module

**File:** `src/claude_social/scrapers/_instagrapi_client.py` (private, leading underscore — same convention as the existing `_normalize_post_fallback` helpers; this module is consumed only by `InstagramScraper`, not by the registry).

This module owns:
- A singleton `instagrapi.Client` instance, lazily constructed.
- Session bootstrap from `INSTAGRAM_COOKIES` JSON (one-time conversion to instagrapi's native format).
- Session persistence to a host-mounted volume.
- Proxy wiring against `RESIDENTIAL_PROXY_URL`.
- Public methods: `fetch_user_medias(handle, limit) -> list[ScrapedPost]` and `fetch_user_stories(handle) -> list[ScrapedStory]`.
- Exception translation: instagrapi's exception zoo (`LoginRequired`, `ChallengeRequired`, `PleaseWaitFewMinutes`, `ClientError`) translated into a small set of internal errors the caller can match against.

### Integration into `InstagramScraper`

**Posts.** The existing two-tier flow in `src/claude_social/scrapers/instagram.py` (lines 56–80) becomes three-tier, gated by a new env var `USE_INSTAGRAPI_FALLBACK`:

```
scrape_posts(handle)
  posts, raw_count = _scrape_posts_primary(...)      # apify/instagram-scraper (line 82)
  if raw_count > 0: return posts
  if INSTAGRAM_COOKIES and not USE_INSTAGRAPI_FALLBACK:
      return _scrape_posts_fallback(...)              # get-leads actor (line 124)
  if INSTAGRAM_COOKIES and USE_INSTAGRAPI_FALLBACK:
      try:
          return _scrape_posts_instagrapi(...)        # NEW — third tier
      except InstagrapiFatal:
          # Telegram alert, then fall back to Apify so cron doesn't go dark
          return _scrape_posts_fallback(...)
  return []
```

**Why third tier, not replacement.** The Apify fallback's cookie pool is currently the safer harness (verified working on the 3 active accounts; their cookies, not ours). Cutting it out before instagrapi has 2 weeks of clean runs would risk losing the 3 working accounts to harvest the 4 broken ones — the wrong trade. Once instagrapi proves out on pulzeczech, Stage 4 of rollout collapses the middle tier.

**Stories.** `scrape_stories` (line 278) gets the same flag-gated extension. Stories are dailier (cron runs ~09:00–10:15 UTC) and `igview-owner/instagram-story-viewer` doesn't authenticate, so it can't help on restricted handles. instagrapi's `client.user_stories_v1(user_id)` is the right call. Same exception-and-fall-back pattern as posts.

### Container

**Stay in the existing scraping container.** Adding one Python dep + one host-mounted volume doesn't justify a second container. Separating would create cross-container state coordination (which container holds the lock on the cookie file? what if both run simultaneously?). One container, one cookie, one volume — simplest invariant.

## 3. Session / cookie management

This is the load-bearing piece. The whole approach falls over if cookies break and we don't know it.

### Bootstrap (one-time, manual)

The existing `INSTAGRAM_COOKIES` env var is a raw JSON cookie-export from Cookie-Editor. instagrapi's native format is a settings dict (`uuids`, `device_settings`, `user_agent`, `cookies`). A bootstrap script — `scripts/bootstrap_instagrapi_session.py` — runs once to convert and persist:

```python
# scripts/bootstrap_instagrapi_session.py
# Run ONCE on the VPS:  docker compose run --rm app python -m scripts.bootstrap_instagrapi_session
from instagrapi import Client
from claude_social.config import get_settings
import json, pathlib

s = get_settings()
cookies = json.loads(s.instagram_cookies)            # raw JSON from Cookie-Editor
sessionid = next(c["value"] for c in cookies if c["name"] == "sessionid")

cl = Client()
cl.set_proxy(s.residential_proxy_url)
cl.login_by_sessionid(sessionid)                     # builds the full settings dict from sessionid
cl.get_timeline_feed()                               # cheap warm-up; raises if cookie is bad

session_path = pathlib.Path(s.instagrapi_session_path)
session_path.parent.mkdir(parents=True, exist_ok=True)
cl.dump_settings(session_path)
print(f"OK session written to {session_path}")
```

After this run, `INSTAGRAM_COOKIES` becomes vestigial — instagrapi runs from the persisted settings file. We keep the env var because the Apify fallback (middle tier) still consumes it.

### Persistence: bind-mounted host volume

Not Supabase Storage (network round-trip per run, extra failure mode) and not container-internal disk (container recreation wipes it). Host directory `/opt/social_bot/state/` bind-mounted at `/state` inside the container:

```yaml
# docker/docker-compose.yml additions
services:
  app:
    volumes:
      - ../config:/app/config:ro
      - /opt/social_bot/state:/state:rw            # NEW
```

New env var: `INSTAGRAPI_SESSION_PATH=/state/instagrapi/session.json`.

Container restarts/recreations don't wipe `/opt/social_bot/state/` (it's on the host). The user creates the dir once: `sudo mkdir -p /opt/social_bot/state/instagrapi && sudo chown -R <docker-uid> /opt/social_bot/state`.

### Detecting session-expired

instagrapi raises `LoginRequired` when the session is dead. We catch this at the `_instagrapi_client` boundary, fire a Telegram alert (reuse `notifications.telegram.send`), and re-raise as `InstagrapiFatal` so the caller falls back to Apify. The cookie won't auto-heal — the user must re-bootstrap with a fresh cookie.

```python
# pseudocode in _instagrapi_client.py
class InstagrapiFatal(Exception): pass
class InstagrapiTransient(Exception): pass

def fetch_user_medias(self, handle: str, limit: int) -> list[ScrapedPost]:
    try:
        user_id = self._client.user_id_from_username(handle.lstrip("@"))
        medias = self._client.user_medias_v1(user_id, amount=limit)
        return [self._normalize_media(m) for m in medias]
    except LoginRequired as exc:
        notifications.telegram.send(
            f"INSTAGRAPI LoginRequired on @{handle} — IE burner cookie is dead. "
            f"Re-bootstrap with a fresh export. See runbook."
        )
        raise InstagrapiFatal("session expired") from exc
    except ChallengeRequired as exc:
        notifications.telegram.send(
            f"INSTAGRAPI ChallengeRequired on @{handle} — IG flagged the account. "
            f"Log in manually from IE IP, resolve challenge, re-bootstrap."
        )
        raise InstagrapiFatal("challenge required") from exc
    except PleaseWaitFewMinutes as exc:
        # Backoff is handled by retry loop in the caller, not here.
        raise InstagrapiTransient("rate limit") from exc
```

## 4. Proxy wiring

instagrapi exposes `client.set_proxy(url)`. The IPRoyal URL already encodes IE country in the password (`pass_country-ie`) and the sticky-session token keeps the same IP across calls.

```python
# _instagrapi_client.py — client construction
def _build_client(self) -> Client:
    cl = Client()
    if self._settings.residential_proxy_url:
        cl.set_proxy(self._settings.residential_proxy_url)
    else:
        log.warning("instagrapi.no_proxy_configured")  # works, but raises ban risk
    cl.delay_range = [2, 6]                  # built-in human-like jitter between calls
    cl.request_timeout = 30
    if self._session_path.exists():
        cl.load_settings(self._session_path)
    return cl
```

**Per-account proxy stability.** IPRoyal's sticky-session token is already pinned in the URL (set at provisioning, not per-account). All 4–7 accounts share one IE IP. That's fine: from Instagram's perspective the burner account *should* always come from one geographic origin (matches the cookie's login IP), and switching IPs per account would actually be suspicious. Trade-off accepted.

**Proxy failure.** IPRoyal-side outage = instagrapi requests fail with `httpx.ConnectError`-equivalent. We treat this as `InstagrapiTransient`, sleep 30s, retry once, then bail to Apify fallback. Should be rare; IPRoyal has been stable in earlier tests.

## 5. Challenge / ban handling

| Exception | Failure mode | Response |
|---|---|---|
| `LoginRequired` | Session expired (cookie dead) | Telegram alert + fail this run; manual re-bootstrap required |
| `ChallengeRequired` | IG demands email/SMS challenge | Telegram alert + fail this run; manual login from IE IP required |
| `PleaseWaitFewMinutes` | Soft rate limit | Sleep 60s, retry once; if still failing → fall back to Apify for this run |
| `ClientError` (other 4xx/5xx) | Unknown — could be transient or perma | Single retry with 10s backoff, then bail |
| `httpx.ConnectError` | Proxy outage | Retry once after 30s, then bail to Apify |

All alert paths reuse `src/claude_social/notifications/telegram.py` — `send()` already exists at line 34. Messages must be specific enough that the user knows exactly which account broke and what to do.

**Runbook (to live in `docs/runbooks/instagrapi_session.md` — out of scope for this plan, but required before Stage 3):**
1. Open Firefox/Chrome from an IE-located VPN session.
2. Log into the burner account, resolve any challenge dialog.
3. Export cookies via Cookie-Editor extension, paste into `INSTAGRAM_COOKIES`.
4. SSH to VPS, `docker compose run --rm app python -m scripts.bootstrap_instagrapi_session`.
5. Verify with `docker compose run --rm app python -m scripts.scrape_posts --client agape --account pulzeczech --limit 3`.

## 6. Rate limit / cadence

instagrapi's docs cite ~200 requests/cookie/day as the soft ceiling. Our actual load on a single burner cookie:

- **Posts cron (Monday 06:00 UTC):** 7 accounts × (1 `user_id_from_username` + 1 `user_medias_v1`) = 14 base requests. Carousels need `media_info_v1` per item to get child slides — assume ~30% of ~30 posts/account/week are carousels, ~6 carousels × 7 accounts = ~42 additional requests. **Weekly total: ~56 requests, all on Monday morning.**
- **Stories cron (daily 09:00 UTC):** 7 accounts × 2 requests (`user_id` + `user_stories_v1`) = 14/day.
- **Combined daily peak (Monday): ~70.** Other days: ~14.

That's well below the 200/day ceiling. **Headroom evaporates if retry loops kick in.** Single retries on transient errors = fine. A bad-day retry storm (e.g. flapping proxy + 7 accounts × 3 retries) would push us into the danger zone — log retry counts via the existing `RunContext` and alert if a single run exceeds, say, 30 retries.

**Cadence between accounts.** instagrapi's built-in `delay_range = [2, 6]` adds 2–6s jitter between requests. On top of that, we add a per-account sleep of 8–15s in the scraper loop (random). Net: a Monday cron run takes ~10 minutes for all 7 accounts, which is fine (the current cron window is 06:00–07:55 UTC).

**Serial only.** Parallelism = simultaneous requests from one cookie = ban-shaped behaviour. The cron already serializes by scheduling each account as a separate entry; keep it.

## 7. Output schema mapping

instagrapi's `Media` model (verify against v2.7.10 source — field names below are from public docs):

| instagrapi field | `ScrapedPost` field | Notes |
|---|---|---|
| `media.code` | `platform_post_id` | Shortcode — same as Apify's `shortCode` |
| `media.pk` | (kept in `raw`) | Numeric primary key, not used downstream |
| `media.media_type` | derives `post_type` | 1=image, 2=video/reel, 8=carousel |
| `media.product_type` | refines `post_type` | `"clips"` → `reel`, `"feed"` → `video` |
| `media.caption_text` | `caption` | |
| `media.like_count` | `like_count` | |
| `media.comment_count` | `comment_count` | |
| `media.view_count` | `view_count` | Nullable on non-video |
| `media.play_count` | `play_count` | Reel-only |
| `media.taken_at` | `posted_at` | `datetime` in UTC, already tz-aware |
| `media.thumbnail_url` / `media.image_versions2.candidates[0].url` | `media[0].source_url` (image) | First candidate is highest-res |
| `media.video_url` / `media.video_versions[0].url` | `media[0].source_url` (video) | |
| `media.video_duration` | `media[0].duration_seconds` | |
| `media.code` → `https://www.instagram.com/p/{code}/` | `permalink` | Construct manually |

**Carousel children — the complexity flag.** `user_medias_v1` returns the listing but does *not* include carousel children (`resources` array). To get child slides we must do `client.media_info_v1(media.pk)` per carousel post. That's the +42 requests/week call from §6. Trade-off: if we skip this and only capture the cover image, we match what the current Apify fallback does (`_normalize_post_fallback` line 437 has the same TODO) — acceptable for Stage 1, address in Stage 4.

Normalizer lives next to the existing ones in `instagram.py` as `_normalize_post_instagrapi(media: Any) -> ScrapedPost`.

**Stories schema.** `client.user_stories_v1(user_id) -> list[Story]`. Fields: `pk`, `code`, `taken_at`, `expiring_at` (use this! the current Apify path fakes it as `taken_at + 24h` at line 503), `video_url`, `thumbnail_url`, `media_type`. Carousel-style stories are rare; treat as single media each.

## 8. Deployment changes

| File | Change |
|---|---|
| `pyproject.toml` | Add `"instagrapi>=2.7.10"` to `dependencies` |
| `docker/Dockerfile` | No change — `uv sync` picks up the new dep at line 22 |
| `docker/docker-compose.yml` | Add `/opt/social_bot/state:/state:rw` volume mount under `services.app.volumes` |
| `justfile` | Add `bootstrap-instagrapi` task running `scripts/bootstrap_instagrapi_session.py` |
| `scripts/bootstrap_instagrapi_session.py` | NEW — see §3 |
| `src/claude_social/scrapers/_instagrapi_client.py` | NEW — see §2 |
| `src/claude_social/scrapers/instagram.py` | Add third-tier branches in `scrape_posts` (line 56) and `scrape_stories` (line 278); add `_normalize_post_instagrapi` and `_normalize_story_instagrapi` |
| `src/claude_social/config.py` | New settings: `use_instagrapi_fallback`, `instagrapi_session_path` |
| `.env.example` | Document the new vars |
| `config/clients/agape/client.yaml` etc. | Stage 3 only — flip `is_active: true` on pulzeczech first, then others |
| `docs/runbooks/instagrapi_session.md` | NEW — manual cookie-rotation procedure |

VPS cron entries do NOT change. The new tier is invoked transparently inside `scrape_posts`/`scrape_stories`.

## 9. New env vars

```bash
# --- instagrapi self-host (Option C) ---
# Toggle the instagrapi third-tier fallback. When false, behavior is identical
# to the current two-tier Apify flow. Flip to true once session is bootstrapped.
USE_INSTAGRAPI_FALLBACK=false
# Path inside the container where instagrapi's session settings JSON lives.
# Must match the bind-mount target in docker-compose.yml.
INSTAGRAPI_SESSION_PATH=/state/instagrapi/session.json
```

Reused unchanged: `INSTAGRAM_COOKIES` (for one-time bootstrap), `RESIDENTIAL_PROXY_URL`.

## 10. Migration / rollout

Four stages, ~2 weeks calendar:

### Stage 1 — Ship instagrapi alongside Apify, flag off (day 1–2)
- Add the new module, integration branches, env vars.
- Flag defaults to `false`; cron behaviour unchanged.
- Bootstrap the session on the VPS (`just bootstrap-instagrapi`).
- Manual smoke test: `USE_INSTAGRAPI_FALLBACK=true scrape-posts agape --account agapeslovensko --limit 3`. Verify same shape as Apify run.

### Stage 2 — Soak on pulzeczech (day 2–9)
- Set `USE_INSTAGRAPI_FALLBACK=true` in `.env`.
- Re-enable **only pulzeczech** in `config/clients/<...>/client.yaml` (flip `is_active: true`).
- Watch cron logs for a week. Acceptance: zero `LoginRequired` / `ChallengeRequired` alerts, posts arriving with full metrics + media.
- If banned during this week: roll back (flip flag off, deactivate pulzeczech again) and reassess. We've burned one cookie but learned the operational ceiling.

### Stage 3 — Re-enable remaining restricted accounts (day 9–14)
- Flip `is_active: true` on ploom.cz, iluminatecz, pulzecz in their respective client.yaml files.
- Watch one full weekly posts cycle + 5 daily stories cycles.
- **Note for the user:** these are config-file edits, not code changes. The four currently-deactivated handles are in their client YAMLs as `is_active: false`. Find each in `config/clients/<client_slug>/client.yaml` and flip the flag.

### Stage 4 — Optional: collapse the middle tier (week 3+)
- Only if Apify costs continue to be a problem and instagrapi has run clean for 2+ weeks.
- Remove the `_scrape_posts_fallback` call from `scrape_posts`. Keep the code paths around for a release in case we need to revert.
- Decide separately whether to also remove the primary `apify/instagram-scraper`; that's a bigger call (public-account scraping has no auth risk) and is out of scope here.

## 11. Testing strategy

instagrapi's private API can't be hit from CI — no anonymous endpoints, every call requires a real session. So:

- **Unit tests on normalizers only.** `_normalize_post_instagrapi(media_fixture)` and `_normalize_story_instagrapi(story_fixture)` get tested against captured JSON fixtures saved from real bootstrap runs. Lives next to `tests/test_instagram_normalizer.py`.
- **Mocking the client.** Tests for the three-tier control flow in `InstagramScraper.scrape_posts` use a fake instagrapi client that raises `LoginRequired` / returns canned media lists / returns `[]`. Verifies fall-through behaviour.
- **No integration tests against real IG.** Each test run = real network calls = cookie burn. Manual smoke test in Stage 1 covers this once.
- **Fixture capture.** During Stage 1 smoke test, save the raw `Media` object via `media.dict()` to `tests/fixtures/instagrapi_media_*.json` for each post type (image, video, reel, carousel). These are the canonical normalizer test inputs.

A second cookie *would* let us run integration tests safely, but isn't worth provisioning — the manual smoke test is sufficient and cheaper.

## 12. Risks + open questions

### Risks

1. **IE burner becomes a single point of failure for restricted accounts.** Apify managed pool = their problem; self-host = ours. Mitigation: Telegram alerting + documented runbook + middle-tier Apify fallback retained.
2. **Cookie ban during dev iteration.** Every `bootstrap_instagrapi_session.py` run is a real login. Multiple bootstraps in a short window look like password-attempt churn. Mitigation: bootstrap once, don't iterate; only re-bootstrap on confirmed `LoginRequired`.
3. **Carousel handling adds 30%+ requests.** If we enable `media_info_v1` per carousel from day 1, headroom shrinks. Mitigation: ship Stage 1 with cover-image-only (matches current Apify fallback's TODO), enable child fetching in Stage 4.
4. **Library churn.** instagrapi v2.x has had breaking API changes between minor versions in the past. Pin to `>=2.7.10,<2.8` and review releases before bumping.
5. **The VPS state volume is unbacked.** If `/opt/social_bot/state/` is wiped (disk failure, accidental `rm`), the session is gone — re-bootstrap costs ~5 minutes. Acceptable. Don't put session in Supabase to avoid this; the round-trip is worse than the rare loss.

### Open questions

1. **`media_info_v1` actually needed?** Depends on whether AI classification of restricted-account carousels matters. Defer decision to Stage 4.
2. **iluminatecz status.** Research doc flagged "unavailable in incognito" — might be fully deactivated, not just restricted. instagrapi's `user_id_from_username` will tell us decisively (raises `UserNotFound`). If deactivated, drop from re-enable list.
3. **Single cookie for 4 restricted + 3 active?** Currently only the restricted accounts use the cookie path. If we move all 7 to instagrapi in Stage 4, ~70 requests/day on Monday is still safe, but we should re-do the math then.

### Kill criteria

Roll back to two-tier Apify if any of:
- `ChallengeRequired` fires within 72 hours of Stage 2 start (burner is too hot to use).
- More than one `LoginRequired` in a 30-day window (sessions don't last long enough to operate).
- IPRoyal proxy outage > 1 hour during Monday cron (blocks the whole tier, not just instagrapi).

## 13. Effort breakdown

| Stage | Work | Hours |
|---|---|---|
| 1 | New module, integration branches, normalizer, bootstrap script, env wiring, docker-compose volume, justfile target | 6–8 |
| 1 | Smoke test on VPS, fixture capture, unit tests on normalizers | 2–3 |
| 2 | Watching soak + responding to any alerts | 1–2 (calendar-spread, not contiguous) |
| 3 | Config file edits + monitoring | 1 |
| - | Runbook docs (`docs/runbooks/instagrapi_session.md`) | 1–2 |
| - | Buffer for first-time-instagrapi friction (proxy URL format edge cases, login flow quirks) | 1–2 |
| **Total** | | **12–18h** |

The research doc's "6–8h" estimate was bare-minimum scraper-class work. Honest accounting includes the session bootstrap UX, Telegram wiring, tests, and four-stage rollout.

## 14. What we're NOT doing

- **No replacement of the primary Apify actor.** Public scraping on the 3 active accounts isn't broken; replacing a working cheap path with a self-hosted private API would expand cookie risk without benefit.
- **No multi-cookie pool rotation.** One burner cookie is enough for current volume (see §6). A pool adds coordination complexity (which cookie for which account? cross-cookie session conflict?) and is only worth doing if we hit the 200/day ceiling.
- **No instagrapi-rest container.** Single-container deploy is simpler; we have no other consumers of the IG API.
- **No HikerAPI integration.** The earlier research doc's Top-1 was HikerAPI; Option C is explicitly the self-host alternative. If self-host bans within 30 days, the doc's HikerAPI path is the cheapest pivot ($1 deposit unlocks it).
- **No automated cookie rotation.** When the cookie dies, it dies; the runbook is manual. Automation is post-v1, after we observe how often this actually happens.

---

### Critical Files for Implementation

- `/Users/andy/Desktop/Social_Bot/src/claude_social/scrapers/instagram.py`
- `/Users/andy/Desktop/Social_Bot/src/claude_social/scrapers/_instagrapi_client.py` (NEW)
- `/Users/andy/Desktop/Social_Bot/src/claude_social/config.py`
- `/Users/andy/Desktop/Social_Bot/scripts/bootstrap_instagrapi_session.py` (NEW)
- `/Users/andy/Desktop/Social_Bot/docker/docker-compose.yml`
