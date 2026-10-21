"""Panel HTTP: digest login, camera snapshot, door open, faces, and keys.

Door commands go to the panel of the current call. An unknown panel is not guessed.
Face photos, guest codes, and keys are written to every panel in settings.
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


def parse_face_line(line):
    """One face row from facedb_cgi action=list. Columns are tab-separated.

    0 id, 1 list type, 2 name, 6 document number. The phone stores the
    apartment in both name and document number.
    """
    cols = str(line or "").split("\t")
    if len(cols) < 7 or not cols[0].strip().isdigit():
        return None
    apartment = cols[6].strip() or cols[2].strip()
    return {"id": cols[0].strip(), "apartment": apartment}


def list_faces(panels, exchange=None):
    """Faces stored on the configured panels. A silent panel is skipped."""
    exchange = exchange or panel_exchange
    found = []
    for panel in panels or []:
        if not panel:
            continue
        try:
            people = _panel_faces(panel, exchange)
        except OSError:
            continue
        for person in people:
            found.append(
                {
                    "id": person["id"],
                    "apartment": person["apartment"],
                    "panel": panel.get("ip") or "",
                    "panel_name": panel.get("name") or "",
                }
            )
    return found


def _panel_faces(panel, exchange):
    found = []
    skip = 0
    count = 50
    for _ in range(20):
        status, raw = exchange(
            panel,
            "GET",
            f"/cgi-bin/facedb_cgi?action=list&skip={skip}&count={count}",
            timeout=6,
        )
        if status != 200:
            raise OSError("панель не ответила")
        lines = [line for line in raw.decode("utf-8", "replace").splitlines() if line.strip()]
        for line in lines:
            person = parse_face_line(line)
            if person:
                found.append(person)
        if len(lines) < count:
            break
        skip += count
    return found


def fetch_face(panel, face_id, exchange=None):
    """JPEG stored for one face. The panel page loads it as getface&id=."""
    exchange = exchange or panel_exchange
    if not panel or not str(face_id or "").isdigit():
        return None
    status, raw = exchange(panel, "GET", f"/cgi-bin/facedb_cgi?action=getface&id={int(face_id)}", timeout=8)
    if status != 200 or not raw or not raw.startswith(b"\xff\xd8"):
        return None
    return raw


def remove_face(panel, face_id, exchange=None):
    """Delete one face. The panel page uses facedb_cgi action=remove&id=."""
    exchange = exchange or panel_exchange
    if not str(face_id or "").isdigit():
        return False
    status, _raw = exchange(panel, "GET", f"/cgi-bin/facedb_cgi?action=remove&id={int(face_id)}")
    return status == 200


def delete_face(panels, panel_ip, face_id, exchange=None):
    panel = next((item for item in panels or [] if item and item.get("ip") == panel_ip), None)
    if panel is None:
        return False, "панель не найдена"
    if not remove_face(panel, face_id, exchange):
        return False, "панель не удалила фото"
    return True, "фотография удалена"


def delete_all_faces(panels, exchange=None):
    rows = list_faces(panels, exchange)
    if not rows:
        return True, "фотографий нет"
    failed = []
    for row in rows:
        panel = next((item for item in panels if item.get("ip") == row["panel"]), None)
        if panel is None or not remove_face(panel, row["id"], exchange):
            failed.append(row.get("panel_name") or "панель")
    if failed:
        names = []
        for name in failed:
            if name not in names:
                names.append(name)
        return False, "не удалилось: " + ", ".join(names)
    return True, "все фотографии удалены"


def upload_faces(panels, apartment, image):
    """Store the same face on every configured panel."""
    panels = [panel for panel in (panels or []) if panel]
    if not panels:
        return False, "панель не настроена"
    failed = []
    saved = 0
    last = ""
    for panel in panels:
        ok, message = upload_face(panel, apartment, image)
        last = message
        if message in ("укажите номер квартиры", FACE_RULE):
            return False, message
        if ok:
            saved += 1
        else:
            failed.append(panel.get("name") or panel.get("ip") or "панель")
    if not failed:
        if len(panels) > 1:
            return True, "фото загружено на все панели"
        return True, "фото загружено"
    if saved:
        return False, "не записалось: " + ", ".join(failed)
    return False, last or "панель не сохранила фото"


def apartment_record(panel, number, exchange=None):
    """One apartment as the panel stores it.

    None means the panel answered and this apartment is not there.
    OSError means the panel did not answer.
    """
    exchange = exchange or panel_exchange
    status, raw = exchange(panel, "GET", f"/cgi-bin/apartment_cgi?action=get&Number={number}")
    if status != 200:
        raise OSError("панель не ответила")
    record = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        record[key.strip()] = value.strip()
    if record.get("Number") != str(number):
        return None
    return record


def write_apartment(panel, record):
    """Write one apartment back. The caller must already have its current fields."""
    fields = dict(record)
    fields["action"] = "set"
    status, raw = panel_exchange(panel, "GET", "/cgi-bin/apartment_cgi?" + urlencode(fields))
    return status == 200 and panel_text(raw).startswith("OK")


# The key table on /mifare.asp has twenty rows per page. A 4-byte UID is stored
# as fourteen hex digits with leading zeros. The door code is a different field
# and is never sent here.
KEY_PAGE = 20
_ROW_NAME = re.compile(
    r"^(uid|type|ckprotected|cipher|cknewcipher|newcipher|code|sector|apt|owner|ckautoperson|ckservice)(\d+)$"
)
_ASSIGN = re.compile(
    r"outcfg_frm\.([A-Za-z0-9_]+)\.(?:value|checked)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([^;\s]+))"
)
_KEPT_OUT = {"DoorCode", "DoorCodeActive", "RegCode", "RegCodeActive"}


def normalize_key(value):
    """UID typed by the resident: 8 or 14 hex digits, separators allowed."""
    text = re.sub(r"[\s:\-]", "", str(value or "")).upper()
    if re.fullmatch(r"[0-9A-F]{8}|[0-9A-F]{14}", text):
        return text
    return ""


def same_key(stored, typed):
    """True when the panel's stored UID is the one the resident typed."""
    left = re.sub(r"[^0-9A-F]", "", str(stored or "").upper())
    right = str(typed or "").upper()
    if not left or not right:
        return False
    return left == right or left == right.zfill(14)


def parse_mifare_page(raw):
    """Settings and key rows from the mifare page. UID values stay in the rows."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    start = text.rfind("<script>")
    script = text[start:].split("</script>", 1)[0] if start >= 0 else text
    settings = {}
    bucket = {}
    for match in _ASSIGN.finditer(script):
        name = match.group(1)
        value = next(part for part in match.groups()[1:] if part is not None)
        row = _ROW_NAME.match(name)
        if row:
            bucket.setdefault(int(row.group(2)), {})[row.group(1)] = value
        elif name not in _KEPT_OUT:
            settings[name] = value
    rows = [bucket[index] for index in sorted(bucket) if bucket[index].get("uid")]
    return settings, rows


def _page_number(settings):
    try:
        return int(str(settings.get("curpage") or "1"))
    except ValueError:
        return 1


def _mifare_query(settings, rows, seldir):
    fields = {key: value for key, value in (settings or {}).items() if key not in _KEPT_OUT and not _ROW_NAME.match(key)}
    fields["optype"] = "0"
    fields["seldir"] = str(seldir)
    fields.setdefault("curpage", "1")
    for index, row in enumerate(rows or [], start=1):
        for key, value in row.items():
            if _ROW_NAME.match(f"{key}1") and value is not None:
                fields[f"{key}{index}"] = value
    return urlencode(fields)


def _read_key_page(panel, exchange):
    status, raw = exchange(panel, "GET", "/mifare.asp", timeout=8)
    if status != 200 or not raw:
        raise OSError("панель не ответила")
    return parse_mifare_page(raw)


def _save_key_page(panel, exchange, settings, rows, seldir="0"):
    """Write this page of keys. The response is the page now on screen."""
    query = _mifare_query(settings, rows, seldir)
    status, raw = exchange(panel, "GET", "/webs/sysMifareEx?" + query, timeout=12)
    if status != 200 or not raw:
        raise OSError("панель не ответила")
    return parse_mifare_page(raw)


def _rewind_keys(panel, exchange):
    """The table opens on the last page someone viewed. Walk back to the first."""
    settings, rows = _read_key_page(panel, exchange)
    guard = 0
    while _page_number(settings) > 1 and guard < 40:
        previous = _page_number(settings)
        settings, rows = _save_key_page(panel, exchange, settings, rows, "-1")
        guard += 1
        if _page_number(settings) >= previous:
            break
    return settings, rows


def _add_key_to_panel(panel, apartment, key, exchange):
    settings, rows = _rewind_keys(panel, exchange)
    guard = 0
    while True:
        if any(same_key(row.get("uid"), key) for row in rows):
            return False, "такой ключ уже есть"
        if len(rows) < KEY_PAGE:
            break
        before = [row.get("uid") for row in rows]
        settings, rows = _save_key_page(panel, exchange, settings, rows, "1")
        guard += 1
        if guard > 40 or [row.get("uid") for row in rows] == before:
            return False, "панель не сохранила ключ"
    rows = list(rows)
    rows.append({"uid": key, "type": "1", "apt": str(apartment)})
    _settings, saved = _save_key_page(panel, exchange, settings, rows, "0")
    if not any(same_key(row.get("uid"), key) for row in saved):
        return False, "панель не сохранила ключ"
    return True, ""


def _remove_key_from_panel(panel, key, exchange):
    settings, rows = _rewind_keys(panel, exchange)
    guard = 0
    while True:
        kept = [row for row in rows if not same_key(row.get("uid"), key)]
        full = len(rows) >= KEY_PAGE
        if len(kept) != len(rows):
            settings, rows = _save_key_page(panel, exchange, settings, kept, "0")
            if any(same_key(row.get("uid"), key) for row in rows):
                return False
            if not full:
                return True
            before = [row.get("uid") for row in rows]
            settings, rows = _save_key_page(panel, exchange, settings, rows, "1")
            if [row.get("uid") for row in rows] == before:
                return True
        elif len(rows) < KEY_PAGE:
            return True
        else:
            before = [row.get("uid") for row in rows]
            settings, rows = _save_key_page(panel, exchange, settings, rows, "1")
            if [row.get("uid") for row in rows] == before:
                return True
        guard += 1
        if guard > 40:
            return True
    return True


def _panel_name(panel):
    return panel.get("name") or panel.get("ip") or "панель"


def add_keys(panels, apartment, key, exchange=None):
    """Write one typed UID onto every panel where that apartment already exists.

    A missing apartment is not created. A panel that does not answer is named
    in the message; the panels that answered still receive the key.
    The third value is how many panels now have this key because of this call
    or already had it. Callers that only list keys typed here should keep the
    key when this number is above zero and at least one panel was written.
    """
    exchange = exchange or panel_exchange
    number = str(apartment or "").strip()
    uid = normalize_key(key)
    if not number.isdigit() or not 1 <= int(number) <= 9999:
        return False, "укажите номер квартиры", 0
    if not uid:
        return False, "укажите номер ключа", 0
    panels = [panel for panel in (panels or []) if panel]
    if not panels:
        return False, "панель не настроена", 0
    failed = []
    missing = []
    wrote = 0
    already = 0
    for panel in panels:
        name = _panel_name(panel)
        try:
            record = apartment_record(panel, number, exchange)
        except OSError:
            failed.append(name)
            continue
        if not record:
            missing.append(name)
            continue
        try:
            ok, message = _add_key_to_panel(panel, number, uid, exchange)
        except OSError:
            failed.append(name)
            continue
        if ok:
            wrote += 1
        elif message == "такой ключ уже есть":
            already += 1
        else:
            failed.append(name)
    if wrote and not failed and not missing:
        if len(panels) > 1:
            return True, "ключ записан на все панели", wrote
        return True, "ключ записан", wrote
    if wrote or already:
        skipped = failed + missing
        if skipped:
            return False, "не записалось: " + ", ".join(skipped), wrote
        return False, "такой ключ уже есть", 0
    if missing and not failed:
        return False, "квартира не найдена", 0
    if failed:
        return False, "не записалось: " + ", ".join(failed), 0
    return False, "панель не отвечает", 0


def delete_key(panels, key, exchange=None):
    """Remove one UID from every panel that has it. A silent panel is named."""
    exchange = exchange or panel_exchange
    uid = normalize_key(key)
    if not uid:
        return False, "укажите номер ключа"
    panels = [panel for panel in (panels or []) if panel]
    if not panels:
        return False, "панель не настроена"
    failed = []
    for panel in panels:
        try:
            gone = _remove_key_from_panel(panel, uid, exchange)
        except OSError:
            gone = False
        if not gone:
            failed.append(_panel_name(panel))
    if failed:
        return False, "не удалилось: " + ", ".join(failed)
    return True, "ключ удалён"
