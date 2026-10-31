import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { Color, type Mesh, type ShaderMaterial } from "three";

import type { OrbProps } from "./Orb";

// A sphere pushed outward by 3D value noise; the push grows with the voice level.
const vertex = /* glsl */ `
uniform float uTime; uniform float uLevel;
varying float vPush; varying vec3 vNormal; varying vec3 vView;
float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
float noise(vec3 p) {
  vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}
void main() {
  float n = noise(normal * 2.2 + uTime * 0.35) + 0.5 * noise(normal * 4.4 - uTime * 0.6);
  vPush = n * (0.06 + uLevel * 0.32);
  vec3 p = position + normal * vPush;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vNormal = normalize(normalMatrix * normal); vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
const fragment = /* glsl */ `
uniform vec3 uColor; uniform float uLevel;
varying float vPush; varying vec3 vNormal; varying vec3 vView;
void main() {
  float rim = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.2);
  float body = 0.18 + vPush * 1.6 + uLevel * 0.25;
  gl_FragColor = vec4(uColor * (body + rim * 1.15), clamp(0.55 + rim, 0.0, 1.0));
}`;

function Blob({ level, colour }: OrbProps & { colour: Color }) {
  const mesh = useRef<Mesh>(null);
  const smooth = useRef(0);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uLevel: { value: 0 }, uColor: { value: colour } }), [colour]);
  useFrame((_, dt) => {
    // Ease toward the live level so speech swells and settles instead of flickering.
    smooth.current += (level() - smooth.current) * Math.min(1, dt * 8);
    const m = mesh.current?.material as ShaderMaterial | undefined;
    if (!m?.uniforms.uTime || !m.uniforms.uLevel) return;
    m.uniforms.uTime.value += dt * (0.6 + smooth.current * 2);
    m.uniforms.uLevel.value = smooth.current;
    mesh.current?.rotateY(dt * 0.08);
  });
  return (
    <mesh ref={mesh}>
      <icosahedronGeometry args={[1, 48]} />
      <shaderMaterial vertexShader={vertex} fragmentShader={fragment} uniforms={uniforms} transparent />
    </mesh>
  );
}

/** Renders on demand: 60 fps while there is sound, 30 when quiet, nothing on a hidden tab. */
function Pacer({ level }: OrbProps) {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    let raf = 0;
    let last = 0;
    const tick = (t: number) => {
      raf = requestAnimationFrame(tick);
      if (document.hidden) return;
      const fps = level() > 0.04 ? 60 : 30;
      if (t - last >= 1000 / fps - 2) {
        last = t;
        invalidate();
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [invalidate, level]);
  return null;
}

export default function OrbCanvas(props: OrbProps) {
  // The colour is the accent token, read from CSS so the theme stays the single source.
  const colour = useMemo(() => new Color(getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()), []);
  return (
    <div className="size-full">
      <Canvas frameloop="demand" dpr={[1, 2]} camera={{ position: [0, 0, 3.9], fov: 45 }} gl={{ alpha: true, antialias: true }}>
        <Blob {...props} colour={colour} />
        <Pacer {...props} />
      </Canvas>
    </div>
  );
}
