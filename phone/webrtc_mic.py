"""Browser microphone over WebRTC, then G.711 RTP toward the panel.

The browser cannot send UDP. WebRTC is the media path it does have: capture,
echo control, jitter, and Opus. This process is the gateway. It decodes that
track to 8 kHz PCM and the existing RTP clock sends G.711A to the door station.
The one HTTP exchange is the session description, not the audio.
"""

import asyncio
import threading

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from av.audio.resampler import AudioResampler


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

    def start(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="webrtc", daemon=True).start()

    def accept_offer_sync(self, sdp, timeout=5):
        if self.loop is None:
            raise RuntimeError("WebRTC не запущен")
        future = asyncio.run_coroutine_threadsafe(self.accept_offer(sdp), self.loop)
        return future.result(timeout=timeout)

    def close_sync(self):
        if self.loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self.close(), self.loop)
        future.result(timeout=2)

    async def close(self):
        pc = self.pc
        self.pc = None
        if pc is not None:
            await pc.close()

    async def accept_offer(self, sdp):
        await self.close()
        pc = RTCPeerConnection()
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
        return pc.localDescription.sdp

    async def _wait_ice(self, pc):
        if pc.iceGatheringState == "complete":
            return
        done = asyncio.Event()

        @pc.on("icegatheringstatechange")
        def on_change():
            if pc.iceGatheringState == "complete":
                done.set()

        try:
            await asyncio.wait_for(done.wait(), 2)
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
