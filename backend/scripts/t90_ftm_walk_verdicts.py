r"""T90: run the structural rules against the three real FTM CF files. READ-ONLY.

The task asks for the rules' verdicts on all three months, so this walks
them the way T75 walked SAP's `.ods` and T89 walked FTM's FilmBuild: open
each workbook in place, read it with the code an upload reads it with, and
**write nothing**. Every statement runs inside one ``READ ONLY``
transaction and the row counts of every table the app could touch are
compared before and after.

What it prints, per file and per ``(plant, model)``:

* the group fingerprint (D-90-4) against the model's canonical one;
* the group multiset, file against canonical -- which is the test that
  chooses between the rules (D-90-1);
* whether the walk order could be verified, and in whose words (D-90-7);
* each rule's availability and its reason;
* the 32 pairs, each with its rule, its rough/specific class (D-90-3), its
  colour and whether a side hint was cross-checked (D-90-8, D-90-12).

September is read from the raw store by its batch's ``file_hash``, because
that is where the owner's own upload lives; July and August from
``Data/FTM/CF``. Nothing here applies a pair, writes a proposal, or reads a
confirmed walk: it is the rules against the files and nothing else.

    cd backend && .venv/Scripts/python.exe scripts/t90_ftm_walk_verdicts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.domain.cleaner import Cleaner  # noqa: E402
from app.domain.panel_walk import (  # noqa: E402
    CanonicalPoint,
    WalkRow,
    fingerprint_initials,
    group_counts,
    canonical_fingerprint,
    match_walk,
)
from app.domain.reader import read_sheet, sheet_names  # noqa: E402
from app.domain.ws_plant_gold import gold_key  # noqa: E402
from app.repositories import mappings as maps  # noqa: E402
from app.repositories import reference as reference_repo  # noqa: E402
from run_standing_8012 import app_url  # noqa: E402

PLANT = "FTM"
CF_DIR = Path(r"C:\Users\Salmon\Desktop\Internship\Data\FTM\CF")
RAW_DIR = BACKEND_ROOT.parent / "data" / "raw"
OUT = BACKEND_ROOT.parent / "docs" / "reports" / "evidence" / "T90" / "ftm-walk-verdicts.json"
COUNTED = (
    "load_batch", "stg_raw", "stg_review_row", "wavescan", "filmthickness",
    "audit_event", "proposed_mapping", "ref_plant_zone_map",
    "ref_plant_ws_point",
)


def counts(conn) -> dict[str, int]:
    return {
        table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in COUNTED
    }


def september_bytes(conn) -> tuple[str, bytes] | None:
    """The owner's own September upload, from the raw store."""
    row = conn.execute(
        text(
            "SELECT source_file, file_hash FROM load_batch "
            " WHERE plant_code = :p AND source_file ILIKE '%Sep%CF data FTM%' "
            " ORDER BY load_id DESC LIMIT 1"
        ),
        {"p": PLANT},
    ).mappings().first()
    if row is None:
        return None
    path = RAW_DIR / row["file_hash"]
    if not path.exists():
        return None
    return row["source_file"], path.read_bytes()


def canonical_points(conn, model_code: str) -> list[CanonicalPoint]:
    """The model's canonical walk: every live panel on its own catalogue."""
    catalogue = maps.expected_zone_codes(conn, model_code)
    return sorted(
        (
            CanonicalPoint(zone_code=row["zone_code"], point_no=int(row["point_no"]))
            for row in maps.live_plant_panels(conn, PLANT, model_code)
            if row["zone_code"] in catalogue
        ),
        key=lambda point: point.point_no,
    )


def walk_rows_of(conn, source: bytes, sheet: str, source_file: str) -> dict[str, list[WalkRow]]:
    """The file's rows per resolved model, in the order the file wrote them."""
    ref = reference_repo.load_reference_data(conn)
    per_model: dict[str, list[WalkRow]] = {}
    resolved: dict[str, str | None] = {}
    for index, raw in enumerate(
        read_sheet(source, sheet, ref.column_alias, source_file), start=2
    ):
        zone = (raw.text("checkzone") or "").strip()
        raw_model = (raw.text("model") or "").strip()
        if not zone or not raw_model:
            continue
        if raw_model not in resolved:
            resolved[raw_model] = Cleaner.plant_first(
                ref.model_by_plant, ref.model, PLANT, raw_model
            )
        model = resolved[raw_model]
        if not model:
            continue
        per_model.setdefault(model, []).append(
            WalkRow(
                source_row=index,
                raw_zone_text=zone,
                vehicle="|".join(
                    (
                        str(raw.get("date") or ""),
                        str(raw.text("color") or ""),
                        str(raw.text("serial_no") or ""),
                    )
                ),
            )
        )
    return per_model


def describe(conn, source_file, sheet, model, rows, points, slice_name) -> dict:
    """Print and collect one walk's verdicts."""
    match = match_walk(rows, points)
    file_counts = group_counts(match.fingerprint)
    canon_counts = group_counts(canonical_fingerprint(points))
    print("")
    print(f"  --- [{sheet}] {model}{slice_name}: {len(rows)} rows, "
          f"{len(match.labels)} distinct names")
    print(f"      file fingerprint      {fingerprint_initials(match.fingerprint)}")
    print(f"      canonical fingerprint "
          f"{fingerprint_initials(match.canonical_fingerprint)}")
    print("      groups  " + "  ".join(
        f"{group} {file_counts.get(group, 0)}/{canon_counts.get(group, 0)}"
        for group in sorted(set(file_counts) | set(canon_counts))
    ))
    print(f"      multiset equal: {match.multiset_matches}")
    print(f"      walk order:     {match.walk_order_verified} -- "
          f"{match.walk_order_reason}")
    print(f"      rule (a):       {match.rule_a.available} -- {match.rule_a.reason}")
    print(f"      rule (b):       {match.rule_b.available} -- {match.rule_b.reason}")
    if match.disagreements:
        print(f"      DISAGREE on:    {', '.join(match.disagreements)}")
    rough = sum(1 for v in match.verdicts if v.specificity == "rough")
    print(f"      rough/specific: {rough} rough, {len(match.verdicts) - rough} specific")
    print(f"      verdicts:       {len(match.yellow)} yellow, {len(match.red)} red")
    for verdict in match.verdicts:
        print(
            f"        {verdict.raw_zone_text:<12} -> "
            f"{str(verdict.proposed_zone_code):<11} "
            f"{verdict.rule:<14} {verdict.specificity:<9} "
            f"{verdict.attention:<7} "
            f"side={verdict.side or '-'} checked={verdict.side_hint_checked}"
        )
    return {
        "source_file": source_file,
        "sheet": sheet,
        "model_code": model,
        "slice": slice_name.strip(" ()") or "whole sheet",
        "rows": len(rows),
        "names": len(match.labels),
        "fingerprint": fingerprint_initials(match.fingerprint),
        "canonical_fingerprint": fingerprint_initials(match.canonical_fingerprint),
        "group_counts": {
            group: [file_counts.get(group, 0), canon_counts.get(group, 0)]
            for group in sorted(set(file_counts) | set(canon_counts))
        },
        "multiset_matches": match.multiset_matches,
        "walk_order_verified": match.walk_order_verified,
        "walk_order_reason": match.walk_order_reason,
        "rule_group_ordinal": [match.rule_a.available, match.rule_a.reason],
        "rule_walk_number": [match.rule_b.available, match.rule_b.reason],
        "disagreements": list(match.disagreements),
        "rough": rough,
        "specific": len(match.verdicts) - rough,
        "yellow": len(match.yellow),
        "red": len(match.red),
        "pairs": [
            {
                "raw_zone_text": verdict.raw_zone_text,
                "proposed_zone_code": verdict.proposed_zone_code,
                "rule": verdict.rule,
                "specificity": verdict.specificity,
                "attention": verdict.attention,
                "side": verdict.side,
                "side_hint_checked": verdict.side_hint_checked,
                "rule_group_ordinal_zone_code": verdict.rule_a_zone_code,
                "rule_walk_number_zone_code": verdict.rule_b_zone_code,
            }
            for verdict in match.verdicts
        ],
    }


def report(conn, source_file: str, source: bytes) -> list[dict]:
    out: list[dict] = []
    for sheet in sheet_names(source):
        try:
            per_model = walk_rows_of(conn, source, sheet, source_file)
        except Exception as exc:  # a tab this domain cannot read is not a finding
            print(f"  [{sheet}] not a WaveScan sheet: {type(exc).__name__}")
            continue
        for model, rows in sorted(per_model.items()):
            points = canonical_points(conn, model)
            if not points:
                print(f"  [{sheet}] {model}: no canonical list at {PLANT}")
                continue
            out.append(
                describe(conn, source_file, sheet, model, rows, points, "")
            )
            # T90: the August sheet writes BOTH naming blocks on one tab --
            # the long-form names that ARE the model catalogue and the T58
            # numbered block that is not. That is the 64-identity collision
            # T88's audit found, and on the whole sheet it is 64 names for
            # 32 positions, so no structural rule can apply and all 64 rows
            # are red. The numbered block ALONE is what the task's table and
            # D-90-10 describe, so it is reported separately.
            #
            # The split is a fact in the database, not a guess about the
            # file: the numbered block is exactly the live panels of this
            # plant x model that are NOT on the model's own catalogue (T58
            # points 33..64), matched on `gold_key` the way the cleaner
            # matches the gold list.
            numbered_gold = {
                gold_key(row["zone_code"])
                for row in maps.live_plant_panels(conn, PLANT, model)
                if row["zone_code"] not in {p.zone_code for p in points}
            }
            numbered = [
                row for row in rows if gold_key(row.raw_zone_text) in numbered_gold
            ]
            distinct_numbered = {gold_key(r.raw_zone_text) for r in numbered}
            distinct_all = {gold_key(r.raw_zone_text) for r in rows}
            # Only when those names are themselves a COMPLETE walk of this
            # model's size, so the slice is a second block and not a handful
            # of leftovers.
            if (
                numbered
                and len(distinct_numbered) == len(points)
                and len(distinct_numbered) < len(distinct_all)
            ):
                out.append(
                    describe(
                        conn, source_file, sheet, model, numbered, points,
                        " (the numbered block alone)",
                    )
                )
    return out


def main() -> int:
    engine = create_engine(app_url(), future=True)
    findings: list[dict] = []
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        before = counts(conn)

        files: list[tuple[str, bytes]] = []
        september = september_bytes(conn)
        for name in sorted(p.name for p in CF_DIR.glob("*.xlsx")):
            if "Jul" in name or "Aug" in name:
                files.append((name, (CF_DIR / name).read_bytes()))
        if september is not None:
            files.append(september)
        else:
            print("NOTE: no September batch in load_batch, or its raw bytes "
                  "are gone -- September is reported from the live batch's "
                  "projection by the test suite instead.")

        for source_file, source in files:
            print(f"\n=== {source_file}")
            findings.extend(report(conn, source_file, source))

        after = counts(conn)
        conn.rollback()

    print("\n=== no-write proof")
    for table in COUNTED:
        print(f"  {table:<22} {before[table]} -> {after[table]}")
    print(f"  identical: {before == after}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"no_write_proof": before == after, "counts": before, "walks": findings},
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nevidence: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
