"""Paths and local-only defaults shared by all application components."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("FACE_APP_DATA_DIR", str(BASE_DIR / "data" / "local"))).resolve()
PHOTO_DIR = Path(os.environ.get("FACE_APP_PHOTO_DIR", str(BASE_DIR / "data" / "photo"))).resolve()
MODEL_DIR = BASE_DIR / "models"
LOGIN_DB = Path(os.environ.get("FACE_APP_LOGIN_DB", str(BASE_DIR / "instance" / "login_database.db"))).resolve()
ANALYTICS_DB = DATA_DIR / "analytics.db"

def prepare_directories():
    for path in (DATA_DIR, PHOTO_DIR, LOGIN_DB.parent):
        path.mkdir(parents=True, exist_ok=True)

def secret_key():
    """Persist a random local session key without changing the user's accounts."""
    import secrets
    prepare_directories()
    path = DATA_DIR / ".session-key"
    try:
        with path.open("x", encoding="ascii") as handle:
            handle.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return path.read_text(encoding="ascii").strip()
