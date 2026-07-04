"""
Post-deploy smoke test: `python -m scripts.deploy_check` (run inside the built
image by `just deploy-check`).

Asserts the freshly built `social-bot:latest` image contains the new code AND
guards the prod-only regressions we've actually been bitten by:
  1. a runtime dependency declared dev-only (python-pptx -> `import pptx`),
  2. a missing Dockerfile COPY (`assets/` ending up empty in the image),
  3. env drift: the image's .env must satisfy every required Settings field
     (a renamed/missing var otherwise only surfaces mid-cron-run).

Also prints the installed versions of the critical SDKs so a deploy log shows
exactly what dependency set went live (uv.lock is committed, but trust and
verify).

Exits non-zero (failed assert / pydantic ValidationError) so `just deploy-check`
surfaces the failure.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import pathlib

# Modules that must import in the runtime image (not just as dev deps).
_REQUIRED_MODULES = ("social_bot", "pptx")

# SDKs whose exact deployed version we want in the deploy log.
_VERSIONED_PACKAGES = ("supabase", "google-genai", "openai", "apify-client")


def main() -> None:
    for module in _REQUIRED_MODULES:
        importlib.import_module(module)

    assets = pathlib.Path("assets")
    file_count = (
        sum(1 for path in assets.rglob("*") if path.is_file())
        if assets.is_dir()
        else 0
    )
    assert file_count > 0, "assets/ missing or empty in image"

    # Fails loudly (pydantic ValidationError) if a required env var is missing
    # from the .env the container runs with.
    from social_bot.config import get_settings

    get_settings()

    versions = ", ".join(
        f"{pkg} {importlib.metadata.version(pkg)}" for pkg in _VERSIONED_PACKAGES
    )
    print(
        f"image OK: {', '.join(_REQUIRED_MODULES)} import; "
        f"assets/ has {file_count} files; settings load; {versions}"
    )


if __name__ == "__main__":
    main()
