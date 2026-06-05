import argparse
import json
import urllib.request

from oauth_hub.google_auth import get_existing_credentials
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    config, _account, service, entry = get_connection("youtube_reporting", args.connection_id)
    token_id = entry.get("tokenId", entry["id"])
    scopes = entry.get("scopes", [])
    creds = get_existing_credentials(config, f"{service}.{token_id}", scopes)
    if not creds:
        raise RuntimeError(
            "No valid YouTube Reporting OAuth token with the required scopes. "
            "Run: python -m scripts.auth_google youtube_reporting"
        )

    params = ""
    if entry.get("onBehalfOfContentOwner"):
        params = f"?onBehalfOfContentOwner={entry['onBehalfOfContentOwner']}"

    request = urllib.request.Request(
        f"https://youtubereporting.googleapis.com/v1/reportTypes{params}",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    for item in data.get("reportTypes", [])[:10]:
        print(f"{item.get('id')} | {item.get('name')}")


if __name__ == "__main__":
    main()
