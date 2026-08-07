# Veritic sender setup + warmup runbook (01-08-2026)

Domain `veritic.net` registered at Cloudflare 01-08-2026. This runbook takes it
from "registered" to "batch 1 can send" in about two weeks. Warmup is the
critical path: nothing in the cold-email leg can start until the clock has run.

Companion docs: `cold_email_sequences.md` (the emails), `prospects_ireland.md`
(the list).

---

## 1. Mailbox provider (Andy decides, everything else follows)

| Provider | Cost | Notes |
|----------|------|-------|
| Google Workspace | ~6 EUR/user/mo | Best reputation with receiving filters, easiest DKIM setup, and Gmail-to-Gmail delivery is the common path for Irish SMBs. Default recommendation. |
| Microsoft 365 | ~6 EUR/user/mo | Equivalent deliverability. Pick only if you prefer Outlook. |
| Fastmail | ~5 EUR/user/mo | Clean, no ads, good sender reputation, less "corporate" than Workspace. |
| Zoho Mail | free tier / ~1 EUR | Cheapest, but a weaker default reputation and more likely to need extra warmup. Not worth the saving here. |

Recommendation: **Google Workspace**, one user, `andy@veritic.net`.

Send from a real named human address, never `info@` or `hello@`. The sequences
sign as "Andy from Veritic" and the From address must match that claim.

### Sending domain tradeoff

Sending cold email from `veritic.net` itself puts the brand domain's reputation
at risk if a batch goes badly. The alternative is a separate sending domain
(e.g. `veritic-mail.net`) pointed at the same mailbox, which protects the root.

For this volume (10-15/day, manually approved, opt-out honoured) the risk is
low and the credibility of a matching domain is worth more. Send from
`veritic.net`. Revisit only if volume goes past ~50/day.

---

## 2. DNS records at Cloudflare

All four must exist before the first send. Set DNS records to "DNS only" (grey
cloud), never proxied - proxying mail records breaks them.

1. **MX** - exact values come from the mail provider. Delete any placeholder MX
   Cloudflare added at registration.

2. **SPF** (TXT on root). One SPF record only; multiple records fail validation.
   Google Workspace:
   ```
   v=spf1 include:_spf.google.com ~all
   ```
   Use `~all` (softfail) during warmup, tighten to `-all` once mail flow is
   confirmed working.

3. **DKIM** (TXT). The provider generates the key; in Workspace it is
   Admin console > Apps > Google Workspace > Gmail > Authenticate email.
   Generate a 2048-bit key, publish the record, then click Start Authentication.
   Skipping the final step is the usual reason DKIM silently fails.

4. **DMARC** (TXT on `_dmarc`). Start permissive and watch the reports:
   ```
   v=DMARC1; p=none; rua=mailto:andy@veritic.net; fo=1
   ```
   After two clean weeks, move to `p=quarantine`. Do not start at
   `p=reject`: a misconfigured DKIM would silently bin every email.

Verify all four with an external check (mail-tester.com or MXToolbox) before
sending anything. Target 10/10 on mail-tester.

---

## 3. Warmup schedule

Reputation is built by *replied-to* mail, not volume. A brand new domain that
suddenly emits 15 cold emails a day gets filtered.

- **Days 1-4**: 2-5 mails/day, genuine correspondence only. Real threads with
  people who will reply: yourself on other accounts, friends, suppliers,
  the registrar, anything with a real back-and-forth. Reply to replies.
- **Days 5-10**: 5-10/day, still mostly real correspondence. Introduce a few
  genuinely warm outreach mails if any exist.
- **Days 11-14**: 10/day, first cold batches allowed at the low end, Track B
  first (brands are the more forgiving audience).
- **Day 15+**: steady state 10-15/day per the send playbook.

Rules throughout:
- Plain text, no HTML templates, no tracking pixels. Open-tracking hurts
  deliverability and adds a GDPR wrinkle for no benefit; the sequences already
  measure replies, not opens.
- No attachments on first touch, max one link.
- Never send the same body twice in a day. The personalization slots exist
  precisely so no two mails are identical.
- Honour every opt-out immediately and log it.

---

## 4. Critical path to batch 1

1. Pick provider, create `andy@veritic.net`. (Andy)
2. Publish MX, SPF, DKIM, DMARC at Cloudflare. (Andy)
3. Verify 10/10 on mail-tester. (Andy)
4. Start warmup day 1. Clock runs 14 days from here.
5. In parallel, agent work with no dependency on the mailbox:
   - verification pass over `prospects_ireland.md` (roles, addresses, IG presence)
   - sample report asset for the Track A attachment
   - LinkedIn company page copy
6. Batch 1 sends on warmup day 11 at the earliest, Track B, Andy approves the
   batch before it goes.
