from .config import load_config


def iter_connections(service_name: str | None = None):
    config = load_config()
    for account in config.get("accounts", []):
        services = account.get("services", {})
        for current_service, entries in services.items():
            if service_name and current_service != service_name:
                continue
            for entry in entries:
                yield config, account, current_service, entry


def get_connection(service_name: str, connection_id: str | None = None):
    matches = list(iter_connections(service_name))
    if connection_id:
        matches = [item for item in matches if item[3].get("id") == connection_id]
    if not matches:
        raise KeyError(f"No connection found for service={service_name!r} id={connection_id!r}")
    if len(matches) > 1 and not connection_id:
        ids = ", ".join(item[3].get("id", "<missing>") for item in matches)
        raise ValueError(f"Multiple {service_name} connections exist. Choose one: {ids}")
    return matches[0]
