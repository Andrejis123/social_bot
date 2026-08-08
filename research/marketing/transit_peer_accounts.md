# Transit-operator peer accounts (candidate scrape list)

Date: 08-08-2026. Handles probed against HikerAPI on the night of 07-08-2026,
so "last post" dates and the story snapshot are stamped that evening.

Companion to `transit_vertical_dpb.md` (strategy, outreach rules, pricing) and
`entity_finance_handoff.md` (the blocker). This file is the account layer only:
which Instagram accounts actually exist, are alive, and are worth paying to
scrape.

## How this list was built

Every handle here was resolved through HikerAPI `/v2/user/by/username`, not
taken from a search result. Search generated candidates, the API decided. About
240 lookups plus 80 media-page calls plus 50 story calls, well under a dollar in
total. A handful of follow-up probes ran just after midnight, so two rows carry
an 08-08-2026 stamp.

Accept criteria: resolves to a real pk, public (not private), 500+ followers,
identity confirmed by full_name/bio naming the operator, and a post inside the
last 180 days. Rejections are recorded at the bottom so nobody re-litigates
them next session.

**Read `Posts/30d` as a floor, not a count.** It is measured from ONE media page
(12 items), so any account posting more than 12 times in 30 days shows as 12.
This is deliberately not a cadence figure. The hell demo already produced one
pitch number that turned out to be a media-file count rather than a content
count, and that mistake is not worth repeating on a public-body pitch.

Level column: `operator` runs the vehicles, `authority` runs the integrated
system or tariff, `rail` is national rail. **Benchmark at operator level.** DPB
is an operator, and the resale targets (DPMK, DPMŽ, DPP) are operators too.
Mixing in authorities compares a transport company's feed against a whole
region's marketing budget. The authorities in the list are kept because in a few
cities the authority account is the live one (Warszawa, Praha, Helsinki,
Stockholm, Oslo, London), and Praha usefully has both.

## Tier 1: core set for the DPB sample deck (14 accounts)

DPB itself plus 13 peers, weighted CZ/AT/PL/HU exactly as the brief asks. This
is the set to scrape first. @wienerlinien is in as the acknowledged
best-in-class, @dpmk_as is in as both a peer and the next sales target.

| C | City | Operator | Handle | Followers | Posts | Last post | Posts/30d | Live stories | Level | IG pk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AT | Wien | Wiener Linien | `@wienerlinien` | 112,408 | 2,770 | 07-08-2026 | 10 | 12 | operator | `329677014` |
| AT | Graz | Holding Graz Linien | `@holding_graz` | 16,606 | 4,338 | 07-08-2026 | 11 | 5 | operator | `4707702640` |
| AT | Salzburg | Salzburg Verkehr | `@salzburg_verkehr` | 8,409 | 1,088 | 07-08-2026 | 11 | 2 | operator | `48005873305` |
| CZ | Praha | PID Lítačka | `@pidoficialni` | 33,506 | 2,845 | 06-08-2026 | 12 | 0 | authority | `1600328473` |
| CZ | Praha | DPP Praha | `@dppoficialni` | 24,123 | 1,011 | 06-08-2026 | 9 | 4 | operator | `7187423702` |
| CZ | Brno | DPMB Brno | `@dpmbofficial` | 14,502 | 1,919 | 06-08-2026 | 12 | 0 | operator | `2661073346` |
| CZ | Ostrava | DPO Ostrava | `@dpostrava` | 11,923 | 772 | 05-08-2026 | 12 | 0 | operator | `4085750152` |
| DE | Berlin | BVG Berlin | `@bvg_weilwirdichlieben` | 246,913 | 5,163 | 07-08-2026 | 12 | 2 | operator | `1591712214` |
| DE | München | MVG München | `@muenchen.mvg` | 27,443 | 967 | 07-08-2026 | 12 | 0 | operator | `57702227570` |
| HU | Budapest | BKK Budapest | `@bkkbudapest` | 28,944 | 2,620 | 07-08-2026 | 11 | 2 | authority | `456069851` |
| PL | Warszawa | WTP Warszawa | `@wtp_warszawa` | 13,974 | 2,907 | 07-08-2026 | 12 | 1 | authority | `1603227198` |
| PL | Kraków | MPK Kraków | `@mpk_krakow` | 13,571 | 999 | 01-08-2026 | 9 | 0 | operator | `3113865873` |
| SK | Bratislava | **DPB (report subject)** | `@dpbratislava` | 12,087 | 821 | 07-08-2026 | 9 | 0 | operator | `6352227885` |
| SK | Košice | DPMK Košice | `@dpmk_as` | 2,229 | 529 | 07-08-2026 | 10 | 2 | operator | `28619914948` |

## Tier 2: domestic resale targets and second-ring peers (17 accounts)

Two jobs. The SK/CZ entries are the accounts of the operators we intend to SELL
to next, so having their own history already scraped makes the second and third
pitch nearly free. The DE entries are mid-size German operators, the closest
structural analogues to DPB by city size, and a better comparison set than
Berlin or London.

| C | City | Operator | Handle | Followers | Posts | Last post | Posts/30d | Live stories | Level | IG pk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AT | Linz | Linz AG Linien | `@linz_ag` | 7,678 | 962 | 06-08-2026 | 9 | 0 | operator | `1344805084` |
| CZ | Olomouc | DPMO Olomouc | `@dpmo_official` | 4,775 | 2,226 | 07-08-2026 | 11 | 0 | operator | `4040450519` |
| CZ | Liberec | DPMLJ Liberec | `@dpmlj` | 1,474 | 140 | 30-07-2026 | 1 | - | operator | `8232767280` |
| DE | Hannover | üstra Hannover | `@uestra` | 32,614 | 1,619 | 07-08-2026 | 12 | 1 | operator | `2476049902` |
| DE | Hamburg | Hamburger Hochbahn | `@hochbahn_` | 32,533 | 376 | 06-08-2026 | 11 | 0 | operator | `61535897824` |
| DE | Stuttgart | SSB Stuttgart | `@ssb_ag` | 31,609 | 1,770 | 05-08-2026 | 12 | 0 | operator | `3154390465` |
| DE | Köln | KVB Köln | `@kvbag` | 28,483 | 1,440 | 06-08-2026 | 10 | 0 | operator | `1183584038` |
| DE | Düsseldorf | Rheinbahn | `@rheinbahn` | 23,070 | 2,345 | 07-08-2026 | 11 | 1 | operator | `1428505464` |
| DE | Nürnberg | VAG Nürnberg | `@vagnuernberg` | 16,972 | 1,354 | 07-08-2026 | 12 | 1 | operator | `5961926711` |
| HU | Budapest | BKV Zrt. | `@bkvzrt_official` | 6,190 | 956 | 07-08-2026 | 9 | 0 | operator | `8577531525` |
| PL | Łódź | MPK Łódź | `@mpk_lodz` | 9,177 | 3,691 | 07-08-2026 | 12 | 0 | operator | `2195493106` |
| PL | Wrocław | MPK Wrocław | `@mpkwroclaw` | 8,607 | 1,458 | 07-08-2026 | 12 | 1 | operator | `2280583631` |
| PL | Gdańsk | Gdańskie Autobusy i Tramwaje | `@gaitgdansk` | 7,134 | 3,336 | 07-08-2026 | 12 | 0 | operator | `506219044` |
| PL | Poznań | MPK Poznań | `@mpkpoznan_official` | 3,569 | 591 | 07-08-2026 | 10 | 3 | operator | `47008082797` |
| SK | Bratislava | IDS BK | `@ids_bk` | 1,400 | 337 | 07-08-2026 | 10 | 0 | authority | `20525162815` |
| SK | Žilina | DPMŽ Žilina | `@mhdzilina` | 1,268 | 304 | 01-08-2026 | 3 | 0 | operator | `17135116262` |
| SK | Prešov | DPMP Prešov | `@dpmp_as` | 596 | 229 | 04-08-2026 | 9 | 0 | operator | `74028947305` |

## Tier 3: wider European tail and rail (33 accounts)

Verified and available, not needed for the first deck. Useful as a "we track
this whole set" claim, for a Western-European best-practice slide, and for the
Irish track if that comes back off the shelf. Rail operators are context only,
they are not city-transit peers.

| C | City | Operator | Handle | Followers | Posts | Last post | Posts/30d | Live stories | Level | IG pk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UK | London | Transport for London | `@transportforlondon` | 360,940 | 5,686 | 07-08-2026 | 12 | 0 | authority | `242796675` |
| ES | Madrid | Metro de Madrid | `@metro_madrid` | 185,974 | 2,709 | 07-08-2026 | 9 | 0 | operator | `3956537359` |
| FR | Paris | RATP | `@ratp` | 113,159 | 3,315 | 07-08-2026 | 12 | 0 | operator | `2266675173` |
| IT | Milano | ATM Milano | `@atm_milano` | 63,458 | 634 | 31-07-2026 | 2 | 3 | operator | `449456096` |
| IT | Roma | ATAC Roma | `@atacroma` | 59,470 | 1,014 | 30-07-2026 | 2 | - | operator | `3192867997` |
| ES | Barcelona | TMB Barcelona | `@tmb_bcn` | 51,274 | 5,473 | 07-08-2026 | 12 | 1 | operator | `4739168866` |
| FR | Paris | Île-de-France Mobilités | `@idfmobilites` | 50,873 | 451 | 04-08-2026 | 12 | - | authority | `27664743982` |
| BE | Brussel | STIB-MIVB | `@stibmivb` | 39,549 | 1,705 | 05-08-2026 | 12 | 0 | operator | `573282270` |
| ES | Madrid | EMT Madrid | `@emtmadrid` | 23,279 | 1,219 | 07-08-2026 | 12 | 6 | operator | `178123794` |
| BE | Vlaanderen | De Lijn | `@delijn` | 22,517 | 1,329 | 05-08-2026 | 12 | 0 | operator | `722897200` |
| IE | Dublin | Dublin Bus | `@dublinbusnews` | 19,392 | 1,143 | 06-08-2026 | 9 | 1 | operator | `3975579242` |
| PT | Lisboa | Carris Metropolitana | `@carrismetropolitana` | 17,910 | 564 | 07-08-2026 | 10 | 2 | operator | `52593421342` |
| FI | Helsinki | HSL / HRT | `@hsljoukkoliikenne` | 17,215 | 1,798 | 06-08-2026 | 9 | 0 | authority | `1664036997` |
| DK | København | Metroen København | `@metroen_kbh` | 16,694 | 1,202 | 06-08-2026 | 7 | 1 | operator | `636070614` |
| SE | Stockholm | SL Storstockholm | `@sl.storstockholm` | 13,074 | 382 | 29-07-2026 | 1 | 0 | authority | `19371438199` |
| NO | Oslo | Ruter | `@ruter_no` | 12,886 | 463 | 06-08-2026 | 5 | 0 | authority | `623438507` |
| NL | Amsterdam | GVB Amsterdam | `@gvb_online` | 3,755 | 166 | 08-08-2026 | - | - | operator | `71302907581` |
| CH | Zürich | VBZ Zürich | `@vbzzuerilinie` | 12,312 | 1,457 | 07-08-2026 | 10 | 0 | operator | `1973114210` |
| IE | Dublin | Transport for Ireland | `@transportforireland` | 11,200 | 2,780 | 07-08-2026 | 12 | 0 | authority | `7264868662` |
| ES | Bilbao | Metro Bilbao | `@metro_bilbao` | 10,983 | 1,448 | 06-08-2026 | 10 | - | operator | `1736172814` |
| DK | København | Movia | `@movia.dk` | 3,552 | 294 | 07-08-2026 | 12 | 0 | authority | `14758712185` |
| GR | Athens | OASA Athens | `@oasa.gr` | 3,424 | 2,352 | 04-08-2026 | 1 | 0 | authority | `3585611142` |
| LV | Rīga | Rīgas satiksme | `@rigassatiksme` | 3,247 | 386 | 07-08-2026 | 10 | 0 | operator | `31936987` |
| TR | Istanbul | IETT Istanbul | `@iettistanbul` | 3,182 | 2,530 | 07-08-2026 | 10 | 1 | operator | `52009105249` |
| DE | national | Deutsche Bahn | `@deutschebahn` | 531,797 | 3,571 | 07-08-2026 | 12 | - | rail | `485977342` |
| CH | national | SBB | `@sbbcffffs` | 165,885 | 1,512 | 07-08-2026 | 12 | - | rail | `247922960` |
| AT | national | ÖBB | `@unsereoebb` | 104,318 | 2,065 | 07-08-2026 | 12 | - | rail | `794776557` |
| NL | national | NS | `@ns_online` | 85,847 | 1,256 | 07-08-2026 | 12 | - | rail | `1912223876` |
| CZ | national | České dráhy | `@ceskedrahy` | 53,222 | 1,473 | 05-08-2026 | 12 | - | rail | `1908717348` |
| PL | national | PKP Intercity | `@pkp_intercity` | 48,774 | 2,304 | 07-08-2026 | 12 | - | rail | `2027816627` |
| IE | national | Irish Rail | `@irishrail` | 35,857 | 1,411 | 07-08-2026 | 12 | - | rail | `3252209481` |
| SK | national | RegioJet | `@regiojet` | 35,746 | 724 | 06-08-2026 | 6 | - | rail | `363828114` |
| HU | national | MÁV-csoport | `@mavcsoport.hu` | 21,999 | 1,613 | 07-08-2026 | 12 | - | rail | `8206853421` |

## Stories: what the probe actually shows

A single snapshot on the evening of 07-08-2026, across 50 accounts: **20 had
live stories at that minute**, and the spread is the interesting part.

- @wienerlinien had **12 live stories**, @emtmadrid 6, @holding_graz 5,
  @dppoficialni 4, @atm_milano and @mpkpoznan_official 3 each.
- **@dpbratislava had 0.** So did @ids_bk, @pidoficialni, @dpmbofficial,
  @dpostrava, @mpk_krakow, @muenchen.mvg, @transportforlondon and @ratp.

That contrast is the honest version of the pitch: Vienna is running a full
story rail while Bratislava is not, and nothing outside Instagram records what
Vienna ran yesterday. It is worth saying that the top of this vertical uses
stories heavily and that the record vanishes in 24 hours.

**It is not yet a cadence figure and must not be quoted as one.** One snapshot
cannot distinguish "Vienna posts 12 stories every day" from "Vienna happened to
run a campaign burst tonight". The hell demo made exactly this error in the
other direction. Two to three days of live capture across Tier 1 turns this into
a real number, and that capture should start before anything is promised.

## Rejected

Dormant, verified by last-post date. Do not scrape, do not put in a deck as a
peer, do not re-check without reason.

| C | Operator | Handle | Followers | Last post | Days dormant |
| --- | --- | --- | --- | --- | --- |
| CZ | PMDP Plzeň | `@pmdp_plzen` | 954 | 15-01-2024 | 935 |
| ES | TUSSAM Sevilla | `@tussamsevilla` | 582 | 09-03-2018 | 3,073 |
| HR | ZET Zagreb | `@zet_zagreb` | 762 | 07-04-2023 | 1,218 |
| HU | Volánbusz | `@volanbusz` | 8,787 | 03-01-2025 | 581 |

`@pmdp_plzen` and `@zet_zagreb` were re-checked deliberately, because a
single-page dormancy verdict is unsafe: IG returns pinned posts as the first
items on page 1 with older dates, which is exactly why the scraper's paginator
does not stop on the first too-old item (`_hiker_client.py` pagination comment).
Both hold up. Their page 1 spans years rather than weeks (Plzeň 09-2021 to
01-2024, Zagreb 12-2022 to 04-2023), which is the signature of a feed that
stopped, not of a pinned-post artefact.

Rejected as fakes, squatters, or wrong entities (resolve but fail the identity
or size check, mostly sub-200 followers with 0-8 posts): `@bvg`, `@hochbahn_hamburg`,
`@mvg_muenchen`, `@kvb.koeln`, `@zssk`, `@mavinfo`, `@metro_warszawskie`,
`@metro_warszawa`, `@mzawarszawa`, `@tramwajewarszawskie`, `@mpk_poznan`,
`@ztmgdansk`, `@slsverige`, `@oasa_athens`, `@stb_sa`, `@zet_official`,
`@gtt_torino`, `@tcllyon`, `@dpmcb`, `@badnerbahn`, `@gvbamsterdam`,
`@gvb.amsterdam`, `@stolichenavtotransport`. Private accounts, unusable:
`@mhdbb` (Banská Bystrica), `@lpp_official` (Ljubljana), `@luas` (Dublin),
`@iett` (Istanbul), `@gvb_amsterdam` (Amsterdam, 0 posts).

Amsterdam is a caution worth recording. The first sweep resolved
`@gvbamsterdam` (3,600 followers, 585 posts, last post 07-2019) and it looked
like a dormant operator. It is not GVB's account at all. GVB is a large live
operator posting daily. The real handle is **`@gvb_online`**, now in Tier 3,
and `@gvb_amsterdam` is a private 0-post shell. A stale unofficial account
with plausible follower numbers is the failure mode to watch for: it reads as
"operator is dead" when the truth is "we had the wrong handle." There is also a
live GVB recruitment account, `@werkenbijgvb.nl` (2,691 followers, last post
07-08-2026), not included since employer-brand-only accounts are not peers.

**Unresolved after two attempts.** Real presence per public search, or no usable
handle found:

- **@zssk_official** (ZSSK, Slovak national rail, reportedly ~25k followers).
  Persistent 404 across three attempts including retries. Rail, so not urgent
  for the DPB deck, but the handle is almost certainly real.
- **VGF Frankfurt**: no variant resolved (`vgf_ffm`, `vgffrankfurt`,
  `vgf_frankfurt`, `vgf.frankfurt`, `traffiq_frankfurt` all 404).
- **Sofia Urban Mobility**: only `@stolichenavtotransport` resolves, at 11
  followers, too small to be the city's account.
- **Tallinn TLT**, **Carris Lisboa proper** (as distinct from the regional
  `@carrismetropolitana`, which is in Tier 3), and **Arriva Slovakia** produced
  no usable handle from the variants tried.

Note that HikerAPI intermittently 404s valid accounts, which is why
`fetch_stories_by_username` retries in the scraper. Round 1 of this probe missed
several real accounts on a bare 404 before the retry was added, so a single 404
is not proof an account is absent.

## Cost of running this

HikerAPI is on the Business tier as of 08-08-2026, about $0.00069/request (down
from $0.001). Per run: 1 request per account for stories (the single-call
endpoint returns the account and its items together) and roughly 1 per 12 posts.

The armed cadence is all 64 accounts, posts daily plus stories twice daily:

- posts: about 90 requests/day (one media page per account, the pk is cached in
  the DB after the first run so the username lookup is skipped)
- stories: 128 requests/day
- roughly 6,500 requests/month, about **USD 4.5/month**

Dropping stories to once daily halves the story half to about USD 3/month, which
is not a saving worth a permanent hole in the dataset. Requests are not the
constraint here at any cadence worth running.

Storage is the real cost, not requests. The hell demo measured about 11 MB per
post for big brands and burned about 135 MB/day across 6 accounts. Transit
accounts post less media-heavy content, but assume the same order of magnitude
until measured: **take a 2-3 day sample before committing to a scrape window**,
which is the explicit lesson from the hell sizing miss. Supabase Pro gives 100
GB, so there is room, but archive and purge per reported period stays the
hygiene default.

## What to do next

Decided with Andy 08-08-2026: **scrape wide, no backfill, stories at the same
cadence as posts.** HikerAPI Business tier cut per-request cost and Supabase Pro
removed the storage squeeze, so all 64 live accounts are in scope rather than
Tier 1 alone. Tiers now describe report priority, not scrape scope.

Also settled: **entity and tax are not a gate on any of this.** That question
moved to its own project and was removed from this board. Scraping proceeds
regardless of where it lands.

1. Client config is `config/clients/transit/` — all 64 accounts, DPB as
   `is_owned: true`, one dataset for the whole vertical. Six transit categories
   in `categories.yaml` plus `prompt.md`; the first ingest classifies against
   them for real, and a pile of Uncategorized would mean the taxonomy needs
   rework rather than the classifier being broken.
2. Cron lines are in `deploy/crontab.txt` (posts daily 02:30, stories 10:30 and
   22:30, describes trailing each). They need `just crontab-install` on the VPS
   after a deploy, and the config mount on those lines is deliberate.
3. After 2-3 days of story capture, replace the snapshot in this file with a
   real per-account daily average. Only then is there a story number fit to
   show a client.
4. Measure actual storage burn on day 2 and confirm the shape of the estimate
   above.
5. **Report scoping is an open gap.** `accounts` is `UNIQUE (platform, handle)`
   with a `NOT NULL client_id`, so an account belongs to exactly one client and
   peers cannot be shared with a second client config. A per-buyer deck (DPB
   sees its 13 peers, Košice sees a different cut) therefore needs report-side
   account selection, which does not exist yet. Rendering `transit` today would
   produce a 64-account deck.
