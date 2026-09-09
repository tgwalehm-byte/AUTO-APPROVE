import os


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# Telegram
API_ID = int(get_env("API_ID", "0"))
API_HASH = get_env("API_HASH")
BOT_TOKEN = get_env("BOT_TOKEN")


# Bot owner
OWNER_ID = int(get_env("OWNER_ID", "0"))


# MongoDB
MONGO_URL = get_env("MONGO_URL")


# ------------------------------------------------------------
# Validation
# ------------------------------------------------------------

missing = []

if API_ID <= 0:
    missing.append("API_ID")

if not API_HASH:
    missing.append("API_HASH")

if not BOT_TOKEN:
    missing.append("BOT_TOKEN")

if OWNER_ID <= 0:
    missing.append("OWNER_ID")

if not MONGO_URL:
    missing.append("MONGO_URL")


if missing:
    raise RuntimeError(
        "Missing Config Vars: "
        + ", ".join(missing)
    )