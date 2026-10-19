import type { components } from "@/api/types";

export type Car = components["schemas"]["ComparisonCandidate"];
export type Points = components["schemas"]["ComparisonPointsOut"];
export type Domain = Car["domain"];
export type Card =
  { kind: "month"; month: string; model: string; domain: Domain } | { kind: "car"; car: Car };
export type SlotKind = Card["kind"];

export const MAX_MONTHS = 4; // matches the previous compare lane
export const MAX_CARS = 8; // comparison/points accepts 1..8 vehicle IDs
export const DOMAIN_LABEL: Record<Domain, string> = {
  WAVESCAN: "WaveScan",
  FILMTHICKNESS: "Film Thickness",
};

/** One domain per bench. Model-qualified month keys keep separate model distributions. */
export interface Bench {
  domain: Domain;
  model: string | null;
  months: string[];
  cars: Car[];
  /** Month drawn as the reference band behind the others; null for none. */
  baseline: string | null;
}
export const emptyBench = (domain: Domain = "WAVESCAN"): Bench => ({
  domain,
  model: null,
  months: [],
  cars: [],
  baseline: null,
});
export const isEmpty = (bench: Bench) => !bench.months.length && !bench.cars.length;

const cardModel = (card: Card) => (card.kind === "month" ? card.model : card.car.model);
const cardDomain = (card: Card) => (card.kind === "month" ? card.domain : card.car.domain);
export const monthValue = (key: string) => key.slice(-7);
export const monthModel = (bench: Bench, key: string) =>
  key.includes("::") ? key.slice(0, -9) : bench.model!;
export const monthKey = (bench: Bench, month: string, model: string) =>
  bench.model && bench.model !== model ? `${model}::${month}` : month;

/** Keep selected calendar months when the deck model changes, without retaining stale model data. */
export function retargetMonths(
  bench: Bench,
  model: string,
  availableMonths: readonly string[],
): Bench {
  const available = new Set(availableMonths);
  const months = [...new Set(bench.months.map(monthValue))].filter((month) => available.has(month));
  const baselineMonth = bench.baseline ? monthValue(bench.baseline) : null;
  const next = {
    ...bench,
    model,
    months,
    baseline: baselineMonth && months.includes(baselineMonth) ? baselineMonth : null,
  };
  return isEmpty(next) ? emptyBench(bench.domain) : next;
}

/** Why the card cannot go on the bench, or null when it can. Shown while dragging. */
export function blockReason(bench: Bench, card: Card): string | null {
  const model = cardModel(card);
  if (!model) return "This car has no model recorded.";
  if (!isEmpty(bench) && cardDomain(card) !== bench.domain)
    return `The bench holds ${DOMAIN_LABEL[bench.domain]}. Clear it to compare ${DOMAIN_LABEL[cardDomain(card)]}.`;
  if (card.kind === "month") {
    if (
      bench.months.some(
        (key) => monthValue(key) === card.month && monthModel(bench, key) === card.model,
      )
    )
      return "This month is already on the bench.";
    if (bench.months.length >= MAX_MONTHS) return `The bench holds ${MAX_MONTHS} months at most.`;
  } else {
    if (bench.cars.some((c) => c.vehicle_id === card.car.vehicle_id))
      return "This car is already on the bench.";
    if (bench.cars.length >= MAX_CARS) return `The bench holds ${MAX_CARS} cars at most.`;
  }
  return null;
}

export function addCard(bench: Bench, card: Card): Bench {
  if (blockReason(bench, card)) return bench;
  return card.kind === "month"
    ? {
        ...bench,
        domain: card.domain,
        model: bench.model ?? card.model,
        months: [...bench.months, monthKey(bench, card.month, card.model)],
      }
    : {
        ...bench,
        domain: card.car.domain,
        model: bench.model ?? card.car.model,
        cars: [...bench.cars, card.car],
      };
}

const slotKeys = (bench: Bench, kind: SlotKind) =>
  kind === "month" ? bench.months : bench.cars.map((c) => c.vehicle_id);

export function removeSlot(bench: Bench, kind: SlotKind, key: string): Bench {
  const next =
    kind === "month"
      ? {
          ...bench,
          months: bench.months.filter((m) => m !== key),
          baseline: bench.baseline === key ? null : bench.baseline,
        }
      : { ...bench, cars: bench.cars.filter((c) => c.vehicle_id !== key) };
  return isEmpty(next) ? emptyBench(bench.domain) : next;
}

/** Put `key` at the position `target` holds now (drag onto a slot, or Alt+Arrow onto a neighbour). */
export function moveSlot(bench: Bench, kind: SlotKind, key: string, target: string): Bench {
  const keys = slotKeys(bench, kind);
  const from = keys.indexOf(key);
  const to = keys.indexOf(target);
  if (from < 0 || to < 0 || from === to) return bench;
  const order = [...keys];
  order.splice(from, 1);
  order.splice(to, 0, key);
  return kind === "month"
    ? { ...bench, months: order }
    : { ...bench, cars: order.map((id) => bench.cars.find((c) => c.vehicle_id === id)!) };
}

/** Fill the bench with consecutive months (oldest left), keeping cars only if domain and model match. */
export function presetMonths(
  bench: Bench,
  domain: Domain,
  model: string,
  newestFirst: string[],
  count: number,
): Bench {
  const months = newestFirst.slice(0, Math.min(count, MAX_MONTHS)).reverse();
  return {
    domain,
    model,
    months,
    cars: bench.domain === domain ? bench.cars : [],
    baseline: months.length > 1 ? months[0] : null,
  };
}

export const neighbour = (bench: Bench, kind: SlotKind, key: string, step: -1 | 1) =>
  slotKeys(bench, kind)[slotKeys(bench, kind).indexOf(key) + step];

export type Metric = Points["metric"];
export type Orient = "Horizontal" | "Vertical";
const WAVE_SPECTRUM: Metric[] = ["du", "wa", "wb", "wc", "wd", "we"];
// Default curve and full metric order per domain: WaveScan structure spectrum fine → coarse,
// then summary values; Film layers in build order, substrate outwards.
export const SPECTRUM: Record<Domain, Metric[]> = {
  WAVESCAN: WAVE_SPECTRUM,
  FILMTHICKNESS: ["ecoat", "primer", "base", "clear"],
};
export const METRIC_ORDER: Record<Domain, Metric[]> = {
  WAVESCAN: [...WAVE_SPECTRUM, "sw", "lw", "doi", "cf", "b"],
  FILMTHICKNESS: SPECTRUM.FILMTHICKNESS,
};
const LAYER_LABEL: Record<string, string> = {
  ecoat: "E-coat",
  primer: "Primer",
  base: "Base",
  clear: "Clear",
};
export const metricLabel = (m: string) =>
  LAYER_LABEL[m] ?? (/^w[a-e]$/.test(m) ? `W${m[1]}` : m === "du" ? "du" : m.toUpperCase());

export const orientOf = (o: string | null | undefined): Orient | null => {
  const first = o?.trim().charAt(0).toUpperCase();
  return first === "H" ? "Horizontal" : first === "V" ? "Vertical" : null;
};

// Point shape follows the body panel named in the checkzone code (RRHOOD, LFFENDER, 090LBXFLOOR...).
export const PANELS = [
  "Hood",
  "Roof",
  "Fender",
  "Door",
  "Pillar",
  "Box",
  "Gate",
  "Bumper",
  "Other",
] as const;
export type Panel = (typeof PANELS)[number];
const PANEL_CODES: Array<[RegExp, Panel]> = [
  [/HOOD/, "Hood"],
  [/ROOF/, "Roof"],
  [/FEND/, "Fender"],
  [/DOO|DOR|DR$/, "Door"],
  [/PILL/, "Pillar"],
  [/BOX|BX/, "Box"],
  [/GATE/, "Gate"],
  [/BUMP/, "Bumper"],
];
export const panelOf = (code: string): Panel =>
  PANEL_CODES.find(([re]) => re.test(code.toUpperCase()))?.[1] ?? "Other";

/** One measured row (car x location x repeat) with its raw value per requested metric. */
export type Trace = {
  key: string;
  vehicle_id: string;
  location: string;
  locationLabel: string;
  panel: Panel;
  point_no: number;
  orient: Orient | null;
  values: Partial<Record<Metric, number>>;
};

/**
 * Join raw readings from one points request per metric on the measured row: WaveScan by
 * measurement_id; Film (one value per car and location) by car + location.
 * Every plotted number stays an API reading: nothing is averaged here.
 */
export function traces(perMetric: Array<{ metric: Metric; points: Points }>): Trace[] {
  const out = new Map<string, Trace>();
  for (const { metric, points } of perMetric)
    for (const location of points.locations)
      for (const cell of location.cells)
        for (const reading of cell.readings) {
          const value = Number(reading.value);
          if (!Number.isFinite(value)) continue;
          const where = `${location.point_no}-${location.code}`;
          const key =
            reading.measurement_id == null
              ? `v${cell.vehicle_id}|${where}`
              : `m${reading.measurement_id}`;
          const trace = out.get(key) ?? {
            key,
            vehicle_id: cell.vehicle_id,
            location: where,
            locationLabel: `${String(location.point_no).padStart(2, "0")} ${location.code}`,
            panel: panelOf(location.code),
            point_no: location.point_no,
            orient: orientOf(location.orientation),
            values: {},
          };
          trace.values[metric] = value;
          out.set(key, trace);
        }
  return [...out.values()].sort((a, b) => a.point_no - b.point_no || a.key.localeCompare(b.key));
}

/** x = metric, one column per trace: the spectrum / layer-profile curve rows. */
export const spectrumRows = (list: Trace[], metrics: Metric[]) =>
  metrics.map((metric) => {
    const row: Record<string, string | number | null> = { metric: metricLabel(metric) };
    for (const t of list) row[t.key] = t.values[metric] ?? null;
    return row;
  });

const DASHES = [undefined, "6 4", "2 3", "10 3 2 3", "1 4"];
/**
 * Colour-by-location style: locations in point order take the 8 colour slots in turn, then
 * the next line pattern (solid, dashed, dotted...), so 40 locations get 40 distinct lines
 * without generating more than eight hues. The panel's point shape is a third cue.
 */
export function locationStyles(list: Trace[]) {
  const locations = [...new Map(list.map((t) => [t.location, t.point_no] as const))].sort(
    (a, b) => a[1] - b[1],
  );
  return new Map(
    locations.map(([location], i) => [
      location,
      { slot: (i % 8) + 1, dash: DASHES[Math.floor(i / 8) % DASHES.length] },
    ]),
  );
}

/**
 * x = location (only locations with a reading, so no blanks), one column per car repeat:
 * `${vehicle_id}#${n}` is that car's n-th row at the location.
 */
export function profileRows(list: Trace[], metric: Metric, cars: string[]) {
  const measured = list.filter((t) => t.values[metric] != null);
  const locations = [...new Map(measured.map((t) => [t.location, t.locationLabel]))];
  const keys = new Set<string>();
  const rows = locations.map(([location, label]) => {
    const row: Record<string, string | number | null> = { location: label };
    for (const car of cars)
      measured
        .filter((t) => t.location === location && t.vehicle_id === car)
        .forEach((t, n) => {
          row[`${car}#${n}`] = t.values[metric]!;
          keys.add(`${car}#${n}`);
        });
    return row;
  });
  return { rows, keys: [...keys] };
}

export function byWeek(cars: Car[]) {
  // RO18 (B4): week 0 ("Day not recorded") sorts after the real weeks.
  const weeks = [...new Set(cars.map((c) => c.week))].sort(
    (a, b) => Number(a === 0) - Number(b === 0) || a - b,
  );
  return weeks.map((week) => ({ week, cars: cars.filter((c) => c.week === week) }));
}

// Film cars usually carry a job number instead of a serial.
export const carLabel = (car: Car) =>
  car.serial_no?.trim() || car.job_nos?.[0]?.trim() || "No serial or job";
export const carMonth = (car: Car) => car.measured_date.slice(0, 7);

/** What a shared link carries: enough to rebuild the bench (cars are re-read by ID). */
export type SharedBench = {
  domain: Domain;
  model: string;
  months: string[];
  cars: string[];
  baseline: string | null;
  carModels?: Record<string, string>;
};

export function parseShared(value: unknown): SharedBench | undefined {
  if (!value || typeof value !== "object") return undefined;
  const v = value as Record<string, unknown>;
  const list = (x: unknown, re: RegExp, max: number) =>
    Array.isArray(x)
      ? [...new Set(x.filter((i): i is string => typeof i === "string" && re.test(i)))].slice(
          0,
          max,
        )
      : [];
  const domain: Domain = v.domain === "FILMTHICKNESS" ? "FILMTHICKNESS" : "WAVESCAN";
  const model = typeof v.model === "string" && v.model.length <= 64 ? v.model.trim() : "";
  const months = Array.isArray(v.months)
    ? [
        ...new Set(
          v.months.filter(
            (key): key is string =>
              typeof key === "string" && /^(?:.{1,64}::)?\d{4}-(0[1-9]|1[0-2])$/.test(key),
          ),
        ),
      ].slice(0, MAX_MONTHS)
    : [];
  const cars = list(v.cars, /^[0-9a-f]{64}$/, MAX_CARS);
  if (!model || (!months.length && !cars.length)) return undefined;
  const baseline =
    typeof v.baseline === "string" && months.includes(v.baseline) ? v.baseline : null;
  const carModels =
    v.carModels && typeof v.carModels === "object"
      ? Object.fromEntries(
          cars.flatMap((id) => {
            const value = (v.carModels as Record<string, unknown>)[id];
            return typeof value === "string" && value.trim().length > 0 && value.length <= 64
              ? [[id, value]]
              : [];
          }),
        )
      : undefined;
  return {
    domain,
    model,
    months,
    cars,
    baseline,
    ...(carModels && Object.keys(carModels).length ? { carModels } : {}),
  };
}

export const toShared = (bench: Bench): SharedBench | undefined =>
  bench.model
    ? {
        domain: bench.domain,
        model: bench.model,
        months: bench.months,
        cars: bench.cars.map((c) => c.vehicle_id),
        baseline: bench.baseline,
        ...(bench.cars.some((car) => car.model !== bench.model)
          ? {
              carModels: Object.fromEntries(
                bench.cars.map((car) => [car.vehicle_id, car.model ?? bench.model!]),
              ),
            }
          : {}),
      }
    : undefined;
