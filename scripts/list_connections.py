from oauth_hub.registry import iter_connections


def main() -> None:
    found = False
    for _config, account, service, entry in iter_connections():
        found = True
        print(f"{service}: {entry.get('id')} ({entry.get('label', account.get('label', 'no label'))})")
    if not found:
        print("No connections configured yet.")


if __name__ == "__main__":
    main()
