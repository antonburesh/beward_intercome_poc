"""Keys typed on the phone are written to every panel, and only those keys."""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from phone.door import add_keys, delete_key, same_key
from phone.keys import KeyBook


TYPED = "AABBCCDD"
OTHER = "11223344"


def panel(ip, name):
    return {"ip": ip, "name": name, "username": "admin", "password": "admin"}


class Board:
    def __init__(self):
        self.apartments = {
            "12": {"Number": "12", "DoorCode": "22222", "RegCode": "0", "Phone1": "12"},
        }
        self.pages = {1: []}
        self.current = 1
        self.down = False
        self.queries = []
        self.settings = {"curpage": "1", "ckcollectkeys": "1", "regkeys": "", "smartdays": "7"}

    def render(self):
        rows = self.pages.get(self.current, [])
        parts = ["<script>"]
        self.settings["curpage"] = str(self.current)
        for name, value in self.settings.items():
            if name.startswith("ck"):
                parts.append(f"document.outcfg_frm.{name}.checked={value};document.outcfg_frm.{name}.value={value};")
            else:
                parts.append(f"document.outcfg_frm.{name}.value='{value}';")
        parts.append("FillTableBody();")
        for index, row in enumerate(rows, start=1):
            for name in ("uid", "type", "sector", "apt"):
                if name in row:
                    parts.append(f"document.outcfg_frm.{name}{index}.value='{row[name]}';")
            for name in ("ckprotected", "cknewcipher", "ckautoperson", "ckservice"):
                value = row.get(name, "0")
                parts.append(
                    f"document.outcfg_frm.{name}{index}.checked={value};"
                    f"document.outcfg_frm.{name}{index}.value={value};"
                )
        parts.append("</script>")
        return "".join(parts).encode()


class Yard:
    def __init__(self):
        self.boards = {"a": Board(), "b": Board()}

    def exchange(self, item, method, path, body=None, content_type=None, timeout=8):
        board = self.boards[item["ip"]]
        if board.down:
            return 0, b""
        parsed = urlsplit(path)
        if parsed.path == "/cgi-bin/apartment_cgi":
            number = parse_qs(parsed.query).get("Number", [""])[0]
            record = board.apartments.get(number)
            if not record:
                return 200, b"\n"
            text = "".join(f"{key}={value}\n" for key, value in record.items())
            return 200, text.encode()
        if parsed.path == "/mifare.asp":
            return 200, board.render()
        if parsed.path == "/webs/sysMifareEx":
            board.queries.append(parsed.query)
            query = parse_qs(parsed.query)
            rows = {}
            for key, values in query.items():
                name = key.rstrip("0123456789")
                if not key[len(name):].isdigit():
                    continue
                if name not in {
                    "uid", "type", "sector", "apt", "ckprotected", "cknewcipher",
                    "ckautoperson", "ckservice", "code", "owner", "cipher", "newcipher",
                }:
                    continue
                rows.setdefault(int(key[len(name):]), {})[name] = values[0]
            ordered = []
            for index in sorted(rows):
                row = rows[index]
                uid = str(row.get("uid") or "").upper()
                if not uid:
                    continue
                if len(uid) < 14:
                    uid = uid.zfill(14)
                row["uid"] = uid
                row.setdefault("type", "1")
                row.setdefault("sector", "1")
                ordered.append(row)
            board.pages[board.current] = ordered
            seldir = (query.get("seldir") or ["0"])[0]
            if seldir == "1":
                board.current += 1
                board.pages.setdefault(board.current, [])
            elif seldir == "-1" and board.current > 1:
                board.current -= 1
            if "ckcollectkeys" in query:
                board.settings["ckcollectkeys"] = query["ckcollectkeys"][0]
            return 200, board.render()
        return 404, b""


class KeyTest(unittest.TestCase):
    def setUp(self):
        self.yard = Yard()
        self.panels = [panel("a", "Первая"), panel("b", "Вторая")]
        self.directory = tempfile.TemporaryDirectory()
        self.book = KeyBook(Path(self.directory.name) / "keys.json")

    def tearDown(self):
        self.directory.cleanup()

    def _add(self, apartment, key, panels=None):
        return add_keys(panels or self.panels, apartment, key, self.yard.exchange)

    def _has(self, ip, key):
        for rows in self.yard.boards[ip].pages.values():
            if any(same_key(row.get("uid"), key) for row in rows):
                return True
        return False

    def test_add_writes_the_key_on_every_panel(self):
        self.yard.boards["a"].pages[1] = [
            {"uid": OTHER.zfill(14), "type": "1", "apt": "12", "sector": "1"}
        ]
        ok, message, wrote = self._add("12", "aa bb-cc:dd")
        self.assertTrue(ok)
        self.assertIn("все панели", message)
        self.assertEqual(wrote, 2)
        self.assertTrue(self._has("a", TYPED))
        self.assertTrue(self._has("b", TYPED))
        self.assertTrue(self._has("a", OTHER))
        self.assertEqual(self.yard.boards["a"].apartments["12"]["DoorCode"], "22222")
        self.assertEqual(self.yard.boards["a"].apartments["12"]["RegCode"], "0")
        self.assertEqual(self.yard.boards["a"].settings["ckcollectkeys"], "1")
        for board in self.yard.boards.values():
            for query in board.queries:
                self.assertNotIn("DoorCode", query)
                self.assertNotIn("RegCode=", query)

    def test_missing_apartment_is_not_created(self):
        ok, message, wrote = self._add("9000", TYPED)
        self.assertFalse(ok)
        self.assertIn("не найдена", message)
        self.assertEqual(wrote, 0)
        self.assertNotIn("9000", self.yard.boards["a"].apartments)
        self.assertNotIn("9000", self.yard.boards["b"].apartments)
        self.assertFalse(self._has("a", TYPED))
        self.assertEqual(self.yard.boards["a"].queries, [])

    def test_delete_removes_the_key_from_every_panel_that_has_it(self):
        self.yard.boards["b"].pages[1] = [
            {"uid": OTHER.zfill(14), "type": "1", "apt": "12", "sector": "1"}
        ]
        self._add("12", TYPED, self.panels[:1])
        self.assertTrue(self._has("a", TYPED))
        self.assertFalse(self._has("b", TYPED))
        ok, message = delete_key(self.panels, TYPED, self.yard.exchange)
        self.assertTrue(ok)
        self.assertIn("удал", message)
        self.assertFalse(self._has("a", TYPED))
        self.assertFalse(self._has("b", TYPED))
        self.assertTrue(self._has("b", OTHER))
        self.assertEqual(self.yard.boards["b"].apartments["12"]["DoorCode"], "22222")

    def test_a_failed_panel_is_reported_and_the_other_is_written(self):
        self.yard.boards["b"].down = True
        ok, message, wrote = self._add("12", TYPED)
        self.assertFalse(ok)
        self.assertIn("Вторая", message)
        self.assertEqual(wrote, 1)
        self.assertTrue(self._has("a", TYPED))
        self.assertFalse(self._has("b", TYPED))
        self.yard.boards["b"].down = False
        ok, message = delete_key(self.panels, TYPED, self.yard.exchange)
        self.yard.boards["a"].down = True
        self.assertTrue(ok)
        self.assertFalse(self._has("a", TYPED))
        ok, message = delete_key(self.panels, TYPED, self.yard.exchange)
        self.assertFalse(ok)
        self.assertIn("Первая", message)

    def test_full_page_keeps_existing_keys_and_uses_the_next_page(self):
        self.yard.boards["a"].pages[1] = [
            {"uid": f"{index:014X}", "type": "1", "apt": "12", "sector": "1"}
            for index in range(1, 21)
        ]
        before = [row["uid"] for row in self.yard.boards["a"].pages[1]]
        ok, _message, wrote = self._add("12", TYPED, self.panels[:1])
        self.assertTrue(ok)
        self.assertEqual(wrote, 1)
        self.assertEqual([row["uid"] for row in self.yard.boards["a"].pages[1]], before)
        self.assertTrue(any(same_key(row.get("uid"), TYPED) for row in self.yard.boards["a"].pages[2]))
        ok, _message = delete_key(self.panels[:1], TYPED, self.yard.exchange)
        self.assertTrue(ok)
        self.assertFalse(self._has("a", TYPED))
        self.assertEqual([row["uid"] for row in self.yard.boards["a"].pages[1]], before)

    def test_the_book_remembers_only_a_key_this_phone_wrote(self):
        book = KeyBook(
            Path(self.directory.name) / "managed.json",
            write=lambda panels, apartment, key: add_keys(panels, apartment, key, self.yard.exchange),
            erase=lambda panels, key: delete_key(panels, key, self.yard.exchange),
        )
        ok, _message = book.add(self.panels, "12", TYPED)
        self.assertTrue(ok)
        self.assertEqual(book.public(), [{"apartment": "12", "key": TYPED}])
        ok, _message = book.remove(self.panels, TYPED)
        self.assertTrue(ok)
        self.assertEqual(book.public(), [])
        self.assertFalse(self._has("a", TYPED))
        self.assertFalse(self._has("b", TYPED))


if __name__ == "__main__":
    unittest.main()
