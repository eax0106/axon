import { fromPcm16Base64, rms, toPcm16Base64 } from "./pcm";

const RATE = 16_000; // engine/web.py WEB_RATE

/**
 * A browser call to the engine's /web/stream: microphone up, the employee's voice down.
 * Speaks the engine's small protocol: media (mic), playAudio, clearAudio (caller barged in) and
 * checkpoint, answered with playedStream once the audio before it has actually played, so the
 * employee's goodbye is never cut off.
 */
export async function startWebCall(wsUrl: string, onEnd: (reason: string) => void) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const ctx = new AudioContext({ sampleRate: RATE });
  const ws = new WebSocket(wsUrl);

  const mic = ctx.createMediaStreamSource(stream);
  const micMeter = ctx.createAnalyser();
  // ponytail: ScriptProcessorNode is deprecated but universal; an AudioWorklet if browsers drop it.
  const tap = ctx.createScriptProcessor(1024, 1, 1);
  tap.onaudioprocess = (e) => {
    if (ws.readyState === WebSocket.OPEN)
      ws.send(JSON.stringify({ event: "media", payload: toPcm16Base64(e.inputBuffer.getChannelData(0)) }));
  };
  mic.connect(micMeter);
  mic.connect(tap);
  tap.connect(ctx.destination); // silent: the processor only runs while connected

  const voice = ctx.createGain();
  const voiceMeter = ctx.createAnalyser();
  voice.connect(voiceMeter);
  voice.connect(ctx.destination);
  let cursor = 0;
  let playing: AudioBufferSourceNode[] = [];
  const timers = new Set<number>();

  ws.onmessage = (m) => {
    const msg = JSON.parse(String(m.data)) as { event?: string; payload?: string; name?: string };
    if (msg.event === "playAudio" && msg.payload) {
      const samples = fromPcm16Base64(msg.payload);
      const buffer = ctx.createBuffer(1, samples.length, RATE);
      buffer.copyToChannel(samples, 0);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(voice);
      cursor = Math.max(cursor, ctx.currentTime);
      src.start(cursor);
      cursor += buffer.duration;
      playing.push(src);
      src.onended = () => (playing = playing.filter((p) => p !== src));
    } else if (msg.event === "clearAudio") {
      playing.forEach((p) => p.stop());
      playing = [];
      cursor = ctx.currentTime;
    } else if (msg.event === "checkpoint" && msg.name) {
      const name = msg.name;
      const wait = Math.max(0, (cursor - ctx.currentTime) * 1000);
      const id = window.setTimeout(() => {
        timers.delete(id);
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ event: "playedStream", name }));
      }, wait);
      timers.add(id);
    }
  };

  const window_ = new Float32Array(512);
  const stop = () => {
    timers.forEach((id) => clearTimeout(id));
    tap.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    if (ws.readyState <= WebSocket.OPEN) ws.close();
    void ctx.close();
  };
  ws.onclose = (e) => {
    stop();
    onEnd(e.reason || (e.code === 1000 ? "ended" : `closed (${e.code})`));
  };
  return {
    stop,
    /** How loud the call is right now: the employee's voice, or the caller's when it is quiet. */
    level: () => Math.max(rms(voiceMeter, window_), rms(micMeter, window_) * 0.6),
  };
}
