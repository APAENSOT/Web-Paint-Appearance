import {
  FLOORPLANS,
  PORTS,
  SCENARIOS,
  SHIPMENTS,
  SUPPLIERS,
  WAREHOUSES,
  mfnRateFor,
  portById,
  supplierById,
  supplierScore,
  type Risk,
  type Scenario,
  type Shipment,
  type Zone,
} from "./data";

/* ---------- geometry ---------- */

export function routePath(
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  mode: Shipment["mode"],
) {
  const dx = toX - fromX;
  const dy = toY - fromY;
  if (mode === "air") {
    /* high, tight great-circle-feeling arc that clears the ocean lanes */
    const lift = 180 + Math.min(120, Math.abs(dx) * 0.12);
    return `M ${fromX} ${fromY} C ${fromX + dx * 0.2} ${fromY - lift}, ${fromX + dx * 0.8} ${toY - lift}, ${toX} ${toY}`;
  }
  if (mode === "ocean") {
    return `M ${fromX} ${fromY} C ${fromX + dx * 0.28} ${fromY - 118}, ${fromX + dx * 0.72} ${toY - 150}, ${toX} ${toY}`;
  }
  const mx = fromX + dx * 0.5 - dy * 0.16;
  const my = fromY + dy * 0.5 + dx * 0.16;
  return `M ${fromX} ${fromY} Q ${mx} ${my}, ${toX} ${toY}`;
}

/* ---------- entry costs: duty is not the whole customs bill ---------- */

/**
 * MERCHANDISE PROCESSING FEE. Ad valorem on entered value, with a per-entry floor and
 * ceiling. CBP indexes all three figures annually for inflation (19 CFR 24.23) — these
 * are the FY2025 numbers and MUST be re-checked against the current Federal Register
 * notice before this model is used for anything but a demo.
 */
const MPF_RATE = 0.003464;
const MPF_MIN = 32.71;
const MPF_MAX = 634.62;

/**
 * HARBOR MAINTENANCE FEE. 0.125% of entered value on cargo arriving through a US
 * seaport. No floor, no ceiling. Air arrivals and domestic freight do not pay it.
 */
const HMF_RATE = 0.00125;

/**
 * ONE SHIPMENT = ONE ENTRY here, which is the pessimistic reading: a real importer
 * consolidates multiple shipments onto a single entry wherever the rules allow,
 * precisely because the MPF ceiling means a bigger entry costs no more in MPF than a
 * $183k one. Model your own consolidation policy before trusting the fee totals.
 */
function entryFees(value: number, mode: Shipment["mode"], country: string) {
  if (country === "US") return { mpf: 0, hmf: 0 }; // crosses no customs line
  const mpf = Math.min(MPF_MAX, Math.max(MPF_MIN, value * MPF_RATE));
  const hmf = mode === "ocean" ? value * HMF_RATE : 0;
  return { mpf: Math.round(mpf), hmf: Math.round(hmf) };
}

/* ---------- resolved shipment ---------- */

export interface ResolvedShipment extends Shipment {
  supplierName: string;
  portName: string;
  portShort: string;
  /** ISO-3166 alpha-2 of the origin port — the tariff join key. */
  country: string;
  ocean: boolean;
  expedited: boolean;
  dualSourced: boolean;
  path: string;
  addedDays: number;
  eta: number;
  /**
   * Day the load physically arrives at the port of entry — transit plus congestion,
   * BEFORE customs clearance. This is the date duty attaches to, and the date the
   * effective-date boundary is tested against.
   */
  entryDay: number;
  /** True when congestion alone pushed this load past a tariff's effective date. */
  missedWindow: boolean;
  risk: number;
  level: Risk;
  frozen: boolean;
  impacted: boolean;
  /** Incremental ad valorem rate added by active tariff scenarios (0 when none apply). */
  tariffRate: number;
  /** value × (baseDutyRate + tariffRate) — total duty payable on this load. */
  dutyCost: number;
  /** Merchandise processing fee on this entry. */
  mpf: number;
  /** Harbor maintenance fee on this entry (ocean arrivals only). */
  hmf: number;
  /** duty + mpf + hmf — the cash this entry puts on the broker invoice. */
  entryCost: number;
  /**
   * Air-charter freight premium paid on this load (0 unless expedited). Carried
   * separately from duty because it is NOT dutiable — see the landed-cost block below.
   */
  freightPremium: number;
  /** value + entryCost + freightPremium. */
  landedCost: number;
  /** Dollars of landed cost above this load's unscenario'd baseline. */
  landedCostDelta: number;
  driver: string;
}

const levelOf = (risk: number): Risk =>
  risk >= 0.62 ? "critical" : risk >= 0.36 ? "caution" : "nominal";

export interface WarehouseState {
  id: string;
  code: string;
  name: string;
  x: number;
  y: number;
  level: Risk;
  openExceptions: number;
  daysOfCover: number;
  stockoutInDays: number | null;
  demandMultiplier: number;
  inboundHeld: number;
  atRiskZones: number;
  note: string;
}

/** Where re-let loads landed, so origin concentration is visible rather than hidden. */
export interface SourcingSplit {
  supplierId: string;
  supplierName: string;
  country: string;
  portShort: string;
  loads: number;
  /** Share of the re-let book sitting with this one alternate origin, 0..1. */
  share: number;
}

/**
 * What a recovery play could and could not reach this run. Both plays only act on
 * freight that has not departed, so "found fewer loads than asked for" is an
 * informative state — it is the app saying the options ran out when the freight sailed.
 */
export interface PlayStatus {
  id: string;
  kind: Scenario["kind"];
  label: string;
  /** Loads the play wanted to act on. */
  requested: number;
  /** Eligible pre-departure loads it actually found. */
  found: number;
  /** In-transit loads that qualified on every count except departure. */
  stranded: number;
  /** Cash sitting on those stranded loads that the play cannot touch, in dollars. */
  strandedCash: number;
}

export interface ControlState {
  shipments: ResolvedShipment[];
  /** Empty unless a dual-source play is running. */
  sourcing: SourcingSplit[];
  /** Empty unless a recovery play is running. */
  plays: PlayStatus[];
  warehouses: WarehouseState[];
  kpis: {
    onTime: number;
    /** Duty + MPF + HMF falling due across the inbound book, in dollars. */
    cashDue: number;
    /** Largest single entry-week of that cash, in dollars. */
    cashPeakWeek: number;
    /** Total landed cost of the inbound book, in dollars. */
    landedCost: number;
    /** Total duty payable (base MFN + active tariffs), in dollars. */
    dutyExposure: number;
    exceptions: number;
  };
  stockouts: {
    warehouseId: string;
    code: string;
    sku: string;
    name: string;
    zone: string;
    baseDays: number;
    days: number;
    level: Risk;
  }[];
  activeScenarios: Scenario[];
}

const zoneRisk = (z: Zone, cover: number): Risk => {
  if (cover < 7 || z.fill > 1.0) return "critical";
  if (cover < 14 || z.fill > 0.9) return "caution";
  return "nominal";
};

export function zoneLevel(z: Zone, demandMultiplier: number): Risk {
  return zoneRisk(z, z.daysOfCover / demandMultiplier);
}

/** Pure derivation of the entire board from the set of active scenario ids. */
export function computeState(activeIds: string[]): ControlState {
  const active = SCENARIOS.filter((s) => activeIds.includes(s.id));

  const portDelay = new Map<string, number>();
  const offlineSuppliers = new Set<string>();
  const demandMult = new Map<string, number>(WAREHOUSES.map((w) => [w.id, 1]));
  const laneDelay = new Map<string, number>();
  /**
   * Tariff front-running congestion, keyed by `${portId}|${mode}` rather than by port
   * alone. A measure scoped to air pulls parcels forward through air gateways; it does
   * not back up container cranes, so an ocean box moving through the same port must not
   * inherit that delay. Physical `port-delay` scenarios stay in `portDelay` and keep
   * hitting every mode at the port, which is correct for a berth/yard queue.
   */
  const surgeDelay = new Map<string, { days: number; effective: number }[]>();
  const surgeKey = (portId: string, mode: Shipment["mode"]) => `${portId}|${mode}`;

  for (const s of active) {
    if (s.kind === "port-delay")
      portDelay.set(s.targetId, (portDelay.get(s.targetId) ?? 0) + s.magnitude);
    if (s.kind === "supplier-offline") offlineSuppliers.add(s.targetId);
    if (s.kind === "demand-spike")
      demandMult.set(s.targetId, (demandMult.get(s.targetId) ?? 1) + s.magnitude);
    if (s.kind === "lane-closure") {
      laneDelay.set(s.targetId, (laneDelay.get(s.targetId) ?? 0) + s.magnitude);
      laneDelay.set("slc", (laneDelay.get("slc") ?? 0) + s.magnitude * 0.6);
    }
  }

  /* ---------- trade policy: rate resolution ---------- */

  const tariffs = active.filter((s) => s.kind === "tariff");

  /**
   * A measure only binds a load that ENTERS on or after its effective date. Pass the
   * load's arrival-at-port day; pass Infinity to ask the origin-level question "is this
   * lane tariffed at all, eventually" (used by the sourcing search, which is a
   * procurement decision about a lane and not about one box's timing).
   *
   * ORDERING — do not reverse this. `entryDay` is transit plus congestion only. Customs
   * clearance is assessed AFTER the boundary test and must never feed back into it: a
   * broker or CBP release delay changes when goods are RELEASED, not the date they were
   * ENTERED, and duty attaches at entry. Letting clearance push a load across its own
   * effective date would be circular — the backlog the measure creates would be the
   * thing that makes the measure apply.
   */
  const tariffBinds = (t: Scenario, entryDay: number) =>
    !t.effectiveInDays || entryDay >= t.effectiveInDays;

  /** Incremental ad valorem rate a load picks up from the active tariff stack. */
  const tariffRateFor = (country: string, mode: Shipment["mode"], entryDay: number) => {
    if (country === "US") return 0; // domestic freight crosses no customs line
    let r = 0;
    for (const t of tariffs) {
      if (t.scope === "air" && mode !== "air") continue;
      if (t.scope === "ocean" && mode !== "ocean") continue;
      if (t.originCountry && t.originCountry !== country) continue;
      if (!tariffBinds(t, entryDay)) continue; // beat the date, clears at MFN
      r += t.magnitude;
    }
    return r;
  };

  /** True when a tariff measure covers a given origin/mode pair. */
  const tariffCovers = (t: Scenario, country: string, mode: Shipment["mode"]) => {
    if (country === "US") return false;
    if (t.scope === "air" && mode !== "air") return false;
    if (t.scope === "ocean" && mode !== "ocean") return false;
    if (t.originCountry && t.originCountry !== country) return false;
    return true;
  };

  /**
   * TARIFF FRONT-RUNNING. A duty with a future effective date does not just raise cost
   * on the day it lands — importers rush freight in ahead of it, and that pull-forward
   * congests the very origin ports the affected goods move through. Modelling it here,
   * as congestion days fed into the existing portDelay map, keeps cost and delay on one
   * causal chain instead of two unrelated fudges, and means the ripple animation and
   * risk maths downstream need no changes at all.
   *
   * Intensity scales with the size of the duty and inversely with how soon it lands: a
   * big tariff three weeks out congests far harder than a small one three months out,
   * because the window to beat it is short and everyone books at once.
   *
   * BREADTH. A measure hitting many origins at once is worse than its per-port intensity
   * suggests. When one origin is tariffed, carriers reposition equipment and capacity
   * around it; when everything is tariffed there is nowhere to send the boxes, so the
   * same nominal rate produces materially more congestion per port. The breadth term
   * multiplies the surge by the number of distinct origin countries the measure touches.
   *
   * DEMO-TUNED: the 0.10 reference rate, 30-day reference horizon, 1.6 gain, 0.55
   * breadth coefficient and 12-day cap are hand-picked so the scenarios read well on
   * screen. They are not fitted to empirical port throughput data — recalibrate against
   * your own dwell history.
   */
  for (const t of tariffs) {
    if (!t.effectiveInDays) continue;
    const covered = SHIPMENTS.filter((s) => tariffCovers(t, portById(s.portId).country, s.mode));
    const origins = new Set(covered.map((s) => portById(s.portId).country));
    const breadth = 1 + 0.55 * (origins.size - 1);
    const surge = Math.min(12, (t.magnitude / 0.1) * (30 / t.effectiveInDays) * 1.6 * breadth);
    /* land the surge only on the port/mode pairs the measure actually covers */
    for (const key of new Set(covered.map((s) => surgeKey(s.portId, s.mode)))) {
      surgeDelay.set(key, [
        ...(surgeDelay.get(key) ?? []),
        { days: Number(surge.toFixed(1)), effective: t.effectiveInDays },
      ]);
    }
  }

  /**
   * DECAY PROFILE 1 — PHYSICAL DISRUPTION. A berth queue clears, a closed pass reopens,
   * a shut-down supplier restarts. Applying today's Oakland crane outage at full force to
   * a box that ships in three months is simply wrong, so physical delay bites loads
   * arriving in the near term and fades out beyond it. Keyed on the load's NOMINAL
   * arrival (`etaDays`), never on the congested one, so the decay cannot feed itself.
   * DEMO-TUNED: full force inside 10 days, e-folding over 16 days after that, so a
   * 30-day arrival absorbs ~29% and a 60-day arrival is effectively untouched.
   */
  const physicalDecay = (etaDays: number) =>
    etaDays <= 10 ? 1 : Math.max(0, Math.exp(-(etaDays - 10) / 16));

  /**
   * DECAY PROFILE 2 — TARIFF FRONT-RUNNING. Shaped quite differently, because the rush
   * is tied to a date rather than to today. Bookings pile into the run-up to the
   * effective date, peak just before it, and collapse after it: once the duty has landed
   * there is nothing left to beat, and the pulled-forward volume has already moved.
   * DEMO-TUNED: a gaussian lead-in scaled to the measure's own horizon, and a 12-day
   * e-folding tail afterwards.
   */
  const surgeFor = (portId: string, mode: Shipment["mode"], etaDays: number) =>
    (surgeDelay.get(surgeKey(portId, mode)) ?? []).reduce((a, r) => {
      if (etaDays <= r.effective) {
        const lead = (r.effective - etaDays) / Math.max(8, r.effective * 0.7);
        return a + r.days * Math.exp(-lead * lead);
      }
      return a + r.days * Math.exp(-(etaDays - r.effective) / 12);
    }, 0);

  /**
   * CUSTOMS CLEARANCE BACKLOG — deliberately a separate mechanism from berth congestion
   * above. Port dwell is a physical queue for cranes and yard space, and an air charter
   * routes around it (hence the 0.12 air bypass factor applied to portDelay later). A
   * clearance backlog is not physical: repealing de minimis pushes millions of parcels
   * that previously entered informally into formal entry, against broker and CBP
   * capacity that did not grow. Chartering a plane does not move you up the customs
   * queue, so this delay attaches to the lanes the measure covers and is NOT damped by
   * the air bypass. That is exactly why the air-scoped de minimis scenario needs it: its
   * whole effect would otherwise vanish into the bypass factor.
   *
   * DEMO-TUNED: the 2.0 gain for lane-scoped measures (parcel-heavy, broker-bound) versus
   * 0.5 for broad ones, and the 9-day cap, are hand-picked for legibility.
   */
  const clearanceRules: { t: Scenario; days: number }[] = [];
  for (const t of tariffs) {
    const horizon = t.effectiveInDays ?? 30;
    const gain = t.scope && t.scope !== "all" ? 2.0 : 0.5;
    const days = Math.min(9, (t.magnitude / 0.1) * (30 / horizon) * gain);
    if (days > 0.05) clearanceRules.push({ t, days: Number(days.toFixed(1)) });
  }
  /**
   * Gated on the same entry-date boundary as duty: a load entering before the measure
   * takes effect does not queue behind a formal-entry crush that has not started yet.
   */
  const clearanceDaysFor = (country: string, mode: Shipment["mode"], entryDay: number) =>
    clearanceRules.reduce(
      (a, r) => a + (tariffCovers(r.t, country, mode) && tariffBinds(r.t, entryDay) ? r.days : 0),
      0,
    );

  /* ---------- recovery play: dual-source away from the tariffed origin ---------- */

  let dualStatus: PlayStatus | null = null;
  let expediteStatus: PlayStatus | null = null;

  const dualScenario = active.find((s) => s.kind === "dual-source");
  const dualSourced = new Map<string, { supplierId: string; portId: string }>();

  if (dualScenario) {
    /**
     * Candidate origins must be untariffed across every mode actually in play — checking
     * only "ocean" would let an air origin look clean under an air-scoped measure.
     */
    const modesInPlay: Shipment["mode"][] = ["ocean", "air", "rail", "road"];
    const alts = SUPPLIERS.filter((sup) => {
      const p = portById(sup.portId);
      /* lane-level question: is this origin tariffed at all, eventually — not per-box timing */
      return (
        p.country !== "US" && modesInPlay.every((m) => tariffRateFor(p.country, m, Infinity) === 0)
      );
    })
      .sort((a, b) => supplierScore(b) - supplierScore(a))
      .slice(0, 3);

    /* a measure covering every overseas origin leaves nowhere clean to re-let to */
    dualStatus = {
      id: dualScenario.id,
      kind: dualScenario.kind,
      label: dualScenario.label,
      requested: dualScenario.magnitude,
      found: 0,
      stranded: 0,
      strandedCash: 0,
    };
    if (alts.length) {
      const scored = SHIPMENTS.map((s) => {
        const p = portById(s.portId);
        /* ranked on go-forward exposure (Infinity), not on whether this one box beats the
           date — you re-let a lane for the duty it will keep paying, not for one entry */
        return { s, duty: s.value * tariffRateFor(p.country, s.mode, Infinity) };
      }).filter((e) => e.duty > 0 && !alts.some((a) => a.id === e.s.supplierId));
      /**
       * PHYSICAL GATE. You cannot re-let a container that is 96% of the way across the
       * Pacific: the goods are made, the entry is set, the duty is locked. Only
       * pre-departure freight is reroutable, which is exactly why the forward book is
       * where a sourcing play earns its keep and why it visibly fails to touch the
       * exposure already on the water.
       */
      const eligible = scored
        .filter((e) => e.s.stage !== "transit")
        .sort((a, b) => b.duty - a.duty || (a.s.id < b.s.id ? -1 : 1))
        .slice(0, dualScenario.magnitude);
      const strandedLoads = scored.filter((e) => e.s.stage === "transit");
      dualStatus = {
        id: dualScenario.id,
        kind: dualScenario.kind,
        label: dualScenario.label,
        requested: dualScenario.magnitude,
        found: eligible.length,
        stranded: strandedLoads.length,
        strandedCash: Math.round(strandedLoads.reduce((a, e) => a + e.duty, 0)),
      };
      /**
       * Spread the re-let loads across the top few clean origins rather than piling them
       * all on the single best-scoring supplier. Sending everything to one alternate
       * trades tariff exposure for single-source concentration, which is the first
       * objection a procurement team raises — better to model it than hide it.
       */
      eligible.forEach((e, i) => {
        const alt = alts[i % alts.length];
        dualSourced.set(e.s.id, { supplierId: alt.id, portId: alt.portId });
      });
    }
  }

  /* pre-pass: rank ocean loads so the expedite play can target the worst three */
  const expediteOn = active.some((s) => s.kind === "expedite-air");
  const expediteScenario = active.find((s) => s.kind === "expedite-air");
  const expedited = new Set<string>();
  if (expediteOn && expediteScenario) {
    /**
     * Frozen loads are excluded from candidacy: you cannot air-freight goods a shut-down
     * supplier never made. Without this the freeze penalty in the score made exactly
     * those loads the top charter picks. And, as with dual-source, a load already at sea
     * cannot be chartered — you re-book the mode before it departs or not at all.
     */
    const candidates = SHIPMENTS.filter(
      (s) => s.mode === "ocean" && !dualSourced.has(s.id) && !offlineSuppliers.has(s.supplierId),
    ).map((s) => {
      const added =
        (portDelay.get(s.portId) ?? 0) * physicalDecay(s.etaDays) +
        surgeFor(s.portId, s.mode, s.etaDays) +
        (laneDelay.get(s.warehouseId) ?? 0) * physicalDecay(s.etaDays);
      return { s, score: s.baseRisk + added * 0.055 };
    });
    const ranked = candidates
      .filter((c) => c.s.stage !== "transit")
      .sort((a, b) => b.score - a.score || (a.s.id < b.s.id ? -1 : 1))
      .slice(0, expediteScenario.magnitude);
    for (const r of ranked) expedited.add(r.s.id);
    const strandedAtSea = candidates.filter((c) => c.s.stage === "transit" && c.score > 0.55);
    expediteStatus = {
      id: expediteScenario.id,
      kind: expediteScenario.kind,
      label: expediteScenario.label,
      requested: expediteScenario.magnitude,
      found: ranked.length,
      stranded: strandedAtSea.length,
      strandedCash: Math.round(
        strandedAtSea.reduce(
          (a, c) => a + c.s.value * tariffRateFor(portById(c.s.portId).country, c.s.mode, Infinity),
          0,
        ),
      ),
    };
  }

  const shipments: ResolvedShipment[] = SHIPMENTS.map((base) => {
    /**
     * Two distinct concepts, deliberately not one flag:
     *   `chartered` — this load was remediated by the expedite play this run. Drives
     *                 exception accounting and the freight premium.
     *   `flying`    — the load's RESOLVED mode is air. Drives physics: berth and inland
     *                 dwell are bypassed whether the load was always air or was
     *                 chartered this morning.
     * Overloading one flag made native air freight absorb full berth dwell.
     */
    const chartered = expedited.has(base.id);
    const air = chartered;
    const dual = dualSourced.get(base.id);
    /**
     * Dual-sourcing is a real tradeoff, not a free win. The alternate lane is longer and
     * carries more execution risk on a supplier this network has less history with — and,
     * crucially, the goods themselves cost more: you are spot-buying on short notice with
     * no volume commitment, so the supplier's `spotPremium` (8–16%) lifts the declared
     * value before any duty is calculated. The re-let load also picks up the MFN rate of
     * the origin it lands in rather than keeping the rate of the origin it left.
     *
     * STAGE FRICTION. Cancelling a load that is already booked — space held, production
     * run finished or nearly — costs more than redirecting one that is only planned: you
     * eat qualification and rebooking time at the back of someone else's queue, and you
     * pay a worse spot price for the urgency. DEMO-TUNED: booked pays +8 days and 4
     * points of extra premium, planned +3 days and none.
     */
    const reletDays = base.stage === "booked" ? 8 : 3;
    const reletPremium = base.stage === "booked" ? 0.04 : 0;
    const s: Shipment = dual
      ? {
          ...base,
          supplierId: dual.supplierId,
          portId: dual.portId,
          etaDays: Math.round(base.etaDays * 1.35) + reletDays,
          baseRisk: Math.min(0.97, base.baseRisk + (base.stage === "booked" ? 0.11 : 0.06)),
          value: Math.round(
            base.value * (1 + supplierById(dual.supplierId).spotPremium + reletPremium),
          ),
          baseDutyRate: mfnRateFor(dual.supplierId),
        }
      : air
        ? {
            ...base,
            mode: "air",
            /* a booked load still has to be pulled from its ocean booking and re-manifested */
            etaDays: Math.max(
              2,
              Math.round(base.etaDays * 0.34) + (base.stage === "booked" ? 3 : 0),
            ),
          }
        : base;
    const flying = s.mode === "air";
    const port = portById(s.portId);
    const sup = supplierById(s.supplierId);
    const ocean = s.mode === "ocean";
    const frozen = offlineSuppliers.has(s.supplierId);
    /* physical disruptions decay with distance to arrival; the front-running surge has
       its own date-anchored shape — see both DECAY PROFILE comments above */
    const decay = physicalDecay(s.etaDays);
    const rawAdded =
      (portDelay.get(s.portId) ?? 0) * decay +
      surgeFor(s.portId, s.mode, s.etaDays) +
      (laneDelay.get(s.warehouseId) ?? 0) * decay +
      (frozen ? 14 * decay : 0);

    /* air freight bypasses most of the berth/lane dwell — but not the customs queue */
    const transitAdded = flying ? rawAdded * 0.12 : rawAdded;
    /**
     * STEP 1–2. Arrival at the port of entry is transit plus congestion, and that is the
     * day the effective-date boundary is tested against. Clearance is NOT in here (see
     * `tariffBinds`). The second-order effect falls out of this ordering rather than
     * being special-cased: a load that would have arrived day 19 against a 21-day tranche
     * clears at MFN, but the tariff's own pull-forward surge can add four days of berth
     * dwell, land it on day 23, and make it pay the very duty it was rushing to beat.
     */
    const entryDay = s.etaDays + transitAdded;
    const cleanEntryDay = s.etaDays; // where it would have entered with no congestion

    /* STEP 3. Duty and the clearance backlog are both assessed against that entry day. */
    const tariffRate = tariffRateFor(port.country, s.mode, entryDay);
    const clearance = clearanceDaysFor(port.country, s.mode, entryDay);
    /* would have beaten every binding measure, and congestion alone cost it the window */
    const missedWindow =
      tariffRate > 0 && tariffRateFor(port.country, s.mode, cleanEntryDay) < tariffRate;

    /* STEP 4. Final ETA is arrival plus customs release. */
    const added = transitAdded + clearance;
    const risk = Math.min(
      0.99,
      (s.baseRisk +
        added * 0.055 +
        (frozen ? 0.4 : 0) +
        (demandMult.get(s.warehouseId)! - 1) * 0.22) *
        (flying ? 0.45 : 1),
    );

    const dutyCost = Math.round(s.value * (s.baseDutyRate + tariffRate));
    const { mpf, hmf } = entryFees(s.value, s.mode, port.country);
    const entryCost = dutyCost + mpf + hmf;
    /**
     * FOB. US customs value is the FOB price of the goods, so international freight sits
     * outside the dutiable base: chartering a plane raises what you PAY and not what you
     * OWE. That gives the two recovery plays different cost signatures — dual-sourcing
     * lifts the goods price itself, so it is dutiable and duty compounds on the spot
     * premium (see the re-let branch above), while an air charter adds a freight line
     * that no duty is ever assessed on.
     */
    const freightPremium = chartered ? Math.round(base.value * base.airPremiumRate) : 0;
    const landedCost = s.value + entryCost + freightPremium;
    /* baseline for this load: its own MFN duty and fees, no scenario applied */
    const baseCountry = portById(base.portId).country;
    const baseFees = entryFees(base.value, base.mode, baseCountry);
    const landedCostDelta =
      landedCost - (Math.round(base.value * (1 + base.baseDutyRate)) + baseFees.mpf + baseFees.hmf);

    /**
     * DEMO NARRATIVE STRINGS. The risk-driver copy below (and the warehouse `note` and
     * stockout wording further down) is hand-written for the fictional Meridian network
     * and its phrasing — berth dwell, inland lane holds, OTIF floors. The selection
     * logic is generic, but reword these for your own operation's vocabulary when you
     * swap in real data.
     */
    const driver = dual
      ? `Re-let to ${sup.name} (${port.country}) — spot premium +${Math.round(supplierById(dual.supplierId).spotPremium * 100)}%, +${Math.round(s.etaDays - base.etaDays)}d transit`
      : chartered
        ? `Air charter booked — ${Math.max(2, Math.round(s.etaDays))}d wheels-down, freight premium +${Math.round(base.airPremiumRate * 100)}% (non-dutiable)`
        : missedWindow
          ? `Missed the window — was clearing day ${Math.round(cleanEntryDay)}, congestion +${Math.round(entryDay - cleanEntryDay)}d pushed entry to day ${Math.round(entryDay)} and it now pays +${(tariffRate * 100).toFixed(0)}pts`
          : tariffRate > 0
            ? `Duty +${(tariffRate * 100).toFixed(0)}pts on ${port.country} origin — landed cost +$${Math.round((s.value * tariffRate) / 1000)}k${clearance > 0.4 ? ` · customs backlog +${clearance.toFixed(1)}d` : ""}`
            : clearance > 0.4
              ? `Formal-entry backlog +${clearance.toFixed(1)}d — broker/CBP capacity, not berth`
              : frozen
                ? `${sup.name} shutdown — PO frozen, 14d recovery`
                : (portDelay.get(s.portId) ?? 0) * decay + surgeFor(s.portId, s.mode, s.etaDays) >
                    0.4
                  ? `${port.name} congestion +${Number(((portDelay.get(s.portId) ?? 0) * decay + surgeFor(s.portId, s.mode, s.etaDays)).toFixed(1))}d dwell`
                  : (laneDelay.get(s.warehouseId) ?? 0) * decay > 0.4
                    ? `Inland lane hold to ${s.warehouseId.toUpperCase()}`
                    : s.baseRisk > 0.55
                      ? `Supplier OTIF ${Math.round(sup.otif.at(-1)!)}% · lead-time variance`
                      : s.baseRisk > 0.32
                        ? "Carrier schedule drift (2d rolling)"
                        : "On plan — no active driver";
    return {
      ...s,
      supplierName: sup.name,
      portName: port.name,
      portShort: port.short,
      country: port.country,
      ocean,
      expedited: air,
      dualSourced: Boolean(dual),
      path: routePath(
        port.x,
        port.y,
        WAREHOUSES.find((w) => w.id === s.warehouseId)!.x,
        WAREHOUSES.find((w) => w.id === s.warehouseId)!.y,
        s.mode,
      ),
      addedDays: Math.round(added),
      eta: Math.round(s.etaDays + added),
      entryDay: Number(entryDay.toFixed(1)),
      missedWindow,
      risk,
      level: levelOf(risk),
      /* reported honestly; remediation is expressed through `impacted`, not by hiding it */
      frozen,
      /* a chartered load has been actively remediated, so it is no longer an open exception */
      /* 0.4d floor: with the decay profiles a 100-day arrival picks up a fractional
         residue of today's berth queue, and that is not an open exception */
      impacted: chartered ? clearance > 0.4 : added > 0.4,

      tariffRate,
      dutyCost,
      mpf,
      hmf,
      entryCost,
      freightPremium,
      landedCost,
      landedCostDelta,
      driver,
    };
  });

  const warehouses: WarehouseState[] = WAREHOUSES.map((w) => {
    const mult = demandMult.get(w.id)!;
    const inbound = shipments.filter((s) => s.warehouseId === w.id);
    const held = inbound.filter((s) => s.impacted).length;
    const criticals = inbound.filter((s) => s.level === "critical").length;
    const zones = FLOORPLANS[w.id];
    const atRiskZones = zones.filter((z) => zoneLevel(z, mult) !== "nominal").length;
    const cover = Number(
      (zones.reduce((a, z) => a + z.daysOfCover, 0) / zones.length / mult).toFixed(1),
    );
    const pressure = criticals * 0.8 + held * 0.6 + (mult - 1) * 9 + atRiskZones * 0.5;
    const level: Risk = pressure >= 7.5 ? "critical" : pressure >= 4.2 ? "caution" : "nominal";
    const stockoutInDays = level === "nominal" ? null : Math.max(2, Math.round(cover - held * 0.9));
    return {
      id: w.id,
      code: w.code,
      name: w.name,
      x: w.x,
      y: w.y,
      level,
      openExceptions: criticals + held,
      daysOfCover: cover,
      stockoutInDays,
      demandMultiplier: mult,
      inboundHeld: held,
      atRiskZones,
      note:
        mult > 1
          ? `Demand +${Math.round((mult - 1) * 100)}% · cover compressed`
          : held > 0
            ? `${held} inbound held upstream`
            : criticals > 0
              ? `${criticals} shipment(s) at critical risk`
              : "All lanes nominal",
    };
  });

  const stockouts = warehouses
    .flatMap((w) =>
      FLOORPLANS[w.id]
        .flatMap((z) =>
          z.topSkus.slice(0, 1).map((sku) => {
            const baseDays = Math.round(z.daysOfCover);
            const days = Math.max(
              1,
              Math.round(z.daysOfCover / w.demandMultiplier - w.inboundHeld * 1.1),
            );
            return {
              warehouseId: w.id,
              code: w.code,
              sku: sku.sku,
              name: sku.name,
              zone: z.label,
              baseDays,
              days,
              level: (days <= 7 ? "critical" : days <= 16 ? "caution" : "nominal") as Risk,
            };
          }),
        )
        .filter((s) => s.days <= 26),
    )
    .sort((a, b) => a.days - b.days)
    .slice(0, 9);

  const exceptions =
    shipments.filter((s) => s.level === "critical").length +
    warehouses.reduce((a, w) => a + w.atRiskZones, 0);
  const impactShare = shipments.filter((s) => s.impacted).length / shipments.length;
  const landedCost = shipments.reduce((a, s) => a + s.landedCost, 0);
  const dutyExposure = shipments.reduce((a, s) => a + s.dutyCost, 0);

  /**
   * CASH DUE. Duty + MPF + HMF across the whole inbound book — the cheque, not the
   * margin. Timing is bucketed by the week the load ENTERS, because that is when the
   * liability arises.
   *
   * SIMPLIFICATION: importers on a periodic monthly statement do not actually pay on
   * entry — they settle on the 15th business day of the month FOLLOWING the month of
   * entry, which shifts real cash out by up to six weeks and smooths the peak. A real
   * deployment should bucket on the statement date, not the entry date.
   */
  const cashDue = shipments.reduce((a, s) => a + s.entryCost, 0);
  const weekBuckets = new Map<number, number>();
  for (const s of shipments) {
    const wk = Math.max(0, Math.floor(s.entryDay / 7));
    weekBuckets.set(wk, (weekBuckets.get(wk) ?? 0) + s.entryCost);
  }
  const cashPeakWeek = Math.max(0, ...weekBuckets.values());

  /**
   * DEMO KPI MODEL. Unlike landed cost and cash due — which are identities over value,
   * duty rates and statutory fee rates — `onTime` below is a linear approximation with
   * hand-tuned constants, not derived from the underlying operational maths.
   * `impactShare` (the fraction of loads touched by a disruption) is used as a single
   * proxy for schedule reliability, and the 94.2 intercept is simply the demo's nominal
   * posture. It moves in the right direction with the right rough magnitude, which is
   * what a what-if demo needs — it is not a forecast. Replace with your own OTIF
   * computation over real order lines when you swap in real data.
   */
  const relet = shipments.filter((s) => s.dualSourced);
  const sourcing: SourcingSplit[] = [...new Set(relet.map((s) => s.supplierId))]
    .map((id) => {
      const loads = relet.filter((s) => s.supplierId === id);
      return {
        supplierId: id,
        supplierName: loads[0].supplierName,
        country: loads[0].country,
        portShort: loads[0].portShort,
        loads: loads.length,
        share: loads.length / relet.length,
      };
    })
    .sort((a, b) => b.loads - a.loads);

  return {
    shipments,
    sourcing,
    plays: [dualStatus, expediteStatus].filter((p): p is PlayStatus => p !== null),

    warehouses,
    activeScenarios: active,
    stockouts,
    kpis: {
      onTime: Number((94.2 - impactShare * 26).toFixed(1)),
      cashDue,
      cashPeakWeek,
      landedCost,
      dutyExposure,
      exceptions,
    },
  };
}

export const BASELINE = computeState([]);

export { SCENARIOS, SUPPLIERS, PORTS, WAREHOUSES, FLOORPLANS, supplierScore };
