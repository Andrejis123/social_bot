"""
Post-deploy smoke test: `python -m scripts.deploy_check` (run inside the built
image by `just deploy-check`).

Asserts the freshly built `social-bot:latest` image contains the new code AND
guards the two prod-only regressions we've actually been bitten by:
  1. a runtime dependency declared dev-only (python-pptx -> `import pptx`), and
  2. a missing Dockerfile COPY (`assets/` ending up empty in the image).

Exits non-zero (failed assert) so `just deploy-check` surfaces the failure.
"""

from __future__ import annotations

import importlib
import pathlib

# Modules that must import in the runtime image (not just as dev deps).
_REQUIRED_MODULES = ("social_bot", "pptx")


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

    print(
        f"image OK: {', '.join(_REQUIRED_MODULES)} import; "
        f"assets/ has {file_count} files"
    )


if __name__ == "__main__":
    main()
