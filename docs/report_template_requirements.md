# Report Master Template — Requirements Checklist

**Purpose:** evaluate any `.pptx` template (whether client-provided or built in-house) for compatibility with the automated python-pptx report renderer.

The renderer needs to *find* specific slide layouts and named placeholders inside the master `.pptx` to inject content. If the layouts don't exist or aren't named, the renderer can't populate them. This checklist lets you spot gaps before code touches the file.

---

## 1. Required slide layouts (must exist in the Slide Master)

Each layout must be a real Slide Layout in PowerPoint (View → Slide Master). The renderer uses layout name as the lookup key.

| Layout name (suggested) | Purpose | Frequency in deck |
|---|---|---|
| `Cover` | Title page: client logo, report title, period, hero visual | 1 per report |
| `Intro` | Short intro prose on themed background | 1 per report |
| `AccountOverview` | Per-account stats: 3 large metric circles (posts, reactions, comments) | 1 per account |
| `CategorySection` | Per-category slide: heading + 2-3 sentence narrative + horizontal image strip | 1 per (account, category) with content |
| `CategorySectionTopPosts` | Variant: includes a "Top liked / Top commented" callout box | optional — could merge into above |
| `AccountSummary` | Per-account wrap: bullet list + image grid (2×3) | 1 per account |
| `LowActivity` | Single-slide collapse pattern for low-volume accounts (see AUGUST Pulze p.18) | conditional |

If naming control is impossible (e.g., template was inherited from non-Python tooling), document the actual layout names and we'll map them in renderer config.

---

## 2. Required named placeholders (per layout)

Open each layout in the Slide Master and verify these named placeholders exist. To name a placeholder in PowerPoint: select it → Home tab → Arrange → Selection Pane → rename.

### `Cover`
- `client_logo` (picture placeholder, top-right or top-left)
- `report_title` (text placeholder, large heading)
- `period_subtitle` (text placeholder, smaller, e.g. "April 25 – May 25, 2026")
- `hero_visual` (picture placeholder, large, right or center)

### `Intro`
- `intro_text` (text placeholder, 1-3 sentences)
- `client_logo` (small, top-right, consistent across non-cover slides)

### `AccountOverview`
- `account_title` (heading, e.g. "IQOS - Overview")
- `metric_circle_1_label` / `metric_circle_1_value` (e.g. "Number of posts" / "16")
- `metric_circle_2_label` / `metric_circle_2_value`
- `metric_circle_3_label` / `metric_circle_3_value`
- `client_logo` (small, consistent)

### `CategorySection`
- `section_title` (heading, e.g. "IQOS - Events")
- `narrative_text` (body, 2-3 sentences from Gemini synthesis)
- `image_strip_1` … `image_strip_5` (picture placeholders for horizontal strip — sized for IG-story aspect ratio ~9:16)
- The renderer should hide unused image placeholders gracefully (1-5 variable)
- `client_logo` (small, consistent)

### `AccountSummary`
- `summary_title`
- `summary_bullets` (multi-line text placeholder, 3-6 bullets)
- `grid_image_1` … `grid_image_6` (picture placeholders in 2×3 layout)
- `client_logo` (small, consistent)

### `LowActivity` (collapse pattern)
- `account_title`
- `low_activity_text` (e.g. "They did share only 5 posts...")
- `image_strip_1` … `image_strip_5`
- `client_logo`

---

## 3. Theme & styling that should live in the master (not the script)

The renderer should **not** set colors or fonts inline — these come from the master:

- **Slide background color** (BAT-style: deep navy; agape-style: white)
- **Font family** for headings and body
- **Heading color**, **body text color**
- **Accent color** (used for metric circles, callout boxes)
- **Footer stripe** (the rainbow accent bar at bottom of AUGUST slides — should be part of the master, NOT redrawn per slide)
- **Client logo** as a master-level decoration (top-right consistent placement)

If any of these end up hardcoded inside individual layouts, swapping in a different client's master deck becomes painful. They should be theme-level.

---

## 4. Image-strip layout variants (3 shapes)

From AUGUST observation — the horizontal image strip slides have three flavors:

| Post count in (account, category) | Layout shape | AUGUST example |
|---|---|---|
| 1 | Single hero image, large | (low-volume case) |
| 2–5 | Horizontal strip, ~equal widths | IQOS Events (5 images), IQOS Collaborations (5) |
| 6+ | Top-N by engagement, may need 2-row grid | (not used in AUGUST — emerged from spike: ploom.cz Events has 17) |

Decision needed: do we want one `CategorySection` layout with 5 image slots (renderer hides unused), or distinct `CategorySection_1` / `CategorySection_5` / `CategorySection_Grid` layouts? Recommend the single-layout approach — fewer master surfaces, renderer handles visibility.

---

## 5. Aspect ratio + image handling

- Slide size: 16:9 (PowerPoint default `Widescreen`)
- IG story / reel aspect: 9:16 (tall) — fits the AUGUST image strip well
- IG feed posts: 1:1 (square) or 4:5 (portrait) — may need padding/cropping
- The renderer pulls images from Supabase Storage via `storage_path` (download or signed URL); should fit-to-placeholder without distortion (crop, not stretch)

---

## 6. Conditional rendering rules (script behavior, but template should support)

- **Empty categories** → skip the `CategorySection` slide entirely (don't render with placeholder text)
- **Zero stories in a category** → still render posts-only, no awkward "Stories: 0"
- **Single-category account** (e.g. pulzeczech this month) → consider `LowActivity` collapse
- **Top-N post overlap** (most liked = most commented) → label both metrics on the same callout

---

## 7. What to verify when the client's `.pptx` arrives

Run this mental checklist on the file:

1. Open in PowerPoint → View → Slide Master. Are there 6-7 layouts matching the table in §1?
2. For each layout, open Selection Pane (Home → Arrange → Selection Pane). Are placeholders named or generic ("Title 1", "Picture Placeholder 2")?
3. Are colors/fonts set in the theme (Design tab → Variants), or hardcoded on shapes?
4. Is the footer stripe a master-level element or repeated per slide?
5. Is the client logo a master-level element with a single source?
6. Does the master use 16:9? (Design → Slide Size)

If any of these are missing/wrong, the build phase will start with template-prep work in PowerPoint before any Python code. That's fine — but better to know upfront than to discover mid-build.

---

## 8. Fallback plan if the client's `.pptx` is unsuitable

If the file is locked, broken, or built without named placeholders:

- **Option A:** Strip it for parts (extract theme colors + logo + master layouts) and rebuild a clean Python-friendly master from scratch in PowerPoint. ~2-3 hours of design work.
- **Option B:** Use the file as-is and write a heuristic renderer (find placeholders by position/order, not by name). Brittle but works for one-shot use.
- **Option C:** Skip the client file entirely. Hand-build a generic dark-theme master and a generic light-theme master. Apply per-client palette via theme swap.

Recommended: A. The investment pays back across every future report.
