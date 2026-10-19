import { Suspense, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import {
  ContactShadows,
  Environment,
  Html,
  Lightformer,
  OrbitControls,
  useGLTF,
} from "@react-three/drei";
import { RotateCcw } from "lucide-react";
import * as THREE from "three";
import { HOTSPOTS, STATUS_COLOR, STATUS_LABEL, type Hotspot } from "@/lib/ct/hotspots";

/**
 * Center stage — free-rotating 3D pickup with clickable paint-measurement
 * hotspots (flatcar-configurator reference).
 *
 * Concept: the vehicle is the inspection subject; each hotspot is one
 * measurement point on the body. Hovering a marker previews its name and
 * score, clicking selects it and the left detail panel follows. Hovering a
 * box in the zone charts highlights the same marker here.
 *
 * Function note: model is Kenney car-kit "truck" (CC0), served from
 * /models/pickup.glb. Body material is repainted to the colour accent.
 * OrbitControls = free rotation, wheel zoom, no pan; the reset button
 * remounts the controls at the default camera framing.
 */

function PickupModel({ accent }: { accent: string }) {
  const { scene } = useGLTF("/models/pickup.glb");

  const cloned = useMemo(() => {
    const c = scene.clone(true);
    c.traverse((obj) => {
      if (obj instanceof THREE.Mesh && obj.name === "body") {
        obj.material = new THREE.MeshStandardMaterial({
          color: accent,
          metalness: 0.35,
          roughness: 0.4,
        });
      }
      if (obj instanceof THREE.Mesh) obj.castShadow = true;
    });
    return c;
  }, [scene, accent]);

  return <primitive object={cloned} />;
}

/** Wireframe stand-in while the GLB streams in. */
function StageLoader() {
  return (
    <Html center>
      <div className="flex flex-col items-center gap-2">
        <span
          className="block size-8 animate-spin rounded-full border-2 border-border"
          style={{ borderTopColor: "var(--color-primary)" }}
        />
        <span className="eyebrow">Loading model</span>
      </div>
    </Html>
  );
}

function HotspotMarker({
  spot,
  selected,
  highlighted,
  onSelect,
  onHover,
}: {
  spot: Hotspot;
  selected: boolean;
  highlighted: boolean;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const [hover, setHover] = useState(false);
  const show = hover || highlighted;
  return (
    <Html position={spot.position} center zIndexRange={[20, 0]}>
      <div className="relative">
        <button
          type="button"
          onClick={() => onSelect(spot.id)}
          onPointerEnter={() => {
            setHover(true);
            onHover(spot.id);
          }}
          onPointerLeave={() => {
            setHover(false);
            onHover(null);
          }}
          aria-label={`Measure point: ${spot.label}`}
          className="hotspot-marker"
          data-selected={selected || highlighted}
          style={{ ["--hs" as string]: STATUS_COLOR[spot.status] }}
        >
          <span className="hotspot-ring" />
          <span className="hotspot-dot" />
        </button>

        {/* hover preview — name + score before committing to a click */}
        <div
          className="panel pointer-events-none absolute bottom-full left-1/2 mb-1 -translate-x-1/2 whitespace-nowrap px-2 py-1 transition-all"
          style={{
            transitionDuration: "var(--dur-fast)",
            opacity: show ? 1 : 0,
            transform: `translate(-50%, ${show ? "0" : "4px"})`,
          }}
        >
          <span className="text-[11px] font-bold">{spot.label}</span>
          <span
            className="num ml-1.5 text-[11px] font-bold"
            style={{ color: STATUS_COLOR[spot.status] }}
          >
            {spot.pct.toFixed(1)}%
          </span>
          <span className="eyebrow ml-1.5">{STATUS_LABEL[spot.status]}</span>
        </div>
      </div>
    </Html>
  );
}

export function ModelStage({
  accent,
  selectedId,
  highlightId,
  onSelect,
  onHover,
}: {
  accent: string;
  selectedId: string;
  /** point highlighted from outside (zone chart hover) */
  highlightId?: string | null;
  onSelect: (id: string) => void;
  onHover?: (id: string | null) => void;
}) {
  const controls = useRef<{ reset: () => void } | null>(null);
  const hover = useRef(onHover);
  hover.current = onHover;

  return (
    <>
      <Canvas
        shadows
        camera={{ position: [4.2, 2.6, 5.2], fov: 38 }}
        dpr={[1, 2]}
        style={{ background: "transparent" }}
      >
        <ambientLight intensity={0.45} />
        <directionalLight position={[6, 8, 4]} intensity={1.2} castShadow />
        <Suspense fallback={<StageLoader />}>
          <group position={[0, -0.55, 0]}>
            <PickupModel accent={accent} />
            {HOTSPOTS.map((s) => (
              <HotspotMarker
                key={s.id}
                spot={s}
                selected={s.id === selectedId}
                highlighted={s.id === highlightId}
                onSelect={onSelect}
                onHover={(id) => hover.current?.(id)}
              />
            ))}
          </group>
          <ContactShadows position={[0, -0.56, 0]} opacity={0.35} scale={9} blur={2.4} />
          <Environment resolution={64}>
            <Lightformer intensity={2} position={[0, 5, 0]} scale={[10, 10, 1]} />
            <Lightformer
              intensity={1}
              color="#bcd4ea"
              position={[-5, 1, -1]}
              rotation-y={Math.PI / 2}
              scale={[20, 1, 1]}
            />
            <Lightformer
              intensity={0.8}
              color="#ffffff"
              position={[5, 1, 0]}
              rotation-y={-Math.PI / 2}
              scale={[20, 1, 1]}
            />
          </Environment>
        </Suspense>
        <OrbitControls
          ref={controls as never}
          enablePan={false}
          minDistance={3.2}
          maxDistance={9}
          maxPolarAngle={Math.PI / 2.05}
          enableDamping
          dampingFactor={0.08}
        />
      </Canvas>

      <button
        type="button"
        onClick={() => controls.current?.reset()}
        className="chip absolute bottom-4 right-4 z-10 flex items-center gap-1.5 bg-[var(--color-panel)] px-2.5 py-1.5"
        aria-label="Reset camera view"
      >
        <RotateCcw className="size-3.5" />
        Reset view
      </button>
    </>
  );
}
