r"""T88 Part 4: find duplicate panel identities, at every plant. READ-ONLY.

August's defect (T87 Part C) was found by hand, after it had already been
committed: `load_id 43601` stores 32 physical panels under 64 `checkzone`
values, because FTM changed naming convention mid-month and both blocks are
live. Nothing warned, and nothing would have warned at the next plant
either. This script is the thing that looks.

Three checks, over **every plant, model and batch**:

1. **one walk position, two names** -- a batch where one `src_zone_no`
   carries more than one `checkzone`. That is August exactly: `RRHOOD` and
   `01HOOD` at position 1;
2. **a batch walking more panels than its model has live** -- the shape of a
   file that mixes two naming blocks;
3. **two live naming blocks** -- a plant x model whose live panel list
   splits into two groups with the *same* tolerance pattern, which is what
   makes (1) possible in the first place.

**T89 (D-89-10)** adds a fifth listing: every global `ref_checkzone_alias`
row whose target is live gold at more than one plant. It is not a finding
-- the rows are gated and the app never writes that table -- it is the
shared layer made visible instead of assumed.

It also lists every **exhaustion-derived** learned pair (G-88-6): a pair
proposed by "nothing else was left" is the one that can be confidently
wrong, and the whole point of recording the signal is being able to find
them all again.

**It asserts nothing about which name is right.** That is the owner's to
say (T87 D-87-10 / D-87-13); this only says where to look. Read-only: the
only statements are SELECTs, and a test greps the source for that.

    cd backend && .venv/Scripts/python.exe scripts/audit_panel_identities.py
    cd backend && .venv/Scripts/python.exe scripts/audit_panel_identities.py --plant FTM
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine, make_url  # noqa: E402

from run_standing_8012 import keyword_dsn_to_url, load_env_test  # noqa: E402

#: `ref_plant_zone_map.proposal_method` of a pair T88's screen learned.
#: The suffix names the signal that proposed it, so an exhaustion-derived
#: mapping can be listed again (G-88-6).
T88_METHOD_PREFIX = "T88_PANEL_MATCH"


def one_position_two_names(engine: Engine, plant: str | None) -> list[dict]:
    """A batch where one walk position carries more than one panel name."""
    where = "AND w.plant = :plant" if plant else ""
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    f"""
                    SELECT w.plant, w.model, w.load_id, b.source_file,
                           w.src_zone_no,
                           count(DISTINCT w.checkzone) AS names,
                           string_agg(DISTINCT w.checkzone, ' + '
                                      ORDER BY w.checkzone) AS which,
                           min(w.measured_date) AS first_day,
                           max(w.measured_date) AS last_day,
                           count(*) AS rows
                      FROM wavescan w
                      JOIN load_batch b ON b.load_id = w.load_id
                     WHERE w.src_zone_no IS NOT NULL
                       AND w.corrects_measurement_id IS NULL
                       AND w.is_superseded = false
                       {where}
                     GROUP BY 1, 2, 3, 4, 5
                    HAVING count(DISTINCT w.checkzone) > 1
                     ORDER BY 1, 2, 3, 5
                    """
                ),
                {"plant": plant} if plant else {},
            )
            .mappings()
            .all()
        ]


def batch_wider_than_catalogue(engine: Engine, plant: str | None) -> list[dict]:
    """A batch walking more distinct panels than its model has live."""
    where = "AND w.plant = :plant" if plant else ""
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    f"""
                    SELECT w.plant, w.model, w.load_id, b.source_file,
                           count(DISTINCT w.checkzone) AS walked,
                           (SELECT count(*) FROM ref_plant_ws_point p
                             WHERE p.plant_code = w.plant
                               AND p.model_code = w.model
                               AND p.retired_at IS NULL) AS live
                      FROM wavescan w
                      JOIN load_batch b ON b.load_id = w.load_id
                     WHERE w.corrects_measurement_id IS NULL
                       AND w.is_superseded = false
                       {where}
                     GROUP BY 1, 2, 3, 4
                    HAVING count(DISTINCT w.checkzone) >
                           (SELECT count(*) FROM ref_plant_ws_point p
                             WHERE p.plant_code = w.plant
                               AND p.model_code = w.model
                               AND p.retired_at IS NULL)
                     ORDER BY 1, 2, 3
                    """
                ),
                {"plant": plant} if plant else {},
            )
            .mappings()
            .all()
        ]


def two_live_blocks(engine: Engine, plant: str | None) -> list[dict]:
    """A plant x model whose live list is two blocks of equal size.

    The signal is a live count that is exactly twice the model's own
    `ref_model_zone` catalogue: FTM carries 64 live panels for a 32-position
    model, which is the catalogue holding each physical panel twice. That is
    what lets one file write two names for one position and have both
    accepted.
    """
    where = "AND p.plant_code = :plant" if plant else ""
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    f"""
                    SELECT p.plant_code AS plant, p.model_code AS model,
                           count(*) AS live,
                           (SELECT count(*) FROM ref_model_zone z
                             WHERE z.model_code = p.model_code) AS catalogue,
                           count(*) FILTER (WHERE p.tolerance_group = 'Horizontal')
                               AS horizontal,
                           count(*) FILTER (WHERE p.tolerance_group = 'Vertical')
                               AS vertical
                      FROM ref_plant_ws_point p
                     WHERE p.retired_at IS NULL
                       {where}
                     GROUP BY 1, 2
                    HAVING count(*) > (SELECT count(*) FROM ref_model_zone z
                                        WHERE z.model_code = p.model_code)
                     ORDER BY 1, 2
                    """
                ),
                {"plant": plant} if plant else {},
            )
            .mappings()
            .all()
        ]


def learned_pairs(engine: Engine, plant: str | None) -> list[dict]:
    """Every pair T88's screen learned, with the signal that proposed it.

    G-88-6: an exhaustion-derived pair is the one that can be confidently
    wrong, so it has to be findable again -- by anyone, at any plant, after
    the fact.
    """
    where = "AND m.plant_code = :plant" if plant else ""
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    f"""
                    SELECT m.plant_code AS plant, m.model_code AS model,
                           m.raw_zone_text, m.zone_code, m.proposal_method,
                           m.approved_by, m.approved_at, m.note
                      FROM ref_plant_zone_map m
                     WHERE m.proposal_method LIKE :prefix
                       {where}
                     ORDER BY m.proposal_method, 1, 2, 3
                    """
                ),
                {"prefix": f"{T88_METHOD_PREFIX}%", **({"plant": plant} if plant else {})},
            )
            .mappings()
            .all()
        ]


def shared_global_aliases(engine: Engine, plant: str | None) -> list[dict]:
    """Every global `ref_checkzone_alias` row reaching more than one plant.

    **T89 (D-89-10).** Plant separation is a property of the learning
    table: `ref_plant_zone_map` is keyed `(plant_code, model_code,
    raw_zone_text)`, so a pair taught at FTM can never fire at AAT, and the
    application **never writes** the global table -- `ALIAS_TABLE_BY_KIND`
    has no entry for it and T89 does not add one.

    The 83 pre-existing global rows have no plant column, though, and at
    least one of them (`06LFFENDER -> LFFENDER`) has a target that is live
    gold at several plants. It is gated -- `cleaner.resolve_checkzone` only
    honours a global alias whose target is gold **here** -- so it can never
    pull another plant's panel in. But the text-to-code mapping is shared,
    and a shared layer should be visible rather than assumed, so this lists
    every row whose target is gold at more than one plant and says where.

    `--plant` narrows the listing to rows that reach that plant; the
    `plants` column still names every plant the row reaches, because
    "shared" is the whole point of the finding.
    """
    having = (
        "HAVING count(DISTINCT p.plant_code) > 1"
        + (
            " AND bool_or(p.plant_code = :plant)"
            if plant
            else ""
        )
    )
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    f"""
                    SELECT a.raw_value, a.zone_code,
                           count(DISTINCT p.plant_code) AS plants,
                           string_agg(DISTINCT p.plant_code, ', '
                                      ORDER BY p.plant_code) AS which_plants,
                           count(*) AS plant_models
                      FROM ref_checkzone_alias a
                      JOIN ref_plant_ws_point p
                        ON p.zone_code = a.zone_code
                       AND p.retired_at IS NULL
                     GROUP BY 1, 2
                     {having}
                     ORDER BY 3 DESC, 1
                    """
                ),
                {"plant": plant} if plant else {},
            )
            .mappings()
            .all()
        ]


def _table(rows: list[dict], columns: list[str]) -> None:
    if not rows:
        print("  none")
        return
    widths = {
        c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in columns
    }
    print("  " + "  ".join(c.ljust(widths[c]) for c in columns))
    print("  " + "  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  " + "  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def audit(engine: Engine, plant: str | None) -> int:
    """Print every finding. Returns the number of findings, 0 when clean."""
    print("T88 panel identity audit -- read-only")
    print("=" * 72)
    print(f"  scope            {plant or 'every plant'}")
    print()

    positions = one_position_two_names(engine, plant)
    print(f"1. ONE WALK POSITION, TWO PANEL NAMES  ({len(positions)})")
    print("   The August shape: one physical point stored under two names, so")
    print("   every per-panel view shows it twice with half its readings.")
    _table(
        positions,
        ["plant", "model", "load_id", "source_file", "src_zone_no", "which",
         "first_day", "last_day", "rows"],
    )
    print()

    wide = batch_wider_than_catalogue(engine, plant)
    print(f"2. A BATCH WALKING MORE PANELS THAN ITS MODEL HAS LIVE  ({len(wide)})")
    _table(wide, ["plant", "model", "load_id", "source_file", "walked", "live"])
    print()

    blocks = two_live_blocks(engine, plant)
    print(f"3. A LIVE PANEL LIST WIDER THAN ITS MODEL CATALOGUE  ({len(blocks)})")
    print("   What makes check 1 possible: the catalogue carrying one physical")
    print("   panel under two live names.")
    _table(blocks, ["plant", "model", "live", "catalogue", "horizontal", "vertical"])
    print()

    learned = learned_pairs(engine, plant)
    by_exhaustion = [
        row for row in learned
        if str(row["proposal_method"]).endswith("EXHAUSTION")
    ]
    print(f"4. PAIRS LEARNED BY THE MATCH SCREEN  ({len(learned)}, "
          f"{len(by_exhaustion)} by exhaustion)")
    print("   G-88-6: exhaustion is the signal that can be confidently wrong,")
    print("   so every pair records which signal proposed it.")
    _table(
        learned,
        ["plant", "model", "raw_zone_text", "zone_code", "proposal_method",
         "approved_at"],
    )
    print()

    shared = shared_global_aliases(engine, plant)
    print(f"5. GLOBAL ALIASES WHOSE TARGET IS GOLD AT MORE THAN ONE PLANT  "
          f"({len(shared)})")
    print("   D-89-10: the app never writes ref_checkzone_alias and T89 does")
    print("   not start. These pre-existing rows have no plant column, so the")
    print("   shared text->code layer is listed rather than assumed. Each is")
    print("   still gated by \"only if the target is gold here\".")
    _table(
        shared,
        ["raw_value", "zone_code", "plants", "which_plants", "plant_models"],
    )
    print()

    findings = len(positions) + len(wide) + len(blocks)
    print("=" * 72)
    if findings:
        print(f"{findings} finding(s). This script says WHERE to look and nothing")
        print("about which name is right -- that is the owner's to say.")
    else:
        print("No duplicate panel identities found in scope.")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T88: audit panel identities (read-only)")
    parser.add_argument("--plant", default=None, help="one plant, or every plant")
    args = parser.parse_args(argv)

    load_env_test()
    dsn = os.environ.get("T01_ADMIN_DSN", "").strip()
    if not dsn:
        print("T01_ADMIN_DSN is not set (backend/.env.test)", file=sys.stderr)
        return 2
    engine = create_engine(make_url(keyword_dsn_to_url(dsn)))
    try:
        audit(engine, args.plant)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
