from oauth_hub.config import bootstrap_config
from oauth_hub.paths import SECRETS_DIR, TOKENS_DIR, ensure_dirs


def main() -> None:
    ensure_dirs()
    config_path = bootstrap_config()
    print(f"Ready: {config_path}")
    print(f"Secrets: {SECRETS_DIR}")
    print(f"Tokens: {TOKENS_DIR}")


if __name__ == "__main__":
    main()
