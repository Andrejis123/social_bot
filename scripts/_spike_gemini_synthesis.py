"""
One-shot spike: dry-run Gemini synthesis prompt against real ai_descriptions.

Generates AUGUST-style 2-3 sentence category narratives for two test cells:
  - iqos_cz Collaborations (4 posts) — small-N, direct AUGUST comparison
  - ploom.cz Events (17 posts) — large-N stress test

Prints both the input pack and the generated narrative so the user can judge
prompt quality before committing to it.

Cost: ~$0.001 total (Gemini Flash).
"""

from __future__ import annotations

from google import genai
from google.genai import types

from claude_social.config import get_settings
from claude_social.db.client import get_supabase

WINDOW_START = "2026-04-25T00:00:00+00:00"
WINDOW_END = "2026-05-25T23:59:59+00:00"

# (handle, category, brand_label_for_prompt)
CELLS = [
    ("iqos_cz", "Collaborations", "IQOS"),
    ("ploom.cz", "Events", "Ploom"),
]


SYSTEM_INSTRUCTION = """You are a social-media analyst writing concise monthly category summaries for a competitor-monitoring report.

Style requirements (mirror these — they come from a polished human-made reference):
- 2-3 sentences max. Never more.
- Past tense ("was", "had", "promoted") describing what the brand did during the month.
- Name specific events, brands, people, campaigns, products by name when present.
- Factual and observational tone — NOT promotional. You are reporting on the brand, not for them.
- Plain English. Translate non-English content references inline if needed.
- No hashtags. No emoji. No bullet points. Pure prose.
- Do NOT mention post count, view count, or any metric — just describe activities.

Reference examples of the target style (from a real BAT/IQOS August report):

"In collaboration with Tomáš Třeštík, the work Memory was created, which also had its ceremonial exhibition in the IQOS store in the Palladium in Prague. They also went on a joint tour with the work (Film Festival in Karlovy Vary, Pohoda, Colours Of Ostrava,...)."

"IQOS was a partner of several events or had its own partner zone there. These were various events or festivals - e.g. HRADY CZ, Prague Harley Days, Brutal Assault... They also announced an event in collaboration with the Seletti brand, where Swiss DJ duo Adriatique will perform at the Sensorium Worlds event in Milan."

"Ploom was a sponsor of the Czech Design Awards. They also attended a party in Ibiza, where they published a lot of content with influencers, and also had partnerships with Prague Pride and the Let it Roll festival."

Now write a similar 2-3 sentence summary for the brand and category given.
"""


def fetch_account_id(handle: str) -> str:
    sb = get_supabase()
    res = sb.table("accounts").select("id").eq("handle", handle).limit(1).execute()
    if not res.data:
        raise SystemExit(f"account not found: {handle}")
    return res.data[0]["id"]


def fetch_cell_posts(handle: str, category: str) -> list[dict]:
    sb = get_supabase()
    aid = fetch_account_id(handle)
    res = (
        sb.table("posts")
        .select("posted_at, caption, ai_description, post_type")
        .eq("account_id", aid)
        .eq("ai_category", category)
        .gte("posted_at", WINDOW_START)
        .lte("posted_at", WINDOW_END)
        .order("posted_at")
        .execute()
    )
    return res.data or []


def build_user_prompt(brand: str, category: str, posts: list[dict]) -> str:
    lines = [
        f"Brand: {brand}",
        f"Category: {category}",
        f"Period: {WINDOW_START[:10]} to {WINDOW_END[:10]}",
        f"Post count in this category: {len(posts)}",
        "",
        "Per-post evidence (use this to identify named events/people/campaigns):",
        "",
    ]
    for i, p in enumerate(posts, 1):
        cap = (p.get("caption") or "").strip().replace("\n", " ")
        desc = (p.get("ai_description") or "").strip().replace("\n", " ")
        date = (p.get("posted_at") or "")[:10]
        kind = p.get("post_type") or "post"
        lines.append(f"--- Post {i} ({date}, {kind}) ---")
        if cap:
            lines.append(f"Caption: {cap[:400]}")
        if desc:
            lines.append(f"AI description: {desc}")
        lines.append("")
    lines.append(
        "Write the 2-3 sentence summary now. Output only the prose — no preamble, no label."
    )
    return "\n".join(lines)


def synthesize(brand: str, category: str, posts: list[dict]) -> str:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    user_prompt = build_user_prompt(brand, category, posts)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Part.from_text(text=user_prompt)],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,
            max_output_tokens=400,
            # gemini-2.5-flash uses thinking tokens by default — disable for cost
            # and to keep budget for actual output prose
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    # Diagnostics
    cand = response.candidates[0] if response.candidates else None
    fr = getattr(cand, "finish_reason", None) if cand else None
    usage = getattr(response, "usage_metadata", None)
    text = (response.text or "").strip()
    print(f"  [diag finish_reason={fr} usage={usage}]")
    return text


def main() -> None:
    for handle, category, brand in CELLS:
        print(f"\n{'='*80}\n# Cell: @{handle} · {category} ({brand})\n{'='*80}")
        posts = fetch_cell_posts(handle, category)
        print(f"  → {len(posts)} posts pulled\n")
        if not posts:
            print("  (no posts — skipping)")
            continue
        print("--- INPUT EVIDENCE (compressed for readability) ---")
        for i, p in enumerate(posts, 1):
            cap = (p.get("caption") or "")[:80].replace("\n", " ")
            print(f"  {i}. {p.get('posted_at', '')[:10]} [{p.get('post_type')}] {cap}…")
        print("\n--- GENERATED NARRATIVE ---")
        narrative = synthesize(brand, category, posts)
        print(narrative)


if __name__ == "__main__":
    main()
