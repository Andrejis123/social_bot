"""
One-time OAuth helper to mint a Google Drive refresh token.

Run once on the Mac after `credentials.json` has been downloaded from the GCP
console. Opens a local browser, asks for `drive.file` consent, then prints the
three values to copy into `.env`:

    GOOGLE_OAUTH_CLIENT_ID=...
    GOOGLE_OAUTH_CLIENT_SECRET=...
    GOOGLE_OAUTH_REFRESH_TOKEN=...

After that, `src/social_bot/drive.py` reads them from settings and never
needs an interactive flow again.
"""

from __future__ import annotations

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from social_bot.config import REPO_ROOT

CREDENTIALS_PATH = REPO_ROOT / "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> None:
    if not CREDENTIALS_PATH.exists():
        sys.exit(
            f"Missing {CREDENTIALS_PATH}. Download the OAuth client JSON from "
            "GCP console (APIs & Services > Credentials > your Desktop client > "
            "Download JSON), rename to credentials.json, place at the repo root."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        scopes=SCOPES,
    )
    # Opens browser, runs local callback on a random free port.
    creds = flow.run_local_server(port=0, prompt="consent")

    client_data = json.loads(CREDENTIALS_PATH.read_text())["installed"]

    if not creds.refresh_token:
        sys.exit(
            "No refresh_token returned. This usually means the OAuth consent "
            "screen is still in 'Testing' mode (refresh tokens expire in 7 days "
            "there and aren't always issued). Publish the app to 'In production' "
            "in the GCP console, then re-run this script."
        )

    print()
    print("=" * 60)
    print("SUCCESS — paste these three lines into your .env:")
    print("=" * 60)
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_data['client_id']}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_data['client_secret']}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60)


if __name__ == "__main__":
    main()
