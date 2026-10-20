"""Panel HTTP: digest login, camera snapshot, and door open.

Commands go to the panel of the current call. An unknown panel is not guessed.
"""

import hashlib
import re
import secrets
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def http_url(ip, path):
    """http://<panel-ip><cgi path>."""
    if not path.startswith('/'):
        path = '/' + path
    return f'http://{ip}{path}'


def http_digest(method, url, user, password, challenge):
    fields = {}
    for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', challenge):
        fields[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
    realm = fields.get("realm", "")
    nonce = fields.get("nonce", "")
    qop = (fields.get("qop") or "").split(",")[0].strip()
    opaque = fields.get("opaque")
    parsed = urlsplit(url)
    uri = parsed.path + (("?" + parsed.query) if parsed.query else "")
    ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    cnonce = secrets.token_hex(8)
    nc = "00000001"
    if qop:
        response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    else:
        response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    header = (
        f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
        f'algorithm=MD5, response="{response}"'
    )
    if qop:
        header += f', qop={qop}, nc={nc}, cnonce="{cnonce}"'
    if opaque:
        header += f', opaque="{opaque}"'
    return header


def fetch_snapshot(panel):
    if not panel:
        return None
    url = http_url(panel['ip'], panel['snapshot_path'])
    user = panel['username']
    password = panel['password']

    def read(response):
        data = response.read()
        if data.startswith(b"\xff\xd8"):
            return data
        return None

    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return read(response)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            return None
        challenge = exc.headers.get("WWW-Authenticate", "")
        if not challenge:
            return None
        authed = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": http_digest("GET", url, user, password, challenge)},
        )
        try:
            with urllib.request.urlopen(authed, timeout=4) as response:
                return read(response)
        except (urllib.error.HTTPError, OSError):
            return None
    except OSError:
        return None


def open_door(panel):
    if not panel:
        return False, "панель неизвестна"
    url = http_url(panel['ip'], panel['door_path'])
    user = panel['username']
    password = panel['password']
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            return False, "панель не открыла дверь"
        challenge = exc.headers.get("WWW-Authenticate", "")
        if not challenge:
            return False, "панель не открыла дверь"
        authed = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": http_digest("GET", url, user, password, challenge)},
        )
        try:
            with urllib.request.urlopen(authed, timeout=4) as response:
                status = response.status
        except urllib.error.HTTPError:
            return False, "панель не приняла команду"
        except OSError:
            return False, "панель не ответила"
    except OSError:
        return False, "панель не ответила"
    if status in (200, 204, 302):
        return True, "дверь открыта"
    return False, "панель не открыла дверь"
