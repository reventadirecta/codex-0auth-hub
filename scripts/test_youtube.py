import argparse

from googleapiclient.discovery import build

from oauth_hub.google_auth import get_credentials
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    config, _account, service, entry = get_connection("youtube", args.connection_id)
    token_id = entry.get("tokenId", entry["id"])
    creds = get_credentials(config, f"{service}.{token_id}", entry.get("scopes", []))
    youtube = build("youtube", "v3", credentials=creds)
    response = youtube.channels().list(part="snippet,contentDetails,statistics", mine=True).execute()
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        print(f"{item.get('id')} | {snippet.get('title')} | subscribers={stats.get('subscriberCount', 'hidden')}")


if __name__ == "__main__":
    main()
