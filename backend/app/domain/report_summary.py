"""Analysis report summary: fixed sentence templates filled with numbers (AR03 section 4).

Pure: no SQL, no network, no AI service (D-AR03-7). Status words are the
site's (D-AR03-6); counts are "x of y", never a share (D-AR03-10). A
sentence whose data is absent is skipped.
"""

from __future__ import annotations

from calendar import month_name

STATUS_WORD = {"PASS": "Pass", "WARNING": "Acceptable", "FAIL": "Fail", "OVER": "Over"}
LAYER_WORD = {"ECOAT": "E-coat", "PRIMER": "Primer", "BASE": "Base", "CLEAR": "Clear"}
BAND_WORD = {"du": "du", "wa": "Wa", "wb": "Wb", "wc": "Wc", "wd": "Wd", "we": "We", "cf": "CF"}
#: The "Points to" of each band note (superseded AR03 section 4); CF has no note.
BAND_LAYERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "du": (("Clear",), ()),
    "wa": (("Clear",), ()),
    "wb": (("Clear", "Base"), ()),
    "wc": (("Base",), ()),
    "wd": (("Primer",), ("Substrate",)),
    "we": (("E-coat",), ("Substrate",)),
}
BAND_POINTS_TO = {b: ", ".join(p + s) for b, (p, s) in BAND_LAYERS.items()}
PAIRED_ENOUGH = 100


def status_word(code: str | None, scope: str | None = None, layer: str | None = None) -> str:
    """The site's word; null is "No standard", or "Not graded" for a Film box with a rule."""
    if code is None:
        return "Not graded" if scope in ("COLOR", "PLANT") else "No standard"
    if code == "WARNING" and layer == "CLEAR":
        return "For Improvement"
    return STATUS_WORD[code]


def month_words(month: str) -> str:
    year, number = month.split("-")
    return f"{month_name[int(number)]} {year}"


def _d(x) -> str:
    return f"{float(x):.1f}"


def _orient(orient: str) -> str:
    return orient[0]


def _change(row: dict) -> str:
    layer = f"{LAYER_WORD[row['layer']]} " if row["layer"] else ""
    before = status_word(row["status_before"], row.get("_scope_before"), row.get("layer"))
    now = status_word(row["status_now"], row.get("_scope_now"), row.get("layer"))
    return f"{layer}{row['model']} {row['color']} {_orient(row['orient'])}: {before} → {now}"


def sentences(report: dict) -> list[str]:
    out: list[str] = []
    plant, month = report["plant_code"], report["month"]
    ws = (report["glance"] or {}).get("wavescan")
    film = (report["glance"] or {}).get("film")

    if month and ws and film:
        out.append(
            f"{plant} {month_words(month)}: {ws['readings']} Wave Scan readings on "
            f"{ws['cars']} cars; {film['cars']} cars with Film readings."
        )
    if ws and sum(ws["boxes"].values()):
        b = ws["boxes"]
        out.append(
            f"Wave Scan: {b['PASS']} of {sum(b.values())} boxes Pass, {b['WARNING']} Acceptable, "
            f"{b['FAIL']} Fail; {ws['below_minimum']} readings below the minimum."
        )
    for row in (film or {}).get("boxes_by_layer", []):
        total = row["PASS"] + row["WARNING"] + row["FAIL"] + row["OVER"] + row["NONE"]
        word = LAYER_WORD[row["layer"]]
        if total and row["PASS"] == total:
            out.append(f"{word}: all {total} boxes Pass.")
        elif total:
            out.append(
                f"{word}: {total - row['PASS']} of {total} boxes not Pass ({row['WARNING']} "
                f"{status_word('WARNING', layer=row['layer'])}, {row['FAIL']} Fail, {row['OVER']} Over)."
            )

    both = [r for r in report["comparison"] if r["mean_now"] is not None and r["mean_before"] is not None]
    if report["previous_month"] and both:
        changed = [r for r in both if r["status_now"] != r["status_before"]]
        listed = f" ({'; '.join(_change(r) for r in changed[:3])})" if changed else ""
        out.append(
            f"Compared with {month_words(report['previous_month'])}: "
            f"{len(changed)} boxes changed status{listed}."
        )

    bands = report["bands"]
    medians = [
        (b["all"]["median"], b["band"])
        for b in (bands or {}).get("bands", [])
        if b["band"] in BAND_POINTS_TO and b["all"] is not None
    ]
    if medians:
        median, band = max(medians)
        out.append(
            f"Highest Wave Scan band: {BAND_WORD[band]} (median {_d(median)}); "
            f"it points to {BAND_POINTS_TO[band]}."
        )

    rel = report["relationships"]
    top = rel["strongest"][0] if rel["strongest"] else None
    if top and top["rho"]:
        way = "together" if top["rho"] > 0 else "in opposite directions"
        out.append(
            f"Strongest relationship: {top['a']} and {top['b']} move {way} "
            f"(rho {_d(top['rho'])}, n {top['n']})."
        )
    paired = rel["paired"]
    if paired is not None and paired["cars"] < PAIRED_ENOUGH:
        out.append(
            f"Film and Wave Scan were measured on the same car {paired['cars']} times; "
            f"relationships between them are exploratory."
        )
    return out
