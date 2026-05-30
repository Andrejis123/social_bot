"""Smoke-test: render the full per-account report sequence with placeholder data.

Sequence (per locked spec 2026-05-26):
    Cover → Intro → Overview → Category × N → Summary → Additional Data

Usage:
    uv run python scripts/_spike_report_render.py

Output:
    /tmp/report_spike/test.pptx
    /tmp/report_spike/test.pdf
    /tmp/report_spike/slide-NN.png
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pptx import Presentation

from claude_social.reports import theme
from claude_social.reports.brand import REPO_ROOT, Brand
from claude_social.reports.layouts import (
    CategoryItem,
    CategoryPreview,
    MetricCard,
    draw_account_overview,
    draw_account_summary,
    draw_additional_data,
    draw_category_section,
    draw_cover,
    draw_intro,
    format_metric,
)


OUT_DIR = Path("/tmp/report_spike")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in OUT_DIR.glob("slide-*.png"):
        f.unlink()

    brand = Brand.load("ecig-monitoring")
    sample_dir = REPO_ROOT / "assets" / "reference" / "sample_posts"
    sample_imgs = sorted(sample_dir.glob("post*.png"))

    prs = Presentation()
    prs.slide_width = theme.SLIDE_W
    prs.slide_height = theme.SLIDE_H

    # ─── Slide 1: Cover ────────────────────────────────────────────
    draw_cover(prs, brand,
               title="Social Media Monitoring",
               subtitle="for Ecig Monitoring",
               period="25 April – 25 May 2026")

    # ─── Slide 2: Per-account Intro (IQOS) ──────────────────────────
    draw_intro(prs, brand,
               title="IQOS CZ",
               body=("IQOS activity tracked across Events, Collaborations, "
                     "Competitions, and Ongoing campaigns. 12 posts in the "
                     "period; festival-heavy month with two new cross-brand collabs."),
               previews=[
                   CategoryPreview("Events", sample_imgs[0]),
                   CategoryPreview("Collaborations", sample_imgs[1]),
                   CategoryPreview("Competitions", sample_imgs[2]),
                   CategoryPreview("Ongoing", sample_imgs[3]),
               ])

    # ─── Slide 3: Account Overview (5 metric circles) ───────────────
    draw_account_overview(prs, brand,
                          title="IQOS CZ: Overview",
                          metrics=[
                              ("Posts", format_metric(12)),
                              ("Reels", format_metric(4)),
                              ("Stories", format_metric(8)),
                              ("Likes", format_metric(12300)),
                              ("Comments", format_metric(412)),
                          ])

    # ─── Slide 4: Category, Events (4 items) ───────────────────────
    draw_category_section(
        prs, brand,
        title="IQOS CZ: Events",
        narrative=(
            "IQOS was a partner at several events this period across CZ: "
            "festivals, rallies, and concept activations. They ran dedicated "
            "partner zones at music festivals (HRADY CZ, Brutal Assault), "
            "hosted attendees at Prague Harley Days, and announced an upcoming "
            "collaboration with Seletti for Sensorium Worlds in Milan."
        ),
        items=[
            CategoryItem("HRADY CZ",
                         "HRADY CZ festival, partner zone with attendees, mid-May.",
                         sample_imgs[0]),
            CategoryItem("Prague Harley Days",
                         "Prague Harley Days, IQOS lounge for visitors at the rally.",
                         sample_imgs[1]),
            CategoryItem("Brutal Assault",
                         "Brutal Assault festival, second year as partner.",
                         sample_imgs[2]),
            CategoryItem("Sensorium Worlds",
                         "Sensorium Worlds × Seletti, Adriatique DJ duo, Milan.",
                         sample_imgs[3]),
        ])

    # ─── Slide 5,6: Category, Collaborations (pagination demo: 6 items, 2 slides) ──
    draw_category_section(
        prs, brand,
        title="IQOS CZ: Collaborations",
        narrative=(
            "Six distinct cross-brand collaborations ran in the period. "
            "Highlights include the Italian design house Seletti partnership "
            "with DJ duo Adriatique, a sustained influencer cooperation with "
            "creator XY, and a limited-edition device drop with Czech visual "
            "artist Z. Several regional activations supported the summer tour."
        ),
        items=[
            CategoryItem("Seletti × Adriatique",
                         "Cross-brand reel launch with Italian design house Seletti.",
                         sample_imgs[0]),
            CategoryItem("Influencer XY",
                         "Continued partnership with lifestyle creator XY (4 posts).",
                         sample_imgs[1]),
            CategoryItem("Artist Z",
                         "Limited-edition device drop with Czech visual artist Z.",
                         sample_imgs[2]),
            CategoryItem("Music venue P",
                         "Pop-up at Prague venue P, weekly residency.",
                         sample_imgs[3]),
            CategoryItem("Festival Q",
                         "Co-branded merch with festival Q for summer tour.",
                         sample_imgs[4]),
            CategoryItem("Designer R",
                         "Capsule sleeve collection with Bratislava designer R.",
                         sample_imgs[5]),
        ])

    # ─── Slide 7: Summary (light theme, 2x3 card grid) ──────────────
    draw_account_summary(prs, brand,
                         title="IQOS CZ: Summary",
                         cards=[
                             MetricCard(
                                 label="Volume",
                                 value="12 posts (4 reels)",
                                 caption="Led by Events (4) and Competitions (3)."),
                             MetricCard(
                                 label="Collaborations",
                                 value="6 distinct",
                                 caption="Seletti, Influencer XY, Artist Z, Music venue P, Festival Q, Designer R."),
                             MetricCard(
                                 label="Post cadence",
                                 value="3 / week",
                                 caption="Steady throughout the period."),
                             MetricCard(
                                 label="Story cadence",
                                 value="2 / day",
                                 caption="Peaking on weekends."),
                             MetricCard(
                                 label="Likes",
                                 value="770 avg",
                                 caption="Top post: 2,143 (Sensorium Worlds reel)."),
                             MetricCard(
                                 label="Comments",
                                 value="26 avg",
                                 caption="Top: 89 (Brutal Assault announcement)."),
                         ])

    # ─── Slide 8: Additional Data (light theme, placeholder values) ──
    draw_additional_data(prs, brand,
                         title="IQOS CZ: Additional Data",
                         cards=[
                             MetricCard("Posting time window",
                                        "10:00 – 18:00",
                                        "Most posts published in the afternoon block."),
                             MetricCard("Story time window",
                                        "08:00 – 22:00",
                                        "Wider spread; evening peak."),
                             MetricCard("Top day of week",
                                        "Friday",
                                        "Highest engagement; weekend launches."),
                             MetricCard("Fastest-growing post",
                                        "+340% / 6h",
                                        "Reel: Sensorium Worlds teaser."),
                             MetricCard("Fastest-commenting post",
                                        "89 in 2h",
                                        "Brutal Assault festival announcement."),
                             MetricCard("Hashtag diversity",
                                        "18 unique",
                                        "Top: #IQOSCZ #SensoriumWorlds #BrutalAssault."),
                         ])

    pptx_path = OUT_DIR / "test.pptx"
    prs.save(pptx_path)
    print(f"wrote {pptx_path}")

    subprocess.run(
        ["/Applications/LibreOffice.app/Contents/MacOS/soffice",
         "--headless", "--convert-to", "pdf",
         "--outdir", str(OUT_DIR), str(pptx_path)],
        check=True, capture_output=True,
    )
    pdf_path = OUT_DIR / "test.pdf"
    subprocess.run(
        ["pdftoppm", "-png", "-r", "120", str(pdf_path), str(OUT_DIR / "slide")],
        check=True,
    )
    for p in sorted(OUT_DIR.glob("slide-*.png")):
        print(f"rendered {p}")


if __name__ == "__main__":
    main()
