import { ref, watch } from "vue";
import { state } from "./phoneState";

export const micNote = ref("");

let mediaStarted = false;
let audioCtx;
let audioNext = 0;
let micStream = null;
let micPc = null;
let videoDecoder = null;
let videoCodec = "";
let videoDescription = null;
let pendingVideo = [];
let videoTime = 0;
let armed = false;

export function beep() {
  try {
    audioCtx = audioCtx || new AudioContext();
    const tone = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    tone.frequency.value = 880;
    gain.gain.value = 0.04;
    tone.connect(gain);
    gain.connect(audioCtx.destination);
    tone.start();
    setTimeout(() => tone.stop(), 180);
  } catch {
    // The first beep can be blocked until the browser hears a click.
  }
}

export function startMedia() {
  if (mediaStarted) return;
  mediaStarted = true;
  audioCtx = audioCtx || new AudioContext();
  audioCtx.resume();
  readMedia();
  startMic();
}

function startMic() {
  if (!navigator.mediaDevices || micStream) return;
  micNote.value = "микрофон включается";
  navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    video: false,
  }).then(async (stream) => {
    if (!mediaStarted) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    micStream = stream;
    const pc = new RTCPeerConnection();
    micPc = pc;
    stream.getTracks().forEach((track) => pc.addTrack(track, stream));
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitIce(pc);
    const response = await fetch("/api-intercom/webrtc", {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: pc.localDescription.sdp,
    });
    if (!response.ok) throw new Error("сервер не принял микрофон");
    const answer = await response.text();
    if (micPc !== pc) return;
    await pc.setRemoteDescription({ type: "answer", sdp: answer });
    micNote.value = "микрофон включён";
  }).catch((err) => {
    if (micPc) micPc.close();
    micPc = null;
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
    micNote.value = denied ? "нет доступа к микрофону" : "микрофон не подключился";
  });
}

function waitIce(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      if (pc.iceGatheringState !== "complete") return;
      pc.removeEventListener("icegatheringstatechange", done);
      resolve();
    };
    pc.addEventListener("icegatheringstatechange", done);
    setTimeout(resolve, 1500);
  });
}

function stopMedia() {
  if (micStream) micStream.getTracks().forEach((track) => track.stop());
  if (micPc) micPc.close();
  micPc = null;
  micStream = null;
  micNote.value = "";
  mediaStarted = false;
  if (videoDecoder && videoDecoder.state !== "closed") {
    try {
      videoDecoder.close();
    } catch {
      // The decoder can already be closed when the call ends.
    }
  }
  videoDecoder = null;
  videoCodec = "";
  videoDescription = null;
  pendingVideo = [];
  videoTime = 0;
}

function playPcm(bytes) {
  if (!audioCtx) return;
  const samples = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  const floats = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) floats[i] = samples[i] / 32768;
  const buffer = audioCtx.createBuffer(1, floats.length, 8000);
  buffer.copyToChannel(floats, 0);
  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(audioCtx.destination);
  if (audioNext < audioCtx.currentTime) audioNext = audioCtx.currentTime + 0.08;
  source.start(audioNext);
  audioNext += buffer.duration;
}

function configureVideo(codec, description) {
  if (typeof VideoDecoder === "undefined") return;
  videoCodec = codec;
  videoDescription = description instanceof Uint8Array ? description : new Uint8Array(description);
  if (videoDecoder && videoDecoder.state !== "closed") videoDecoder.close();
  const decoder = new VideoDecoder({
    output(frame) {
      const canvas = document.getElementById("cam");
      if (canvas) {
        if (canvas.width !== frame.displayWidth) canvas.width = frame.displayWidth;
        if (canvas.height !== frame.displayHeight) canvas.height = frame.displayHeight;
        canvas.getContext("2d").drawImage(frame, 0, 0);
      }
      frame.close();
    },
    error() {
      if (videoDecoder === decoder) videoDecoder = null;
    },
  });
  videoDecoder = decoder;
  videoDecoder.configure({ codec, description: videoDescription, optimizeForLatency: true });
  pendingVideo.splice(0).forEach((item) => decodeVideo(item.key, item.data));
}

function decodeVideo(key, data) {
  if ((!videoDecoder || videoDecoder.state !== "configured") && key && videoCodec) {
    configureVideo(videoCodec, videoDescription);
  }
  if (!videoDecoder || videoDecoder.state !== "configured") {
    if (key) pendingVideo = [{ key, data }];
    return;
  }
  videoTime += 33333;
  try {
    videoDecoder.decode(new EncodedVideoChunk({
      type: key ? "key" : "delta",
      timestamp: videoTime,
      data,
    }));
  } catch {
    videoDecoder = null;
    if (key) pendingVideo = [{ key, data }];
  }
}

async function readMedia() {
  while (mediaStarted) {
    try {
      const response = await fetch("/media");
      const reader = response.body.getReader();
      let buf = new Uint8Array(0);
      while (mediaStarted) {
        const chunk = await reader.read();
        if (chunk.done) break;
        const merged = new Uint8Array(buf.length + chunk.value.length);
        merged.set(buf);
        merged.set(chunk.value, buf.length);
        buf = merged;
        while (buf.length >= 5) {
          const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
          const kind = view.getUint8(0);
          const size = view.getUint32(1);
          if (buf.length < 5 + size) break;
          const payload = buf.slice(5, 5 + size);
          buf = buf.slice(5 + size);
          if (kind === 1) playPcm(payload);
          else if (kind === 3 && payload.length > 1) {
            const nameLength = payload[0];
            configureVideo(
              new TextDecoder().decode(payload.slice(1, 1 + nameLength)),
              payload.slice(1 + nameLength),
            );
          } else if (kind === 2 && payload.length > 0) {
            decodeVideo(payload[0] === 1, payload.slice(1));
          }
        }
      }
    } catch {
      if (mediaStarted) await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
}

export function startCallMedia() {
  if (armed) return;
  armed = true;
  watch(() => state.call, (call) => {
    if (call && call.state === "talking") startMedia();
    if (!call) stopMedia();
  });
}
