import os
from dotenv import load_dotenv

load_dotenv()

def _get_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _get_int(name, default):
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default

def get_settings():
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env not in {"development", "production"}:
        raise RuntimeError("APP_ENV must be 'development' or 'production'.")

    is_production = app_env == "production"
    secret_key = os.getenv("SECRET_KEY", "")
    weak_secrets = {"", "change-me", "development-only-secret-key", "development-only-change-before-production"}
    if is_production and (len(secret_key) < 32 or secret_key in weak_secrets):
        raise RuntimeError("Production SECRET_KEY must contain at least 32 characters.")

    return {
        "APP_ENV": app_env,
        "DEBUG": False if is_production else _get_bool("APP_DEBUG", True),
        "SECRET_KEY": secret_key or "development-only-secret-key",
        "TEMPLATES_AUTO_RELOAD": not is_production,
        "WAITRESS_HOST": os.getenv("WAITRESS_HOST", "127.0.0.1"),
        "WAITRESS_PORT": _get_int("WAITRESS_PORT", 50001),
        "WAITRESS_THREADS": _get_int("WAITRESS_THREADS", 8),
        "WAITRESS_BACKLOG": _get_int("WAITRESS_BACKLOG", 256),
        "WAITRESS_CONNECTION_LIMIT": _get_int("WAITRESS_CONNECTION_LIMIT", 256),
        "WAITRESS_CHANNEL_TIMEOUT": _get_int("WAITRESS_CHANNEL_TIMEOUT", 300),
        "TRUSTED_PROXY": os.getenv("TRUSTED_PROXY", "127.0.0.1"),
        "PROXY_COUNT": _get_int("PROXY_COUNT", 1 if is_production else 0),
        "ENABLE_SCHEDULER": _get_bool("ENABLE_SCHEDULER", is_production),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        "SESSION_COOKIE_SECURE": _get_bool("SESSION_COOKIE_SECURE", False),
        "PERMANENT_SESSION_LIFETIME": _get_int("SESSION_LIFETIME_SECONDS", 28800),
        "MAX_CONTENT_LENGTH": _get_int("MAX_UPLOAD_MB", 200) * 1024 * 1024,
    }
