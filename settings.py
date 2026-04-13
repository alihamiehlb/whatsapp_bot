"""Environment-based settings for local runs and Railway deployments."""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# ---- Green API Credentials ----
API_URL = os.getenv("API_URL", "https://api.green-api.com").rstrip("/")
INSTANCE_ID = os.getenv("INSTANCE_ID", "")
API_TOKEN = os.getenv("API_TOKEN", "")

# ---- Groups (pick ONE way: names OR chat ids) ----
SOURCE_GROUP_NAME = os.getenv("SOURCE_GROUP_NAME", "")
DESTINATION_GROUP_NAME = os.getenv("DESTINATION_GROUP_NAME", "")
SOURCE_GROUP_CHAT_ID = os.getenv("SOURCE_GROUP_CHAT_ID", "")
DESTINATION_GROUP_CHAT_ID = os.getenv("DESTINATION_GROUP_CHAT_ID", "")
GROUP_LINK_URL = os.getenv("GROUP_LINK_URL", "")

# ---- Runtime ----
MIRROR_DEBUG = _get_bool("MIRROR_DEBUG", True)
STRIP_LINKS_FROM_TEXT = _get_bool("STRIP_LINKS_FROM_TEXT", True)
APPEND_GROUP_LINK_TO_MESSAGES = _get_bool("APPEND_GROUP_LINK_TO_MESSAGES", True)
ENABLE_OUTGOING_DEDUP = _get_bool("ENABLE_OUTGOING_DEDUP", True)
DEDUPE_WINDOW_SECONDS = _get_int("DEDUPE_WINDOW_SECONDS", 10800)
SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "Asia/Beirut")
SCHEDULE_DB_PATH = os.getenv("SCHEDULE_DB_PATH", "data/schedules.db")

# ---- Panel auth (sensitive) ----
PANEL_SECRET_KEY = os.getenv("PANEL_SECRET_KEY", "change-me-before-production")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
