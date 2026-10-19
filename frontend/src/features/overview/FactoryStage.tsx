import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { Building2, RotateCcw, RotateCw } from "lucide-react";
import type { Group } from "three";
import { FACTORY_DESIGNS, FACTORY_PALETTES } from "./factory-design";
import { FactorySmoke } from "./FactoryLandmark";

export type FactoryDomain = "wave" | "film";

function Unavailable() {
  return (
    <div className="factory-stage__fallback">
      <Building2 size={52} strokeWidth={1} />
      <p>3D view unavailable on this device.</p>
      <span>Plant details are available below.</span>
    </div>
  );
}

class StageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <Unavailable /> : this.props.children;
  }
}

function Block({
  position,
  size,
  color,
  emissive = false,
}: {
  position: [number, number, number];
  size: [number, number, number];
  color: string;
  emissive?: boolean;
}) {
  return (
    <mesh position={position} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial
        color={color}
        roughness={0.65}
        metalness={0.15}
        emissive={emissive ? color : "#000000"}
        emissiveIntensity={0.2}
      />
    </mesh>
  );
}

function Factory({
  code,
  paused,
  dark,
  domain,
  onDomain,
  reduced,
  rotation,
}: {
  code: string;
  paused: boolean;
  dark: boolean;
  domain: FactoryDomain;
  onDomain: (domain: FactoryDomain) => void;
  reduced: boolean;
  rotation: number;
}) {
  const group = useRef<Group>(null);
  const invalidate = useThree((state) => state.invalidate);
  const settled = useRef(false);
  const elapsed = useRef(0);
  useFrame((_, delta) => {
    if (!group.current || settled.current) return;
    elapsed.current += Math.min(delta, 0.05);
    const progress = reduced ? 1 : Math.min(1, elapsed.current / 0.65);
    const ease = 1 - Math.pow(1 - progress, 4);
    group.current.position.y = -0.3 * (1 - ease);
    group.current.rotation.y = -0.16 * (1 - ease);
    if (progress < 1) invalidate();
    else settled.current = true;
  });
  const design = FACTORY_DESIGNS[code] ?? FACTORY_DESIGNS.FTM;
  const palette = FACTORY_PALETTES[dark ? "dark" : "light"];
  return (
    <group rotation={[0, rotation, 0]}>
      <group ref={group}>
        {design.parts.map((part, index) => (
          <Block
            key={index}
            position={part.position}
            size={part.size}
            color={part.area === domain ? (dark ? "#55b4d2" : "#347ca9") : palette[part.material]}
            emissive={part.area === domain || (dark && part.material === "glass")}
          />
        ))}
        <Html position={design.vent} center zIndexRange={[8, 0]} style={{ pointerEvents: "none" }}>
          <FactorySmoke paused={paused || reduced} />
        </Html>
        <Html position={design.wave} center zIndexRange={[10, 0]}>
          <button
            type="button"
            className="factory-hotspot"
            aria-label="Highlight Wave Scan area"
            aria-pressed={domain === "wave"}
            onClick={() => onDomain("wave")}
          >
            WS
          </button>
        </Html>
        <Html position={design.film} center zIndexRange={[10, 0]}>
          <button
            type="button"
            className="factory-hotspot"
            aria-label="Highlight Film Thickness area"
            aria-pressed={domain === "film"}
            onClick={() => onDomain("film")}
          >
            FT
          </button>
        </Html>
      </group>
    </group>
  );
}

function ContextGuard({ onLost }: { onLost: () => void }) {
  const gl = useThree((state) => state.gl);
  useEffect(() => {
    const canvas = gl.domElement;
    const lost = (event: Event) => {
      event.preventDefault();
      onLost();
    };
    canvas.addEventListener("webglcontextlost", lost);
    return () => canvas.removeEventListener("webglcontextlost", lost);
  }, [gl, onLost]);
  return null;
}

function CameraReset({ revision }: { revision: number }) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  useEffect(() => {
    camera.position.set(8.4, 6.9, 9.5);
    camera.lookAt(0, 0.25, 0);
    invalidate();
  }, [camera, invalidate, revision]);
  return null;
}

export default function FactoryStage({
  code,
  paused,
  domain,
  onDomain,
  reduced,
}: {
  code: string;
  paused: boolean;
  domain: FactoryDomain;
  onDomain: (domain: FactoryDomain) => void;
  reduced: boolean;
}) {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [rotation, setRotation] = useState(0);
  const [reset, setReset] = useState(0);
  const [lost, setLost] = useState(false);
  const [supported] = useState(() => {
    try {
      const context = document.createElement("canvas").getContext("webgl2");
      if (!context) return false;
      context.getExtension("WEBGL_lose_context")?.loseContext();
      return true;
    } catch {
      return false;
    }
  });
  useEffect(() => {
    const observer = new MutationObserver(() =>
      setDark(document.documentElement.classList.contains("dark")),
    );
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return (
    <div
      className="factory-stage"
      data-design={FACTORY_DESIGNS[code]?.name}
      aria-label={`Illustrative factory model for ${code}`}
    >
      <StageBoundary>
        {lost || !supported ? (
          <Unavailable />
        ) : (
          <Canvas
            shadows
            frameloop="demand"
            dpr={[1, 1.5]}
            camera={{ position: [8.4, 6.9, 9.5], fov: 36 }}
            gl={{ antialias: true, powerPreference: "low-power" }}
            fallback={<Unavailable />}
          >
            <ambientLight intensity={dark ? 1.2 : 1.7} />
            <directionalLight
              position={[3, 8, 4]}
              intensity={2.6}
              castShadow
              shadow-mapSize={[512, 512]}
              shadow-camera-left={-6}
              shadow-camera-right={6}
              shadow-camera-top={6}
              shadow-camera-bottom={-6}
              shadow-bias={-0.001}
            />
            <directionalLight position={[-4, 3, -3]} color="#9bc4e5" intensity={1.6} />
            <Factory
              key={code}
              code={code}
              paused={paused}
              dark={dark}
              domain={domain}
              onDomain={onDomain}
              reduced={reduced}
              rotation={rotation}
            />
            <OrbitControls
              key={reset}
              enablePan={false}
              enableZoom={false}
              enableDamping={!reduced}
              dampingFactor={0.12}
              minPolarAngle={Math.PI / 6}
              maxPolarAngle={Math.PI / 2.6}
              target={[0, 0.25, 0]}
            />
            <CameraReset revision={reset} />
            <ContextGuard onLost={() => setLost(true)} />
          </Canvas>
        )}
      </StageBoundary>
      <div className="factory-stage__tools">
        <span>{FACTORY_DESIGNS[code]?.name} · illustrative</span>
        <div>
          <button
            type="button"
            aria-label="Rotate factory left"
            onClick={() => setRotation((value) => value - Math.PI / 6)}
          >
            <RotateCcw size={14} />
          </button>
          <button
            type="button"
            aria-label="Rotate factory right"
            onClick={() => setRotation((value) => value + Math.PI / 6)}
          >
            <RotateCw size={14} />
          </button>
          <button
            type="button"
            onClick={() => {
              setRotation(0);
              setReset((value) => value + 1);
            }}
          >
            Reset
          </button>
        </div>
      </div>
    </div>
  );
}
