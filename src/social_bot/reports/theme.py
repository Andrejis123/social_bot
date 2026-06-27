"""Geometric constants for the report layout.

All measurements in inches unless stated. Original measurements extracted from
a recreated AUGUST reference deck on 2026-05-26; iteratively refined
based on user feedback (2026-05-26).

The renderer is code-driven — there is no master template. These constants are
the single source of truth for shape positions and sizes across layouts.
Per-client colors / logos live in brand.yaml; only geometry lives here.
"""
from __future__ import annotations

from pptx.util import Cm, Inches, Pt

SLIDE_W_IN = 13.333333
SLIDE_H_IN = 7.5

SLIDE_W = Inches(SLIDE_W_IN)
SLIDE_H = Inches(SLIDE_H_IN)

# Shared margin used by content-slide titles + logos
CONTENT_TITLE_LEFT_IN = 0.50
CONTENT_LOGO_LEFT_IN = 11.70
CONTENT_TOP_ROW_Y_IN = 0.40  # title + logo both align here


class Cover:
    # Stack: TITLE (large) → DATES (same large size) → CLIENT SUBTITLE (smaller)
    # All top-anchored — matches the original AUGUST 3-line cover stack.
    # Title left edge matches the BAT logo at bottom-left (0.50).
    title_left = Inches(0.50)
    title_top = Inches(1.40)
    title_w = Inches(7.60)
    title_h = Inches(1.85)
    title_font_pt = Pt(54)

    period_left = Inches(0.50)
    period_top = Inches(3.50)
    period_w = Inches(7.60)
    period_h = Inches(0.80)
    period_font_pt = Pt(40)

    subtitle_left = Inches(0.50)
    subtitle_top = Inches(4.45)
    subtitle_w = Inches(7.60)
    subtitle_h = Inches(0.55)
    subtitle_font_pt = Pt(24)

    # hero_left chosen so right margin (13.333 - hero_left - hero_w) equals
    # the gap between image bottom and the stripe (stripe_top - hero_top -
    # hero_h = 5.40 - 0.51 - 4.72 = 0.17). Symmetric padding on the two
    # exposed edges.
    hero_left = Inches(8.263)
    hero_top = Inches(0.51)
    hero_w = Inches(4.90)
    hero_h = Inches(4.72)

    logo_left = Inches(0.50)
    logo_top = Inches(6.45)
    logo_w = Inches(1.80)
    logo_h = Inches(0.78)

    stripe_left = Inches(0.0)
    stripe_top = Inches(5.40)
    stripe_w = SLIDE_W
    stripe_h = Inches(0.80)


class Content:
    """Top-row chrome shared by all content slides."""
    title_left = Inches(CONTENT_TITLE_LEFT_IN)
    title_top = Cm(0.47)
    title_w = Inches(8.00)
    title_h = Inches(0.90)
    title_font_pt = Pt(28)

    logo_left = Inches(CONTENT_LOGO_LEFT_IN)
    logo_top = Cm(0.47)
    logo_w = Inches(1.35)
    logo_h = Inches(0.585)

    # Rainbow stripe (8 segments, full slide width)
    rainbow_top = Inches(7.35)
    rainbow_h = Inches(0.15)
    rainbow_count = 8
    rainbow_seg_w = Inches(SLIDE_W_IN / rainbow_count)
    rainbow_start_left = Inches(0.0)


class CategorySection:
    """Per-category slide: prose summary at top + up to 4 items below
    (each = image + small caption with a 2-line break for readability).

    Multiple posts about the same campaign/event collapse into one item.
    Pagination: items 1-4 on slide 1, 5-8 on slide 2, etc. When a page has
    fewer than items_per_slide entries, the row is horizontally centered.
    Images are separated by small gaps so they read as distinct items, not a
    continuous strip.
    """
    items_per_slide = 4

    col_count = 4
    col_w_in = 2.95
    col_w = Inches(col_w_in)
    col_gap_in = 0.15

    # Prose summary above the items (the category-level narrative)
    narrative_left = Inches(CONTENT_TITLE_LEFT_IN)
    narrative_top = Cm(4.0)
    narrative_w = Inches(12.30)
    narrative_h = Inches(1.10)
    narrative_font_pt = Pt(16)

    img_top = Inches(2.95)
    img_w_in = col_w_in
    img_w = Inches(img_w_in)
    img_h = Inches(3.60)

    caption_top = Inches(6.65)
    caption_h = Inches(0.65)
    caption_font_pt = Pt(10)


def category_col_left(index: int, n_in_page: int):
    """X-position (Inches) of column `index` (0-based). Row is horizontally
    centered for any `n_in_page` (1..items_per_slide). Gaps between columns
    are included in the centering calculation."""
    cw = CategorySection.col_w_in
    g = CategorySection.col_gap_in
    total_w = n_in_page * cw + (n_in_page - 1) * g
    start = (SLIDE_W_IN - total_w) / 2.0
    return Inches(start + index * (cw + g))


class Overview:
    """Account overview: 5 metric circles (Posts / Reels / Stories / Likes / Comments)."""
    circle_count = 5
    circle_d_in = 2.00
    circle_d = Inches(circle_d_in)
    circle_top = Inches(2.80)

    # 5 evenly-spaced centers across the slide (precomputed for SLIDE_W_IN=13.333)
    circle_centers_x_in = tuple(
        SLIDE_W_IN * (2 * i + 1) / 10.0 for i in range(5)
    )

    label_font_pt = Pt(14)
    label_h = Inches(0.40)
    label_gap = Inches(0.20)
    # Optional second line under the label (used by the Posts circle to clarify
    # "incl. N reels"). Smaller font, rendered immediately below the label.
    sub_caption_font_pt = Pt(10)
    sub_caption_h = Inches(0.30)


def overview_circle_left(index: int):
    cx = Overview.circle_centers_x_in[index]
    return Inches(cx - Overview.circle_d_in / 2.0)


class Intro:
    """Per-account intro: title + categories description + 3 or 4 representative images."""
    # Body describes what categories are covered
    body_left = Inches(CONTENT_TITLE_LEFT_IN)
    body_top = Cm(4.0)
    body_w = Inches(12.30)
    body_h = Inches(1.45)
    body_font_pt = Pt(18)

    # 3 or 4 representative images. Rendered with a small gap between columns
    # and horizontally centered when fewer than `col_count`.
    img_top = Inches(3.30)
    img_h = Inches(3.85)
    col_count = 4
    col_w_in = 2.95
    col_w = Inches(col_w_in)
    col_gap_in = 0.15
    min_previews = 3


def intro_col_left(index: int, n_in_page: int):
    """X-position (Inches) of preview column `index` (0-based). Row is
    horizontally centered for any `n_in_page` (1..col_count). Gaps included.
    """
    cw = Intro.col_w_in
    g = Intro.col_gap_in
    total_w = n_in_page * cw + (n_in_page - 1) * g
    start = (SLIDE_W_IN - total_w) / 2.0
    return Inches(start + index * (cw + g))


# ─────────────────────────────────────────────────────────────────────────
# Light-theme layouts (Summary, AdditionalData)
# White background, navy text, brand-color strip under heading.
# ─────────────────────────────────────────────────────────────────────────

class LightTitle:
    """Shared header strip used by light-theme slides (Summary, AdditionalData)."""
    title_left = Inches(CONTENT_TITLE_LEFT_IN)
    title_top = Cm(0.47)
    title_w = Inches(8.00)
    title_h = Inches(0.90)
    title_font_pt = Pt(28)

    logo_left = Inches(CONTENT_LOGO_LEFT_IN)
    logo_top = Cm(0.47)
    logo_w = Inches(1.35)
    logo_h = Inches(0.585)

    rainbow_top = Cm(2.8)
    rainbow_h = Inches(0.15)
    rainbow_count = 8
    rainbow_seg_w = Inches(SLIDE_W_IN / rainbow_count)
    rainbow_start_left = Inches(0.0)


class Summary:
    """Data digest — 2×3 card grid. Light theme.

    6 fixed subheadings (user-locked 2026-05-26):
      Volume / Collaborations / Post cadence / Story cadence / Likes / Comments

    Grid is vertically centered between the rainbow strip (y=1.45) and slide
    bottom (y=7.50). Tighter card height keeps content close to its label.
    """
    grid_top_in = 2.35
    grid_bottom_in = 6.55
    grid_left_in = 0.50
    grid_right_in = 12.83

    grid_cols = 3
    grid_rows = 2
    grid_gap_in = 0.30

    @classmethod
    def card_w_in(cls):
        usable = cls.grid_right_in - cls.grid_left_in
        return (usable - (cls.grid_cols - 1) * cls.grid_gap_in) / cls.grid_cols

    @classmethod
    def card_h_in(cls):
        usable = cls.grid_bottom_in - cls.grid_top_in
        return (usable - (cls.grid_rows - 1) * cls.grid_gap_in) / cls.grid_rows

    label_font_pt = Pt(16)
    value_font_pt = Pt(32)
    caption_font_pt = Pt(13)


def summary_card_pos(row: int, col: int):
    w = Summary.card_w_in()
    h = Summary.card_h_in()
    left = Summary.grid_left_in + col * (w + Summary.grid_gap_in)
    top = Summary.grid_top_in + row * (h + Summary.grid_gap_in)
    return Inches(left), Inches(top), Inches(w), Inches(h)


class AdditionalData:
    """Extended-tier data slide. Light theme, same card-grid shape as Summary.

    Rows planned (placeholder values for v1):
      Posting time window / Story time window / Top day-of-week /
      Fastest-growing post / Fastest-commenting post / Hashtag diversity
    """
    grid_top_in = Summary.grid_top_in
    grid_bottom_in = Summary.grid_bottom_in
    grid_left_in = Summary.grid_left_in
    grid_right_in = Summary.grid_right_in
    grid_cols = Summary.grid_cols
    grid_rows = Summary.grid_rows
    grid_gap_in = Summary.grid_gap_in

    label_font_pt = Pt(16)
    value_font_pt = Pt(28)
    caption_font_pt = Pt(13)
