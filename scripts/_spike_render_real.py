"""Real-data end-to-end smoke test for the report renderer.

Runs `generate_report` against ecig-monitoring for 2026-04-25..2026-05-25,
converts to PDF + per-slide PNGs via LibreOffice headless so the deck can be
inspected without leaving the terminal.

Usage:
    uv run python scripts/_spike_render_real.py
    uv run python scripts/_spike_render_real.py agape
    uv run python scripts/_spike_render_real.py agape --publish

Pass `--publish` to also upload to Supabase Storage + send a Telegram
notification. Default is local-only (fast iteration, no spam).

Output:
    /tmp/reports/<slug>_<period>.pptx
    /tmp/reports/<slug>_<period>.pdf
    /tmp/reports/<slug>_<period>/slide-NN.png
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone

from claude_social.reports.data import build_period
from claude_social.reports.renderer import (
    DEFAULT_OUT_DIR,
    generate_report,
    publish_report,
)


SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def main() -> None:
    args = [a for a in sys.argv[1:]]
    publish = "--publish" in args
    args = [a for a in args if a != "--publish"]
    client_slug = args[0] if args else "ecig-monitoring"

    start = datetime(2026, 4, 25, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, 23, 59, 59, tzinfo=timezone.utc)
    period = build_period(start, end)

    print(f"→ generating report for {client_slug} ({period.label})"
          + (" (+publish)" if publish else ""))
    if publish:
        pptx_path, uploaded = publish_report(client_slug, period)
        print(f"  wrote {pptx_path}")
        print(f"  uploaded {uploaded.bytes_size / (1024 * 1024):.1f} MB → "
              f"{uploaded.storage_path}")
        print(f"  signed URL: {uploaded.signed_url}")
    else:
        pptx_path = generate_report(client_slug, period)
        print(f"  wrote {pptx_path}")

    pdf_path = pptx_path.with_suffix(".pdf")
    subprocess.run(
        [SOFFICE, "--headless", "--convert-to", "pdf",
         "--outdir", str(DEFAULT_OUT_DIR), str(pptx_path)],
        check=True, capture_output=True,
    )
    print(f"  wrote {pdf_path}")

    png_dir = pptx_path.with_suffix("")
    if png_dir.exists():
        shutil.rmtree(png_dir)
    png_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-png", "-r", "100", str(pdf_path), str(png_dir / "slide")],
        check=True,
    )
    pngs = sorted(png_dir.glob("slide-*.png"))
    print(f"  wrote {len(pngs)} PNGs to {png_dir}")
    for p in pngs:
        print(f"    {p}")


if __name__ == "__main__":
    main()
