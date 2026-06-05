from oauth_hub.paths import SECRETS_DIR


def main() -> None:
    files = sorted(path for path in SECRETS_DIR.iterdir() if path.is_file() and path.name != ".gitkeep")
    if not files:
        print("No secret files found.")
        return

    for path in files:
        suffix = path.suffix.lower() or "<none>"
        print(f"{path.name} | {suffix} | {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
