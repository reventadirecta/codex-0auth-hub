import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request

from oauth_hub.google_auth import get_existing_credentials
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    config, _account, service, entry = get_connection("youtube_analytics", args.connection_id)
    token_id = entry.get("tokenId", entry["id"])
    scopes = entry.get("scopes", [])
    creds = get_existing_credentials(config, f"{service}.{token_id}", scopes)
    if not creds:
        raise RuntimeError(
            "No valid YouTube Analytics OAuth token with the required scopes. "
            "Run: python -m scripts.auth_google youtube_analytics"
        )

    end_date = dt.date.today() - dt.timedelta(days=1)
    start_date = end_date - dt.timedelta(days=6)
    params = urllib.parse.urlencode(
        {
            "ids": entry.get("ids", "channel==MINE"),
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": "views",
            "dimensions": "day",
            "sort": "day",
            "maxResults": 7,
        }
    )
    request = urllib.request.Request(
        f"https://youtubeanalytics.googleapis.com/v2/reports?{params}",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    rows = data.get("rows", [])
    for row in rows:
        print(f"{row[0]} | views={row[1]}")


if __name__ == "__main__":
    main()
