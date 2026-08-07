# Cold email sequences - Ireland push (draft v1, 28-07-2026)

Sender identity: **Veritic** (`veritic.net`), decided 01-08-2026. The signature
domain below is provisional until registration: if `veritic.ie` is taken as the
Irish-track sender instead, update the two signature blocks. All emails send as
"Andy from Veritic" - a person at a company, never a company alone. Plain text,
no HTML, max one link, no attachments on first touch.

Personalization slots per prospect (filled from `prospects_ireland.md` + a
2-minute look at their IG): `[FIRST_NAME]`, `[AGENCY]`, `[CLIENT_NICHE]`,
`[BRAND_CO]`, `[COMPETITOR_1]`, `[COMPETITOR_2]`, `[SPECIFIC_OBSERVATION]`.

GDPR/PECR posture: B2B legitimate interest; role/company addresses from the
prospect list only; every email carries the one-line opt-out footer; opt-outs
logged and never re-mailed. Sends start at 10-15/day after 2+ weeks of domain
warmup, manual batches with Andy's approval.

Style rules applied: no em-dashes, no "hope this finds you well", no jargon,
one CTA per email, breakup email honored.

---

## TRACK A - agencies (data-led)

Audience: founders / heads of social at Irish social & digital agencies.
Angle: their dashboard stack cannot see competitor stories at all (official
API limitation), so that work is done manually by juniors or not at all. We
are the data layer, not a rival dashboard. White-label deck = upsell, second
email onward. Never say "scraper".

### A1 - opener

Subject: `competitor stories`

> [FIRST_NAME] - quick one about the reporting you run for clients like
> [CLIENT_NICHE].
>
> Sprout, Metricool and the rest can't show a client what their competitors
> posted to stories. The API doesn't expose it, so it either gets screenshotted
> by hand every morning or it's missing from the report.
>
> We archive any public account's stories (and posts) twice a day and hand you
> the raw feed, or a finished white-label deck if you want the reporting done
> too. We ran a 2-week teardown of an energy-drink brand against Red Bull and
> Monster recently and the story-cadence gap alone carried the report.
>
> Worth a look at a sample for one of your clients' markets?
>
> Andy
> Veritic - veritic.net
> If you'd rather not hear from me again, reply "no" and that's that.

### A2 - +4 days, proof angle

Subject: `re: competitor stories`

> One number from the teardown I mentioned: one competitor posted 18 stories
> in a single day; the brand we monitored posted zero all week. None of that
> gap shows up in any dashboard your clients' rivals also have.
>
> Happy to run the same two-week pass on any account set you name - no charge,
> you see exactly what the feed and the deck look like. Useful?
>
> Andy

### A3 - +7 days, workload angle

Subject: `report week`

> Different angle on why I'm pestering you: the monthly client deck. Most
> teams we talk to spend 4-8 hours per client turning dashboard exports into
> something presentable.
>
> Ours arrives as an editable branded PPTX with the commentary already
> written - your logo, your client's competitors, stories included. You edit
> tone, not build slides.
>
> Want one built on a real client of yours as the test?
>
> Andy

### A4 - +10 days, breakup

Subject: `closing the loop`

> Taking the silence as "not now" - no hard feelings, inbox zero is sacred.
>
> If competitor stories ever become a thing a client asks for, the offer of a
> free two-week sample stands. Good luck with the season ahead.
>
> Andy

---

## TRACK B - direct brands (report-led, free first report)

Audience: marketing manager / founder at Irish consumer brands (food & drink,
fitness, hospitality, beauty). Angle: the finished report about THEIR market;
they never had anything like it; how the data is collected is irrelevant to
them. Strongest personalization: name their real competitors.

### B1 - opener

Subject: `[COMPETITOR_1] last fortnight`

> [FIRST_NAME] - I put together competitive Instagram reports and
> [BRAND_CO] vs [COMPETITOR_1] and [COMPETITOR_2] is exactly the kind of
> matchup they're built for.
>
> Two weeks of everything all three of you post (stories included - those
> vanish after 24h, we archive them), sorted into what's working, with the
> analysis written out. Lands as a deck you can forward internally.
>
> [SPECIFIC_OBSERVATION]
>
> First one's free - it's how we show what it is. Want me to start the clock
> on the next two weeks?
>
> Andy
> Veritic - veritic.net
> Reply "no" if this isn't for you and I won't write again.

### B2 - +4 days, concrete-sample angle

Subject: `re: [COMPETITOR_1] last fortnight`

> To make it less abstract: for an energy-drink brand we tracked against
> Red Bull and Monster, the report caught a rival flooding 18 stories in one
> day around an event while the brand posted nothing that week. That kind of
> gap is invisible unless someone watches stories daily.
>
> Same lens on [BRAND_CO]'s market, free, two weeks. Interested?
>
> Andy

### B3 - +7 days, effort-free angle

Subject: `zero setup`

> Worth saying: this needs nothing from your side. No access, no logins, no
> pixel - it's all public content, we just never let it expire. You get a
> deck in a fortnight and decide then if it's worth keeping monthly.
>
> Start it?
>
> Andy

### B4 - +10 days, breakup

Subject: `last one from me`

> I'll leave it here. If a launch or a competitor push ever makes you wish
> you'd been watching their feed properly, the free first report offer
> stands.
>
> Good luck with [BRAND_CO] - genuinely a nice brand to watch.
>
> Andy

---

## Send playbook (machine notes)

1. Brand decided 01-08-2026: Veritic. `veritic.net` free at decision time
   (`.io`/`.ie`/`.eu`/`.sk` also free; `.com` held by an unrelated Swiss web3
   firm). Next: register, then 2+ weeks domain warmup before batch 1
   (SPF/DKIM/DMARC, low-volume normal correspondence first). BLOCKED on
   registration + mailbox setup, no longer on the naming decision.
2. Batch = 10-15/day, one track at a time, Tue-Thu mornings Irish time.
3. Every send personalized at slot level minimum; A-track openers get a real
   [CLIENT_NICHE] from the agency's own site; B-track needs real competitor
   names or the email does not send.
4. Andy approves each batch before send; human edits encouraged (the drafts
   are deliberately plain so his voice fits on top).
5. Tracking: replies > opens. Log per prospect: sent date, sequence step,
   reply, opt-out. Simple sheet first; tooling later if volume justifies.
6. The "energy-drink teardown" proof line stays anonymized until Hell agrees
   to be named (or converts and approves a case study).
