import argparse

from oauth_hub.google_auth import get_credentials
from oauth_hub.registry import get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("service")
    parser.add_argument("--id", dest="connection_id")
    args = parser.parse_args()

    config, _account, service, entry = get_connection(args.service, args.connection_id)
    scopes = entry.get("scopes", [])
    if not scopes:
        raise ValueError(f"Service {service!r} does not define OAuth scopes.")
    token_id = entry.get("tokenId", entry["id"])
    creds = get_credentials(config, f"{service}.{token_id}", scopes)
    print(f"Authenticated: {service}.{entry['id']}")
    print(f"Token valid: {creds.valid}")


if __name__ == "__main__":
    main()
