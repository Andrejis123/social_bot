# TikTok Platform Expansion: Research + Integration Plan

*Research date: 2026-06-29*
*Status: complete. Scraping capability, policy, vendor pricing, and ecig-brand presence all researched.*

## TL;DR

- TikTok content maps cleanly onto our existing shapes: **regular videos = posts/reels**, **Photo Mode = carousels**, **Stories = stories** (24h, scrapeable). Our `Scraper` protocol already has the right fields.
- **No official commercial API.** TikTok's Research API is non-commercial (academic/non-profit only) and lags content 48-72h — unusable for us. Display/Business APIs don't fit competitor monitoring.
- **TikTok is materially harder to scrape than Instagram** and breaks more often (multi-layer crypto-signed headers + device-trust + ML detection + endpoint churn every 4-8 weeks). Plan for higher maintenance and a managed third-party vendor rather than raw scraping.
- **Architecture impact is small**: add a `TikTokScraper` conforming to the existing `Scraper` protocol, register it, add `"tiktok"` accounts. The pipeline is already platform-agnostic on a `(platform, handle)` key.
- **Per-client scoping:** the ecig accounts we monitor (pulzeczech, pulzecz, ploom.cz, iqos_cz) have no TikTok presence, so there's nothing to scrape there — same as Facebook, where not all accounts had a presence. TikTok also prohibits tobacco/vape content platform-wide. Expansion gets scoped per-client to whoever actually posts on TikTok. See §5.
- **Vendor tiers + pricing resolved** (§4): primary = EnsembleData (unit-based, 50 units/day free, ~$100/mo entry); fallback = Apify clockworks actors (pay-per-result, ~$0.005-0.010/item).

---

## 1. Content model — what's scrapeable, and how it maps to us

| Our IG concept | TikTok equivalent | Scrapeable? | Notes |
|---|---|---|---|
| Feed post / reel | Regular video (vertical, all "reels") | Yes | Full metadata via 3rd-party; Research API non-commercial only |
| Story | TikTok Story | Yes, 24h window | 3rd-party only (no Research API endpoint); same ephemeral capture constraint as IG |
| Carousel/album | Photo Mode (up to 35 images) | Yes | `carousel_images` array in 3rd-party APIs; Research API lacks explicit carousel schema |
| Pinned post | Pinned video (up to 3) | Yes | Subset of regular video; identifiable on profile |
| Highlights | No direct equivalent | N/A | Playlists exist (evergreen series), not curated highlights |
| LIVE | TikTok LIVE | Limited | Ephemeral; only useful if polled during stream — **low priority** |
| — | Repost | Yes | Available but low value for competitor monitoring |
| — | Playlist | Yes | `playlist_id` on each video |

**Per-video public fields** (Research API field names, mirrored by 3rd-party scrapers): `id`, `video_description` (caption), `create_time` (Unix UTC = our `posted_at`), `video_duration`, `username`, `region_code`, `view_count`, `like_count`, `comment_count`, `share_count`, `favorites_count`/`collect_count` (= saves), `music_id`, `hashtag_names`, `voice_to_text` (auto captions), `video_tag` (AIGC/branded flag). 3rd-party scrapers (e.g. Bright Data) return 41-48 fields/video including `video_url`, cover image URLs, resolution, bitrate.

**Engagement coverage vs our `ScrapedPost`**: we already carry `like_count`, `comment_count`, `view_count`, `play_count`, `save_count`, `share_count` — TikTok fills all of these (view/play distinction matters less here; TikTok exposes a single `view_count` plus `collect_count` for saves).

**Stories specifics**: max 15s, 24h expiry, surface on FYP (unlike IG follower-only), public comments, requires 1,000+ followers. Apify's TikTok Story Viewer returns play/digg/comment/share/download/collect counts, watermarked + clean video URLs, duration, cover, music, ISO timestamp. **No historical archive after expiry** — needs near-real-time nightly polling exactly like our IG stories cron.

**Caveats / uncertain (per agent research):**
- Music title/artist fields frequently empty since an early-2026 UMG dispute — `music_id` present, names degraded. Don't rely on music metadata.
- Carousel `view_count` may count per-swipe vs per-post depending on source — not well documented.

---

## 2. Official APIs — none fit commercial competitor monitoring

- **Research API**: non-profit/academic only in US/EEA/UK/CH/NO/IS/LI/BR; commercial entities explicitly excluded. 4-week approval, research proposal + ethics review required. Quotas 1k req/day, 100k records/day, 100 records/req. New content lags 48-72h. EU has a DSA Art.40 "vetted researcher" path (live from 2025-10-29) — still not us. **Verdict: unusable.**
- **Display API**: case-by-case written approval, oriented to embedding/displaying content, not bulk extraction. High friction.
- **TikTok for Business / Commercial Content API**: ads + Shop focused. Not organic competitor content.

**Conclusion:** same posture as IG — we go through a third-party scraping layer, not an official API.

---

## 3. Scraping policy & enforcement — harder than Instagram

TikTok's anti-scraping stack is described by 2025-2026 sources as among the most sophisticated of any platform:

- **Crypto-signed headers (mobile API)**: every request needs `X-Argus`, `X-Gorgon`, `X-Ladon`, `X-Khronos` (device trust, SM3 integrity hash, session binding, anti-replay timestamp). Web uses a parallel system (`MSToken`, `_signature`, `X-Bogus`).
- **Device trust scoring**: new/unregistered device identities get rate-limited or served *degraded/truncated data* (empty stats, missing fields) before any hard block — a silent failure mode that's hard to detect in a cron.
- **Behavioral/fingerprint detection**: canvas/WebGL fingerprinting, timing analysis, ML fraud scoring. Unauthenticated sessions hit limits within a few page views.
- **TikTok publicly states** it uses CAPTCHAs, device/network/interaction monitoring, rate limiting and detection to combat scraping.

**Churn / breakage cadence (operationally the most important):**
- API endpoints change every **4-8 weeks**; web frontend every **2-4 weeks**; signature algorithms updated frequently and undocumented.
- vs IG: Instagram's main break vector is the single GraphQL `doc_id` rotation (2-4 weeks) — well-known, community-patched fast. TikTok's is **multi-layered**, so each break is harder to diagnose/fix.

**Reliability bottom line:** premium vendors hit ~99% success on TikTok *with dedicated residential proxies + maintained device identities*, but commodity scrapers fall below 90% (Apify's TikTok success rate reported sub-90%, vs staying above for IG/FB). **Implication: lean on a managed vendor, expect more maintenance than IG, and build degradation detection (empty-stats / truncated-list = failure, not success).**

---

## 4. Vendor landscape (primary + fallback tiers)

Candidates (HikerAPI-equivalents and Apify actors), pricing confirmed via web search 2026-06-29:

| Vendor / actor | Type | What | Pricing (confirmed) | Media? | EU? |
|---|---|---|---|---|---|
| **EnsembleData** | Private-API SaaS | TikTok profile/posts/hashtag/stories | **Unit-based**: 1-10 units/call; **50 units/day free**; paid $100-$1,400/mo by volume (daily reset, no carryover) | Yes (URLs) | Yes |
| **clockworks/tiktok-profile-scraper** (Apify) | Apify actor | Profile videos | **$0.005/item** ($5/1k), pay-per-result | Yes | Yes |
| **clockworks/tiktok-video-scraper** (Apify) | Apify actor | Single videos | **$0.010/item** ($10/1k) | Yes | Yes |
| **clockworks/tiktok-scraper** (general) | Apify actor | Profile/hashtag/search/comments | ~**$1.70/1k** (confirm on Pricing tab) | Yes | Yes |
| **Apify TikTok Story Viewer** (igview-owner) | Apify actor | Stories within 24h | Per-result (confirm tab) | Yes (clean + WM) | Yes |
| LamaTok / ScrapTik / TikAPI | RapidAPI-style private-API | TikTok endpoints | Varies; positioned vs EnsembleData | Varies | Verify |
| Bright Data TikTok Scraper | Managed scraper | 41-48 fields/video, ~99% success | Premium (higher) | Yes | Yes |

**Pricing-model note (matches our `feedback.md` Apify caution):** EnsembleData bills **daily units that reset and don't carry over** — budget by peak-day usage, not monthly total. Apify clockworks actors are **pay-per-result** (no rental, no obvious per-event surcharge found, but dry-run 1-3 items and check the Pricing tab before any cron run, per our standing rule).

**Tier recommendation** (mirrors IG's HikerAPI→Apify):
- **Primary**: EnsembleData for posts + stories — fast, returns media, unit model. For ~5 accounts scraped weekly (posts) + nightly (stories), the **50 units/day free tier** plausibly covers it or the **$100/mo entry plan** does; confirm unit cost per endpoint in their docs against our cadence before committing.
- **Fallback**: `clockworks/tiktok-profile-scraper` (posts, $0.005/item) + Story Viewer actor (stories) on Apify — same pattern we already run for IG. At ~5 accounts the monthly Apify spend is trivial (well within or near the $5 free credit for posts; stories add volume).

This pairing slots directly into the existing tiered `TikTokScraper` design (§6) with no pipeline change.

---

## 5. Content restrictions & ecig-client impact — RESOLVED: NO-GO for ecig

- **Tobacco/vape policy is platform-wide, not just ads.** TikTok's Community Guidelines ("Regulated Goods, Services, and Commercial Activities") prohibit cigarettes, cigars, tobacco, nicotine, e-cigarettes, vape pens, vape oils/cartridges and other smoking/nicotine alternatives — **including devices without tobacco content**. This is broader than IG's ad-restriction posture: it targets the content itself, so brand organic content is disallowed, not merely un-advertisable.
- **Enforcement is imperfect but the brands stay off.** Research (PMC, marketing press) shows e-cig content does leak through via third parties/reviewers, and vape ads get banned when they appear — but the *brands themselves* (IQOS, Ploom, Glo, Lil) do not run sanctioned organic accounts the way they do on IG.
- **Account-existence check (CZ/SK)**: no dedicated IQOS or Ploom TikTok account was found for Czech/Slovak market. IQOS CZ/SK presence is on **Instagram** (@iqos_cz, @iqos.slovakia) and **YouTube** — not TikTok.
- **Age-gating**: where age-restricted content exists, profile reachability can differ from FYP eligibility — but this is moot for ecig given the brands aren't present.

### Impact on ecig-monitoring client
The accounts we currently monitor for the ecig client — **pulzeczech, pulzecz, ploom.cz, iqos_cz** — have no TikTok presence. Nothing to note beyond the obvious: we can't scrape an account that isn't there, and no client will ask us to monitor a platform their competitors aren't on. Same situation as Facebook, where not all testing accounts had a presence either. TikTok expansion simply gets scoped per-client to whoever actually posts there.

### Where TikTok expansion DOES make sense
Our **non-ecig** clients — agape (agapeslovensko, agape_bratislava) and iluminatecz — face no such content prohibition. If any of them have (or plan) a TikTok presence, that is the right pilot for TikTok expansion. **Confirm those clients' TikTok handles before building.**

---

## 6. Integration plan (high-level) — small surface, existing abstraction

The codebase is already platform-agnostic. Account identity is the `(platform, handle)` natural key; the pipeline consumes normalized `ScrapedPost` / `ScrapedStory` shapes from any `Scraper`. Adding TikTok is mostly **one new scraper class + registration + config + client YAMLs**, not a pipeline rewrite.

**Phase 0 — Decision gate (no code):** ecig is NO-GO (§5) — do not build TikTok for the ecig client. Gate is now: **confirm a non-ecig client (agape or iluminatecz) has a TikTok presence worth monitoring**, then sign up for EnsembleData (free tier) and dry-run a real handle to validate field coverage before writing the adapter.

**Phase 1 — Scraper adapter:**
- Add `src/social_bot/scrapers/tiktok.py` implementing the `Scraper` protocol: `platform = "tiktok"`, `scrape_posts(...)`, `scrape_stories(...)`, sets `discovered_platform_account_id` (TikTok internal `sec_uid`/user id) so subsequent runs skip the username→id lookup, exactly like IG's `pk`.
- Tiered internally: private-API SaaS primary → Apify actor fallback, mirroring `instagram.py`. Same defensive `.get(...)` + preserve full `raw` dict.
- Map TikTok fields → `ScrapedPost` (`post_type`: `video`/`carousel`; metrics all available) and `ScrapedStory`.
- **Degradation guard**: treat empty-stats / truncated lists as failure → fall through tiers (TikTok's silent-degrade behavior, §3).
- Register `"tiktok": TikTokScraper` in `scrapers/registry.py`.

**Phase 2 — Config & secrets:**
- New settings in `config.py`: `tiktok_api_key` (primary SaaS), `apify_tiktok_actor`, `apify_tiktok_story_actor`. Graceful degradation when primary unset (Apify-only), same as IG.
- Add `platform: tiktok` accounts to client YAMLs in `config/clients`.

**Phase 3 — Pipeline & storage:** expected to be **no-op** — `ingest_posts`/`ingest_stories`, describe (Gemini), Supabase storage, and the pptx renderer are platform-agnostic. Verify dedup (`platform_post_id` numeric pk vs shortcode — confirm TikTok's id choice matches our dedup convention) and media optimization handles TikTok video/Photo-Mode.

**Phase 4 — Reporting:** confirm renderer/synthesis copy doesn't hardcode "Instagram"; @handle rule and house palette already platform-neutral. TikTok metric labels (views-centric) may want a tweak vs IG.

**Phase 5 — Cron:** add TikTok scrape/describe jobs to the VPS crontab mirroring IG cadence (weekly posts, nightly stories). Rebuild image (`just deploy`), `just deploy-check`.

**Protocol** (per CLAUDE.md): Exploration → /write-tests (failing) → code → tests → debug/iterate, real-data run before "done".

**Anti-over-engineering notes:** skip LIVE and Reposts (low value). Don't build a generic multi-vendor abstraction beyond the two-tier pattern we already use. Don't touch the renderer until a real TikTok scrape proves the data shape.

---

## 7. Open items (mostly resolved)

1. ~~**[GO/NO-GO] ecig brand presence on TikTok in CZ/SK.**~~ **RESOLVED → NO-GO** (§5). Tobacco/vape prohibited platform-wide; no IQOS/Ploom CZ/SK TikTok accounts.
2. ~~**[Pricing] Vendor pricing.**~~ **RESOLVED** (§4). EnsembleData unit-based (50/day free, $100-$1,400/mo); Apify clockworks pay-per-result ($0.005-0.010/item). No per-event surcharge found; still dry-run before any cron.
3. **[Client] Non-ecig TikTok presence.** Confirm whether agape / iluminatecz have TikTok handles worth monitoring — this is now the real GO/NO-GO for the expansion (replaces the ecig gate).
4. **[Verify-at-build] EnsembleData unit cost vs our cadence.** Confirm per-endpoint unit cost in their docs against ~5 accounts weekly posts + nightly stories, to know whether the free tier or the $100 plan is needed.
5. **[Dedup] TikTok post id.** Confirm TikTok video `id` is the stable numeric pk for our `platform_post_id` dedup (matches the IG numeric-pk decision). Validate during the Phase-0 dry-run.
6. **[GDPR] TikTok-specific scraping considerations** — fold into the existing GDPR compliance Notion task rather than duplicating here.

---

## Sources (from completed scraping/policy research)

- TikTok Research API Video Specs / Eligibility / FAQ — developers.tiktok.com (official)
- TikTok "How We Combat Unauthorized Scraping" — tiktok.com/privacy/blog (official)
- scrapebadger.com — TikTok Scraping APIs in 2026 (deep guide)
- scrapfly.io — How To Scrape TikTok in 2026 / Guide to TikTok API
- decodo.com — Scrape TikTok 2026; multilogin.com — TikTok IP ban 2026
- aimultiple.com — Social media scrapers benchmarked 2026; socialcrawl.dev — Best scraping APIs 2026
- Apify TikTok Story Viewer (igview-owner); Apify clockworks/tiktok-scraper
- sociavault.com, measure.studio, SocialBee, echotik.live, buffer.com, scrapegraphai.com (2025-2026)

**Resolved §4-5 (web search 2026-06-29):**
- EnsembleData pricing — ensembledata.com/pricing; Blotato "TikTok API Pricing 2026"; LamaTok comparison
- Apify clockworks actor pricing — apify.com/clockworks/tiktok-profile-scraper, /tiktok-video-scraper, /tiktok-scraper
- TikTok tobacco/vape prohibition — tiktok.com/community-guidelines (Regulated Goods); ads.tiktok.com dangerous-products policy; PMC "Promotion of E-Cigarettes on TikTok"; marketingweek.com "Four TikTok vape ads banned"
- ecig CZ/SK presence — IQOS on Instagram (@iqos_cz, @iqos.slovakia) + YouTube; no dedicated TikTok account found
