import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import type { useWaveMotion } from "./use-wave-motion";

const vertexSource = `
attribute vec2 position;
varying vec2 uv;
void main() {
  uv = position * .5 + .5;
  gl_Position = vec4(position, 0., 1.);
}`;

// Soft paint ribbons with a defined shoulder and satin highlight. Each theme
// has its own flow field; this decoration is independent of measurement data.
const fragmentSource = `
precision highp float;
varying vec2 uv;
uniform float time;
uniform float dark;
uniform vec2 viewport;
void main() {
  vec2 p = vec2(uv.x * viewport.x / viewport.y, uv.y);
  float dayField = p.y * 3.2 + p.x * .34
    + .33 * sin(p.x * 2.3 + time * .15)
    + .14 * sin(p.x * 4.1 - time * .10);
  float nightField = p.y * 4.1 + p.x * .85
    + .38 * sin(p.x * 2.8 - time * .10 + p.y * 1.6)
    + .16 * sin(p.x * 5.0 + time * .08);
  float field = mix(dayField, nightField, dark);
  float wave = .5 + .5 * sin(field * 6.283185 + time * mix(.12, -.09, dark));
  float shoulder = smoothstep(.08, .82, wave);
  float satin = pow(wave, mix(5., 7., dark));
  vec3 base = mix(vec3(.945, .968, .99), vec3(.026, .045, .075), dark);
  vec3 paint = mix(vec3(.55, .735, .855), vec3(.065, .18, .285), dark);
  vec3 sheen = mix(vec3(.99, 1., 1.), vec3(.245, .445, .56), dark);
  vec3 color = mix(base, paint, shoulder * mix(.67, .80, dark));
  color = mix(color, sheen, satin * mix(.82, .55, dark));
  // Ambient theme color ties the visible ribbons back into the page surface.
  color = mix(base, color, .92);
  gl_FragColor = vec4(color, 1.);
}`;

export function WaveMotionControl({ paused, reduced, toggle }: ReturnType<typeof useWaveMotion>) {
  if (reduced) return <span className="text-xs text-muted-foreground">Ambient motion off</span>;
  const Icon = paused ? Play : Pause;
  return (
    <button type="button" onClick={toggle} className="wave-motion-control">
      <Icon size={12} aria-hidden="true" />
      {paused ? "Resume ambient motion" : "Pause ambient motion"}
    </button>
  );
}

export function LandingWaves({ paused, reduced }: { paused: boolean; reduced: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const elapsed = useRef(0);
  const [renderer, setRenderer] = useState("fallback");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", {
      alpha: false,
      antialias: false,
      depth: false,
      powerPreference: "low-power",
    });
    if (!gl) return;
    const shaders: WebGLShader[] = [];
    const compile = (kind: number, source: string) => {
      const shader = gl.createShader(kind);
      if (!shader) return null;
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      return gl.getShaderParameter(shader, gl.COMPILE_STATUS) ? shader : null;
    };
    const vertex = compile(gl.VERTEX_SHADER, vertexSource);
    const fragment = compile(gl.FRAGMENT_SHADER, fragmentSource);
    const program = gl.createProgram();
    const buffer = gl.createBuffer();
    const dispose = () => {
      shaders.forEach((shader) => gl.deleteShader(shader));
      gl.deleteProgram(program);
      gl.deleteBuffer(buffer);
    };
    if (!vertex || !fragment || !program || !buffer) {
      dispose();
      return;
    }
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      dispose();
      return;
    }
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const time = gl.getUniformLocation(program, "time");
    const dark = gl.getUniformLocation(program, "dark");
    const viewport = gl.getUniformLocation(program, "viewport");
    let frame = 0;
    let last = 0;
    let lost = false;
    const draw = () => {
      gl.uniform1f(time, elapsed.current);
      gl.uniform1f(dark, document.documentElement.classList.contains("dark") ? 1 : 0);
      gl.uniform2f(viewport, innerWidth, innerHeight);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };
    const resize = () => {
      // At most ~1M pixels, independent of device pixel ratio.
      const scale = Math.min(1, 1280 / innerWidth, 800 / innerHeight);
      canvas.width = Math.max(1, Math.round(innerWidth * scale));
      canvas.height = Math.max(1, Math.round(innerHeight * scale));
      gl.viewport(0, 0, canvas.width, canvas.height);
      draw();
    };
    const tick = (now: number) => {
      if (lost || document.hidden || paused || reduced) return;
      if (!last) last = now;
      if (now - last >= 1000 / 24) {
        elapsed.current += Math.min(now - last, 100) / 1000;
        last = now;
        draw();
      }
      frame = requestAnimationFrame(tick);
    };
    const visibility = () => {
      cancelAnimationFrame(frame);
      last = 0;
      if (!document.hidden && !paused && !reduced && !lost) frame = requestAnimationFrame(tick);
    };
    const contextLost = () => {
      lost = true;
      cancelAnimationFrame(frame);
      setRenderer("fallback");
    };
    resize();
    setRenderer("webgl");
    visibility();
    const themeObserver = new MutationObserver(() => {
      if (!lost) draw();
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", visibility);
    canvas.addEventListener("webglcontextlost", contextLost);
    return () => {
      cancelAnimationFrame(frame);
      themeObserver.disconnect();
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", visibility);
      canvas.removeEventListener("webglcontextlost", contextLost);
      dispose();
    };
  }, [paused, reduced]);

  return (
    <div
      className="landing-waves"
      aria-hidden="true"
      data-renderer={renderer}
      data-motion={reduced ? "reduced" : paused ? "paused" : "running"}
    >
      <canvas ref={canvasRef} />
    </div>
  );
}
