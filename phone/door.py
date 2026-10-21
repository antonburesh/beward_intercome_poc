"""Panel HTTP: digest login, camera snapshot, door open, and face upload.

Door commands go to the panel of the current call. An unknown panel is not guessed.
Face photos go to the panel listed in settings.
"""

import hashlib
import os
import re
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit

# Official rule from the panel page /xml/facedb.xml:
# JPG, at least 300 px on each side, file at most 100 KB.
MAX_FACE_BYTES = 100 * 1024
MAX_FACE_UPLOAD = 12 * 1024 * 1024
FACE_RULE = "Нужен JPG: каждая сторона от 300 пикселей и файл не больше 100 КБ"


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


def panel_text(raw):
    text = (raw or b"").decode("utf-8", "replace").strip()
    return text[:180]


def panel_exchange(panel, method, path, body=None, content_type=None, timeout=8):
    """One HTTP request to a panel, with digest login. Does not follow a write by itself."""
    url = http_url(panel["ip"], path)
    user = panel["username"]
    password = panel["password"]
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type

    def send(extra):
        merged = dict(headers)
        merged.update(extra)
        request = urllib.request.Request(url, data=body, method=method, headers=merged)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()

    try:
        return send({})
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            return exc.code, exc.read() if exc.fp else b""
        challenge = exc.headers.get("WWW-Authenticate", "")
        if not challenge:
            return exc.code, b""
        try:
            return send({"Authorization": http_digest(method, url, user, password, challenge)})
        except urllib.error.HTTPError as exc2:
            return exc2.code, exc2.read() if exc2.fp else b""
        except OSError:
            return 0, b""
    except OSError:
        return 0, b""


def _sips_size(path):
    proc = subprocess.run(
        ["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    width = height = 0
    for line in proc.stdout.splitlines():
        if "pixelWidth:" in line:
            width = int(line.split(":")[1])
        elif "pixelHeight:" in line:
            height = int(line.split(":")[1])
    if width < 1 or height < 1:
        return None
    return width, height


def prepare_face_jpeg(data):
    """Turn a phone photo into the JPG facedb.asp accepts.

    The panel page states the rule in facedb.xml: JPEG, at least 300 px on
    each side, at most 100 KB. A picture straight from the phone is larger
    than that, so it is scaled down here before the upload.
    """
    if not data or len(data) > MAX_FACE_UPLOAD or not os.path.isfile("/usr/bin/sips"):
        return None
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "source"
        dest = Path(folder) / "face.jpg"
        source.write_bytes(data)
        if _sips_size(source) is None:
            return None
        for long_side in (800, 640, 480):
            for quality in (60, 40, 25, 15):
                made = subprocess.run(
                    [
                        "/usr/bin/sips",
                        "-Z", str(long_side),
                        "-s", "format", "jpeg",
                        "-s", "formatOptions", str(quality),
                        str(source),
                        "--out", str(dest),
                    ],
                    capture_output=True,
                )
                if made.returncode != 0 or not dest.is_file():
                    continue
                size = _sips_size(dest)
                if not size:
                    continue
                width, height = size
                if min(width, height) < 300:
                    flag = "--resampleWidth" if width <= height else "--resampleHeight"
                    subprocess.run(
                        ["/usr/bin/sips", flag, "300", str(dest), "--out", str(dest)],
                        capture_output=True,
                    )
                    size = _sips_size(dest)
                    if not size:
                        continue
                    width, height = size
                blob = dest.read_bytes()
                if blob.startswith(b"\xff\xd8") and min(width, height) >= 300 and len(blob) <= MAX_FACE_BYTES:
                    return blob
    return None


def upload_face(panel, apartment, image):
    """Add one face the way the panel page facedb.asp does.

    The page first POSTs the JPG to /cgi-bin/facedb_cgi?action=upload, then
    GETs action=add. There is no apartment field: name and idnumber are the
    person. The apartment number is written into both, list type 0 is the
    white list.
    """
    if not panel:
        return False, "панель не настроена"
    number = str(apartment or "").strip()
    if not number.isdigit() or not 1 <= int(number) <= 9999:
        return False, "укажите номер квартиры"
    jpeg = prepare_face_jpeg(image)
    if not jpeg:
        return False, FACE_RULE
    boundary = secrets.token_hex(8)
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="face.jpg"; filename="face.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + jpeg + f"\r\n--{boundary}--\r\n".encode()
    status, raw = panel_exchange(
        panel,
        "POST",
        "/cgi-bin/facedb_cgi?action=upload",
        payload,
        f"multipart/form-data; boundary={boundary}",
        timeout=20,
    )
    uploaded = panel_text(raw)
    if status != 200 or not uploaded.startswith("OK"):
        return False, uploaded or "панель не приняла фото"
    query = urlencode(
        {
            "action": "add",
            "listtype": "0",
            "name": number,
            "gender": "0",
            "birthdate": "00-00-0000",
            "idnumber": number,
            "phone": "",
            "address": "",
        }
    )
    status, raw = panel_exchange(panel, "GET", "/cgi-bin/facedb_cgi?" + query, timeout=20)
    saved = panel_text(raw)
    if status == 200 and "id=" in saved.lower():
        return True, "фото загружено"
    return False, saved or "панель не сохранила фото"
