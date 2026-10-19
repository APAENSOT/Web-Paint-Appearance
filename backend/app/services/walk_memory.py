"""T107: the walk memory, read from **both** kinds of confirmation.

T90 built the pre-fill on `ZONE` panel-match proposals: the match screen's
Confirm writes one, carrying the walk it was confirmed under, and the next
file with the same fingerprint arrives filled in. T94 then put the same
question *in the row* of the review screen, and that one-click answer
writes a ``PANEL_CONFIRM`` `worksheet_decision` and no proposal at all
(D-94-3, D-94-6).

T98 section 1 measured what that costs. After three real FTM months were
worked end to end through the review screen -- 140 in-row confirms across
July, August and September -- ``confirmed_walk_sets(FTM, P703 DBL RAPTOR)``
and the Ranger's still returned **0**, so October would have arrived red
again and the owner would have answered the same walk a fourth time.
D-90-5's promise was being kept only on the path the owner does not use.

So the memory reads both, in one place, with the same shape (D-107-1):

* the ``ZONE`` proposals, which carry their own ``walk.fingerprint``
  (`repositories.mappings.confirmed_walk_sets`, unchanged);
* the ``PANEL_CONFIRM`` decisions of **committed, not superseded** sheets
  of the same ``(plant, model)`` (`repositories.worksheet
  .committed_panel_confirms`, D-107-4), each one carrying the fingerprint of
  **that batch's own walk**, computed here from that batch's stored rows by
  the same `domain.panel_walk` functions the live match uses. A remembered
  set whose fingerprint was computed any other way would be a pre-fill under
  a walk nobody confirmed.

Newest first, by the time the answer was confirmed (D-107-3), so one `[0]`
is the latest confirmed set whichever path wrote it and
`services/panel_match` needs no new branch.

**Pre-fill only, and only the pre-fill read (D-107-2).** The write
boundary's refusal path -- `services/mapping._prior_walk_targets`, which
asks whether this plant has already confirmed a spelling as a *different*
panel before letting it become a permanent `ref_plant_zone_map` alias
(D-91-2) -- still reads `repositories.mappings.confirmed_walk_sets` alone,
deliberately. Widening it was measured and is a real change to what the
match screen may write: with the owner's September in-row confirms visible
to it, ``07LFFENDER -> LFFENDER`` is refused 422 because September
confirmed that spelling as ``LCFENDER``, and two T86 tests that expect 201
turn red. That refusal may well be right, and it is a decision about
writing aliases rather than about pre-filling a walk, so T107 does not
make it. It is reported instead (T107 report section 5).

**This changes nothing about what resolves.** Both halves are batch data
(D-90-11): `domain/cleaner.py` resolves a panel from `ReferenceData` alone,
`load_reference_data` builds that from ``ref_*`` tables alone, and neither
can reach a `proposed_mapping` row, a `load_batch` or a
`worksheet_decision`. Nothing here writes anything. A rough label is still
confirmed for one upload and never learned forever, and the tests that
assert that structurally are untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import Connection

from app.domain.cleaner import Cleaner
from app.domain.panel_walk import WalkRow, fingerprint_text, read_walk
from app.domain.panel_walk import fingerprint as walk_fingerprint
from app.repositories import batches as batch_repo
from app.repositories import mappings as maps
from app.repositories import reference as reference_repo
from app.repositories import worksheet as worksheet_repo

#: Sorting key for a set whose confirmation time was never recorded: it is
#: older than anything that has one, rather than newest by accident.
_FOREVER_AGO = datetime.min.replace(tzinfo=timezone.utc)


def walk_rows_for_model(
    conn: Connection, load_id: int, plant: str, model_code: str
) -> list[WalkRow]:
    """This model's rows of one sheet, in file order, with their vehicle.

    Split by **resolved** model through the same plant-first alias maps the
    cleaner uses, because one sheet carries two models and they are two
    different walks (D-90-1). A row whose Model cell resolves to nothing
    belongs to no walk and is left out rather than attached to one.

    T107 moved this out of `services/panel_match` so the memory can read a
    remembered batch's walk with the same function the live match reads this
    batch's walk with, rather than a second copy of it.
    """
    ref = reference_repo.load_reference_data(conn)
    resolved_by_raw: dict[str, str | None] = {}
    out: list[WalkRow] = []
    for row in batch_repo.walk_rows(conn, load_id):
        raw_model = row["raw_model"]
        if raw_model not in resolved_by_raw:
            resolved_by_raw[raw_model] = Cleaner.plant_first(
                ref.model_by_plant, ref.model, plant, raw_model
            )
        if resolved_by_raw[raw_model] != model_code:
            continue
        if not row["raw_zone_text"]:
            continue
        out.append(
            WalkRow(
                source_row=int(row["source_row"]),
                raw_zone_text=row["raw_zone_text"],
                # RO16 (D-RO16-5): the car of a many-car blank-serial sheet
                # joins it, so two cars are two blocks. Absent, it is today's.
                vehicle="|".join(
                    (row["raw_date"], row["raw_color"], row["raw_serial"])
                    + ((row["car_key"],) if row.get("car_key") else ())
                ),
            )
        )
    return out


def walk_fingerprint_of(rows: Sequence[WalkRow]) -> str:
    """The stored fingerprint of the walk these rows write.

    One definition, used for both sides of the comparison: the fingerprint a
    remembered batch is filed under (T107) and the fingerprint the sheet
    being reviewed is matched by (T107-FIX).
    """
    return fingerprint_text(walk_fingerprint(read_walk(rows)))


def prefill_set(sets: Sequence[dict], rows: Sequence[WalkRow]) -> dict | None:
    """T107-FIX (D-107F-1): the newest remembered set that walks **this** walk.

    `sets` arrives newest first, so the first fingerprint match is the most
    recent month that walked what this sheet walks. None when no remembered
    set matches, which is a red answer and not a weaker pre-fill: the caller
    then keeps the newest set overall, whose fingerprint differs, so
    `match_walk` reports the walk as moved and the screen says since when
    (D-107F-2). D-91-1 is unharmed -- a walk that differs by one label
    matches nothing here, so August's `13LFRDOOR` still cannot carry into
    September.
    """
    fingerprint = walk_fingerprint_of(rows)
    return next(
        (item for item in sets if item.get("fingerprint") == fingerprint), None
    )


def _row_confirm_sets(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    fingerprint: str | None,
    exclude_load_id: int | None,
) -> list[dict]:
    """T107: one remembered set per committed sheet that answered in the row.

    The subject carries the model (`repositories.worksheet.panel_pair`), and
    a subject written without one applies to any model of its sheet, which
    is what it meant when it was written (D-94-1). The fingerprint is that
    sheet's own walk for **this** model: a sheet carrying two models holds
    two walks and two fingerprints, and this answer belongs to one of them.
    """
    per_batch: dict[int, dict] = {}
    for row in worksheet_repo.committed_panel_confirms(
        conn, plant_code=plant_code, exclude_load_id=exclude_load_id
    ):
        pair = worksheet_repo.panel_pair(row["subject"])
        if pair is None:
            continue
        model, raw, zone = pair
        if model is not None and model != model_code:
            continue
        load_id = int(row["load_id"])
        batch = per_batch.setdefault(load_id, {"row": row, "pairs": {}})
        # Append-only table read in decision order: the last answer stands.
        batch["pairs"][raw] = zone

    out: list[dict] = []
    for load_id, batch in per_batch.items():
        if not batch["pairs"]:
            continue
        labels = read_walk(
            walk_rows_for_model(conn, load_id, plant_code, model_code)
        )
        if not labels:
            # The sheet's rows are gone or this model never walked it, so
            # there is no fingerprint to remember the answer under. Saying
            # nothing is the honest answer; guessing one would pre-fill a
            # walk nobody confirmed.
            continue
        walk = fingerprint_text(walk_fingerprint(labels))
        if fingerprint is not None and walk != fingerprint:
            continue
        row = batch["row"]
        out.append({
            "proposal_id": None,
            "load_id": load_id,
            "source_file": row["source_file"],
            "source_sheet": row["source_sheet"],
            "status": row["status"],
            "confirmed_at": row["committed_at"],
            "fingerprint": walk,
            "pairs": dict(batch["pairs"]),
            # Every pair here was a question the review screen put *in the
            # row*, and it only asks about a label its rough test holds, so
            # the asked set is the whole set. `classify_specificity` alone
            # would under-report it: T96 (D-96-1) also asks about a label
            # that leads with a number and names no canonical panel, which
            # is what July's `14 LFBoox` is and what its core-sharing test
            # calls specific.
            "rough": sorted(batch["pairs"]),
            "kind": worksheet_repo.KIND_PANEL_CONFIRM,
        })
    return out


def confirmed_walk_sets(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    fingerprint: str | None = None,
    exclude_load_id: int | None = None,
) -> list[dict]:
    """Every confirmed walk of one ``(plant, model)``, newest first.

    The same signature and the same shape `repositories.mappings
    .confirmed_walk_sets` has, with the in-row confirms of committed sheets
    merged in (D-107-1). `fingerprint` of None asks for the most recent
    confirmed walk **whatever** its fingerprint, which is how "the walk has
    changed since the last confirmed set" is detected at all (D-90-6).
    """
    sets = list(
        maps.confirmed_walk_sets(
            conn,
            plant_code=plant_code,
            model_code=model_code,
            fingerprint=fingerprint,
            exclude_load_id=exclude_load_id,
        )
    )
    sets.extend(
        _row_confirm_sets(
            conn,
            plant_code=plant_code,
            model_code=model_code,
            fingerprint=fingerprint,
            exclude_load_id=exclude_load_id,
        )
    )
    sets.sort(key=lambda item: item.get("confirmed_at") or _FOREVER_AGO, reverse=True)
    return sets


__all__ = [
    "confirmed_walk_sets",
    "prefill_set",
    "walk_fingerprint_of",
    "walk_rows_for_model",
]
