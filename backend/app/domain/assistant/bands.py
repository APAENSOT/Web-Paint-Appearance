"""AR04 topic `bands`: which Wave Scan band is up, which paint layer to check (owner's table)."""

from __future__ import annotations

from math import sqrt
from statistics import median

from app.domain.assistant.answer import (
    MIN_BOX_N, PAIRED_MIN_REGRESSION, SHIFT_P, Answer, BandRow, all_clear, not_enough,
)
from app.domain.assistant.plain_words import model_word
from app.domain.report_stats import mann_whitney, mean_sd, multiple_ols, spearman
from app.domain.report_summary import BAND_LAYERS, BAND_WORD, LAYER_WORD

RULE = "Band rise (Mann-Whitney) or highest vs plant, mapped to the owner's layer table"
BANDS = tuple(BAND_LAYERS)  # du wa wb wc wd we (no CF)
LAYERS = ("ECOAT", "PRIMER", "BASE", "CLEAR")
NO_PAIRS = "Not enough paired cars to check."
NO_FILM = "Film is filtered out, so the layer check is skipped."


def _groups(rows: list[BandRow]) -> dict[tuple, list[float]]:
    g: dict[tuple, list[float]] = {}
    for r in rows:
        for b in BANDS:
            v = r.values.get(b)
            if v is not None:
                g.setdefault((r.model, r.color, b), []).append(float(v))
    return g


def _check(paired: list[dict] | None, band: str, primaries: tuple[str, ...]):
    """(proof, rho_shown, regression caveat or None, paragraph sentence)."""
    per: dict[str, dict[tuple, tuple[float, float]]] = {c: {} for c in LAYERS}
    for r in paired or []:
        if r["layer_code"] in per and r.get("thickness") is not None and r.get(band) is not None:
            per[r["layer_code"]][(r["car_no"], r["pair_group"])] = (float(r["thickness"]), float(r[band]))
    best = None
    for code, units in per.items():
        if len(units) < 3:
            continue
        rho, n = spearman([t for t, _ in units.values()], [v for _, v in units.values()])
        if rho is not None and (best is None or abs(rho) > abs(best[1])):
            best = (code, rho, n)
    if best is None:
        return NO_PAIRS, False, None, ""
    word = LAYER_WORD[best[0]]
    proof = (f"Data agrees ({word} ρ {best[1]:.2f}, n {best[2]}, exploratory)" if word in primaries
             else f"Data points elsewhere: {word} (ρ {best[1]:.2f}, n {best[2]})")
    lead = f"from {best[2]} cars measured on both instruments, so treat it as a lead, not proof"
    said = (f" The paired cars agree: the thicker the {word}, the {'higher' if best[1] > 0 else 'lower'} the "
            f"{BAND_WORD[band]}, {lead}." if word in primaries else
            f" The paired cars point to {word} instead, {lead}.")
    full = [u for u in per["ECOAT"] if all(u in per[c] for c in LAYERS)]
    caveat = None
    if len(full) >= PAIRED_MIN_REGRESSION:
        b = multiple_ols([[per[c][u][0] for c in LAYERS] for u in full], [per["ECOAT"][u][1] for u in full])
        if b:
            parts = ", ".join(f"{LAYER_WORD[c]} {v:+.2f}" for c, v in zip(LAYERS, b[1:]))
            caveat = f"Regression {BAND_WORD[band]} on layers (n {len(full)}): {parts}"
    return proof, True, caveat, said


def bands(now: list[BandRow], before: list[BandRow], paired: list[dict] | None, *,
          film_filtered: bool = False) -> Answer:
    if not now:
        return not_enough("Band answers need Wave Scan data.", 0, RULE)
    gn, gb = _groups(now), _groups(before)
    plant: dict[str, list[float]] = {}
    for (_, _, b), v in gn.items():
        plant.setdefault(b, []).extend(v)
    plant_stat = {b: (median(v), mean_sd(v)[1]) for b, v in plant.items()}

    cands = []  # (key, delta, verdict, size)
    for key, vals in gn.items():
        if len(vals) < MIN_BOX_N:
            continue
        old = gb.get(key, [])
        mn, mo = median(vals), (median(old) if old else None)
        verdict, size = "Too few readings", None
        if len(old) >= MIN_BOX_N:
            verdict, p = "Noise", mann_whitney(vals, old)
            sn, so = mean_sd(vals)[1] or 0.0, mean_sd(old)[1] or 0.0
            pooled = sqrt((sn**2 + so**2) / 2)
            if p is not None and p < SHIFT_P and mn > mo and pooled >= 1e-9:
                verdict, size = "Real rise", (mn - mo) / pooled
        cands.append([key, None if mo is None else mn - mo, verdict, size])
    rises = [c for c in cands if c[3] is not None]
    if rises:
        top = max(rises, key=lambda c: c[3])
    else:
        top = None
        best = 0.0
        for c in cands:
            pm, psd = plant_stat[c[0][2]]
            if psd is None or psd < 1e-9:
                continue
            c[1] = median(gn[c[0]]) - pm
            if c[1] > 0:
                c[2] = "Above plant"
                z = c[1] / psd
                if z > best:
                    best, top = z, c
    if top is None:
        a = all_clear("No Wave Scan band stands out this month.", RULE, len(now))
        a.explanation = "No Wave Scan band has risen since last month or runs above the plant on any model and colour."
        return a

    (model, color, band), delta, verdict, _ = top
    primary, secondary = BAND_LAYERS[band]
    layers = " and ".join(primary)
    tail = f" ({delta:+.1f} vs plant)" if verdict == "Above plant" else f" ({delta:+.1f})"
    verb = "high" if verdict == "Above plant" else "up"
    where = f"{model or '—'} {color or '—'}"
    proof, shown, caveat, said = (NO_FILM, True, None, "") if film_filtered else _check(paired, band, primary)
    who = " ".join(x for x in (model_word(model) if model else "", color or "") if x) or "the plant"
    gap = f"{abs(delta):.1f}"
    text = (f"The {BAND_WORD[band]} band on {who} " + (
        f"runs {gap} above the plant this month." if verdict == "Above plant" else
        f"rose {gap} since last month, a real difference, not day-to-day noise.")
        + f" By the band-to-layer table, {BAND_WORD[band]} points to {layers}, so check that build first." + said)
    rest = [c for c in cands if c is not top]
    return Answer(
        status="answer",
        headline=f"{BAND_WORD[band]} {verb} on {where}{tail} → check {layers}",
        proof=proof,
        explanation=text,
        next_step=f"Check the {layers} build" + (f"; then {' and '.join(secondary)}" if secondary else ""),
        confidence="exploratory" if shown else "solid",
        evidence={
            "kind": "bar",
            "columns": ["Model", "Colour", "Band", "Change", "Verdict", "Layer"],
            "rows": [
                [c[0][0], c[0][1], BAND_WORD[c[0][2]], "" if c[1] is None else f"{c[1]:+.1f}", c[2],
                 ", ".join(BAND_LAYERS[c[0][2]][0])]
                for c in [top, *rest]
            ],
            "series": [],
        },
        followups=[{"label": "Which colours?", "topic": "colours", "target": None}],
        method={"rule": RULE, "n": len(gn[top[0]]), "caveats": [caveat] if caveat else []},
    )
