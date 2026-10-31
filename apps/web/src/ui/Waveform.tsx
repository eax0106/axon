import { useEffect, useRef } from "react";

/** Live level bars from an AnalyserNode, drawn in the accent token. */
export function Waveform({ analyser }: { analyser: AnalyserNode }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current;
    const g = el?.getContext("2d");
    if (!el || !g) return;
    const data = new Uint8Array(analyser.fftSize);
    const colour = getComputedStyle(el).color; // text-accent on the canvas: stays a token
    let frame = 0;
    const draw = () => {
      const { width, height } = el;
      analyser.getByteTimeDomainData(data);
      g.clearRect(0, 0, width, height);
      g.fillStyle = colour;
      const bars = 48;
      const step = Math.floor(data.length / bars);
      for (let i = 0; i < bars; i++) {
        let peak = 0;
        for (let j = 0; j < step; j++) peak = Math.max(peak, Math.abs((data[i * step + j] ?? 128) - 128));
        const h = Math.max(2, (peak / 128) * height);
        g.fillRect(i * (width / bars) + 1, (height - h) / 2, width / bars - 2, h);
      }
      frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [analyser]);
  return <canvas ref={canvas} width={480} height={56} aria-hidden className="h-14 w-full text-accent" />;
}
