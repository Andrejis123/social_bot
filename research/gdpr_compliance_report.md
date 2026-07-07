# GDPR Compliance Assessment: Social_Bot (pre-production)

Date: 07-07-2026
Scope: the Social_Bot service as planned for production: Instagram scraping of public business accounts + data delivery (zip archive) + monthly PPTX report generation, sold to a business client for competitor monitoring.
Related prior work: `research/apify_actor_market_research.md` section 10 (GDPR deep-dive for the Apify actor spin-off). This report covers the Social_Bot service itself, which has a narrower risk profile (fixed small account set, one client, operator-controlled scope).

---

## 1. Executive summary

| Dimension | Verdict |
|---|---|
| Overall risk | **Low-Medium** for public *business/brand* accounts; Medium-High if personal accounts ever enter scope |
| Lawful basis | Art. 6(1)(f) legitimate interest is viable, but a documented LIA is **mandatory homework, not yet done** |
| Hard blockers | None technical. Two paper blockers: no LIA/RoPA/DPIA documentation, no DPAs with processors |
| Biggest processor gap | Consumer Google Drive (gmail.com account) holds archive zips: no processor DPA available on consumer tier |
| Biggest technical gap | `raw_payload` stores the full scraper JSON (data minimisation), 10-year signed URLs (Art. 32) |
| Strongest existing asset | Deletion tooling is real and tested (archive/purge/tombstone, storage+Drive orphan sweepers): Art. 17 is executable today |

The service is defensible as a B2B competitive-monitoring tool over public business accounts, operated at small scale (single-digit accounts, one client). The compliance work needed before production is mostly **documentation and contracts**, plus two or three targeted technical fixes. Nothing requires re-architecting.

---

## 2. Processing inventory (what the system actually does)

Data collected per monitored account (source: `migrations/0001+`, `scrapers/instagram.py`, ingest pipeline):

| Data | Where | Personal-data status |
|---|---|---|
| Posts: caption, permalink, timestamps, type | `posts` table | Yes: captions can name/@mention individuals; account handle identifies the operator |
| **Full raw scraper item** | `posts.raw_payload`, `stories.raw_payload` (jsonb) | Yes: includes owner user object (username, full name, profile pic URL, pk) and whatever else HikerAPI/Apify returns (tagged users, mentions) |
| Media files (images/video incl. stories, reel covers) | Supabase Storage bucket; archived to Drive zips | Yes: photos/videos of identifiable persons |
| Engagement metrics (likes/comments/views counts) | `post_metrics` | Aggregated counts only: low risk (no commenter identities are scraped) |
| AI outputs (category, description, synthesis narratives) | `posts`/`stories` AI columns, `synthesis_artifacts` | Derived; can describe depicted persons |
| Run/ops logs | `run_history`, `run_item_errors`, VPS logs | Handles only; low risk |

Not collected (relevant, keep it that way): commenter identities, comment text, follower lists, DMs, location data of individuals.

Processing chain and parties:

1. **HikerAPI** (primary scraper) and **Apify** actors (fallback): external scraping providers.
2. **Gemini (Google)** and **OpenAI** (fallback): captions + media bytes sent for classify/describe/synthesis. Both operate US infrastructure.
3. **Supabase**: Postgres + Storage (project `yscnquudhzfyvtpimolr`; **region unverified, check dashboard**: EU region strongly preferred).
4. **Google Drive**: archive zips (cold storage) + report copies + Live View folders, under a consumer gmail.com account.
5. **Telegram**: bot notifications; report files are pushed through Telegram servers.
6. **DigitalOcean VPS** (161.35.170.254): runtime; region unverified (likely AMS/FRA, confirm).

---

## 3. Controller/processor analysis

- **Operator (Andy) is a controller** for the scraping pipeline: he determines means (which API, which fields, retention) and largely the purposes. Depending on the client contract, the realistic framing is **independent controller providing a monitoring service** (client picks target accounts and receives outputs) rather than a pure Art. 28 processor: the pipeline retains and reuses data on its own schedule. Either framing requires a **written data-terms agreement with the client** allocating roles; pick one and write it down.
- **Processors of the operator**: Supabase, DigitalOcean, Google (Drive + Gemini API), OpenAI, Telegram, Apify: each needs a DPA (Art. 28). All except consumer Drive and Telegram offer standard DPAs.
- **HikerAPI** is an independent controller for its own scraping infrastructure; document reliance, but their compliance is not inheritable: your processing is your own.

---

## 4. Lawful basis (Art. 6)

Only **Art. 6(1)(f) legitimate interest** is available (no consent channel, no contract with data subjects). Three-part LIA:

1. **Purpose**: competitive market monitoring for a business client: recognised commercial interest. Passes.
2. **Necessity**: monitoring public brand communications cannot be done less intrusively at practical cost. Passes for business accounts.
3. **Balancing**: business accounts publish deliberately for public reach: low reasonable-expectation-of-privacy. Balancing holds **provided**: (a) only business/brand accounts, (b) no commenter/follower harvesting, (c) bounded retention, (d) no profiling of individuals.

"Public data" is not itself a lawful basis (EDPB, Dutch AP, CNIL, Garante consistent on this): the LIA document is what makes the processing defensible. **It does not exist yet: writing it is the top action item.**

Special-category caution (Art. 9): monitoring accounts whose content reveals religion/health/politics (e.g. a church client's community photos: identifiable congregation members imply religious belief) can technically touch Art. 9 data, where legitimate interest is NOT available. For a client's **own** accounts, cover it in the client contract (client warrants it has the right to have its content processed). Avoid taking on *competitor* monitoring of religious/health/political organisations.

---

## 5. Risk evaluation

| # | Risk | Severity | Likelihood | Notes |
|---|---|---|---|---|
| R1 | No LIA/RoPA documentation if an SA asks | High | Low (SK/CZ SA, tiny scale) | Pure paperwork; cheap to fix |
| R2 | Consumer Drive holds personal-data archives without DPA | Medium | Medium | Structural: consumer Google terms make YOU responsible with no processor guarantees |
| R3 | `raw_payload` over-collection (tagged users, full user objects) | Medium | Medium | Data minimisation (Art. 5(1)(c)); also inflates erasure surface |
| R4 | US transfers (Gemini, OpenAI, possibly Supabase/DO region) without documented safeguards | Medium | Low | All vendors offer SCCs/DPF; needs paper, not code |
| R5 | 10-year signed URLs on stored media | Medium | Low | Accepted by design for usability; for GDPR it is an Art. 32 weakness: any leaked report URL exposes media for a decade |
| R6 | No data-subject-rights intake channel | Medium | Low | Deletion tooling exists; the missing piece is a contact point + procedure |
| R7 | Unbounded retention of Drive zips + `raw_payload` | Medium | Medium | Storage-purge exists for Supabase; define retention for archives too |
| R8 | AI providers training on submitted content | Low | Low | Gemini API + OpenAI API default to no-training for API traffic; verify + pin in settings |
| R9 | Telegram delivery of reports (personal data in slides) | Low | Low | Reports contain brand content + hero images; keep them business-content-only |
| R10 | Scaling to personal accounts / more clients invalidates the LIA | High | Controlled | Re-run this assessment before any scope change |

Enforcement reality: lead SA would be the Slovak DPA (ÚOOÚ SR): historically low enforcement intensity, and this is a narrow B2B tool over a handful of business accounts. The Clearview-class fines targeted mass biometric scraping of personal data. Residual risk after mitigations: **Low**.

---

## 6. Blockers before production (must-do)

1. **Write the LIA** (legitimate interest assessment, the 3-part test above) and a **Records of Processing (Art. 30)** doc: one afternoon, template-driven. Store in `docs/compliance/`.
2. **Conduct a lightweight DPIA** (Art. 35): systematic monitoring is on most SAs' indicative DPIA lists; even a 2-page DPIA proactively closes the "you should have done one" argument.
3. **Client contract with data terms**: role allocation (controller/controller or Art. 28), client warrants targets are business accounts, client responsibility for downstream use of the zip.
4. **Sign/collect processor DPAs**: Supabase, DigitalOcean, Google Cloud (Gemini API), OpenAI, Apify: all are click-through. Record where each is filed.
5. **Fix the Drive problem** (pick one):
   - Move archives to **Google Workspace** (Business Starter, ~7 EUR/mo: gives a real DPA + EU data-region controls), or
   - Keep archives in Supabase-adjacent storage with a DPA (e.g. a second bucket / cheap S3-compatible EU storage), or
   - Accept documented risk for the prototype phase, migrate before first paying client. **Do not** leave this unaddressed once revenue starts.
6. **Verify regions**: Supabase project region and DO droplet region. If either is US, prefer migrating to EU at the next natural opportunity; until then, SCCs/DPF cover it on paper.

## 7. Mitigations (should-do, mostly cheap)

1. **Trim `raw_payload`** at ingest: keep only fields the pipeline can actually re-derive from (drop tagged-user arrays, third-party user objects; keep the owner block + media descriptors). Reduces both minimisation exposure and the Art. 17 erasure surface. Medium effort: touches ingest, one migration for backfill-or-null.
2. **Shorten signed URL TTL** for anything embedded in deliverables (e.g. 90 days) OR document the 10-year decision with compensating controls (bucket non-listable, unguessable paths).
3. **Retention policy**: state it (e.g. "raw media 12 months in archive, DB rows 24 months, then hard-delete") and wire it into the existing archive/purge + orphan-sweep tooling: the mechanics already exist and are tested, which is unusual and good.
4. **Rights procedure** (1 page): an email contact; on erasure request for a depicted individual: locate via handle/post, use the storage-first delete + `cleanup_storage_orphans` + `cleanup_drive_orphans` flow. The tooling makes 30-day compliance trivial.
5. **Pin no-training flags**: confirm Gemini API data-usage settings and OpenAI API (default off) and note in `tools_inventory`/RoPA.
6. **Business-accounts-only rule**: encode as a stated constraint in client onboarding docs and config review, mirroring the Apify-actor mitigation list.
7. **Transparency**: Art. 14 notice to scraped account operators is formally required; rely on the Art. 14(5)(b) disproportionate-effort exemption at this scale, but **document that reliance** in the LIA, and put a public privacy notice on whatever website/landing page sells the service.

## 8. What is already in good shape

- **Erasure capability**: storage-first delete invariant, row-independent orphan sweepers (Supabase + Drive), tombstone/restore semantics: Art. 17 execution is provably real (round-trip tested 04-07-2026).
- **Data minimisation partially respected**: no commenter identities, no follower lists, no DMs, metrics are aggregate counts.
- **Access control**: single-operator system, secrets in `.env`, no public endpoints, one-way Telegram bot.
- **Small scale**: seven-ish accounts, one prospective client: keeps every balancing test and the enforcement profile favourable.
- **Prompt-injection hardening** in synthesis (22-06-2026): reduces the risk of scraped content exfiltrating other data through AI calls.

## 9. Suggested step order

1. LIA + RoPA + mini-DPIA (docs only, no code) → `docs/compliance/`
2. Collect processor DPAs + verify Supabase/DO regions (an hour of clicking)
3. Client data-terms template (before first contract signature)
4. Drive decision (Workspace upgrade vs EU bucket) before first paying client
5. `raw_payload` trim + retention wiring (code; schedule as a normal Notion task)
6. Re-run this assessment when: a new client signs, personal accounts are requested, TikTok lands, or the Apify actor launches (that product has its own, higher-risk assessment in the market-research doc).

---

*Assessment produced with the gdpr-dsgvo-expert skill, grounded in the repo schema (`migrations/`), scraper field inventory (`scrapers/instagram.py`), and the storage/deletion tooling. Not legal advice; for the client contract and DPA review, a one-off consultation with a Slovak/Czech data-protection lawyer is recommended.*
