# Entity / finance / legality: context handed off from Social_Bot

Date: 07-08-2026

**Decided 07-08-2026 (Andy):** the legal-entity question keeps recurring across
projects and gets its own dedicated ongoing project covering tax, finance and
legality. This file is Social_Bot's contribution of facts. It deliberately does
NOT recommend a structure. Jurisdiction, entity type and tax treatment are that
project's decision, taken with a professional. A parallel extraction is being
made from a Claude app conversation that covered the same ground.

## Residency and current status (as stated by Andy, 07-08-2026)

- Irish tax resident. Already registered with Revenue.
- Lives in Slovakia over the summer.
- Holds no živnosť (Slovak sole-trader licence).
- No registered company anywhere. No VAT position.
- Not verified by me. Treat as Andy's account, to be confirmed before use.

## What the business actually is

Automated social-media monitoring sold as a recurring service. Scrapes public
competitor accounts on Instagram (TikTok tier built, dormant), classifies and
describes the content with an LLM, and renders a branded monthly .pptx report.
Delivery is a report plus, for some buyers, the underlying content feed.

Two revenue tracks are live in planning:
1. **Ireland-first cold outreach.** Two ICPs: social/marketing agencies (data-led
   pitch) and SMB consumer brands (report-led). Anchor EUR 200-400/mo per
   monitored brand. Free first report as the hook.
2. **Transit-operator vertical (now the priority).** Public transport operators
   benchmarked against European peers. Anchor EUR 500/mo. First target DPB
   Bratislava, a CITY-OWNED body, which is what forces the entity question now.
   See `research/marketing/transit_vertical_dpb.md`.

A separate business, Apify_Actor, runs in its own project and already has
customer revenue through the Apify marketplace. **Any entity decision has to
cover both**, since they share Andy and currently share a HikerAPI key.

Brand decided 01-08-2026: **Veritic** (`veritic.net`), with `veritic.ie`
possible for the Irish track.

## Why an entity is now blocking, not theoretical

DPB is a municipal company. It cannot pay an individual with no entity. It will
require, at minimum:
- A legal entity able to issue a compliant invoice, with a defined VAT position.
- A written service contract.
- Almost certainly a GDPR Data Processing Agreement.

Procurement note: EUR 500/mo = EUR 6,000/yr, which should fall under Slovakia's
low-value procurement threshold and avoid a public tender. **The threshold is
unconfirmed and needs checking** — it effectively caps the price, because
crossing it converts a direct purchase into a tender.

Cross-border question this raises and does not answer: an Irish tax resident
invoicing a Slovak municipal body. Where the trade should sit is exactly what the
new project is for.

## Cost base (real numbers, useful for any projection)

Very low and mostly usage-based:
- **Supabase Pro** USD 25/mo (upgraded 05-08-2026, 100 GB file storage). The only
  fixed subscription.
- **DigitalOcean droplet** running the VPS, small (961 MB RAM, has been OOM-killed
  by a large archive job before).
- **HikerAPI** pay-per-request at ~USD 0.001/req. Whole 13-day, 6-account Hell
  demo cost ~USD 0.32. Balance was USD 90.6 for ~90k requests. **Key is shared
  with Apify_Actor**, so the balance is not attributable to one business.
- **Apify** free tier, USD 5/mo of credit, used only for fallback and TikTok.
- **Gemini** flash-tier calls, cents per month at current volume.
- **Google Drive** on a consumer Gmail account. Flagged in the GDPR report as
  having no DPA, which must be fixed before a first paying client.

Marginal cost of an additional client in the same vertical is close to zero,
because the scraped dataset is shared. This matters for how revenue is modelled.

## Compliance state already assessed

`research/gdpr_compliance_report.md` (07-07-2026) rated the operation Low-Medium
risk for public business accounts. The open blockers are paperwork, not code:
- LIA, RoPA and a mini-DPIA.
- Processor DPA inventory: Supabase, DigitalOcean, HikerAPI, Apify, Google,
  Telegram.
- A client data-terms contract template.
- Consumer-Gmail Drive archives have no DPA.
- Supabase and DigitalOcean regions need verifying.
Ireland and Slovakia are the same GDPR regime, and contracts can be in English.
Tracked as a Medium Notion task, "GDPR paperwork pack".

## Open questions for the new project

1. Where should the trade sit given Irish tax residency plus Slovak summer
   presence, and Slovak and Irish customers on both sides?
2. Entity type and VAT: does invoicing a Slovak municipal body change the answer?
3. One entity for both Social_Bot and Apify_Actor, or separate?
4. Slovak low-value procurement threshold, confirmed figure.
5. Shared-cost attribution between the two businesses, starting with the shared
   HikerAPI key.
6. What Apify marketplace revenue is already being received and how it is
   currently treated.
