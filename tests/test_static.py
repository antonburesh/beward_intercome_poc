"""The browser page is the built Vue app."""

import tempfile
import unittest
from pathlib import Path

from phone.httpapi import static_target


class StaticPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self.tmp.name)
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text("<!DOCTYPE html><div id=app>", encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_call_and_settings_routes_serve_the_app(self):
        index = (self.dist / "index.html").resolve()
        self.assertEqual(static_target("/", self.dist), index)
        self.assertEqual(static_target("/settings", self.dist), index)
        self.assertEqual(static_target("/index.html", self.dist), index)

    def test_built_asset_is_served_as_itself(self):
        script = (self.dist / "assets" / "app.js").resolve()
        self.assertEqual(static_target("/assets/app.js", self.dist), script)

    def test_missing_asset_and_path_escape_are_not_the_app(self):
        self.assertIsNone(static_target("/assets/missing.js", self.dist))
        self.assertIsNone(static_target("/../phone/sip.py", self.dist))
        self.assertIsNone(static_target("/%2e%2e/phone/sip.py", self.dist))


if __name__ == "__main__":
    unittest.main()
