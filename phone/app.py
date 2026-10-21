#!/usr/bin/env python3
"""Local proof-of-concept softphone for the door station.

Registers as SIP user 101 and shows an incoming apartment call,
including the X-Apartment parameter added by Kamailio.

Run from the project directory:

    python3 phone/app.py
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PHONE = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# `python3 phone/app.py` puts this directory ahead of the standard library.
# Drop it so phone/codecs.py does not replace the stdlib codecs module.
sys.path[:] = [
    item for item in sys.path if not item or Path(item).resolve() != _PHONE
]

import threading
import time
from http.server import ThreadingHTTPServer

from phone import config, httpapi
from phone.door import apartment_record, write_apartment
from phone.guest import GuestCodes
from phone.keys import KeyBook
from phone.sip import Softphone
from phone.webrtc_mic import WebRtcMic


def watch_guest_codes():
    while True:
        try:
            if httpapi.GUESTS:
                httpapi.GUESTS.sweep(config.PANELS)
        except Exception as exc:
            print("гость:", exc, flush=True)
        time.sleep(5)


def main():
    config.load_settings()
    httpapi.PHONE = Softphone()
    httpapi.WEBRTC = WebRtcMic(httpapi.PHONE)
    httpapi.WEBRTC.start()
    httpapi.GUESTS = GuestCodes(
        Path(__file__).resolve().parent / "guest_codes.json",
        apartment_record,
        write_apartment,
    )
    httpapi.KEYS = KeyBook(Path(__file__).resolve().parent / "keys.json")
    httpapi.GUESTS.sweep(config.PANELS)
    thread = threading.Thread(target=httpapi.PHONE.loop, daemon=True)
    thread.start()
    threading.Thread(target=watch_guest_codes, name="guest-codes", daemon=True).start()
    server = ThreadingHTTPServer((config.HTTP_HOST, config.HTTP_PORT), httpapi.Handler)
    print(f"Софтфон {config.SIP_USER} → sip:{config.SERVER_IP}:{config.SERVER_PORT}")
    print(f"Откройте http://{config.HTTP_HOST}:{config.HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        httpapi.PHONE.running = False
        server.shutdown()


if __name__ == "__main__":
    main()
