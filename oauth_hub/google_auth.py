import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import find_google_client_secret, token_path


def _token_scopes(token_file: Path) -> set[str]:
    data = json.loads(token_file.read_text(encoding="utf-8"))
    scopes = data.get("scopes", [])
    if isinstance(scopes, str):
        scopes = [scopes]
    return set(scopes)


def get_existing_credentials(config: dict, connection_id: str, scopes: list[str]) -> Credentials | None:
    token_file = token_path(connection_id)
    if not token_file.exists():
        return None

    existing_scopes = _token_scopes(token_file)
    if scopes and not set(scopes).issubset(existing_scopes):
        return None

    creds = Credentials.from_authorized_user_file(str(token_file), scopes)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return creds if creds and creds.valid else None


def get_credentials(config: dict, connection_id: str, scopes: list[str]) -> Credentials:
    token_file = token_path(connection_id)
    creds = get_existing_credentials(config, connection_id, scopes)
    if creds:
        return creds

    client_secret = find_google_client_secret(config)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes)
    creds = flow.run_local_server(port=0)

    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds
