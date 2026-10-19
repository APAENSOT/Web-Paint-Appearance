import { Car } from "lucide-react";
import { useId } from "react";
import { profilePhoto } from "./display";
const DIMENSIONS: Record<string, [number, number]> = {
  "ranger.png": [1290, 860],
  "raptor.png": [1290, 608],
  "super-duty.png": [1290, 902],
  "everest.png": [1290, 731],
  "transit.png": [1290, 1021],
  "amarok.png": [1290, 664],
  "territory.png": [1290, 891],
};
/** Original photo stays intact; a body-surface mask limits the saved colour preview. */
export function ProfilePhoto({
  model,
  hex,
  colorName,
}: {
  model: string;
  hex?: string | null;
  colorName?: string;
}) {
  const photo = profilePhoto(model);
  const id = useId().replaceAll(":", "");
  const rgb =
    hex && /^#[0-9a-f]{6}$/i.test(hex)
      ? [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255)
      : null;
  const [width, height] = DIMENSIONS[photo?.src ?? ""] ?? [1290, 860];
  const src = `/models/profiles/${photo?.src}`;
  const curve = (channel: number) => `0 ${channel * 0.4} ${channel * 0.85} ${channel * 0.98} 1`;
  return (
    <div className="monthly-photo">
      {photo && rgb ? (
        <svg
          className="monthly-painted-photo"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`${model}, ${colorName ?? "configured colour"} body preview`}
        >
          <defs>
            <mask
              id={`body-mask-${id}`}
              maskUnits="userSpaceOnUse"
              x="0"
              y="0"
              width={width}
              height={height}
              style={{ maskType: "luminance" }}
            >
              <image
                href={`/models/profiles/masks/${photo.src}`}
                width={width}
                height={height}
                preserveAspectRatio="none"
              />
            </mask>
            <filter id={`body-paint-${id}`} colorInterpolationFilters="sRGB">
              <feColorMatrix type="saturate" values="0" />
              <feComponentTransfer>
                <feFuncR type="table" tableValues={curve(rgb[0])} />
                <feFuncG type="table" tableValues={curve(rgb[1])} />
                <feFuncB type="table" tableValues={curve(rgb[2])} />
              </feComponentTransfer>
            </filter>
          </defs>
          <image href={src} width={width} height={height} />
          <image
            href={src}
            width={width}
            height={height}
            filter={`url(#body-paint-${id})`}
            mask={`url(#body-mask-${id})`}
          />
        </svg>
      ) : photo ? (
        <img
          src={`/models/profiles/${photo.src}`}
          alt={`${model} original vehicle reference`}
          loading="lazy"
          decoding="async"
        />
      ) : (
        <div className="monthly-photo-empty">
          <Car size={44} aria-hidden="true" />
          <span>{model}</span>
          <small>Open the prepared 3D body</small>
        </div>
      )}
      {photo?.note && <small className="monthly-photo-note">{photo.note}</small>}
    </div>
  );
}
