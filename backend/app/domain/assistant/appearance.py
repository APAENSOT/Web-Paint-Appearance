"""AR05 appearance topics: a colour's wave profile, what drives CF down, layer thickness vs a band.

Pure: medians, Spearman and a fitted slope, linked to layers by the owner's band table. Wave Scan only.
"""

from __future__ import annotations

from statistics import median

from app.domain.assistant.answer import MIN_BOX_N, Answer, Box, all_clear, not_enough
from app.domain.assistant.plain_words import box_words
from app.domain.assistant.readings import Reading
from app.domain.report_stats import mean_sd, ols_slope, spearman
from app.domain.report_summary import BAND_LAYERS, BAND_WORD, LAYER_WORD

PROFILE_RULE = ("Colour median per metric against the plant median, in plant σ units; a band is high from "
                "half a σ up; layers from the owner's band table")
DRIVERS_RULE = "Spearman correlation of CF with each band over Wave Scan readings sharing a measurement (needs 10)"
LINK_RULE = "Spearman correlation and fitted line of one layer's thickness against one band over paired cars"
NEEDS_WS = "This question needs Wave Scan data; the instrument filter is Film only."
NEEDS_FILM = "This question needs Film data; the instrument filter is Wave Scan only."
PROFILE_METRICS = ("du", "wa", "wb", "wc", "wd", "we", "lw", "sw", "doi")
PROFILE_COLUMNS = ["Band", "Colour", "Plant", "Gap (σ)", "High"]
SHORT, HIGH_GAP, DRIVER_RHO, MIN_PAIRS = ("du", "wa", "wb"), 0.5, -0.3, 3


def domain_gate(topic: str, domain: str) -> str | None:
    """The not-enough sentence when the instrument filter rules the question out, else None."""
    if domain == "film" and topic in ("appearance_profile", "cf_drivers", "layer_vs_band"):
        return NEEDS_WS
    return NEEDS_FILM if domain == "wavescan" and topic == "layer_vs_band" else None


def _word(metric: str) -> str:
    return BAND_WORD.get(metric, metric)


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _layers(bands: list[str]) -> tuple[list[str], list[str]]:
    """(primary layers, secondary layers) for the bands, band order, no repeats."""
    prim: list[str] = []
    sec: list[str] = []
    for b in bands:
        prim += [x for x in BAND_LAYERS[b][0] if x not in prim]
    for b in bands:
        sec += [x for x in BAND_LAYERS[b][1] if x not in sec and x not in prim]
    return prim, sec


def appearance_profile(colour: str, readings: list[Reading]) -> Answer:
    ws = [r for r in readings if r.domain == "wavescan"]
    rows, series, high, caveats = [], [], [], []
    for m in PROFILE_METRICS:
        plant = [r.value for r in ws if r.metric == m]
        mine = [r.value for r in ws if r.metric == m and r.color == colour]
        if len(mine) < MIN_BOX_N:
            if mine:
                caveats.append(f"{_word(m)} skipped: {len(mine)} readings, {MIN_BOX_N} needed.")
            continue
        sd = mean_sd(plant)[1] or 0.0
        mid, pm = median(mine), median(plant)
        gap = (mid - pm) / sd if sd >= 1e-9 else 0.0
        is_high = gap >= HIGH_GAP
        if is_high and m in BAND_LAYERS:
            high.append(m)
        series.append({"x": _word(m), "y": mid})
        # Only du..we feed the headline; higher DOI is better and lw/sw show their gap only.
        rows.append([_word(m), round(mid, 1), round(pm, 1), round(gap, 1),
                     "high" if is_high and m in BAND_LAYERS else ""])
    if not rows:
        return not_enough(f"Not enough Wave Scan readings for {colour} this month.", len(ws), PROFILE_RULE)
    evidence = {"kind": "spectrum", "columns": PROFILE_COLUMNS, "rows": rows, "series": series}
    method = {"rule": PROFILE_RULE, "n": len(ws), "caveats": caveats}
    if not high:
        a = all_clear(f"{colour}: appearance bands are in line with the plant.", PROFILE_RULE, len(ws))
        a.evidence, a.method = evidence, method
        a.explanation = f"Every appearance band checked for {colour} this month is in line with the plant."
        return a
    names = "/".join(_word(b) for b in high)
    prim, sec = _layers(high)
    where = " and ".join(prim)
    kind = ("short waves" if all(b in SHORT for b in high)
            else "long waves" if not any(b in SHORT for b in high) else None)
    head = f"{colour}: {kind} high ({names}) → check {where}" if kind else f"{colour}: {names} high → check {where}"
    far = max((r for r in rows if r[4]), key=lambda r: r[3])
    text = (f"{colour} runs high on {kind or 'some waviness bands'} this month, on {_and([_word(b) for b in high])}. "
            f"By the band-to-layer table that points to {where}, so check "
            f"{'that build' if len(prim) == 1 else 'those builds'} first. {far[0]} is furthest out, with a median of "
            f"{far[1]} against {far[2]} across the plant.")
    return Answer(
        status="answer", headline=head, confidence="exploratory", explanation=text,
        next_step=f"Check {where}" + (f"; then {' and '.join(sec)}" if sec else ""),
        evidence=evidence, method=method,
        followups=[{"label": "Which layer to check?", "topic": "bands", "target": None}])


def cf_drivers(box: Box, readings: list[Reading]) -> Answer:
    if box.domain != "wavescan":
        return not_enough("Pick a Wave Scan box; CF drivers come from Wave Scan bands.", 0, DRIVERS_RULE)
    mine = [r for r in readings if r.box_key == box.key and r.domain == "wavescan" and r.measurement]
    cf = {r.measurement: r.value for r in mine if r.metric == "cf"}
    found = []  # (rho, n, band)
    for b in BAND_LAYERS:
        v = {r.measurement: r.value for r in mine if r.metric == b}
        keys = [k for k in cf if k in v]
        rho, n = spearman([cf[k] for k in keys], [v[k] for k in keys])
        if rho is not None:
            found.append((rho, n, b))
    if not found:
        return not_enough(f"{box.label}: not enough Wave Scan readings to link bands and CF.", len(cf), DRIVERS_RULE)
    found.sort()
    drivers = [f for f in found if f[0] <= DRIVER_RHO and f[1] >= MIN_BOX_N]
    evidence = {"kind": "bar", "columns": ["Band", "ρ", "n"],
                "rows": [[_word(b), round(r, 2), n] for r, n, b in found], "series": []}
    method = {"rule": DRIVERS_RULE, "n": len(cf), "caveats": []}
    if not drivers:
        return Answer(status="answer", status_code=box.status, confidence="exploratory",
                      headline=f"{box.label}: no band clearly drives CF", evidence=evidence, method=method,
                      explanation=(f"For {box_words(box)}, no band clearly moves with CF this month. "
                                   f"That's across {len(found)} bands and {len(cf)} measurements, so the CF loss "
                                   "doesn't point to one paint layer."))
    names = [_word(b) for _, _, b in drivers[:2]]
    layers = " and ".join(BAND_LAYERS[drivers[0][2]][0])
    strong = "a strong" if drivers[0][0] <= -0.7 else "a moderate"
    text = (f"For {box_words(box)}, CF loss tracks {' and '.join(names)}: the higher the {names[0]}, the lower the "
            f"CF. It's {strong} link across {drivers[0][1]} measurements, and by the band-to-layer table "
            f"{names[0]} points to {layers}, so check {layers} first.")
    return Answer(
        status="answer", status_code=box.status, confidence="exploratory",
        headline=(f"{box.label}: CF loss tracks {' and '.join(_word(b) for _, _, b in drivers[:2])} "
                  f"(ρ {', '.join(f'{r:.1f}' for r, _, _ in drivers[:2])})"),
        next_step="Check " + " and ".join(BAND_LAYERS[drivers[0][2]][0]), explanation=text,
        evidence=evidence, method=method,
        followups=[{"label": "Which layer to check?", "topic": "bands", "target": None}])


def layer_vs_band(layer: str, band: str, paired: list[dict] | None) -> Answer:
    lw, bw = LAYER_WORD.get(layer, layer), _word(band)
    units = {(r["car_no"], r["pair_group"]): (float(r["thickness"]), float(r[band]), r["car_no"])
             for r in paired or []
             if r["layer_code"] == layer and r.get("thickness") is not None and r.get(band) is not None}
    xs, ys = [u[0] for u in units.values()], [u[1] for u in units.values()]
    rho, n = spearman(xs, ys)
    if rho is None and n >= MIN_PAIRS:  # spearman is None on a constant side too
        return not_enough(f"{lw} or {bw} didn't vary across the paired cars, so no link can be measured.", n, LINK_RULE)
    if rho is None:
        return not_enough(f"Not enough paired cars to link {lw} and {bw} ({MIN_PAIRS} needed).", n, LINK_RULE)
    if abs(rho) < -DRIVER_RHO:
        head = f"No clear link between {lw} thickness and {bw} (ρ {rho:.1f}, n {n}, exploratory)"
    else:
        head = f"Thicker {lw} → {'lower' if rho < 0 else 'higher'} {bw} (ρ {rho:.1f}, n {n}, exploratory)"
    slope = ols_slope(xs, ys)
    lead = f"That's from {n} cars measured on both instruments, so treat it as a lead, not proof."
    if abs(rho) < -DRIVER_RHO:
        text = f"{lw} thickness and {bw} don't move together in any clear way. {lead}"
    else:
        more = "lower" if rho < 0 else "higher"
        # The size comes from the fitted line: show it only when the line runs the same way as the ranks.
        size = slope is not None and round(abs(slope), 2) > 0 and (slope < 0) == (rho < 0)
        text = (f"The thicker the {lw}, the {more} the {bw}, {'a strong' if abs(rho) >= 0.7 else 'a moderate'} link"
                + (f": each extra µm of {lw} goes with about {abs(slope):.2f} {more} {bw}." if size else ".")
                + f" {lead}")
    card = [] if slope is None else [
        {"label": "Slope", "value": f"{slope:.4g}"},
        {"label": "Intercept", "value": f"{sum(ys) / n - slope * sum(xs) / n:.4g}"}]
    return Answer(
        status="answer", headline=head, confidence="exploratory", proof=f"{n} paired cars, Spearman ρ {rho:.2f}",
        explanation=text,
        evidence={"kind": "scatter", "columns": ["Car", "Thickness", bw],
                  "rows": [[c, x, y] for x, y, c in units.values()], "series": [],
                  "points": [{"x": x, "y": y, "label": c} for x, y, c in units.values()], "card": card},
        method={"rule": LINK_RULE, "n": n, "caveats": ["Uses paired cars from all months."]})
