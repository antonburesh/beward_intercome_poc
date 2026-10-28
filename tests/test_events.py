"""The call stream ignores the panel and ignores RTP counters."""

import unittest

from phone.httpapi import call_event_key, call_payload


class _Phone:
    def __init__(self, call, registered=True):
        self.call = call
        self.registered = registered

    def snapshot(self):
        return {
            "registered": self.registered,
            "error": "",
            "user": "101",
            "server": "192.168.1.10:5060",
            "call": self.call,
            "log": [],
        }


def ringing():
    return {
        "id": "abc",
        "state": "ringing",
        "apartment": "181",
        "panel": "Подъезд 1",
        "panel_known": True,
        "from": "sip:100@host",
        "to": "sip:101@host",
        "params": [],
        "headers": [],
        "rtp": 0,
    }


class CallEventTest(unittest.TestCase):
    def test_payload_is_the_call_without_panel_lists(self):
        payload = call_payload(_Phone(ringing()))
        self.assertEqual(payload["call"]["apartment"], "181")
        self.assertTrue(payload["registered"])
        self.assertNotIn("faces", payload)
        self.assertNotIn("guests", payload)
        self.assertNotIn("keys", payload)

    def test_rtp_ticks_are_the_same_event(self):
        first = call_payload(_Phone(ringing()))
        later = ringing()
        later["rtp"] = 40
        second = call_payload(_Phone(later))
        self.assertEqual(call_event_key(first), call_event_key(second))

    def test_answer_and_hangup_are_new_events(self):
        ringing_key = call_event_key(call_payload(_Phone(ringing())))
        talking = ringing()
        talking["state"] = "talking"
        talking_key = call_event_key(call_payload(_Phone(talking)))
        idle_key = call_event_key(call_payload(_Phone(None)))
        self.assertNotEqual(ringing_key, talking_key)
        self.assertNotEqual(talking_key, idle_key)

    def test_registration_loss_is_a_new_event(self):
        up = call_event_key(call_payload(_Phone(None, registered=True)))
        down = call_event_key(call_payload(_Phone(None, registered=False)))
        self.assertNotEqual(up, down)


if __name__ == "__main__":
    unittest.main()
