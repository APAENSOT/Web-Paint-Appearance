/** Compact USD for dense table cells and KPI sublines: $1.2M, $840k, $312. */
export function usd(n: number) {
  const a = Math.abs(n);
  const s = n < 0 ? "−" : "";
  if (a >= 1_000_000) return `${s}$${(a / 1_000_000).toFixed(a >= 10_000_000 ? 1 : 2)}M`;
  if (a >= 1_000) return `${s}$${Math.round(a / 1_000)}k`;
  return `${s}$${Math.round(a)}`;
}

/** Signed compact USD, used for landed-cost deltas where direction is the point. */
export function usdDelta(n: number) {
  if (Math.round(n) === 0) return "—";
  return `${n > 0 ? "+" : "−"}${usd(Math.abs(n)).replace("−", "")}`;
}

/** Ad valorem rate as a percentage string, e.g. 0.0425 → "4.3%". */
export function pctRate(r: number) {
  return `${(r * 100).toFixed(1)}%`;
}
