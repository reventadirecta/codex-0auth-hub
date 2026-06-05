import argparse
import json
import urllib.parse
import urllib.request

from oauth_hub.config import read_api_key
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    _config, _account, _service, entry = get_connection("youtube_data", args.connection_id)
    api_key = read_api_key(entry["apiKeyFile"])
    channel_id = entry.get("channelId")
    if not channel_id:
        raise ValueError("Set channelId in config/accounts.local.json before testing YouTube Data API v3.")

    params = urllib.parse.urlencode(
        {
            "key": api_key,
            "id": channel_id,
            "part": "snippet,statistics",
        }
    )
    url = f"https://www.googleapis.com/youtube/v3/channels?{params}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        print(f"{item.get('id')} | {snippet.get('title')} | subscribers={stats.get('subscriberCount', 'hidden')}")


if __name__ == "__main__":
    main()
