import json
import shutil
from pathlib import Path

from .paths import DEFAULT_CONFIG, EXAMPLE_CONFIG, ROOT, SECRETS_DIR, TOKENS_DIR, ensure_dirs


def bootstrap_config() -> Path:
    ensure_dirs()
    if not DEFAULT_CONFIG.exists():
        shutil.copyfile(EXAMPLE_CONFIG, DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or bootstrap_config()
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_google_client_secret(config: dict) -> Path:
    configured = config.get("defaults", {}).get("googleClientSecretFile", "auto")
    if configured and configured != "auto":
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path

    candidates = sorted(SECRETS_DIR.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(
            "No Google OAuth JSON file found in secrets/. Put the downloaded client JSON there."
        )
    return candidates[0]


def token_path(connection_id: str) -> Path:
    TOKENS_DIR.mkdir(exist_ok=True)
    clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in connection_id)
    return TOKENS_DIR / f"{clean}.token.json"


def resolve_secret_path(path_text: str) -> Path:
    path = Path(path_text)
    candidates: list[Path] = []

    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(ROOT / path)
        candidates.append(SECRETS_DIR / path)

    if path.suffix:
        if path.suffix == ".txt":
            base = path.with_suffix("")
            if base.is_absolute():
                candidates.append(base)
            else:
                candidates.append(ROOT / base)
                candidates.append(SECRETS_DIR / base)
    else:
        with_txt = Path(f"{path_text}.txt")
        candidates.append(ROOT / with_txt)
        candidates.append(SECRETS_DIR / with_txt)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Secret file not found for {path_text!r}")


def read_api_key(path_text: str) -> str:
    path = resolve_secret_path(path_text)
    raw = path.read_text(encoding="utf-8").strip()
    if "=" in raw:
        return raw.split("=", 1)[1].strip()
    return raw
