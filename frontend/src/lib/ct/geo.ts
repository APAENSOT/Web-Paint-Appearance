/**
 * Real-world geography for the plant location map.
 *
 * Coastlines come from Natural Earth (world-atlas 110m countries), projected
 * with a real Mercator projection centred on the Indian Ocean so the four
 * plants — Silverton (ZA), Rayong (TH ×2) and Hai Duong (VN) — all sit in one
 * frame, exactly as they do on a real chart.
 */
import { geoMercator, geoPath, type GeoProjection } from "d3-geo";
import { feature, mesh } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import countriesTopo from "world-atlas/countries-110m.json";

export const MAP_W = 1000;
export const MAP_H = 620;

/** Visible window: Southern Africa (left/bottom) through Vietnam/South China Sea (right). */
const NW: [number, number] = [14, 36];
const SE: [number, number] = [118, -40];

function buildProjection(): GeoProjection {
  const p = geoMercator().scale(1).translate([0, 0]);
  const a = p(NW)!;
  const b = p(SE)!;
  const k = Math.min(MAP_W / (b[0] - a[0]), MAP_H / (b[1] - a[1]));
  const cx = (a[0] + b[0]) / 2;
  const cy = (a[1] + b[1]) / 2;
  return p.scale(k).translate([MAP_W / 2 - cx * k, MAP_H / 2 - cy * k]);
}

export const projection = buildProjection();
const pathGen = geoPath(projection);

/** Project real [lon, lat] into SVG space. */
export function project(lon: number, lat: number): { x: number; y: number } {
  const [x, y] = projection([lon, lat]) ?? [0, 0];
  return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)) };
}

const countries = countriesTopo as unknown as Topology<{
  countries: GeometryCollection;
}>;

/** Filled landmasses (one path per country in view). */
export const LAND_PATHS: string[] = feature(countries, countries.objects.countries)
  .features.map((f) => pathGen(f))
  .filter((d): d is string => Boolean(d));

/** Country identity is retained for selection; geometry comes from the same atlas. */
export const PLANT_COUNTRIES = feature(countries, countries.objects.countries)
  .features.filter((f) => ["764", "704", "710"].includes(String(f.id)))
  .map((f) => ({
    id: String(f.id),
    name: (
      { "764": "Thailand", "704": "Vietnam", "710": "South Africa" } as Record<string, string>
    )[String(f.id)],
    path: pathGen(f) ?? "",
    bounds: pathGen.bounds(f),
  }));

/** Country borders as a single mesh (interior boundaries only). */
export const COUNTRY_BORDERS: string =
  pathGen(mesh(countries, countries.objects.countries, (a, b) => a !== b)) ?? "";

/** Latitude/longitude reference lines for the control-room feel. */
export const GRATICULE: string[] = [
  ...[-30, -20, -10, 0, 10, 20, 30].map((lat) => {
    const pts: string[] = [];
    for (let lon = 14; lon <= 118; lon += 4) {
      const { x, y } = project(lon, lat);
      pts.push(`${x} ${y}`);
    }
    return `M ${pts.join(" L ")}`;
  }),
  ...[20, 40, 60, 80, 100].map((lon) => {
    const pts: string[] = [];
    for (let lat = -40; lat <= 36; lat += 2) {
      const { x, y } = project(lon, lat);
      pts.push(`${x} ${y}`);
    }
    return `M ${pts.join(" L ")}`;
  }),
];
