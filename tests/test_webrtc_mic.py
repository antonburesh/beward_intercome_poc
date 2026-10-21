"""WebRTC microphone audio must come out as 8 kHz speech, in order."""

import asyncio
import math
import struct
import unittest
from fractions import Fraction

from av import AudioFrame
from av.audio.resampler import AudioResampler

from phone.codecs import alaw_to_linear
from phone.sip import Softphone
from phone.webrtc_mic import WebRtcMic, resample_to_pcm8


def tone(rate, count, amplitude=10000):
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(count)
    )


def frame_at(pcm, rate, pts):
    samples = len(pcm) // 2
    frame = AudioFrame(format="s16", layout="mono", samples=samples)
    frame.planes[0].update(pcm)
    frame.sample_rate = rate
    frame.pts = pts
    frame.time_base = Fraction(1, rate)
    return frame


class WebRtcMicTest(unittest.TestCase):
    def test_resample_keeps_the_tone(self):
        resampler = AudioResampler(format="s16", layout="mono", rate=8000)
        pcm = b""
        for index in range(10):
            chunk = tone(48000, 960)
            # Continue the sine across frames so the resampler sees one tone.
            start = index * 960
            chunk = b"".join(
                struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * (start + i) / 48000)))
                for i in range(960)
            )
            pcm += resample_to_pcm8(resampler, frame_at(chunk, 48000, start))
        pcm += resample_to_pcm8(resampler, None)
        self.assertGreaterEqual(len(pcm), 160 * 2 * 8)
        decoded = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
        reference = [int(10000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(len(decoded))]
        # The resampler delays the signal by a few samples. Slide to the best fit.
        best = max(correlation(decoded[shift:], reference[:-shift or None]) for shift in range(1, 40))
        self.assertGreater(best, 0.9)

    def test_peer_connection_fills_the_microphone(self):
        asyncio.run(self._peer())

    async def _peer(self):
        from aiortc import RTCPeerConnection
        from aiortc.mediastreams import AudioStreamTrack, MediaStreamError

        class Tone(AudioStreamTrack):
            def __init__(self):
                super().__init__()
                self.n = 0

            async def recv(self):
                if self.n >= 960 * 12:
                    self.stop()
                    raise MediaStreamError
                start = self.n
                pcm = b"".join(
                    struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * (start + i) / 48000)))
                    for i in range(960)
                )
                self.n += 960
                await asyncio.sleep(0.02)
                return frame_at(pcm, 48000, start)

        phone = Softphone()
        bridge = WebRtcMic(phone)
        left = RTCPeerConnection()
        try:
            left.addTrack(Tone())
            offer = await left.createOffer()
            await left.setLocalDescription(offer)
            answer = await bridge.accept_offer(left.localDescription.sdp)
            await left.setRemoteDescription(
                __import__("aiortc").RTCSessionDescription(sdp=answer, type="answer")
            )
            for _ in range(40):
                if len(phone.mic) >= 320 * 6:
                    break
                await asyncio.sleep(0.05)
            self.assertGreaterEqual(len(phone.mic), 320 * 4)
            phone.rtp_sock = _Sock()
            phone.rtp_target = ("192.168.9.82", 4024)
            self.assertTrue(phone._send_audio_frame())
            payload = phone.rtp_sock.packets[-1][12:]
            self.assertNotEqual(payload, bytes([0xD5]) * 160)
            decoded = [alaw_to_linear(byte) for byte in payload]
            self.assertGreater(max(abs(sample) for sample in decoded), 500)
        finally:
            await bridge.close()
            await left.close()
            phone.running = False
            phone.sock.close()


class _Sock:
    def __init__(self):
        self.packets = []

    def sendto(self, data, addr):
        self.packets.append(data)


def correlation(left, right):
    count = min(len(left), len(right))
    if count < 20:
        return 0
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
