"""One guest code per apartment, on one panel or on every panel.

Each panel keeps a single door code on the apartment. This book writes the
guest code only to the panels that were chosen, remembers the previous code
there, and puts that previous code back when the time runs out.
"""

import json
import secrets
import threading
import time
from pathlib import Path


def _code(taken):
    for _ in range(20):
        value = str(10000 + secrets.randbelow(90000))
        if value not in taken:
            return value
    return ""


def _panels(panels):
    return [panel for panel in (panels or []) if panel]


def _name(panel):
    return panel.get("name") or panel.get("ip") or "панель"


def _key(panel):
    return str(panel.get("ip") or panel.get("name") or "")


def _choose(panels, target):
    """Panels that should receive this code. An unknown ip is refused."""
    if target in (None, "", "all"):
        return panels, "all", ""
    wanted = str(target).strip()
    if wanted == "all":
        return panels, "all", ""
    match = [panel for panel in panels if str(panel.get("ip") or "") == wanted]
    if len(match) != 1:
        return [], "", "такого домофона нет"
    return match, "one", ""


class GuestCodes:
    def __init__(self, path, read_apartment, write_apartment):
        self.path = Path(path)
        self.read_apartment = read_apartment
        self.write_apartment = write_apartment
        self.lock = threading.Lock()
        self.grants = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            self.grants = {str(key): value for key, value in raw.items() if isinstance(value, dict)}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.grants))
        temporary.replace(self.path)

    def public(self):
        now = time.time()
        with self.lock:
            rows = []
            for apartment, grant in self.grants.items():
                rows.append(
                    {
                        "apartment": apartment,
                        "code": grant.get("code") or "",
                        "expires": grant.get("expires") or now,
                        "doors": grant.get("door") or "Все домофоны",
                    }
                )
        rows.sort(key=lambda item: int(item["apartment"]) if item["apartment"].isdigit() else 0)
        return rows

    def issue(self, panels, apartment, minutes, target=None):
        panels = _panels(panels)
        number = str(apartment or "").strip()
        if not number.isdigit() or not 1 <= int(number) <= 9999:
            return False, "укажите номер квартиры"
        try:
            span = int(minutes)
        except (TypeError, ValueError):
            return False, "срок от 5 минут до суток"
        if not 5 <= span <= 1440:
            return False, "срок от 5 минут до суток"
        if not panels:
            return False, "панель не настроена"
        chosen, scope, error = _choose(panels, target)
        if error:
            return False, error
        with self.lock:
            if number in self.grants:
                return False, "для этой квартиры код уже есть"
            taken = {item.get("code") for item in self.grants.values()}
        records = []
        waiting = []
        missing = []
        for panel in chosen:
            try:
                record = self.read_apartment(panel, number)
            except OSError:
                waiting.append(panel)
                continue
            if not record:
                missing.append(_name(panel))
                continue
            records.append((panel, record))
        if missing:
            return False, "квартира не найдена на " + ", ".join(missing)
        # A chosen panel that is down stays pending and is written later.
        # If every panel was requested and none answered, nothing is saved.
        if not records and not (scope == "one" and waiting):
            return False, "панель не отвечает"
        code = _code(taken | {record.get("DoorCode") for _, record in records})
        if not code:
            return False, "не удалось выбрать код"
        written = []
        for panel, record in records:
            updated = dict(record)
            updated["DoorCode"] = code
            updated["DoorCodeActive"] = "on"
            if not self.write_apartment(panel, updated):
                self._rollback(number, code, written)
                return False, f"{_name(panel)} не записала код"
            written.append((panel, record))
        grant = {
            "code": code,
            "expires": time.time() + span * 60,
            "scope": scope,
            "door": "Все домофоны" if scope == "all" else _name(chosen[0]),
            "pending": [_key(panel) for panel in waiting],
            "panels": {
                _key(panel): {
                    "name": _name(panel),
                    "previous_code": record.get("DoorCode", "0"),
                    "previous_active": record.get("DoorCodeActive", "off"),
                }
                for panel, record in records
            },
        }
        with self.lock:
            if number in self.grants:
                self._rollback(number, code, written)
                return False, "для этой квартиры код уже есть"
            self.grants[number] = grant
            self._save()
        if waiting:
            where = "ждёт: " + ", ".join(_name(panel) for panel in waiting)
            text = f"код записан, {where}"
        elif scope == "one":
            where = _name(chosen[0])
            text = f"код записан на домофон {where}"
        elif len(chosen) > 1:
            where = "все панели"
            text = f"код записан на {where}"
        else:
            where = "панель"
            text = f"код записан на {where}"
        print(f"гость: квартира {number} на {span} мин, {where}", flush=True)
        return True, text

    def revoke(self, panels, apartment):
        panels = _panels(panels)
        number = str(apartment or "").strip()
        with self.lock:
            grant = self.grants.get(number)
            grant = json.loads(json.dumps(grant)) if grant else None
        if not grant:
            return False, "кода нет"
        if not panels:
            return False, "панель не настроена"
        failed = []
        for panel in panels:
            state = self._previous(grant, panel)
            if state is None:
                continue
            if not self._restore(panel, number, grant.get("code"), state):
                failed.append(_name(panel))
        if failed:
            return False, "не снялось: " + ", ".join(failed)
        with self.lock:
            self.grants.pop(number, None)
            self._save()
        print(f"гость: код квартиры {number} снят", flush=True)
        return True, "код снят"

    def revoke_all(self, panels):
        with self.lock:
            numbers = list(self.grants)
        if not numbers:
            return True, "кодов нет"
        failed = []
        for number in numbers:
            ok, _message = self.revoke(panels, number)
            if not ok:
                failed.append(number)
        if failed:
            return False, "не снялись квартиры: " + ", ".join(failed)
        return True, "все коды сняты"

    def sweep(self, panels):
        self._catch_up(_panels(panels))
        now = time.time()
        with self.lock:
            due = [apartment for apartment, grant in self.grants.items() if grant.get("expires", 0) <= now]
        for apartment in due:
            self.revoke(panels, apartment)

    def _catch_up(self, panels):
        """Write a guest code onto a panel that was down when the code was issued."""
        now = time.time()
        with self.lock:
            waiting = []
            for apartment, grant in self.grants.items():
                if grant.get("expires", 0) <= now or not grant.get("pending"):
                    continue
                waiting.append((apartment, json.loads(json.dumps(grant))))
        for apartment, grant in waiting:
            pending = set(grant.get("pending") or [])
            for panel in panels:
                key = _key(panel)
                if key not in pending:
                    continue
                try:
                    record = self.read_apartment(panel, apartment)
                except OSError:
                    continue
                if not record:
                    with self.lock:
                        current = self.grants.get(apartment)
                        if current:
                            current["pending"] = [item for item in current.get("pending") or [] if item != key]
                            self._save()
                    pending.discard(key)
                    continue
                updated = dict(record)
                updated["DoorCode"] = grant.get("code")
                updated["DoorCodeActive"] = "on"
                if not self.write_apartment(panel, updated):
                    continue
                with self.lock:
                    current = self.grants.get(apartment)
                    if not current or current.get("code") != grant.get("code"):
                        self._restore(
                            panel,
                            apartment,
                            grant.get("code"),
                            {
                                "previous_code": record.get("DoorCode", "0"),
                                "previous_active": record.get("DoorCodeActive", "off"),
                            },
                        )
                        continue
                    current.setdefault("panels", {})[key] = {
                        "previous_code": record.get("DoorCode", "0"),
                        "previous_active": record.get("DoorCodeActive", "off"),
                    }
                    current["pending"] = [item for item in current.get("pending") or [] if item != key]
                    self._save()
                pending.discard(key)
                print(f"гость: квартира {apartment} дописана на {_name(panel)}", flush=True)

    def _previous(self, grant, panel):
        stored = grant.get("panels")
        if isinstance(stored, dict):
            state = stored.get(_key(panel))
            if state:
                return state
        if "previous_code" in grant:
            return {
                "previous_code": grant.get("previous_code", "0"),
                "previous_active": grant.get("previous_active", "off"),
            }
        return None

    def _rollback(self, number, code, written):
        for panel, record in written:
            self._restore(
                panel,
                number,
                code,
                {
                    "previous_code": record.get("DoorCode", "0"),
                    "previous_active": record.get("DoorCodeActive", "off"),
                },
            )

    def _restore(self, panel, number, code, state):
        try:
            record = self.read_apartment(panel, number)
        except OSError:
            return False
        if not record:
            return False
        if record.get("DoorCode") != code:
            return True
        record["DoorCode"] = state.get("previous_code", "0")
        record["DoorCodeActive"] = state.get("previous_active", "off")
        return self.write_apartment(panel, record)
