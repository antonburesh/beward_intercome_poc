"""Outgoing voice must arrive as an even stream, without holes or bursts."""

import struct
import threading
import time
import unittest

from phone.codecs import alaw_to_linear
from phone.sip import MIC_PREROLL_FRAMES, Softphone

SILENCE = bytes([0xD5]) * 160


class Sock:
    def __init__(self):
        self.packets = []
        self.lock = threading.Lock()

    def sendto(self, data, addr):
        with self.lock:
            self.packets.append((time.monotonic(), data))


def tone(samples, amplitude=8000):
    import math

    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * i / 8000)))
        for i in range(samples)
    )


def frame(amplitude=8000, step=0):
    import math

    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * (step + i) / 8000)))
        for i in range(160)
    )


class OutgoingAudioTest(unittest.TestCase):
    def setUp(self):
        self.phone = Softphone()
        self.sock = Sock()
        self.phone.rtp_sock = self.sock
        self.phone.rtp_target = ("192.168.9.82", 4024)

    def tearDown(self):
        self.phone.running = False
        self.phone.sock.close()

    def payload(self, index):
        return self.sock.packets[index][1][12:]

    def test_playback_waits_until_the_buffer_is_full(self):
        self.phone.mic = bytearray(frame() * (MIC_PREROLL_FRAMES - 1))
        for _ in range(MIC_PREROLL_FRAMES - 1):
            self.assertFalse(self.phone._send_audio_frame())
            self.assertEqual(self.payload(-1), SILENCE)
        self.phone.mic.extend(frame())
        self.assertTrue(self.phone._send_audio_frame())
        self.assertNotEqual(self.payload(-1), SILENCE)
        self.assertEqual(self.phone.audio_gaps, 0)

    def test_missing_frame_is_silence_not_a_repeated_syllable(self):
        self.phone.mic = bytearray(frame() * MIC_PREROLL_FRAMES)
        self.assertTrue(self.phone._send_audio_frame())
        first = self.payload(-1)
        self.phone.mic.clear()
        self.assertFalse(self.phone._send_audio_frame())
        self.assertEqual(self.payload(-1), SILENCE)
        self.assertNotEqual(self.payload(-1), first)
        self.assertEqual(self.phone.audio_gaps, 1)

    def test_steady_microphone_has_no_holes(self):
        self.phone.mic = bytearray(frame() * MIC_PREROLL_FRAMES)
        for index in range(12):
            self.assertTrue(self.phone._send_audio_frame())
            self.assertNotEqual(self.payload(-1), SILENCE)
            self.phone.mic.extend(frame(step=160 * index))
        self.assertEqual(self.phone.audio_gaps, 0)

    def test_sequence_and_timestamp_step_once_per_frame(self):
        self.phone.mic = bytearray(frame() * MIC_PREROLL_FRAMES)
        for _ in range(5):
            self.phone._send_audio_frame()
        headers = [struct.unpack("!BBHII", packet[:12]) for _, packet in self.sock.packets]
        sequences = [item[2] for item in headers]
        stamps = [item[3] for item in headers]
        self.assertEqual(sequences, [1, 2, 3, 4, 5])
        self.assertEqual([stamps[i] - stamps[i - 1] for i in range(1, 5)], [160, 160, 160, 160])
        self.assertEqual(headers[0][1] & 0x7F, 8)
        self.assertEqual(headers[0][1] & 0x80, 0x80)
        self.assertEqual(headers[1][1] & 0x80, 0)

    def test_tone_survives_alaw(self):
        self.phone.mic = bytearray(tone(160 * MIC_PREROLL_FRAMES))
        self.phone._send_audio_frame()
        decoded = [alaw_to_linear(byte) for byte in self.payload(-1)]
        original = struct.unpack("<160h", tone(160))
        self.assertGreater(correlation(decoded, original), 0.95)

    def test_a_second_of_backlog_is_dropped(self):
        stale = b"\x00\x00" * 8000
        fresh = frame(amplitude=9000) * MIC_PREROLL_FRAMES
        self.phone.push_mic(stale + fresh)
        self.assertLessEqual(len(self.phone.mic), 320 * MIC_PREROLL_FRAMES)
        self.assertTrue(self.phone._send_audio_frame())
        decoded = [alaw_to_linear(byte) for byte in self.payload(-1)]
        self.assertGreater(max(abs(sample) for sample in decoded), 1000)

    def test_late_clock_does_not_burst(self):
        self.phone.mic = bytearray(frame() * MIC_PREROLL_FRAMES)
        self.phone.next_rtp = time.monotonic()

        def feed():
            while self.phone.running:
                self.phone.push_mic(frame())
                time.sleep(0.02)

        threading.Thread(target=feed, daemon=True).start()
        threading.Thread(target=self.phone.audio_clock, daemon=True).start()
        time.sleep(0.45)
        self.phone.running = False
        time.sleep(0.05)
        packets = list(self.sock.packets)
        gaps = [(packets[i][0] - packets[i - 1][0]) * 1000 for i in range(1, len(packets))]
        speech = [packet for _, packet in packets if packet[12:] != SILENCE]
        self.assertGreaterEqual(len(speech), 15)
        self.assertLessEqual(len(packets), 28)
        self.assertGreaterEqual(min(gaps), 15)
        self.assertLessEqual(max(gaps), 45)
        self.assertEqual(self.phone.audio_gaps, 0)

    def test_pcm_bytes_stay_in_order(self):
        first = frame(amplitude=4000)
        second = frame(amplitude=12000)
        self.phone.push_mic(first[:1])
        self.phone.push_mic(first[1:] + second)
        self.assertEqual(bytes(self.phone.mic), first + second)

    def test_successive_frames_are_not_copied(self):
        pieces = [frame(amplitude=3000 + index * 1500) for index in range(MIC_PREROLL_FRAMES + 4)]
        self.phone.push_mic(b"".join(pieces[:MIC_PREROLL_FRAMES]))
        payloads = []
        for index in range(4):
            self.assertTrue(self.phone._send_audio_frame())
            payloads.append(self.payload(-1))
            self.phone.push_mic(pieces[MIC_PREROLL_FRAMES + index])
        self.assertTrue(all(payload != SILENCE for payload in payloads))
        self.assertEqual(len(payloads), len(set(payloads)))
        self.assertEqual(self.phone.audio_gaps, 0)


def correlation(left, right):
    count = min(len(left), len(right))
    left = left[:count]
    right = right[:count]
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    var_left = sum((item - mean_left) ** 2 for item in left)
    var_right = sum((item - mean_right) ** 2 for item in right)
    if var_left == 0 or var_right == 0:
        return 0
    mixed = sum((left[i] - mean_left) * (right[i] - mean_right) for i in range(count))
    return mixed / (var_left ** 0.5 * var_right ** 0.5)


if __name__ == "__main__":
    unittest.main()
