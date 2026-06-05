import argparse
import urllib.parse
import urllib.request
import json

from oauth_hub.config import read_api_key
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    _config, _account, _service, entry = get_connection("search", args.connection_id)
    api_key = read_api_key(entry["apiKeyFile"])
    engine_id = entry["engineId"]
    if not engine_id:
        raise ValueError("Set engineId in config/accounts.local.json before testing Search.")

    params = urllib.parse.urlencode({"key": api_key, "cx": engine_id, "q": args.query})
    url = f"https://www.googleapis.com/customsearch/v1?{params}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    for item in data.get("items", [])[:5]:
        print(f"{item.get('title')} | {item.get('link')}")


if __name__ == "__main__":
    main()
