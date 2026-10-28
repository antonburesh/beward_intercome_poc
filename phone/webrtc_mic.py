"""Browser microphone over WebRTC, then G.711 RTP toward the panel.

The browser cannot send UDP. WebRTC is the media path it does have: capture,
echo control, jitter, and Opus. This process is the gateway. It decodes that
track to 8 kHz PCM and the existing RTP clock sends G.711A to the door station.
The one HTTP exchange is the session description, not the audio.
"""

import asyncio
import os
import threading
from concurrent.futures import TimeoutError as OfferTimeout

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
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


class WebRtcMic:
    def __init__(self, phone):
        self.phone = phone
        self.loop = None
        self.pc = None
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

    async def close(self):
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
