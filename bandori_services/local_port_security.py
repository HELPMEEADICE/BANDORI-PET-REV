import secrets


def ensure_local_port_token(config, token_key: str) -> str:
    """Return a configured token, generating and persisting one when absent.

    Loopback HTTP endpoints still need authentication because another local
    process or a web page can send plain requests to them.
    """
    token = str(config.get(token_key, "") or "").strip()
    if token:
        return token

    token = secrets.token_urlsafe(18)
    config.set(token_key, token)
    try:
        config.save()
    except Exception as exc:
        print(f"Failed to persist generated {token_key}: {exc}")
    return token
