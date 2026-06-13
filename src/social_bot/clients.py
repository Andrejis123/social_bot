"""
Loader for per-client config.

Layout:
    config/clients/{slug}/
        client.yaml        — accounts + AI provider choice + prompt version
        prompt.md          — system prompt template (supports `{{categories}}`)
        categories.yaml    — list of {name, description} for classification

This module returns a `LoadedClient` with everything the pipeline needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .config import get_settings


class AccountConfig(BaseModel):
    platform: str
    handle: str
    is_owned: bool = True
    is_active: bool = True


class AIConfig(BaseModel):
    provider: str = "gemini"                # 'gemini' | 'openai'
    prompt_version: str = "v1"
    prompt_file: str = "prompt.md"
    categories_file: str = "categories.yaml"


class ClientConfig(BaseModel):
    slug: str
    name: str
    accounts: list[AccountConfig] = Field(default_factory=list)
    ai: AIConfig = AIConfig()


class Category(BaseModel):
    name: str
    description: str = ""


@dataclass(slots=True)
class LoadedClient:
    """Parsed config + materialized prompt template + categories."""
    config: ClientConfig
    prompt_template: str
    categories: list[Category]
    dir: Path

    @property
    def slug(self) -> str:
        return self.config.slug

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def active_accounts(self) -> list[AccountConfig]:
        return [a for a in self.config.accounts if a.is_active]


def load_client(slug: str) -> LoadedClient:
    settings = get_settings()
    client_dir = settings.client_dir(slug)

    client_yaml = _read_yaml(client_dir / "client.yaml")
    cfg = ClientConfig(**client_yaml)

    # Enforce slug consistency — folder name is the source of truth.
    if cfg.slug != slug:
        raise ValueError(
            f"client.yaml slug {cfg.slug!r} does not match folder name {slug!r}"
        )

    prompt_path = client_dir / cfg.ai.prompt_file
    categories_path = client_dir / cfg.ai.categories_file

    prompt_template = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    categories = _load_categories(categories_path)

    return LoadedClient(
        config=cfg,
        prompt_template=prompt_template,
        categories=categories,
        dir=client_dir,
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_categories(path: Path) -> list[Category]:
    if not path.exists():
        return []
    data = _read_yaml(path)
    raw = data.get("categories", []) if isinstance(data, dict) else data
    return [Category(**item) for item in raw]
