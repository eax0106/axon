/** 16-bit mono PCM WAV, as the speech-to-text endpoint takes it. */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (at: number, s: string) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}

export const RATE = 16_000;
// 25 s of 16 kHz 16-bit audio is 800 KB, well inside the API's 2 MB chunk limit.
const CHUNK_SAMPLES = RATE * 25;

/**
 * Microphone capture at 16 kHz. `onChunk` gets a WAV every 25 s and once more on stop; `analyser`
 * feeds the live waveform.
 * ponytail: ScriptProcessorNode is deprecated but universal and one function; move to an
 * AudioWorklet if it is ever removed from browsers.
 */
export async function record(onChunk: (wav: Blob) => void) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
  const ctx = new AudioContext({ sampleRate: RATE });
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  let pending: Float32Array[] = [];
  let count = 0;
  const flush = () => {
    if (!count) return;
    const all = new Float32Array(count);
    let at = 0;
    for (const part of pending) {
      all.set(part, at);
      at += part.length;
    }
    pending = [];
    count = 0;
    onChunk(encodeWav(all, ctx.sampleRate));
  };
  processor.onaudioprocess = (e) => {
    pending.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    count += e.inputBuffer.length;
    if (count >= CHUNK_SAMPLES) flush();
  };
  source.connect(analyser);
  source.connect(processor);
  processor.connect(ctx.destination); // a ScriptProcessor only runs while connected
  return {
    analyser,
    stop() {
      flush();
      processor.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
    },
  };
}
