"""Wave Scan <-> Film pairing readiness (AR01). Counts only.

A pair is one car number at one plant that both domains measured: the film
car number (read from ``job_no`` by the plant's rule, D-AR01-1) equals the
Wave Scan ``serial_no`` exactly (D-AR01-2). A pair whose model or colour
disagree is kept and flagged, never dropped. No score, percentage, rate,
status or target (D-AR01-6, D-AR01-7); no grading.
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import Connection

from app.repositories import pairing as repo
from app.services.history import resolve_plant

QUALITY_KINDS = (
    "film_no_car_number",
    "wavescan_serial_not_7_digits",
    "film_colour_code_shared",
    "pair_model_mismatch",
    "pair_colour_mismatch",
    "wavescan_reading_unmapped",
    "film_reading_unmapped",
)
EXAMPLES = 5
_SEVEN_DIGITS = re.compile(r"[0-9]{7}")


def read(conn: Connection, plant_code: str) -> dict:
    plant = resolve_plant(conn, plant_code)["plant_code"]
    rule = repo.car_rule(conn, plant)
    pattern = rule["pattern"] if rule else None
    return assemble(
        plant,
        rule,
        ws_rows=repo.wavescan_cars(conn, plant),
        film_rows=repo.film_jobs(conn, plant, pattern),
        groups=repo.pair_groups(conn, plant),
        ws_groups=repo.wavescan_car_groups(conn, plant),
        film_groups=repo.film_car_groups(conn, plant, pattern),
        ws_unmapped=repo.wavescan_unmapped(conn, plant),
        film_unmapped=repo.film_unmapped(conn, plant),
    )


def _cars(rows: list[dict]) -> dict[str, dict]:
    cars: dict[str, dict] = defaultdict(lambda: {"models": set(), "colors": set(), "dates": set()})
    for r in rows:
        if r["car_no"] is None:
            continue
        car = cars[r["car_no"]]
        car["models"].add(r["model"])
        car["colors"].add(r["color"])
        car["dates"].add(r["measured_date"])
    return cars


def _quality(kind: str, items: list[str], count: int | None = None) -> dict:
    return {"kind": kind, "count": len(items) if count is None else count,
            "examples": items[:EXAMPLES]}


def _shared_colour_codes(film_rows: list[dict]) -> list[str]:
    """D-AR01-10: a job_no first code used with more than one colour. Only
    job_nos the rule reads are in a known format; no other code is guessed."""
    jobs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in film_rows:
        if r["car_no"] is not None:
            jobs[r["job_no"].split("_", 1)[0]][r["color"]].add(r["job_no"])
    shown = []
    for code, colours in sorted(jobs.items()):
        if len(colours) < 2:
            continue
        ranked = sorted(colours.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        (top, top_jobs), rest = ranked[0], ranked[1:]
        parts = [f"{top} ({len(top_jobs)})"] + [f"{c} ({', '.join(sorted(j))})" for c, j in rest]
        shown.append(f"{code}: {', '.join(parts)}")
    return shown


def assemble(
    plant: str,
    rule: dict | None,
    *,
    ws_rows: list[dict],
    film_rows: list[dict],
    groups: list[dict],
    ws_groups: list[tuple[str, str]],
    film_groups: list[tuple[str, str]],
    ws_unmapped: list[tuple[str, int]],
    film_unmapped: list[tuple[str, int]],
) -> dict:
    ws, film = _cars(ws_rows), _cars(film_rows)
    paired = sorted(ws.keys() & film.keys())

    pairs = []
    for car_no in paired:
        w, f = ws[car_no], film[car_no]
        flags = []
        if w["models"] != f["models"]:
            flags.append("model_mismatch")
        if w["colors"] != f["colors"]:
            flags.append("colour_mismatch")
        pairs.append({
            "car_no": car_no,
            "wavescan_model": " / ".join(sorted(w["models"])),
            "film_model": " / ".join(sorted(f["models"])),
            "wavescan_color": " / ".join(sorted(w["colors"])),
            "film_color": " / ".join(sorted(f["colors"])),
            "wavescan_dates": sorted(w["dates"]),
            "film_dates": sorted(f["dates"]),
            "gap_days": min(abs((a - b).days) for a in w["dates"] for b in f["dates"]),
            "flags": flags,
        })

    # A pair counts in a model x colour row when both domains measured it so.
    ws_mc, film_mc = defaultdict(set), defaultdict(set)
    for r in ws_rows:
        ws_mc[(r["model"], r["color"])].add(r["car_no"])
    for r in film_rows:
        film_mc[(r["model"], r["color"])]  # seen even when no car number is read
        if r["car_no"] is not None:
            film_mc[(r["model"], r["color"])].add(r["car_no"])
    by_model_colour = [
        {"model": m, "color": c, "wavescan_cars": len(ws_mc[(m, c)]),
         "film_cars": len(film_mc[(m, c)]), "paired_cars": len(ws_mc[(m, c)] & film_mc[(m, c)])}
        for m, c in sorted(ws_mc.keys() | film_mc.keys())
    ]

    ws_g, film_g = defaultdict(set), defaultdict(set)
    for car_no, group in ws_groups:
        ws_g[group].add(car_no)
    for car_no, group in film_groups:
        film_g[group].add(car_no)
    by_pair_group = [
        {**g, "wavescan_zones": list(g["wavescan_zones"]),
         "paired_cars": len(ws_g[g["pair_group"]] & film_g[g["pair_group"]])}
        for g in groups
    ]

    quality = [
        _quality("film_no_car_number", sorted(
            {r["job_no"] for r in film_rows if r["car_no"] is None and r["job_no"] is not None})),
        _quality("wavescan_serial_not_7_digits",
                 sorted(c for c in ws if not _SEVEN_DIGITS.fullmatch(c))),
        _quality("film_colour_code_shared", _shared_colour_codes(film_rows)),
        _quality("pair_model_mismatch",
                 [p["car_no"] for p in pairs if "model_mismatch" in p["flags"]]),
        _quality("pair_colour_mismatch",
                 [p["car_no"] for p in pairs if "colour_mismatch" in p["flags"]]),
        _quality("wavescan_reading_unmapped", [z for z, _ in ws_unmapped],
                 sum(n for _, n in ws_unmapped)),
        _quality("film_reading_unmapped", [p for p, _ in film_unmapped],
                 sum(n for _, n in film_unmapped)),
    ]
    assert [q["kind"] for q in quality] == list(QUALITY_KINDS)

    return {
        "plant_code": plant,
        "car_rule": rule,
        "wavescan_cars": len(ws),
        "film_cars": len(film),
        "paired_cars": len(paired),
        "by_model_colour": by_model_colour,
        "by_pair_group": by_pair_group,
        "pairs": pairs,
        "quality": quality,
    }
