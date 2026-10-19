r"""T113: retire FTM's duplicate Wave Scan block 33-64. DRY RUN unless --apply.

FTM carries 64 live points on `P703 DBL RANGER` and on `P703 DBL RAPTOR`:
the long-name block 1-32 (every reading lives there) and the short-name
block 33-64 (`01HOOD` .. `32RTFENDE`, note `T58 owner lock 2026-10-05`, no
reading, no map). While a short-named point is live an exact-label match to
it wins (T89), so a future file could store onto the empty block and split
the data. Owner, 2026-10-11: "they have to be 32".

ADR 0005: nothing is deleted. A retire sets `retired_at` + `retired_reason`
once (`repositories.mappings.retire_plant_panels`, the D-86-2 write) and one
`audit_event` per model records it (`catalogue.plant_ws_point.retire`).

**D-113-1, the set.** Exactly the rows where all hold: the plant, the model,
`point_no` in the block, live, the T58 note, **0** `wavescan` rows (any
status) and **0** `ref_plant_zone_map` rows. Anything but exactly 32 per
model -- 64 in all -- is a refusal and nothing is written. A rerun after the
apply finds the 64 already retired with this script's reason and retires 0.

**D-113-2, the proof.** In one transaction: re-plan each committed FTM Wave
Scan load from its stored bytes through the real ingest plan
(`IngestService._plan`, the code a replay runs) and read the panel-match
(`walk_view`) and in-row (`rough_panel_rows`) answers; apply the retire;
read all of it again; compare row by row. Dry run: always ROLLBACK. With
`--apply`: COMMIT only when every row is identical, else ROLLBACK and say
which rows moved.

    cd backend && .venv/Scripts/python.exe scripts/t113_retire_ftm_duplicate_panels.py
    cd backend && .venv/Scripts/python.exe scripts/t113_retire_ftm_duplicate_panels.py --apply
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from sqlalchemy import Connection, create_engine, text  # noqa: E402

from app.repositories import audit  # noqa: E402
from app.repositories import mappings as maps  # noqa: E402

PLANT = "FTM"
MODELS = ("P703 DBL RANGER", "P703 DBL RAPTOR")
NOTE = "T58 owner lock 2026-10-05"
FIRST_POINT, LAST_POINT = 33, 64
PER_MODEL = 32
#: The three committed FTM Wave Scan loads (Jul / Aug / Sep), D-113-2.
LOADS = (120969, 116283, 116284)
REASON = (
    "T113: duplicate short-name block of FTM's 32 Wave Scan panels "
    "(0 readings, 0 maps); the long-name block 1-32 holds every reading. "
    "Owner 2026-10-11."
)
AUDIT_ACTION = "catalogue.plant_ws_point.retire"


class Refused(Exception):
    """The set is not what D-113-1 says it must be. Nothing was written."""


@dataclass(frozen=True)
class Block:
    """Which rows D-113-1 names. Parameters so a test can name its own."""

    plant: str = PLANT
    models: tuple[str, ...] = MODELS
    note: str = NOTE
    first_point: int = FIRST_POINT
    last_point: int = LAST_POINT
    per_model: int = PER_MODEL
    reason: str = REASON


def block_rows(conn: Connection, block: Block, *, lock: bool = False) -> list[dict]:
    """Every point in the block's range, with what D-113-1 tests about it."""
    return [
        dict(row)
        for row in conn.execute(
            text(
                f"""
                SELECT p.model_code, p.point_no, p.zone_code, p.tolerance_group,
                       p.note, p.retired_at, p.retired_reason,
                       (SELECT count(*) FROM wavescan w
                         WHERE w.plant = p.plant_code AND w.model = p.model_code
                           AND w.checkzone = p.zone_code) AS readings,
                       (SELECT count(*) FROM ref_plant_zone_map m
                         WHERE m.plant_code = p.plant_code
                           AND m.model_code = p.model_code
                           AND m.zone_code = p.zone_code) AS maps
                  FROM ref_plant_ws_point p
                 WHERE p.plant_code = :plant AND p.model_code = ANY(:models)
                   AND p.point_no BETWEEN :lo AND :hi
                 ORDER BY p.model_code, p.point_no
                 {"FOR UPDATE OF p" if lock else ""}
                """
            ),
            {
                "plant": block.plant, "models": list(block.models),
                "lo": block.first_point, "hi": block.last_point,
            },
        ).mappings()
    ]


def qualifies(row: dict, block: Block) -> bool:
    return (
        row["note"] == block.note
        and row["readings"] == 0
        and row["maps"] == 0
    )


def select_set(rows: Sequence[dict], block: Block) -> tuple[list[dict], list[dict]]:
    """``(to_retire, already_retired)`` -- or `Refused`, naming why.

    A row already retired by **this** reason counts toward the 64, so a
    rerun after the apply is a no-op rather than a refusal. A row retired
    for any other reason does not.
    """
    todo = [r for r in rows if r["retired_at"] is None and qualifies(r, block)]
    done = [
        r for r in rows
        if r["retired_at"] is not None and r["retired_reason"] == block.reason
        and qualifies(r, block)
    ]
    problems = []
    for model in block.models:
        n = sum(r["model_code"] == model for r in todo + done)
        if n != block.per_model:
            problems.append(f"{model}: {n} qualifying point(s), not {block.per_model}")
    outside = [r for r in rows if r not in todo and r not in done]
    if problems:
        detail = "; ".join(
            f"{r['model_code']} #{r['point_no']} {r['zone_code']} "
            f"(note={r['note']!r}, live={r['retired_at'] is None}, "
            f"readings={r['readings']}, maps={r['maps']})"
            for r in outside
        )
        raise Refused(
            f"D-113-1 refused: {'; '.join(problems)}. Rows in range that do "
            f"not qualify: {detail or 'none -- the block is short'}. "
            f"Nothing was written."
        )
    return todo, done


def retire(
    conn: Connection, block: Block, todo: Sequence[dict]
) -> dict[str, list[str]]:
    """The D-86-2 write, one audit row per model that changed."""
    out: dict[str, list[str]] = {}
    for model in block.models:
        zones = sorted(r["zone_code"] for r in todo if r["model_code"] == model)
        retired = maps.retire_plant_panels(
            conn, plant_code=block.plant, model_code=model,
            zone_codes=zones, reason=block.reason,
        )
        out[model] = sorted(retired)
        if retired:
            audit.record(
                conn,
                action=AUDIT_ACTION,
                entity_type="ref_plant_ws_point",
                entity_id=f"{block.plant}:{model}",
                actor_user_id=None,
                actor_type=audit.ACTOR_SYSTEM,
                before={"live": zones},
                after={
                    "retired": sorted(retired),
                    "retired_reason": block.reason,
                    "decided_by": "owner 2026-10-11 (T113 D-113-1)",
                    "via": "scripts/t113_retire_ftm_duplicate_panels.py",
                },
            )
    return out


# ---------------------------------------------------------------------
# D-113-2: what each committed load reads as, before and after
# ---------------------------------------------------------------------
def _ingest_service():
    from app.core.config import Settings
    from app.services.ingest import IngestService
    from app.services.raw_store import RawStore
    from run_standing_8012 import app_url

    settings = Settings(env="development", app_database_url=app_url())
    return IngestService(settings, RawStore(settings.raw_store_path))


def snapshot(conn: Connection, service, load_ids: Sequence[int]) -> dict:
    """``{load_id: {row key: comparable value}}`` for every row the proof compares.

    Three readings per load, each keyed so before and after line up:

    * ``plan``  -- every source row of the real ingest plan: disposition,
      reason, the panel it would store onto;
    * ``walk``  -- per model, the panel-match read: the set it pre-fills
      from (`confirmed_load_id`) and each label's proposal, pre-fill and
      colour;
    * ``ask``   -- per (model, label), the in-row question: proposal,
      pre-fill, confirmed answer, colour.
    """
    from app.repositories import batches as batch_repo
    from app.repositories import reference as reference_repo
    from app.services.ingest import _projection
    from app.services.panel_match import rough_panel_rows, walk_view

    ref = reference_repo.load_reference_data(conn)
    out: dict[int, dict] = {}
    for load_id in load_ids:
        batch = batch_repo.get_batch(conn, load_id)
        if batch is None:
            raise Refused(f"load {load_id} does not exist; the proof cannot run.")
        plant = batch["plant_code"]
        data = service.store.get(batch["raw_store_key"])
        plan, raw_rows, context = service._plan(conn, batch, data, ref)
        rows: dict[str, object] = {}
        for entry in _projection(plan, raw_rows, context):
            rows[f"plan row {entry['source_row']}"] = (
                entry["disposition"], entry["reason"],
                (entry["canonical"] or {}).get("checkzone"),
            )
        for model in MODELS:
            walk = walk_view(conn, load_id, plant, model)
            if walk is None:
                rows[f"walk {model}"] = None
                continue
            rows[f"walk {model}"] = (
                walk["confirmed_load_id"], walk["fingerprint_moved"],
                walk["yellow_count"], walk["red_count"],
            )
            for row in walk["rows"]:
                rows[f"walk {model} {row['raw_zone_text']}"] = (
                    row["proposed_zone_code"], row["prefilled_zone_code"],
                    row["attention"],
                )
        for row in rough_panel_rows(conn, load_id, plant):
            rows[f"ask {row['model_code']} {row['raw_zone_text']}"] = (
                row["proposed_zone_code"], row["prefilled_zone_code"],
                row["confirmed_zone_code"], row["attention"],
            )
        out[load_id] = rows
    return out


def compare(before: dict, after: dict) -> dict[int, dict]:
    """Per load: rows compared, identical, and each difference."""
    result: dict[int, dict] = {}
    for load_id, rows in before.items():
        other = after[load_id]
        keys = sorted(set(rows) | set(other))
        diffs = [
            (key, rows.get(key, "<absent>"), other.get(key, "<absent>"))
            for key in keys if rows.get(key, "<absent>") != other.get(key, "<absent>")
        ]
        result[load_id] = {
            "compared": len(keys), "identical": len(keys) - len(diffs),
            "different": diffs,
        }
    return result


def _identity_finding_3(conn: Connection, plant: str) -> int:
    """`audit_panel_identities` check 3 on this connection (sees the retire)."""
    import audit_panel_identities as identities

    class _Same:
        def connect(self):
            return contextlib.nullcontext(conn)

    return len(identities.two_live_blocks(_Same(), plant))


@dataclass
class Outcome:
    to_retire: list[dict]
    already: list[dict]
    retired: dict[str, list[str]]
    proof: dict[int, dict]
    finding_3: tuple[int, int] | None
    committed: bool

    @property
    def identical(self) -> bool:
        return all(not p["different"] for p in self.proof.values())


def run(
    conn: Connection,
    *,
    block: Block = Block(),
    load_ids: Sequence[int] = LOADS,
    apply: bool = False,
    service=None,
) -> Outcome:
    """One transaction: check the set, prove, retire; commit only on apply.

    ``conn`` must not be inside a transaction; this opens and ends it.
    """
    trans = conn.begin()
    try:
        rows = block_rows(conn, block, lock=apply)
        todo, done = select_set(rows, block)
        if load_ids and service is None:
            service = _ingest_service()
        before = snapshot(conn, service, load_ids)
        f3_before = _identity_finding_3(conn, block.plant)
        retired = retire(conn, block, todo)
        after = snapshot(conn, service, load_ids)
        f3_after = _identity_finding_3(conn, block.plant)
        outcome = Outcome(
            to_retire=todo, already=done, retired=retired,
            proof=compare(before, after), finding_3=(f3_before, f3_after),
            committed=False,
        )
        if apply and outcome.identical:
            trans.commit()
            outcome.committed = True
        else:
            trans.rollback()
        return outcome
    except BaseException:
        if trans.is_active:
            trans.rollback()
        raise


def _print(outcome: Outcome, apply: bool) -> None:
    rows = outcome.to_retire + outcome.already
    print(f"T113 FTM Wave Scan duplicate block -- {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 78)
    print(f"{'model':<17}{'#':>3}  {'zone_code':<11}{'tol':<11}{'readings':>8}{'maps':>5}  state")
    for r in sorted(rows, key=lambda r: (r["model_code"], r["point_no"])):
        state = "live -> retire" if r in outcome.to_retire else "already retired (T113)"
        print(f"{r['model_code']:<17}{r['point_no']:>3}  {r['zone_code']:<11}"
              f"{r['tolerance_group']:<11}{r['readings']:>8}{r['maps']:>5}  {state}")
    print(f"\n{len(outcome.to_retire)} to retire, {len(outcome.already)} already retired")
    print("\nD-113-2 proof (retire applied inside the transaction):")
    print(f"{'load':>8}{'compared':>10}{'identical':>11}{'different':>11}")
    for load_id, p in outcome.proof.items():
        print(f"{load_id:>8}{p['compared']:>10}{p['identical']:>11}{len(p['different']):>11}")
        for key, was, now in p["different"]:
            print(f"      {key}: {was!r} -> {now!r}")
    if outcome.finding_3:
        print(f"\naudit_panel_identities finding 3 at {PLANT}: "
              f"{outcome.finding_3[0]} now, {outcome.finding_3[1]} after the retire")
    print("\nretired in this transaction: "
          + json.dumps({m: len(z) for m, z in outcome.retired.items()}))
    if outcome.committed:
        print("COMMITTED.")
    elif apply:
        print("ROLLED BACK: the proof found a difference. Nothing was written.")
    else:
        print("ROLLED BACK (dry run). Nothing was written.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="commit the retire when the proof is identical")
    args = parser.parse_args(argv)

    from run_standing_8012 import app_url

    engine = create_engine(app_url())
    try:
        with engine.connect() as conn:
            outcome = run(conn, apply=args.apply)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    _print(outcome, args.apply)
    return 0 if outcome.identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
