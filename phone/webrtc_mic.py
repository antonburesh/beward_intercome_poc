"""Browser microphone over WebRTC, then G.711 RTP toward the panel.

The browser cannot send UDP. WebRTC is the media path it does have: capture,
echo control, jitter, and Opus. This process is the gateway. It decodes that
track to 8 kHz PCM and the existing RTP clock sends G.711A to the door station.
The one HTTP exchange is the session description, not the audio.
"""

import asyncio
import os
import struct
import threading
import time
from concurrent.futures import TimeoutError as OfferTimeout
from fractions import Fraction

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack
from av import AudioFrame, Packet
from av.audio.resampler import AudioResampler

from phone import config


def advertise_sdp(sdp, ip, port=0):
    """Point the browser at the LAN address Docker publishes, not the container IP."""
    lines = []
    kept_candidate = False
    for line in sdp.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line:
            continue
        if line.startswith("c=IN IP4 "):
            lines.append(f"c=IN IP4 {ip}")
            continue
        if line.startswith("a=rtcp:") and "IP4" in line:
            parts = line.split()
            if parts[-1].count(".") == 3:
                parts[-1] = ip
            lines.append(" ".join(parts))
            continue
        if line.startswith("a=candidate:"):
            parts = line.split()
            if len(parts) < 6 or ":" in parts[4] or kept_candidate:
                continue
            if port and parts[5] != str(port):
                continue
            parts[4] = ip
            kept_candidate = True
            lines.append(" ".join(parts))
            continue
        lines.append(line)
    return "\r\n".join(lines) + "\r\n"


def _pin_udp_port(loop, port):
    original = loop.create_datagram_endpoint

    async def pinned(protocol_factory, local_addr=None, **kwargs):
        if local_addr and len(local_addr) == 2 and local_addr[1] == 0:
            local_addr = (local_addr[0], port)
        return await original(protocol_factory, local_addr=local_addr, **kwargs)

    loop.create_datagram_endpoint = pinned


def resample_to_pcm8(resampler, frame):
    """48 kHz (or whatever the browser sent) to little-endian 8 kHz PCM16."""
    chunks = []
    for item in resampler.resample(frame):
        raw = bytes(item.planes[0])[: item.samples * 2]
        if raw:
            chunks.append(raw)
    return b"".join(chunks)


class PanelAudio(MediaStreamTrack):
    """PCM from the door station, 20 ms at a time, toward the phone."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self.buffer = bytearray()
        self.pts = 0
        self.started = None

    def push(self, pcm):
        self.buffer.extend(pcm)
        extra = len(self.buffer) - 16000
        if extra > 0:
            del self.buffer[:extra]

    async def recv(self):
        samples = 160
        need = samples * 2
        if self.started is None:
            self.started = time.monotonic()
        if len(self.buffer) < need:
            await asyncio.sleep(0.02)
        chunk = bytes(self.buffer[:need]) if len(self.buffer) >= need else bytes(need)
        if len(self.buffer) >= need:
            del self.buffer[:need]
        frame = AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(chunk)
        frame.sample_rate = 8000
        frame.pts = self.pts
        frame.time_base = Fraction(1, 8000)
        self.pts += samples
        wait = self.started + (self.pts / 8000) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        return frame


class PanelVideo(MediaStreamTrack):
    """H.264 from the door camera, decoded so WebRTC can send it to the phone."""

    kind = "video"

    def __init__(self, phone):
        super().__init__()
        self.phone = phone
        self.queue = asyncio.Queue(maxsize=8)
        self.decoded = []
        self.codec = None
        self.pts = 0

    def push(self, payload):
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            return

    def _nals(self, payload):
        nals = []
        offset = 1
        while offset + 4 <= len(payload):
            size = struct.unpack("!I", payload[offset:offset + 4])[0]
            offset += 4
            if size <= 0 or offset + size > len(payload):
                break
            nals.append(payload[offset:offset + size])
            offset += size
        return nals

    def _decode(self, payload):
        import av

        nals = self._nals(payload)
        if not nals:
            return
        if self.codec is None:
            self.codec = av.CodecContext.create("h264", "r")
        with self.phone.lock:
            sps = self.phone.sps
            pps = self.phone.pps
        blob = b""
        if payload[:1] == b"\x01" and sps and pps:
            blob += b"\x00\x00\x00\x01" + sps + b"\x00\x00\x00\x01" + pps
        for nal in nals:
            blob += b"\x00\x00\x00\x01" + nal
        try:
            frames = self.codec.decode(Packet(blob))
        except Exception:
            self.codec = None
            return
        for frame in frames:
            frame.pts = self.pts
            frame.time_base = Fraction(1, 90000)
            self.pts += 3000
            self.decoded.append(frame)

    def _blank(self):
        from av import VideoFrame

        frame = VideoFrame(640, 480, "yuv420p")
        frame.planes[0].update(b"\x10" * frame.planes[0].buffer_size)
        frame.planes[1].update(b"\x80" * frame.planes[1].buffer_size)
        frame.planes[2].update(b"\x80" * frame.planes[2].buffer_size)
        frame.pts = self.pts
        frame.time_base = Fraction(1, 90000)
        self.pts += 3000
        return frame

    async def recv(self):
        try:
            payload = await asyncio.wait_for(self.queue.get(), 0.2)
        except asyncio.TimeoutError:
            payload = None
        if payload:
            self._decode(payload)
        if self.decoded:
            return self.decoded.pop(0)
        await asyncio.sleep(0.03)
        return self._blank()


class WebRtcMic:
    def __init__(self, phone):
        self.phone = phone
        self.loop = None
        self.pc = None
        self.audio = None
        self.video = None
        self.offer_lock = threading.Lock()

    def start(self):
        self.loop = asyncio.new_event_loop()
        port = int(os.environ.get("WEBRTC_PORT") or 0)
        if port:
            _pin_udp_port(self.loop, port)
        threading.Thread(target=self.loop.run_forever, name="webrtc", daemon=True).start()

    def accept_offer_sync(self, sdp, timeout=8):
        if self.loop is None:
            raise RuntimeError("WebRTC не запущен")
        if not self.offer_lock.acquire(blocking=False):
            raise RuntimeError("микрофон уже поднимается")
        try:
            future = asyncio.run_coroutine_threadsafe(self.accept_offer(sdp), self.loop)
            try:
                return future.result(timeout=timeout)
            except OfferTimeout:
                future.cancel()
                asyncio.run_coroutine_threadsafe(self.close(), self.loop).result(timeout=2)
                raise
        finally:
            self.offer_lock.release()

    def _feed(self, kind, payload):
        if kind == 1 and self.audio is not None:
            self.audio.push(payload)
        elif kind == 2 and self.video is not None:
            self.video.push(payload)

    def _attach_downlink(self):
        def sink(kind, payload):
            if self.loop is None:
                return
            self.loop.call_soon_threadsafe(self._feed, kind, payload)

        self.phone.downlink = sink

    async def close(self):
        if self.phone.downlink is not None:
            self.phone.downlink = None
        self.audio = None
        self.video = None
        pc = self.pc
        self.pc = None
        if pc is not None:
            await pc.close()

    async def accept_offer(self, sdp):
        await self.close()
        # No STUN. The public address is written into the answer below.
        # stun.l.google.com from this host does not answer in time, and the
        # browser then gives up before the answer arrives.
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.pc = pc
        self.audio = PanelAudio()
        pc.addTrack(self.audio)
        if "m=video" in sdp:
            self.video = PanelVideo(self.phone)
            pc.addTrack(self.video)
        self._attach_downlink()

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                print("микрофон WebRTC подключён", flush=True)
                task = asyncio.ensure_future(self._consume(track))
                track.on("ended", lambda: task.cancel())

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await self._wait_ice(pc)
        sdp = pc.localDescription.sdp
        port = int(os.environ.get("WEBRTC_PORT") or 0)
        if port and config.SERVER_IP:
            sdp = advertise_sdp(sdp, config.SERVER_IP, port)
        return sdp

    async def _wait_ice(self, pc):
        if pc.iceGatheringState == "complete":
            return
        done = asyncio.Event()

        @pc.on("icegatheringstatechange")
        def on_change():
            if pc.iceGatheringState == "complete":
                done.set()

        try:
            await asyncio.wait_for(done.wait(), 0.5)
        except asyncio.TimeoutError:
            pass

    async def _consume(self, track):
        resampler = AudioResampler(format="s16", layout="mono", rate=8000)
        try:
            while True:
                frame = await track.recv()
                pcm = resample_to_pcm8(resampler, frame)
                if pcm:
                    self.phone.push_mic(pcm)
        except (MediaStreamError, asyncio.CancelledError):
            return
        except Exception as exc:
            print(f"микрофон WebRTC остановился: {exc}", flush=True)
