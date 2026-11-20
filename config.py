import os
import base64
import json
import logging

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")  # fallback; real one from getMe

ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()
}
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-me-bootstrap-secret")

FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://moddergang-37674-default-rtdb.firebaseio.com")
_sa_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "").strip()
if _sa_b64:
    FIREBASE_SERVICE_ACCOUNT = json.loads(base64.b64decode(_sa_b64))
else:
    FIREBASE_SERVICE_ACCOUNT = None  # local dev: backend/serviceAccountKey.json path via env
FIREBASE_SA_PATH = os.getenv("FIREBASE_SA_PATH", "")  # local dev fallback

UPDATES_CHANNEL = os.getenv("UPDATES_CHANNEL", "").strip().lstrip("@")  # button on files; fallback: first channel
OWNER_NAME = os.getenv("OWNER_NAME", "GOD X MODS")
BOT_NAME = os.getenv("BOT_NAME", "GOD X FILES")

AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "600"))  # default 10 min
UPLOAD_RATE_LIMIT = int(os.getenv("UPLOAD_RATE_LIMIT", "10"))  # files per minute
OPEN_UPLOADS = os.getenv("OPEN_UPLOADS", "0") == "1"  # 1 = anyone can host files (default admin-only)
PORT = int(os.getenv("PORT", "8080"))

DB_ROOT = "botdata"


def validate() -> list[str]:
    """Return list of config problems (empty = OK)."""
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN missing")
    if FIREBASE_SERVICE_ACCOUNT is None and not FIREBASE_SA_PATH:
        problems.append("FIREBASE_SERVICE_ACCOUNT_B64 (or FIREBASE_SA_PATH) missing")
    return problems


def log_summary() -> None:
    logging.getLogger("config").info(
        "config loaded: admins=%s autodel=%ss rate_limit=%s/min updates_channel=@%s",
        sorted(ADMIN_IDS) or "(bootstrap via /admin <secret>)",
        AUTO_DELETE_SECONDS, UPLOAD_RATE_LIMIT, UPDATES_CHANNEL or "(first channel)",
    )
