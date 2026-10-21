"""Keys typed on this phone.

The file remembers only the numbers a resident entered here, so the page can
show and delete those keys. A key that was already on the panel is not copied
into this list.
"""

import threading
from pathlib import Path

from phone.door import add_keys, delete_key, normalize_key
from phone.persist import read_dict, write_dict


class KeyBook:
    def __init__(self, path, write=None, erase=None):
        self.path = Path(path)
        self.write = write or add_keys
        self.erase = erase or delete_key
        self.lock = threading.Lock()
        self.items = {}
        self._load()

    def _load(self):
        for key, value in read_dict(self.path).items():
            number = normalize_key(key)
            if not number or not isinstance(value, dict):
                continue
            apartment = str(value.get("apartment") or "").strip()
            if apartment.isdigit():
                self.items[number] = {"apartment": apartment}

    def _save(self):
        write_dict(self.path, self.items)

    def public(self):
        with self.lock:
            rows = [
                {"apartment": item["apartment"], "key": key}
                for key, item in self.items.items()
            ]
        rows.sort(key=lambda item: (int(item["apartment"]), item["key"]))
        return rows

    def add(self, panels, apartment, key):
        number = normalize_key(key)
        if not number:
            return False, "укажите номер ключа"
        with self.lock:
            if number in self.items:
                return False, "такой ключ уже есть"
            ok, message, wrote = self.write(panels, apartment, number)
            if wrote:
                self.items[number] = {"apartment": str(apartment or "").strip()}
                self._save()
            return ok, message

    def remove(self, panels, key):
        number = normalize_key(key)
        if not number:
            return False, "укажите номер ключа"
        with self.lock:
            if number not in self.items:
                return False, "ключа нет"
        ok, message = self.erase(panels, number)
        if not ok:
            return False, message
        with self.lock:
            self.items.pop(number, None)
            self._save()
        return True, message

    def remove_all(self, panels):
        with self.lock:
            numbers = list(self.items)
        if not numbers:
            return True, "ключей нет"
        failed = []
        for number in numbers:
            ok, _message = self.remove(panels, number)
            if ok:
                continue
            with self.lock:
                apartment = (self.items.get(number) or {}).get("apartment") or ""
            if apartment:
                failed.append(apartment)
        if failed:
            return False, "не удалились квартиры: " + ", ".join(failed)
        return True, "все ключи удалены"
