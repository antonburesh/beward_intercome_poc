"""Guest codes: one per apartment, on one panel or on every panel."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from phone.door import upload_faces
from phone.guest import GuestCodes


def panel(ip, name):
    return {"ip": ip, "name": name}


class Store:
    def __init__(self):
        self.rows = {
            "a": {
                "12": {"Number": "12", "DoorCode": "22222", "DoorCodeActive": "off", "Phone1": "12"},
                "15": {"Number": "15", "DoorCode": "33333", "DoorCodeActive": "on", "Phone1": "15"},
            },
            "b": {
                "12": {"Number": "12", "DoorCode": "55555", "DoorCodeActive": "on", "Phone1": "12"},
                "15": {"Number": "15", "DoorCode": "66666", "DoorCodeActive": "off", "Phone1": "15"},
            },
        }
        self.down = set()
        self.fail_write = set()

    def read(self, item, number):
        if item["ip"] in self.down:
            raise OSError("down")
        row = self.rows.get(item["ip"], {}).get(str(number))
        return dict(row) if row else None

    def write(self, item, record):
        if item["ip"] in self.fail_write:
            return False
        self.rows.setdefault(item["ip"], {})[record["Number"]] = dict(record)
        return True


class GuestTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store()
        self.book = GuestCodes(Path(self.directory.name) / "codes.json", self.store.read, self.store.write)
        self.panels = [panel("a", "Первая"), panel("b", "Вторая")]

    def tearDown(self):
        self.directory.cleanup()

    def test_two_apartments_keep_different_codes(self):
        ok, _ = self.book.issue(self.panels, "12", 30)
        self.assertTrue(ok)
        ok, message = self.book.issue(self.panels, "12", 30)
        self.assertFalse(ok)
        self.assertIn("уже", message)
        ok, _ = self.book.issue(self.panels, "15", 30)
        self.assertTrue(ok)
        issued = {item["apartment"]: item["code"] for item in self.book.public()}
        self.assertEqual(set(issued), {"12", "15"})
        self.assertNotEqual(issued["12"], issued["15"])
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], issued["12"])
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], issued["12"])
        self.assertEqual(self.store.rows["a"]["12"]["Phone1"], "12")

    def test_each_panel_gets_its_own_previous_code_back(self):
        self.book.issue(self.panels, "12", 30)
        self.book.grants["12"]["expires"] = time.time() - 1
        self.book.sweep(self.panels)
        self.assertEqual(self.book.public(), [])
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "off")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")

    def test_revoke_does_not_replace_a_code_changed_on_the_panel(self):
        self.book.issue(self.panels, "15", 30)
        self.store.rows["a"]["15"]["DoorCode"] = "44444"
        ok, _ = self.book.revoke(self.panels, "15")
        self.assertTrue(ok)
        self.assertEqual(self.store.rows["a"]["15"]["DoorCode"], "44444")
        self.assertEqual(self.store.rows["b"]["15"]["DoorCode"], "66666")
        self.assertEqual(self.book.public(), [])

    def test_missing_apartment_is_not_created(self):
        ok, message = self.book.issue(self.panels[:1], "9000", 30)
        self.assertFalse(ok)
        self.assertIn("не найдена", message)
        self.assertNotIn("9000", self.store.rows["a"])

    def test_missing_on_one_panel_writes_nothing(self):
        del self.store.rows["b"]["12"]
        ok, message = self.book.issue(self.panels, "12", 30)
        self.assertFalse(ok)
        self.assertIn("Вторая", message)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.book.public(), [])

    def test_failed_write_rolls_the_first_panel_back(self):
        self.store.fail_write.add("b")
        ok, message = self.book.issue(self.panels, "12", 30)
        self.assertFalse(ok)
        self.assertIn("Вторая", message)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.book.public(), [])

    def test_a_panel_that_was_down_receives_the_code_later(self):
        self.store.down.add("b")
        ok, message = self.book.issue(self.panels, "12", 30)
        self.assertTrue(ok)
        self.assertIn("Вторая", message)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "on")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.store.down.discard("b")
        self.book.sweep(self.panels)
        shared = self.store.rows["a"]["12"]["DoorCode"]
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], shared)
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")
        self.book.grants["12"]["expires"] = time.time() - 1
        self.book.sweep(self.panels)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")

    def test_revoke_keeps_the_grant_while_a_panel_is_down(self):
        self.book.issue(self.panels, "12", 30)
        self.store.down.add("b")
        ok, message = self.book.revoke(self.panels, "12")
        self.assertFalse(ok)
        self.assertIn("Вторая", message)
        self.assertEqual(len(self.book.public()), 1)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.store.down.discard("b")
        ok, _ = self.book.revoke(self.panels, "12")
        self.assertTrue(ok)
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.book.public(), [])

    def test_delete_all_codes_restores_every_apartment(self):
        self.book.issue(self.panels, "12", 30)
        self.book.issue(self.panels, "15", 30)
        ok, message = self.book.revoke_all(self.panels)
        self.assertTrue(ok)
        self.assertEqual(message, "все коды сняты")
        self.assertEqual(self.book.public(), [])
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["b"]["15"]["DoorCode"], "66666")

    def test_one_panel_is_written_and_the_other_stays(self):
        ok, _ = self.book.issue(self.panels, "12", 30, "a")
        self.assertTrue(ok)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "on")
        self.assertNotEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")
        self.assertEqual(set(self.book.grants["12"]["panels"]), {"a"})
        self.assertEqual(self.book.grants["12"]["pending"], [])
        row = self.book.public()[0]
        self.assertEqual(set(row), {"apartment", "code", "expires", "doors"})
        self.assertEqual(row["doors"], "Первая")
        ok, message = self.book.issue(self.panels, "12", 30, "b")
        self.assertFalse(ok)
        self.assertIn("уже", message)
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")

    def test_all_panels_still_get_the_same_code(self):
        ok, _ = self.book.issue(self.panels, "12", 30, "all")
        self.assertTrue(ok)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], self.store.rows["b"]["12"]["DoorCode"])
        self.assertNotEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.book.public()[0]["doors"], "Все домофоны")
        self.assertEqual(set(self.book.grants["12"]["panels"]), {"a", "b"})

    def test_revoke_restores_only_the_panel_that_received_the_code(self):
        self.book.issue(self.panels, "12", 30, "a")
        ok, _ = self.book.revoke(self.panels, "12")
        self.assertTrue(ok)
        self.assertEqual(self.book.public(), [])
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "off")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")

    def test_expiry_restores_only_the_panel_that_received_the_code(self):
        self.book.issue(self.panels, "12", 30, "b")
        self.book.grants["12"]["expires"] = time.time() - 1
        self.book.sweep(self.panels)
        self.assertEqual(self.book.public(), [])
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "off")

    def test_unknown_panel_is_rejected(self):
        ok, message = self.book.issue(self.panels, "12", 30, "192.168.9.99")
        self.assertFalse(ok)
        self.assertIn("домофона нет", message)
        self.assertEqual(self.book.public(), [])
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")

    def test_a_panel_that_was_not_chosen_is_never_caught_up(self):
        self.store.down.add("b")
        ok, _ = self.book.issue(self.panels, "12", 30, "a")
        self.assertTrue(ok)
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertNotIn("b", self.book.grants["12"]["pending"])
        self.store.down.discard("b")
        self.book.sweep(self.panels)
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")
        self.assertNotEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")

    def test_a_chosen_panel_that_is_down_waits_and_the_other_is_left_alone(self):
        self.store.down.add("a")
        ok, message = self.book.issue(self.panels, "12", 30, "a")
        self.assertTrue(ok)
        self.assertIn("Первая", message)
        self.assertEqual(self.book.grants["12"]["pending"], ["a"])
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.store.down.discard("a")
        self.book.sweep(self.panels)
        issued = self.book.grants["12"]["code"]
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], issued)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "on")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCodeActive"], "on")
        self.book.grants["12"]["expires"] = time.time() - 1
        self.book.sweep(self.panels)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["a"]["12"]["DoorCodeActive"], "off")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")

    def test_revoke_does_not_wait_for_a_panel_that_was_not_chosen(self):
        self.book.issue(self.panels, "12", 30, "a")
        self.store.down.add("b")
        ok, _ = self.book.revoke(self.panels, "12")
        self.assertTrue(ok)
        self.assertEqual(self.store.rows["a"]["12"]["DoorCode"], "22222")
        self.assertEqual(self.store.rows["b"]["12"]["DoorCode"], "55555")
        self.assertEqual(self.book.public(), [])


class FaceListTest(unittest.TestCase):
    def test_list_reads_apartment_and_delete_removes_each(self):
        from phone.door import delete_all_faces, delete_face, list_faces

        line = "7\t0\t12\t0\t\t00-00-0000\t12\t\t\t"
        calls = []

        def exchange(panel, method, path, timeout=8, **_kwargs):
            calls.append((panel["ip"], path))
            if "action=list" in path:
                if panel["ip"] == "b":
                    return 0, b""
                return 200, (line + "\n").encode()
            if "action=remove" in path:
                return 200, b"OK"
            return 500, b""

        panels = [panel("a", "Первая"), panel("b", "Вторая")]
        rows = list_faces(panels, exchange)
        self.assertEqual(rows, [{"id": "7", "apartment": "12", "panel": "a", "panel_name": "Первая"}])
        ok, message = delete_face(panels, "a", "7", exchange)
        self.assertTrue(ok)
        self.assertEqual(message, "фотография удалена")
        ok, message = delete_all_faces(panels, exchange)
        self.assertTrue(ok)
        self.assertEqual(message, "все фотографии удалены")
        self.assertTrue(any("action=remove&id=7" in path for _ip, path in calls))

    def test_face_photo_is_the_jpeg_from_the_panel(self):
        from phone.door import fetch_face

        jpeg = b"\xff\xd8\xff" + b"x" * 8
        seen = []

        def exchange(panel, method, path, timeout=8, **_kwargs):
            seen.append(path)
            if path.endswith("id=7"):
                return 200, jpeg
            return 200, b"not a photo"

        image = fetch_face({"ip": "a"}, "7", exchange)
        self.assertEqual(image, jpeg)
        self.assertIsNone(fetch_face({"ip": "a"}, "8", exchange))
        self.assertIsNone(fetch_face({"ip": "a"}, "no", exchange))
        self.assertIn("action=getface&id=7", seen[0])


class FaceBroadcastTest(unittest.TestCase):
    def test_photo_is_sent_to_every_panel(self):
        seen = []

        def fake(item, apartment, image):
            seen.append((item["name"], apartment, image))
            return True, "фото загружено"

        panels = [panel("a", "Первая"), panel("b", "Вторая")]
        with patch("phone.door.upload_face", fake):
            ok, message = upload_faces(panels, "12", b"jpg")
        self.assertTrue(ok)
        self.assertEqual(message, "фото загружено на все панели")
        self.assertEqual(seen, [("Первая", "12", b"jpg"), ("Вторая", "12", b"jpg")])

    def test_one_failed_panel_is_named(self):
        def fake(item, apartment, image):
            if item["ip"] == "b":
                return False, "панель не сохранила фото"
            return True, "фото загружено"

        panels = [panel("a", "Первая"), panel("b", "Вторая")]
        with patch("phone.door.upload_face", fake):
            ok, message = upload_faces(panels, "12", b"jpg")
        self.assertFalse(ok)
        self.assertIn("Вторая", message)


if __name__ == "__main__":
    unittest.main()
