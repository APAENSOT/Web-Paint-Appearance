/**
 * TEMPLATE DATA LAYER. To use real data: replace WAREHOUSES, PORTS, SUPPLIERS, and
 * SHIPMENTS with your network (locations take real lon/lat via project()), and replace
 * FLOORPLANS with your warehouse zone layouts. The engine, map, tables, and KPIs derive
 * automatically. SCENARIOS are authored what-if cases; rewrite them for disruptions
 * relevant to your network.
 *
 * Meridian Freight & Fulfillment — deterministic demo dataset.
 * All figures are fictional and generated from a fixed seed so the
 * dashboard renders identically on server and client.
 */

import { project } from "./geo";

export type Risk = "nominal" | "caution" | "critical";

/**
 * Feed-mode display labels. Internal keys stay nominal/caution/critical so
 * real data wiring needs no refactor — only this display layer maps the words.
 * เขียว = Update (ตรงเวลา) · เหลือง = Late (ช้า) · แดง = Missing (ขาดข้อมูล)
 */
export const FEED_LEVEL_LABEL: Record<Risk, string> = {
  nominal: "Update",
  caution: "Late",
  critical: "Missing",
};

export interface Warehouse {
  id: string;
  code: string;
  name: string;
  x: number;
  y: number;
  capacity: number;
}

export interface Port {
  id: string;
  name: string;
  short: string;
  region: "overseas" | "domestic";
  /** ISO-3166 alpha-2 of the origin country — the key tariff scenarios target. */
  country: string;
  x: number;
  y: number;
}

export interface Supplier {
  id: string;
  name: string;
  portId: string;
  otif: number[]; // last 8 weeks, %
  defectRate: number; // %
  leadTimeVar: number[]; // last 8 weeks, days of variance
  category: string;
  /**
   * Spot-buy premium over contracted unit cost, as a fraction of declared value.
   * What you pay to place volume with a supplier you hold no commitment with, on
   * short notice. Realistic 8–16% band, deterministic per supplier.
   */
  spotPremium: number;
}

/**
 * Where a load sits in its lifecycle. The forward book (booked + planned) is the part
 * of duty exposure anyone can still act on; in-transit freight is already committed.
 */
export type Stage = "transit" | "booked" | "planned";

export interface Shipment {
  id: string;
  supplierId: string;
  portId: string;
  warehouseId: string;
  contents: string;
  units: number;
  value: number;
  /** Days until arrival at the port of ENTRY. Defined identically for every stage. */
  etaDays: number;
  /** Days until the load physically departs origin. 0 for freight already sailing. */
  departsInDays: number;
  stage: Stage;
  baseRisk: number; // 0..1
  progress: number; // 0..1 along route (0 for anything pre-departure)
  mode: "ocean" | "air" | "road" | "rail";
  /** MFN duty already being paid today, as a fraction of declared value. 0 for domestic. */
  baseDutyRate: number;
  /**
   * Air-charter freight premium this load would incur if expedited, as a fraction of
   * declared value. NOT dutiable: US customs value is FOB, so international freight is
   * outside the dutiable base. Demo-tuned 6–14% band, deterministic per load.
   */
  airPremiumRate: number;
}

export interface Zone {
  id: string;
  label: string;
  kind: "rack" | "bulk" | "cold" | "stage" | "dock";
  x: number;
  y: number;
  w: number;
  h: number;
  skuCount: number;
  fill: number; // 0..1 of capacity
  daysOfCover: number;
  topSkus: { sku: string; name: string; onHand: number; reorder: number }[];
}

/* ---------- deterministic RNG ---------- */
function mulberry32(a: number) {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(20260723);
const between = (a: number, b: number) => a + rnd() * (b - a);
const pick = <T>(arr: T[]) => arr[Math.floor(rnd() * arr.length)];
const round = (n: number, d = 0) => Number(n.toFixed(d));

/* ---------- geography (real lon/lat, projected into viewBox 0 0 1000 620) ---------- */

export const WAREHOUSES: Warehouse[] = [
  { id: "oak", code: "OAK", name: "Oakland DC", ...project(-122.27, 37.8), capacity: 42000 },
  { id: "rno", code: "RNO", name: "Reno DC", ...project(-119.81, 39.53), capacity: 28000 },
  {
    id: "slc",
    code: "SLC",
    name: "Salt Lake City DC",
    ...project(-111.89, 40.76),
    capacity: 34000,
  },
  { id: "phx", code: "PHX", name: "Phoenix DC", ...project(-112.07, 33.45), capacity: 31000 },
];

export const PORTS: Port[] = [
  {
    id: "sha",
    name: "Port of Shanghai",
    short: "SHA",
    region: "overseas",
    country: "CN",
    ...project(121.8, 31.2),
  },
  {
    id: "tsn",
    name: "Port of Tianjin",
    short: "TSN",
    region: "overseas",
    country: "CN",
    ...project(117.75, 39.0),
  },
  {
    id: "pus",
    name: "Port of Busan",
    short: "PUS",
    region: "overseas",
    country: "KR",
    ...project(129.05, 35.1),
  },
  {
    id: "sgn",
    name: "Port of Cat Lai",
    short: "SGN",
    region: "overseas",
    country: "VN",
    ...project(106.8, 10.76),
  },
  {
    id: "mnl",
    name: "Port of Manila",
    short: "MNL",
    region: "overseas",
    country: "PH",
    ...project(120.97, 14.6),
  },
  {
    id: "oakp",
    name: "Port of Oakland",
    short: "OAKP",
    region: "domestic",
    country: "US",
    ...project(-122.33, 37.79),
  },
  {
    id: "lax",
    name: "Port of Long Beach",
    short: "LGB",
    region: "domestic",
    country: "US",
    ...project(-118.2, 33.75),
  },
  {
    id: "sea",
    name: "Port of Tacoma",
    short: "TAC",
    region: "domestic",
    country: "US",
    ...project(-122.43, 47.26),
  },
  {
    id: "den",
    name: "Denver Rail Hub",
    short: "DEN",
    region: "domestic",
    country: "US",
    ...project(-104.99, 39.74),
  },
  {
    id: "dfw",
    name: "Dallas Crossdock",
    short: "DFW",
    region: "domestic",
    country: "US",
    ...project(-96.8, 32.78),
  },
];

/* ---------- suppliers ---------- */

const SUPPLIER_SEED: [string, string, string][] = [
  ["Tianjin Metals Ltd.", "tsn", "Fasteners & castings"],
  ["Shanghai Polymer Works", "sha", "Injection-molded housings"],
  ["Busan Precision Co.", "pus", "Bearings & spindles"],
  ["Mekong Textile Group", "sgn", "Industrial textiles"],
  ["Luzon Wire & Cable", "mnl", "Cable assemblies"],
  ["Ridgeline Packaging", "sea", "Corrugate & pallets"],
  ["Sierra Fabrication", "oakp", "Sheet-metal enclosures"],
  ["Harbor Electronics", "lax", "Control boards"],
  ["Front Range Chemical", "den", "Coatings & adhesives"],
  ["Brazos Components", "dfw", "Hydraulic fittings"],
  ["Sonoran Plastics", "lax", "Extruded profiles"],
  ["Wasatch Tooling", "den", "Dies & tooling"],
];

/**
 * Spot-buy premium stream. Kept on its own seed so adding it did not shift any
 * pre-existing figure generated from `rnd`. 8–16% over contract is a demo-plausible
 * band for short-notice volume with a supplier you have no commitment with.
 */
const premRnd = mulberry32(20120917);

export const SUPPLIERS: Supplier[] = SUPPLIER_SEED.map(([name, portId, category], i) => {
  const base = 97 - i * 2.4 - between(0, 4);
  return {
    id: `sup-${i + 1}`,
    name,
    portId,
    category,
    otif: Array.from({ length: 8 }, () =>
      round(Math.max(58, Math.min(99.4, base + between(-5.5, 5.5))), 1),
    ),
    defectRate: round(between(0.2, 4.6), 2),
    leadTimeVar: Array.from({ length: 8 }, () => round(between(-1.5, 6.5 + i * 0.35), 1)),
    spotPremium: round(0.08 + premRnd() * 0.08, 4),
  };
});

export const supplierById = (id: string) => SUPPLIERS.find((s) => s.id === id)!;
export const portById = (id: string) => PORTS.find((p) => p.id === id)!;
export const warehouseById = (id: string) => WAREHOUSES.find((w) => w.id === id)!;

export const supplierScore = (s: Supplier) => {
  const otif = s.otif.reduce((a, b) => a + b, 0) / s.otif.length;
  const ltv = s.leadTimeVar.reduce((a, b) => a + Math.abs(b), 0) / s.leadTimeVar.length;
  return round(otif - ltv * 2.6 - s.defectRate * 2.2, 1);
};

/* ---------- shipments ---------- */

const CONTENTS = [
  "M8 flange bolts (12 pallets)",
  "Polymer housings, rev C",
  "Sealed bearings 6204-2RS",
  "Woven filter media, 900m",
  "24V harness assemblies",
  "Corrugate, B-flute",
  "Powder-coated enclosures",
  "Motor control boards",
  "Two-part epoxy, 55gal",
  "Hydraulic quick-connects",
  "PVC extrusion, 6m lengths",
  "Progressive stamping dies",
  "Stainless standoffs",
  "Gasket sheet stock",
  "Linear rails, 1200mm",
];

/** Deterministic air-freight lanes (5 overseas expedited + 2 domestic hot loads). */
const AIR_INDEXES = new Set([3, 9, 16, 22, 28, 33, 37]);

/**
 * Existing MFN duty already being paid, keyed by supplier category. Real HTS rates
 * vary line by line; here one rate stands in for a whole commodity family, drawn from
 * a realistic 0–6.5% ad valorem spread. This uses its own seeded stream so adding the
 * cost axis did not shift any of the pre-existing figures generated from `rnd`.
 */
const dutyRnd = mulberry32(19870401);
const CATEGORY_DUTY: Record<string, number> = Object.fromEntries(
  [...new Set(SUPPLIERS.map((s) => s.category))].map((c) => [c, round(dutyRnd() * 0.065, 4)]),
);

/**
 * MFN duty for a load sourced from a given supplier. Used by the engine when a load is
 * re-let: the duty rate travels with the origin it lands in, not the one it left.
 */
export const mfnRateFor = (supplierId: string) => {
  const sup = supplierById(supplierId);
  return portById(sup.portId).region === "overseas" ? CATEGORY_DUTY[sup.category] : 0;
};

/**
 * Air-charter premium stream. Its own seed so pricing the expedite play did not shift
 * any pre-existing figure generated from `rnd`, `dutyRnd` or `premRnd`. The 6–14% band
 * is DEMO-TUNED: plausible for short-notice charter over contracted ocean freight on a
 * mid-market book, not drawn from published rate data.
 */
const airRnd = mulberry32(20231105);

const IN_TRANSIT: Shipment[] = Array.from({ length: 41 }, (_, i) => {
  const sup = SUPPLIERS[i % SUPPLIERS.length];
  const port = portById(sup.portId);
  const wh = pick(WAREHOUSES);
  const overseas = port.region === "overseas";
  return {
    id: `MF-${(48210 + i * 37).toString()}`,
    supplierId: sup.id,
    portId: port.id,
    warehouseId: wh.id,
    contents: pick(CONTENTS),
    units: Math.round(between(240, 9800)),
    value: Math.round(between(18, 420)) * 1000,
    etaDays: round(overseas ? between(4, 27) : between(1, 9), 0),
    departsInDays: 0,
    stage: "transit" as const,
    baseRisk: round(
      Math.min(0.97, Math.max(0.03, (100 - supplierScore(sup)) / 90 + between(-0.16, 0.24))),
      3,
    ),
    progress: round(between(0.04, 0.96), 3),
    /* domestic-origin freight clears no customs line, so it carries no duty */
    baseDutyRate: overseas ? CATEGORY_DUTY[sup.category] : 0,
    airPremiumRate: round(0.06 + airRnd() * 0.08, 4),
    mode: (AIR_INDEXES.has(i)
      ? "air"
      : overseas
        ? "ocean"
        : port.id === "den"
          ? "rail"
          : "road") as Shipment["mode"],
  };
})
  .map((s, i) => ({ ...s, contents: CONTENTS[i % CONTENTS.length] }))
  /* air freight: fast, small, high-value, slightly lower base risk */
  .map((s) =>
    s.mode !== "air"
      ? s
      : {
          ...s,
          etaDays: Math.max(1, Math.round(s.etaDays * 0.16) + 1),
          units: Math.round(s.units * 0.14) + 40,
          value: Math.round(s.value * 1.45),
          baseRisk: round(Math.max(0.03, s.baseRisk - 0.12), 3),
        },
  )
  /**
   * Coverage guard: suppliers are assigned round-robin so all 12 always appear, but
   * warehouses are drawn with the seeded pick(), which could in principle leave a DC
   * with no inbound and render an empty section. This deterministic pass reassigns the
   * first spare shipment to any uncovered warehouse. With the current seed every DC is
   * already covered (OAK 7 · RNO 12 · SLC 13 · PHX 9), so it is a no-op today and only
   * engages if you change the seed, the shipment count, or the warehouse list.
   */
  .map((s, i, all) => {
    const missing = WAREHOUSES.filter((w) => !all.some((x) => x.warehouseId === w.id));
    if (missing.length === 0) return s;
    const slot = missing.findIndex((_, k) => k === i);
    return slot === -1 ? s : { ...s, warehouseId: missing[slot].id };
  });

/* ---------- forward order book ---------- */

/**
 * FORWARD ORDER BOOK. Freight already on the water is the smallest and least actionable
 * slice of an importer's tariff exposure — by the time a box is at sea the origin, the
 * entry date and the duty are all locked. The exposure anyone can still do something
 * about sits in POs placed or planned for the next couple of quarters, so the book here
 * is deliberately larger than the in-transit book and runs out to roughly 120 days of
 * arrivals: far enough that a 45-day measure binds a meaningful share rather than
 * nothing at all.
 *
 * Its own seeded stream, so adding it shifted none of the in-transit figures above.
 */
const fwdRnd = mulberry32(20260731);
const fBetween = (a: number, b: number) => a + fwdRnd() * (b - a);

const FORWARD_BOOK: Shipment[] = Array.from({ length: 72 }, (_, i) => {
  const sup = SUPPLIERS[(i * 5 + 3) % SUPPLIERS.length];
  const port = portById(sup.portId);
  const overseas = port.region === "overseas";
  const wh = WAREHOUSES[Math.floor(fwdRnd() * WAREHOUSES.length)];
  /* first third of the book is booked (space held, production done); the rest planned */
  const stage: Stage = i % 3 === 0 ? "booked" : "planned";
  /* one in six overseas loads moves by air, so the air-scoped measure has a book to bite */
  const mode: Shipment["mode"] = overseas
    ? i % 6 === 2
      ? "air"
      : "ocean"
    : port.id === "den"
      ? "rail"
      : "road";
  const transit = overseas ? (mode === "air" ? fBetween(3, 6) : fBetween(19, 31)) : fBetween(2, 9);
  const departsInDays = stage === "booked" ? fBetween(3, 20) : fBetween(24, 92);
  const etaDays = Math.min(124, Math.round(departsInDays + transit));
  const value = Math.round(fBetween(22, 460)) * 1000;
  return {
    id: `MF-${(60400 + i * 41).toString()}`,
    supplierId: sup.id,
    portId: port.id,
    warehouseId: wh.id,
    contents: CONTENTS[(i * 7) % CONTENTS.length],
    units: Math.round(fBetween(300, 11000)),
    value: mode === "air" ? Math.round(value * 1.4) : value,
    etaDays,
    departsInDays: Math.round(departsInDays),
    stage,
    baseRisk: round(
      Math.min(0.94, Math.max(0.03, (100 - supplierScore(sup)) / 95 + fBetween(-0.18, 0.2))),
      3,
    ),
    /* nothing pre-departure is anywhere along its route yet */
    progress: 0,
    baseDutyRate: overseas ? CATEGORY_DUTY[sup.category] : 0,
    airPremiumRate: round(0.06 + fwdRnd() * 0.08, 4),
    mode,
  };
});

export const SHIPMENTS: Shipment[] = [...IN_TRANSIT, ...FORWARD_BOOK];

export const STAGE_LABEL: Record<Stage, string> = {
  transit: "in transit",
  booked: "booked",
  planned: "planned",
};

/* ---------- warehouse floorplan (per-warehouse zone layout) ---------- */

const SKU_NAMES = [
  "Flange bolt M8x30",
  "Housing shell, rev C",
  "Bearing 6204-2RS",
  "Filter media roll",
  "Harness 24V-4P",
  "Corrugate B-flute 40x30",
  "Enclosure 400x300",
  "Control board MC-7",
  "Epoxy resin A/B",
  "Quick-connect 1/2in",
  "PVC profile 6m",
  "Stamping die D-19",
];

/**
 * DEMO SHORTCUT: this single ZONE_TEMPLATE is cloned across all four DCs below, so
 * every warehouse shares one bay layout and only its stock figures differ. A real
 * deployment would define a per-warehouse layout (its own zone list, footprints, and
 * kinds) instead of reusing one template.
 */
const ZONE_TEMPLATE: Omit<Zone, "skuCount" | "fill" | "daysOfCover" | "topSkus">[] = [
  { id: "z-a1", label: "A1", kind: "rack", x: 40, y: 56, w: 118, h: 62 },
  { id: "z-a2", label: "A2", kind: "rack", x: 40, y: 126, w: 118, h: 62 },
  { id: "z-a3", label: "A3", kind: "rack", x: 40, y: 196, w: 118, h: 62 },
  { id: "z-b1", label: "B1", kind: "rack", x: 168, y: 56, w: 118, h: 96 },
  { id: "z-b2", label: "B2", kind: "bulk", x: 168, y: 160, w: 118, h: 98 },
  { id: "z-c1", label: "C1", kind: "bulk", x: 296, y: 56, w: 150, h: 74 },
  { id: "z-c2", label: "C2", kind: "cold", x: 296, y: 138, w: 150, h: 56 },
  { id: "z-c3", label: "C3", kind: "rack", x: 296, y: 202, w: 150, h: 56 },
  { id: "z-d1", label: "D1", kind: "stage", x: 456, y: 56, w: 96, h: 118 },
  { id: "z-d2", label: "DOCK", kind: "dock", x: 456, y: 182, w: 96, h: 76 },
];

export const FLOORPLANS: Record<string, Zone[]> = Object.fromEntries(
  WAREHOUSES.map((w) => [
    w.id,
    ZONE_TEMPLATE.map((z, i) => {
      const fill = round(between(0.18, 1.06), 3);
      return {
        ...z,
        skuCount: Math.round(between(8, 34)),
        fill,
        daysOfCover: round(between(2, 46), 1),
        topSkus: Array.from({ length: 3 }, (_, k) => {
          const onHand = Math.round(between(40, 4200));
          return {
            sku: `MER-${(1200 + i * 17 + k * 3).toString()}`,
            name: SKU_NAMES[(i + k) % SKU_NAMES.length],
            onHand,
            reorder: Math.round(onHand * between(0.35, 1.5)),
          };
        }),
      };
    }),
  ]),
);

/* ---------- scenarios ---------- */

export interface Scenario {
  id: string;
  label: string;
  /** Plant this switch tracks (factory-tracking concept). */
  plantId?: string;
  detail: string;
  kind:
    | "port-delay"
    | "supplier-offline"
    | "demand-spike"
    | "lane-closure"
    | "expedite-air"
    | "tariff"
    | "dual-source";
  targetId: string;
  magnitude: number;
  /** Tariffs: days until the rate lands. Drives the pull-forward surge in the engine. */
  effectiveInDays?: number;
  /** Tariffs: restrict the measure to one transport family (e.g. de minimis → air). */
  scope?: "all" | "air" | "ocean";
  /** Tariffs: ISO-3166 alpha-2 origin the rate applies to. Omitted = all overseas origins. */
  originCountry?: string;
}

/**
 * DEMO SCENARIOS. Labels and details are written for the fictional Meridian network.
 * When you swap in your own network, rewrite these to reference your own ports,
 * suppliers, and lanes; the engine applies them generically by kind and targetId.
 */
/**
 * FACTORY TRACKING CONCEPT — one switch per plant data feed. `plantId` binds a
 * switch to a PLANTS entry; toggling highlights that plant on the map and
 * expands its demo feed detail. The legacy kinds/magnitudes only remain so the
 * KPI engine stays valid — real status logic lands later.
 */
export const SCENARIOS: Scenario[] = [
  {
    id: "sc-oak",
    label: "FTM",
    detail: "Data Feed",
    kind: "port-delay",
    targetId: "oakp",
    magnitude: 5,
    plantId: "ryg-a",
  },
  {
    id: "sc-tsn",
    label: "AAT",
    detail: "Data Feed",
    kind: "supplier-offline",
    targetId: "sup-1",
    magnitude: 1,
    plantId: "ryg-b",
  },
  {
    id: "sc-phx",
    label: "FVL",
    detail: "Data Feed",
    kind: "demand-spike",
    targetId: "phx",
    magnitude: 0.3,
    plantId: "had",
  },
  {
    id: "sc-i80",
    label: "SAP",
    detail: "Data Feed",
    kind: "lane-closure",
    targetId: "rno",
    magnitude: 3,
    plantId: "svt",
  },
];

/** Scenario families, used to group the library and the simulator panel. */
export type ScenarioFamily = "Logistics" | "Trade policy" | "Recovery plays";

export function scenarioFamily(s: Scenario): ScenarioFamily {
  if (s.kind === "tariff") return "Trade policy";
  if (s.kind === "expedite-air" || s.kind === "dual-source") return "Recovery plays";
  return "Logistics";
}

export const SCENARIO_FAMILIES: ScenarioFamily[] = ["Logistics", "Trade policy", "Recovery plays"];

/* ---------- plants (factory tracking concept) ---------- */

/**
 * PLANTS — the four real factory locations shown on the map. One dot per plant,
 * coloured by current data/quality status. Values are demo-authored; wire `level`,
 * `lastSyncMin` and the tooltip rows to real feeds later.
 */
export interface Plant {
  id: string;
  code: string;
  name: string;
  country: string;
  x: number;
  y: number;
  level: Risk;
  /** Production / reporting line shown in the hover card. */
  line: string;
  /** Minutes since the plant's data feed last synced. */
  lastSyncMin: number;
  /** Short reason text for the current status, shown as the tooltip driver. */
  driver: string;
  /** Optional demo display offset (viewBox px). The Rayong pair sits ~9 km
   *  apart and overlaps at overview zoom, so each dot is nudged apart. */
  offset?: [number, number];
}

export const PLANTS: Plant[] = [
  {
    id: "ryg-a",
    code: "FTM",
    name: "Rayong Plant A",
    country: "Thailand",
    ...project(101.25, 12.68),
    offset: [-14, -7],
    level: "nominal",
    line: "Wave scan · film thickness",
    lastSyncMin: 4,
    driver: "All feeds reporting within the last 5 minutes.",
  },
  {
    id: "ryg-b",
    code: "AAT",
    name: "Rayong Plant B",
    country: "Thailand",
    ...project(101.33, 12.62),
    offset: [14, 7],
    level: "caution",
    line: "Wave scan · film thickness",
    lastSyncMin: 38,
    driver: "Film-thickness feed delayed — last packet 38 min ago.",
  },
  {
    id: "had",
    code: "FVL",
    name: "Hai Duong Plant",
    country: "Vietnam",
    ...project(106.31, 20.94),
    level: "critical",
    line: "Wave scan · film thickness",
    lastSyncMin: 132,
    driver: "Feed disconnected — no data received for over 2 hours.",
  },
  {
    id: "svt",
    code: "SAP",
    name: "Silverton Plant",
    country: "South Africa",
    ...project(28.3, -25.73),
    level: "nominal",
    line: "Wave scan · film thickness",
    lastSyncMin: 2,
    driver: "All feeds reporting within the last 5 minutes.",
  },
];

/* ---------- per-plant feed detail (demo) ---------- */

/**
 * PLANT_FEED_DETAIL — demo rows shown under each open plant switch.
 * `summary` mimics the old order-book trio (3 rollup rows), `feeds` mimics the
 * old projected-stockouts list (status dot + metric + value). All values are
 * authored placeholders until the real feeds land.
 */
export interface PlantFeedDetail {
  summary: { label: string; count: number; value: string }[];
  feeds: { code: string; name: string; station: string; value: string; level: Risk }[];
}

export const PLANT_FEED_DETAIL: Record<string, PlantFeedDetail> = {
  "ryg-a": {
    summary: [
      { label: "Wave scan records", count: 1284, value: "on time" },
      { label: "Film thickness", count: 856, value: "on time" },
      { label: "Pending upload", count: 0, value: "—" },
    ],
    feeds: [
      {
        code: "WS-01",
        name: "Wave scan · booth 1",
        station: "Line A",
        value: "4m",
        level: "nominal",
      },
      {
        code: "WS-02",
        name: "Wave scan · booth 2",
        station: "Line A",
        value: "6m",
        level: "nominal",
      },
      {
        code: "FT-01",
        name: "Film thickness · primer",
        station: "Line B",
        value: "3m",
        level: "nominal",
      },
      {
        code: "FT-02",
        name: "Film thickness · topcoat",
        station: "Line B",
        value: "5m",
        level: "nominal",
      },
    ],
  },
  "ryg-b": {
    summary: [
      { label: "Wave scan records", count: 1102, value: "on time" },
      { label: "Film thickness", count: 640, value: "38m late" },
      { label: "Pending upload", count: 12, value: "queued" },
    ],
    feeds: [
      {
        code: "WS-01",
        name: "Wave scan · booth 1",
        station: "Line A",
        value: "7m",
        level: "nominal",
      },
      {
        code: "FT-01",
        name: "Film thickness · primer",
        station: "Line B",
        value: "38m",
        level: "caution",
      },
      {
        code: "FT-02",
        name: "Film thickness · basecoat",
        station: "Line B",
        value: "41m",
        level: "caution",
      },
      {
        code: "FT-03",
        name: "Film thickness · clearcoat",
        station: "Line B",
        value: "35m",
        level: "caution",
      },
    ],
  },
  had: {
    summary: [
      { label: "Wave scan records", count: 0, value: "no feed" },
      { label: "Film thickness", count: 0, value: "no feed" },
      { label: "Pending upload", count: 214, value: "backlog" },
    ],
    feeds: [
      {
        code: "WS-01",
        name: "Wave scan · booth 1",
        station: "Line A",
        value: "2h 12m",
        level: "critical",
      },
      {
        code: "WS-02",
        name: "Wave scan · booth 2",
        station: "Line A",
        value: "2h 12m",
        level: "critical",
      },
      {
        code: "FT-01",
        name: "Film thickness · primer",
        station: "Line B",
        value: "2h 9m",
        level: "critical",
      },
      {
        code: "GW-01",
        name: "Plant gateway",
        station: "Network",
        value: "down",
        level: "critical",
      },
    ],
  },
  svt: {
    summary: [
      { label: "Wave scan records", count: 968, value: "on time" },
      { label: "Film thickness", count: 702, value: "on time" },
      { label: "Pending upload", count: 0, value: "—" },
    ],
    feeds: [
      {
        code: "WS-01",
        name: "Wave scan · booth 1",
        station: "Line A",
        value: "2m",
        level: "nominal",
      },
      {
        code: "FT-01",
        name: "Film thickness · primer",
        station: "Line B",
        value: "2m",
        level: "nominal",
      },
      {
        code: "FT-02",
        name: "Film thickness · topcoat",
        station: "Line B",
        value: "1m",
        level: "nominal",
      },
    ],
  },
};

/* ---------- per-plant KPI tiles (demo) ---------- */

/**
 * PLANT_KPI — the two faces of each top tile.
 * `monthlyPct` is month-to-date product quality (front face, coloured by the
 * plant's map `level`). `dataUpdatePct` is how much of the month's expected
 * data entry landed on time (back face, coloured by lateness thresholds).
 * All demo values; wire to real feeds later.
 */
export interface PlantKpi {
  monthlyPct: number;
  monthlyNote: string;
  dataUpdatePct: number;
  lateCount: number;
  missingCount: number;
}

export const PLANT_KPI: Record<string, PlantKpi> = {
  "ryg-a": {
    monthlyPct: 96.4,
    monthlyNote: "Wave Scan · Film Thickness",
    dataUpdatePct: 98.2,
    lateCount: 1,
    missingCount: 0,
  },
  "ryg-b": {
    monthlyPct: 91.8,
    monthlyNote: "Wave Scan · Film Thickness",
    dataUpdatePct: 86.5,
    lateCount: 7,
    missingCount: 2,
  },
  had: {
    monthlyPct: 78.3,
    monthlyNote: "Wave Scan · Film Thickness",
    dataUpdatePct: 54.1,
    lateCount: 18,
    missingCount: 11,
  },
  svt: {
    monthlyPct: 97.1,
    monthlyNote: "Wave Scan · Film Thickness",
    dataUpdatePct: 96.6,
    lateCount: 2,
    missingCount: 0,
  },
};

/** Lateness thresholds for the data-update face — demo, make configurable later. */
export function dataUpdateLevel(pct: number): Risk {
  if (pct >= 95) return "nominal";
  if (pct >= 80) return "caution";
  return "critical";
}
