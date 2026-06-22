"""Per-client brand profile loader.

Reads `assets/clients/<slug>/brand.yaml` and exposes color helpers.
Geometry stays in theme.py — brand only carries client-specific identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pptx.dml.color import RGBColor

from ..config import REPO_ROOT


def _hex_to_rgb(hex_str: str) -> RGBColor:
    s = hex_str.lstrip("#")
    return RGBColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


@dataclass(frozen=True)
class Brand:
    slug: str
    name: str
    logo_path: Path | None
    hero_path: Path | None
    background: RGBColor
    text: RGBColor
    primary: RGBColor
    secondary: RGBColor
    accent: RGBColor
    stripe_colors: tuple[RGBColor, ...]
    heading_font: str
    body_font: str

    @property
    def is_light(self) -> bool:
        """True when the background is lighter than mid-gray (perceived
        luminance > 0.5). Used to pick between dark-theme (stripe at bottom)
        and light-theme (stripe under title) chrome on content slides."""
        r, g, b = self.background[0], self.background[1], self.background[2]
        # Rec. 601 luma approximation, normalized to 0..1
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.5

    @classmethod
    def load(cls, slug: str) -> Brand:
        path = REPO_ROOT / "assets" / "clients" / slug / "brand.yaml"
        if not path.exists():
            path = REPO_ROOT / "assets" / "clients" / "_default" / "brand.yaml"
        data = yaml.safe_load(path.read_text())
        palette = data["palette"]
        typography = data.get("typography", {})

        def _resolve(rel: str | None) -> Path | None:
            if not rel:
                return None
            p = Path(rel)
            return p if p.is_absolute() else REPO_ROOT / p

        return cls(
            slug=slug,
            name=data["name"],
            logo_path=_resolve(data.get("logo_path")),
            hero_path=_resolve(data.get("hero_path")),
            background=_hex_to_rgb(palette["background"]),
            text=_hex_to_rgb(palette["text"]),
            primary=_hex_to_rgb(palette["primary"]),
            secondary=_hex_to_rgb(palette["secondary"]),
            accent=_hex_to_rgb(palette["accent"]),
            stripe_colors=tuple(_hex_to_rgb(c) for c in palette["stripe_colors"]),
            heading_font=typography.get("heading", "Calibri"),
            body_font=typography.get("body", "Calibri"),
        )
