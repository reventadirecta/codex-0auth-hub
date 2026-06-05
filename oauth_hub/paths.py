from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
SECRETS_DIR = ROOT / "secrets"
TOKENS_DIR = ROOT / "tokens"
DEFAULT_CONFIG = CONFIG_DIR / "accounts.local.json"
EXAMPLE_CONFIG = CONFIG_DIR / "accounts.local.example.json"


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    SECRETS_DIR.mkdir(exist_ok=True)
    TOKENS_DIR.mkdir(exist_ok=True)
