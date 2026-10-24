"""Load config/settings.json. Registration expiry stays fixed."""

import json
import os
from pathlib import Path

# Inside Docker this is 0.0.0.0 and the host publishes only 127.0.0.1:8090.
HTTP_HOST = os.environ.get("HTTP_HOST") or "127.0.0.1"
HTTP_PORT = int(os.environ.get("HTTP_PORT") or 8090)
EXPIRES = 120

# Beward CGI and web login, used when a panel does not set its own.
DEFAULT_SNAPSHOT_PATH = "/cgi-bin/images_cgi?channel=0"
DEFAULT_DOOR_PATH = "/cgi-bin/intercom_cgi?action=maindoor"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"

SERVER_IP = ""
SERVER_PORT = 5060
SIP_USER = ""
SIP_PASSWORD = ""
PANELS = []

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "config" / "settings.json"


def _need(obj, key, where):
    if not isinstance(obj, dict) or key not in obj or obj[key] in ("", None):
        raise SystemExit(f"В {_PATH} не хватает {where}.{key}")
    return obj[key]


def _optional(obj, key, default):
    if key not in obj or obj[key] in ("", None):
        return default
    return obj[key]


def load_settings(path=None):
    """Read settings once at startup into this module."""
    global SERVER_IP, SERVER_PORT, SIP_USER, SIP_PASSWORD, PANELS
    file = Path(path) if path else _PATH
    if not file.is_file():
        raise SystemExit(
            f"Нет файла настроек {file}. Скопируйте примеры: "
            "mkdir -p config && cp config.example/env config.example/settings.json "
            "config.example/subscriber config/"
        )
    raw = json.loads(file.read_text())
    sip = raw.get("sip")
    if not isinstance(sip, dict):
        raise SystemExit(f"В {file} нужен объект sip")
    server_ip = str(_need(sip, "ip", "sip"))
    server_port = int(_need(sip, "port", "sip"))
    sip_user = str(_need(sip, "user", "sip"))
    sip_password = str(_need(sip, "password", "sip"))
    items = raw.get("panels")
    if not isinstance(items, list) or not items:
        raise SystemExit(f"В {file} нужен непустой список panels")
    panels = []
    seen = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"Панель #{index} в {file} должна быть объектом")
        where = f"panels[{index}]"
        user = str(_need(item, "sip_user", where))
        if user in seen:
            raise SystemExit(f"В {file} две панели с sip_user {user}")
        seen.add(user)
        panels.append(
            {
                "name": str(_need(item, "name", where)),
                "sip_user": user,
                "ip": str(_need(item, "ip", where)),
                "snapshot_path": str(_optional(item, "snapshot_path", DEFAULT_SNAPSHOT_PATH)),
                "door_path": str(_optional(item, "door_path", DEFAULT_DOOR_PATH)),
                "username": str(_optional(item, "username", DEFAULT_USERNAME)),
                "password": str(_optional(item, "password", DEFAULT_PASSWORD)),
            }
        )
    SERVER_IP = server_ip
    SERVER_PORT = server_port
    SIP_USER = sip_user
    SIP_PASSWORD = sip_password
    PANELS = panels
    return panels


def panel_for(sip_user):
    """Configured panel for this door SIP user, or None if it is not listed."""
    if not sip_user:
        return None
    wanted = str(sip_user).strip()
    for panel in PANELS:
        if panel["sip_user"] == wanted:
            return panel
    return None
