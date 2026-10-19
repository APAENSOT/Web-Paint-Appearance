"""T86: build the guided panel-match screen for one batch and model.

One read, one place. The held spellings come from the persisted review
projection (so no workbook is opened on a GET), the live panels come from
`ref_plant_ws_point`, and the candidates come from `domain.panel_match` --
the same scorer the tests pin, name only.

**`mappable`.** A match is stored as a `ref_plant_zone_map` row, and that
table's `fk_pzm_model_zone` can only reference a `(model_code, zone_code)`
pair that is on the model's own `ref_model_zone` catalogue. At a plant whose
live list has grown past that catalogue -- FTM carries 64 live panels
against P703's 32 catalogue positions (T58) -- some live panels therefore
cannot be the target of a map at all. This read says which, and why, instead
of offering a choice the approval would refuse. Promoting a live panel into
the model catalogue is an Admin catalogue change and is not T86's to make.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from sqlalchemy import Connection

from app.domain.cleaner import Cleaner
from app.domain.panel_carryover import TaughtPair, carried_over_for
from app.domain.panel_rename import whole_set_rename
from app.domain.panel_match import name_core, read_position
from app.domain.panel_set_match import HeldSpelling, solve_set
from app.domain.panel_walk import (
    ATTENTION_RED,
    CanonicalPoint,
    ATTENTION_YELLOW,
    BINDING_ALIAS,
    BINDING_BATCH,
    SPECIFICITY_ROUGH,
    WalkRow,
    canonical_named_by,
    classify_against_canonical,
    fingerprint_initials,
    fingerprint_text,
    group_counts,
    match_walk,
)
from app.domain.references import normalise_alias
from app.domain.ws_plant_gold import ws_tolerance
from app.repositories import batches as batch_repo
from app.repositories import mappings as maps
from app.repositories import ws_points as ws_points_repo
from app.repositories import reference as reference_repo
from app.repositories import worksheet as worksheet_repo
from app.services import walk_memory
from app.services.walk_memory import walk_rows_for_model
from app.services.panel_pool import (
    NOT_MAPPABLE_REASON,
    PANEL_HOLD_REASONS,
    panel_pool,
)

#: Said to the uploader at the top of the screen. It promises exactly what
#: the screen does: the person answers, the system only sorts by name.
OPERATOR_MESSAGE = (
    "This file writes panel names this model's list at {plant} does not "
    "have. Match each name on the left to the panel it is, from {plant}'s "
    "own list on the right. A panel is only ever suggested because its NAME "
    "could be this one; where the file's number is also this panel's number "
    "we list that one first and say so. The number never puts a panel on the "
    "list -- the same number means different panels at different plants, "
    "which is why this screen exists. If none of the suggestions is right, "
    "pick from the full list or leave it unmatched. Nothing loads until an "
    "Admin approves the set."
)

#: T88 / G-88-2. Said **before** any exhaustion claim, naming both numbers,
#: because exhaustion is only sound over a closed pool and these two numbers
#: disagreeing is the clearest sign the pool may not be what it looks like.
#: FTM today is 64 live panels against the 32 this file walks.
CATALOGUE_WARNING = (
    "{plant}'s list for {model} holds {live} live panels and this file walks "
    "{file}. The catalogue may be carrying the same physical panel under two "
    "names, so a suggestion that says \"the only one left\" can only be "
    "trusted where the remaining panels really are the ones this file is "
    "about. Check each one before you confirm it."
)

class PanelMatchUnavailable(RuntimeError):
    """The screen cannot be built, and the message says what is missing."""

    status_code = 404

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _held_for_model(
    conn: Connection, load_id: int, plant: str, model_code: str
) -> tuple[list[HeldSpelling], list[str]]:
    """This model's own held spellings, with their counts and orientations.

    Also returns the raw Model cell texts that resolved to this model, so
    G-88-2 can count what the **file** walks rather than what is still held.

    **T88 (D-88-1).** The held rows of a tab carrying two models belong to
    two different questions, so they are split here by resolved model: the
    screen for P703 DBL RANGER must not count P703 DBL RAPTOR's rows, offer
    its panels, or read its orientations. The raw Model cells go through the
    same plant-first alias maps the cleaner uses; a cell that resolves to
    nothing contributes nothing.
    """
    counts = batch_repo.held_checkzone_model_counts(conn, load_id, PANEL_HOLD_REASONS)
    orientations = batch_repo.held_checkzone_orientations(
        conn, load_id, PANEL_HOLD_REASONS
    )
    ref = reference_repo.load_reference_data(conn)
    per_spelling: dict[str, dict] = {}
    raw_texts: set[str] = set()
    for (zone, raw_model), n in counts.items():
        if not zone or not raw_model:
            continue
        resolved = Cleaner.plant_first(
            ref.model_by_plant, ref.model, plant, raw_model
        )
        if resolved != model_code:
            continue
        raw_texts.add(raw_model)
        entry = per_spelling.setdefault(zone, {"count": 0, "orientations": set()})
        entry["count"] += n
        entry["orientations"].update(orientations.get((zone, raw_model), set()))
    return [
        HeldSpelling(
            raw_zone_text=zone,
            orientations=tuple(sorted(entry["orientations"])),
            count=entry["count"],
            raw_position=read_position(zone),
        )
        for zone, entry in sorted(
            per_spelling.items(), key=lambda kv: (-kv[1]["count"], kv[0])
        )
    ], sorted(raw_texts)


#: T90 (D-90-5). The one click an unchanged walk earns, in the owner's
#: words. Never silence: even a walk confirmed last month is confirmed
#: again, once, by a person.
ACCEPT_ALL_WORDS = (
    "Same walk as {source}, confirmed {when}. {yellow} of {total} name(s) "
    "match what was confirmed then -- accept all {yellow} in one click. "
    "{red} still need you."
)

#: Said when this walk has never been confirmed here before.
FIRST_WALK_WORDS = (
    "This walk has not been confirmed for {model} at {plant} before, so "
    "every name is open. Confirm the set once and the next file with the "
    "same walk arrives filled in."
)

#: Said when a confirmed set exists and this file does not walk it.
MOVED_WORDS = (
    "The walk has changed since {source} ({when}). The groups now read "
    "{now} and that set was confirmed against {then}, so nothing is carried "
    "over and every name is open again (D-90-6)."
)


def walk_view(
    conn: Connection, load_id: int, plant: str, model_code: str
) -> dict | None:
    """T90: the structural reading of this sheet's walk, as `WalkMatchOut`.

    None when the sheet writes no panel name for this model, or when the
    model has no canonical list to align against -- at FVL / `P703 DBL
    RANGER`, SAP / `J73 DBL` and SAP / `P703 DBL RANGER` **no** live panel
    is on the model's catalogue (T89 Part 1), so there is nothing for an
    ordinal to count against and saying so is the honest answer.

    The memory is read for this `(plant, model)` whatever its fingerprint,
    on purpose: "the walk has changed since the last confirmed set" is a
    red reason (D-90-6), and it cannot be detected by looking only for
    sets that match.

    **T107-FIX (D-107F-1).** What is *pre-filled from* is the newest
    remembered set that walks **this** walk, not simply the newest set. The
    two are different as soon as a plant has more than one walk on record:
    at FTM the last month committed is July and its walk is neither
    August's nor September's, so a file walking September's arrived red
    with September's answers sitting in the memory under September's own
    fingerprint (T107 section 5.2). When nothing matches, the newest set
    overall is kept so the screen can still say what the walk has changed
    *since* (D-107F-2), and every name stays open -- a walk that differs by
    one label matches nothing, which is D-91-1 unchanged.
    """
    rows = walk_rows_for_model(conn, load_id, plant, model_code)
    if not rows:
        return None
    pool = panel_pool(
        conn, load_id=load_id, plant_code=plant, model_code=model_code
    )
    points = pool.canonical_points
    if not points:
        return None

    remembered_sets = walk_memory.confirmed_walk_sets(
        conn,
        plant_code=plant,
        model_code=model_code,
        exclude_load_id=load_id,
    )
    latest = remembered_sets[0] if remembered_sets else None
    # The set this sheet is pre-filled from, which is the newest one that
    # walks the same walk; the newest overall only when none matches, so
    # the moved sentence still names it (D-107F-1, D-107F-2).
    chosen = walk_memory.prefill_set(remembered_sets, rows) or latest
    match = match_walk(
        rows,
        points,
        remembered=chosen["pairs"] if chosen else None,
        remembered_fingerprint=(
            tuple(chosen["fingerprint"].split("|")) if chosen else None
        ),
    )

    when = (
        chosen["confirmed_at"].date().isoformat()
        if chosen and chosen.get("confirmed_at")
        else ""
    )
    source = (chosen or {}).get("source_file") or "an earlier upload"
    if chosen is None:
        message = FIRST_WALK_WORDS.format(model=model_code, plant=plant)
    elif match.fingerprint_moved:
        message = MOVED_WORDS.format(
            source=source,
            when=when,
            now=fingerprint_initials(match.fingerprint),
            then=fingerprint_initials(match.remembered_fingerprint or ()),
        )
    else:
        message = ACCEPT_ALL_WORDS.format(
            source=source,
            when=when,
            yellow=len(match.yellow),
            total=len(match.verdicts),
            red=len(match.red),
        )

    # T91 (D-91-2, D-91-3): every panel each spelling has ever been
    # confirmed as at this plant x model, and the file it was confirmed on.
    # The screen needs it because a *specific* name can still be barred
    # from `ref_plant_zone_map` -- `13LFRDOOR` is a pillar in August and a
    # door in September, and the name alone therefore identifies nothing
    # here any more. Offering it as a permanent alias would be refused at
    # the write boundary, so the screen says `batch` up front instead of
    # letting the owner find out after pressing Confirm.
    prior_targets: dict[str, set[str]] = {}
    prior_files: dict[tuple[str, str], str] = {}
    for walk_set in remembered_sets:
        for spelling, zone in walk_set["pairs"].items():
            key = normalise_alias(spelling)
            prior_targets.setdefault(key, set()).add(zone)
            prior_files.setdefault(
                (key, zone),
                walk_set.get("source_file") or f"batch {walk_set.get('load_id')}",
            )

    def _binding(verdict) -> tuple[str, str | None]:
        answer = verdict.proposed_zone_code or verdict.prefilled_zone_code
        prior = prior_targets.get(normalise_alias(verdict.raw_zone_text), set())
        if answer is not None:
            elsewhere = sorted(prior - {answer})
        else:
            # Nothing proposed here, so there is only a contradiction to
            # see if the plant itself has said two different things.
            elsewhere = sorted(prior) if len(prior) > 1 else []
        if elsewhere:
            where = "; ".join(
                f"{zone} on "
                f"{prior_files.get((normalise_alias(verdict.raw_zone_text), zone), 'an earlier upload')}"
                for zone in elsewhere
            )
            return BINDING_BATCH, (
                f"this plant has already confirmed {verdict.raw_zone_text} as "
                f"{where}. Both files are believed about themselves, so the "
                f"name on its own no longer says which panel it is here: it is "
                f"confirmed for this upload and never learned forever (D-91-2)"
            )
        if verdict.specificity == SPECIFICITY_ROUGH:
            return BINDING_BATCH, (
                "its core is shared with another name of this sheet, so its "
                "NUMBER is what identifies it -- confirmed for this upload "
                "only (D-90-3)"
            )
        return BINDING_ALIAS, None

    return {
        "model_code": model_code,
        "fingerprint": fingerprint_text(match.fingerprint),
        "fingerprint_display": fingerprint_initials(match.fingerprint),
        "canonical_fingerprint": fingerprint_text(match.canonical_fingerprint),
        "canonical_fingerprint_display": fingerprint_initials(
            match.canonical_fingerprint
        ),
        "group_counts": [
            {"panel_group": group, "file": count,
             "canonical": group_counts(match.canonical_fingerprint).get(group, 0)}
            for group, count in sorted(group_counts(match.fingerprint).items())
        ],
        "multiset_matches": match.multiset_matches,
        "walk_order_verified": match.walk_order_verified,
        "walk_order_reason": match.walk_order_reason,
        "rule_group_ordinal_available": match.rule_a.available,
        "rule_group_ordinal_reason": match.rule_a.reason,
        "rule_walk_number_available": match.rule_b.available,
        "rule_walk_number_reason": match.rule_b.reason,
        "disagreements": list(match.disagreements),
        "fingerprint_moved": match.fingerprint_moved,
        "confirmed_before": chosen is not None,
        "confirmed_source_file": (chosen or {}).get("source_file"),
        "confirmed_at": (chosen or {}).get("confirmed_at"),
        "confirmed_load_id": (chosen or {}).get("load_id"),
        "yellow_count": len(match.yellow),
        "red_count": len(match.red),
        "operator_message": message,
        "rows": [
            {
                "raw_zone_text": verdict.raw_zone_text,
                "panel_group": verdict.group,
                "side": verdict.side,
                "specificity": verdict.specificity,
                "attention": verdict.attention,
                "reason": verdict.reason,
                "rule": verdict.rule,
                "proposed_zone_code": verdict.proposed_zone_code,
                "rule_group_ordinal_zone_code": verdict.rule_a_zone_code,
                "rule_walk_number_zone_code": verdict.rule_b_zone_code,
                "side_hint_checked": verdict.side_hint_checked,
                "prefilled_zone_code": verdict.prefilled_zone_code,
                "binding": binding,
                "binding_reason": binding_reason,
            }
            for verdict, (binding, binding_reason) in (
                (verdict, _binding(verdict)) for verdict in match.verdicts
            )
        ],
    }


def panel_match_view(
    conn: Connection,
    load_id: int,
    model_code: str,
    *,
    confirmed: dict[str, str] | None = None,
) -> dict:
    """The whole screen for one `(load_id, model)`, as `PanelMatchOut`."""
    batch = batch_repo.get_batch(conn, load_id)
    if batch is None:
        raise PanelMatchUnavailable(f"No batch {load_id}.")
    plant = batch["plant_code"]
    if maps.model_family(conn, model_code) is None:
        raise PanelMatchUnavailable(
            f"model_code {model_code!r} is not in ref_model."
        )

    # T89 (D-89-6): one builder, for this screen and for the per-row picker
    # in the held-label list. A panel this very batch already loaded rows
    # onto is spoken for -- leaving it in the pool would let the solver
    # offer one spelling a panel another spelling of the same file is
    # already using, and would make an exhaustion claim over a pool that is
    # not what it looks like (T88).
    pool = panel_pool(
        conn, load_id=load_id, plant_code=plant, model_code=model_code
    )
    live_panels: list[dict] = [
        {
            "zone_code": row.zone_code,
            "point_no": row.point_no,
            "tolerance_group": row.tolerance_group,
            "note": row.note,
            "mappable": row.mappable,
            "already_used": row.taken,
            "not_mappable_reason": row.not_mappable_reason,
        }
        for row in pool.rows
    ]

    # T88 (D-88-2): the whole set at once, under the constraints, with the
    # pairs the owner has already confirmed pinned (G-88-4).
    spellings, raw_model_texts = _held_for_model(conn, load_id, plant, model_code)
    # T90: the structural reading of the whole walk, not only of the held
    # part of it. The verdict for a held row is looked up from it by
    # spelling; a row the walk has nothing to say about simply has none.
    walk = walk_view(conn, load_id, plant, model_code)
    walk_by_spelling = {row["raw_zone_text"]: row for row in (walk or {}).get("rows", [])}
    reasons_by_spelling = {
        item["raw_zone_text"]: sorted(item["reasons"])
        for item in batch_repo.held_panel_spellings(conn, load_id)
    }
    taught = [
        TaughtPair(
            raw_zone_text=row["raw_zone_text"],
            zone_code=row["zone_code"],
            model_code=row["model_code"],
            status=row["status"],
            decided_at=row["decided_at"],
            load_id=row["load_id"],
            method=row["method"],
        )
        for row in maps.taught_panel_pairs(conn, plant)
    ]
    solution = solve_set(
        spellings,
        pool.open_mappable,
        confirmed=confirmed,
        live_panel_count=len(live_panels),
        file_panel_count=batch_repo.file_panel_count(
            conn, load_id, raw_model_texts
        ),
    )
    proposals = solution.by_spelling()

    held: list[dict] = []
    for spelling in spellings:
        raw = spelling.raw_zone_text
        proposal = proposals[raw]
        # D-89-6: the one list, in the order it is shown. The per-row picker
        # calls the same `offer`, so a test can assert the two are equal.
        offering = pool.offer(raw, list(spelling.orientations))
        carried = carried_over_for(raw, model_code, taught, offering.offerable)
        held.append({
            "raw_zone_text": raw,
            # Read from the label the file wrote, shown beside it, and never
            # used to build a candidate (D-86-3 / D-87-1).
            "raw_position": spelling.raw_position,
            "count": spelling.count,
            "reasons": reasons_by_spelling.get(raw, []),
            "orientations": list(spelling.orientations),
            "proposed_zone_code": proposal.proposed,
            "signal": proposal.signal,
            "signal_reason": proposal.reason,
            "orientation_conflict": proposal.orientation_conflict,
            "filtered_out": list(proposal.filtered_out),
            "choosable": list(offering.offerable),
            "blocked": [
                {
                    "zone_code": row.zone_code,
                    "point_no": row.point_no,
                    "tolerance_group": row.tolerance_group,
                    "taken_by": row.taken_by,
                    "label": row.taken_label,
                }
                for row in offering.blocked
            ],
            "walk": walk_by_spelling.get(raw),
            "carried_over": (
                None
                if carried is None
                else {
                    "zone_code": carried.zone_code,
                    "kind": carried.kind,
                    "reason": carried.reason,
                    "source_raw_zone_text": carried.source_raw_zone_text,
                    "source_model_code": carried.source_model_code,
                    "decided_at": carried.decided_at,
                    "load_id": carried.load_id,
                }
            ),
            "candidates": [
                {
                    "zone_code": c.zone_code,
                    "point_no": c.point_no,
                    "tolerance_group": c.tolerance_group,
                    "score": c.score,
                    "basis": c.basis,
                }
                for c in proposal.candidates
            ],
        })

    warning = None
    if solution.catalogue_warning is not None:
        live_count, file_count = solution.catalogue_warning
        warning = CATALOGUE_WARNING.format(
            plant=plant, model=model_code, live=live_count, file=file_count
        )

    return {
        "plant_code": plant,
        "model_code": model_code,
        "load_id": load_id,
        "source_sheet": batch.get("source_sheet") or "",
        "batch_status": batch["status"],
        "held_panels": held,
        "live_panels": live_panels,
        "catalogue_warning": warning,
        "walk": walk,
        "orientation_conflicts": sorted(solution.orientation_conflicts),
        "operator_message": OPERATOR_MESSAGE.format(plant=plant),
    }


def held_models(conn: Connection, load_id: int, plant: str) -> list[str]:
    """Every model this sheet's panel holds resolve to, in name order.

    The raw Model cells go through the same plant-first alias maps the
    cleaner uses (T88 / D-88-1); a cell that resolves to nothing contributes
    nothing. One sheet carrying two models produces two entries, because
    they are two independent questions.
    """
    ref = reference_repo.load_reference_data(conn)
    found: set[str] = set()
    for (zone, raw_model) in batch_repo.held_checkzone_model_counts(
        conn, load_id, PANEL_HOLD_REASONS
    ):
        if not zone or not raw_model:
            continue
        resolved = Cleaner.plant_first(
            ref.model_by_plant, ref.model, plant, raw_model
        )
        if resolved:
            found.add(resolved)
    return sorted(found)


def rename_signals(conn: Connection, load_id: int, plant: str) -> list[dict]:
    """T89 Part 5 (D-88-7): the whole-set rename signal for one sheet.

    One entry per model of this sheet whose panel set looks like a renaming
    of the model's own walk rather than a sheet full of bad rows. Empty is
    the normal answer, and it is the honest one for a file with a handful of
    unknown names.

    Read-only, from the persisted projection and the reference tables, like
    every other worksheet read: no workbook is opened and nothing here
    decides a pair.
    """
    out: list[dict] = []
    for model_code in held_models(conn, load_id, plant):
        spellings, raw_model_texts = _held_for_model(
            conn, load_id, plant, model_code
        )
        if not spellings:
            continue
        pool = panel_pool(
            conn, load_id=load_id, plant_code=plant, model_code=model_code
        )
        file_orientations: Counter = Counter()
        for spelling in spellings:
            if len(set(spelling.orientations)) == 1:
                file_orientations[spelling.orientations[0]] += 1
        mappable_orientations: Counter = Counter(
            (row.tolerance_group or "").strip()
            for row in pool.rows
            if row.mappable
        )
        signal = whole_set_rename(
            plant_code=plant,
            model_code=model_code,
            held_spellings=[s.raw_zone_text for s in spellings],
            file_panel_count=batch_repo.file_panel_count(
                conn, load_id, raw_model_texts
            ),
            rows_held=sum(s.count for s in spellings),
            file_orientations=dict(file_orientations),
            mappable_orientations=dict(mappable_orientations),
        )
        if signal is not None:
            out.append({
                "model_code": signal.model_code,
                "file_panel_count": signal.file_panel_count,
                "live_panel_count": signal.live_panel_count,
                "rows_held": signal.rows_held,
                "orientations": [
                    {"tolerance_group": name, "count": count}
                    for name, count in signal.orientations.items()
                ],
                "operator_message": signal.message,
            })
    return out


#: T94 (D-94-3). One sentence in the row itself, so the person answering it
#: never has to leave the table they are reviewing. It names which canonical
#: panels the name fits, because that list IS the reason: five hoods is not a
#: near-miss, it is five positions and no name for any one of them.
ROUGH_ROW_MESSAGE = (
    "{label} does not say which panel this is: with its leading number "
    "dropped the name fits {fits}. We think it is {proposed} -- confirm it "
    "in this row and the reading loads as {proposed}."
)
#: Said when the sheet's own names are what make it rough (D-94-1 b).
ROUGH_ROW_SHARED_MESSAGE = (
    "{label} does not say which panel this is: {shared} on this sheet all "
    "reduce to the same name, so the number is doing the identifying. We "
    "think it is {proposed} -- confirm it in this row and the reading loads "
    "as {proposed}."
)
#: Said when no structural rule can propose anything (T90's rule (c)).
ROUGH_ROW_NO_PROPOSAL = (
    "{label} does not say which panel this is, and no rule on this sheet "
    "can say which one it is either. Pick the panel from this model's list "
    "in this row. Nothing is guessed."
)
#: Said on the row once the person has answered it.
ROUGH_ROW_CONFIRMED = (
    "Confirmed as {zone} for this upload. The reading loads as {zone}; "
    "{label} is kept as what the file wrote."
)

#: The one click D-94-6 allows, in the row table's own words.
ACCEPT_PREFILLED_WORDS = (
    "{count} of these rows already carry the panel we think they are. "
    "Confirm all {count} in one click, or answer them one at a time."
)


def _sheet_models(conn: Connection, load_id: int, plant: str) -> dict[str, list[dict]]:
    """Every model this sheet writes a panel name for, with its own rows.

    Unlike :func:`held_models` this reads the **whole** sheet and not only
    its held part, because T94 classifies every panel label a sheet carries
    -- a label that resolves today is exactly the one D-94-2 has to stop
    resolving. Split by resolved model through the same plant-first alias
    maps the cleaner uses (D-88-1); a Model cell that resolves to nothing
    belongs to no model and is left out rather than attached to one.
    """
    ref = reference_repo.load_reference_data(conn)
    resolved_by_raw: dict[str, str | None] = {}
    out: dict[str, list[dict]] = {}
    for row in batch_repo.walk_rows(conn, load_id):
        raw_model = row["raw_model"]
        if not row["raw_zone_text"] or not raw_model:
            continue
        if raw_model not in resolved_by_raw:
            resolved_by_raw[raw_model] = Cleaner.plant_first(
                ref.model_by_plant, ref.model, plant, raw_model
            )
        model = resolved_by_raw[raw_model]
        if model:
            out.setdefault(model, []).append(dict(row))
    return out


def _fits_words(zones: Sequence[str]) -> str:
    """``5 positions on this model's list (CFHOOD, LFHOOD, ...)``."""
    return f"{len(zones)} positions on this model's list ({', '.join(zones)})"


def _spelling_blocks(rows: Sequence[WalkRow]) -> list[list[WalkRow]]:
    """The sheet's walks: the vehicles writing the same label set, grouped.

    Largest block first, so the most complete walk is read first.
    """
    by_vehicle: dict[str, list[WalkRow]] = {}
    for row in rows:
        by_vehicle.setdefault(row.vehicle, []).append(row)
    blocks: dict[frozenset[str], list[WalkRow]] = {}
    for vehicle_rows in by_vehicle.values():
        key = frozenset(
            normalise_alias(row.raw_zone_text) for row in vehicle_rows
        )
        blocks.setdefault(key, []).extend(vehicle_rows)
    return sorted(blocks.values(), key=len, reverse=True)


def _walk_verdicts(
    conn: Connection,
    load_id: int,
    plant: str,
    model_code: str,
    points: Sequence[CanonicalPoint],
) -> dict[str, dict]:
    """T96 Part 2: the structural verdict per spelling, one walk at a time.

    :func:`walk_view` reads the sheet as **one** walk per ``(plant,
    model)``, and on the owner's August file that is not what the sheet is.
    Measured on `08 Aug2026 CF data FTM.xlsx`: every vehicle carries a
    32-label walk, and the sheet carries **two spellings of it** -- `01
    RRHOOD`..`32 RFFender` on seven of the Ranger's vehicles and the
    truncated `01HOOD`..`32RTFENDE` on six. Deduplicated across the whole
    sheet that is **64 labels against 32 canonical points**, so rule (a)
    refused itself (`BOX 12 in the file against 6 canonical`, and so on for
    every group) and rule (b) refused itself (`the file writes 64 names
    against 32 canonical points`). That, and nothing about the pool or the
    orientation filter, is why every rough row from `17TGATE` on offered
    "Choose panel" with no proposal.

    So the walk is matched per **spelling block**: the vehicles that write
    the same set of labels are one walk, and each block is matched against
    the model's canonical points on its own. Blocks are read largest first
    and a label keeps the first verdict that proposes something, so a
    vehicle with most of its readings missing cannot take a proposal away
    from the walk it belongs to. A sheet with one spelling is one block and
    reads exactly as it did before.
    """
    remembered_sets = walk_memory.confirmed_walk_sets(
        conn, plant_code=plant, model_code=model_code, exclude_load_id=load_id
    )
    latest = remembered_sets[0] if remembered_sets else None
    out: dict[str, dict] = {}
    for block in _spelling_blocks(
        walk_rows_for_model(conn, load_id, plant, model_code)
    ):
        # Per block, because the block is what is being matched: a sheet
        # carrying two spellings of one walk asks its question twice and
        # each half is pre-filled from the month that walked it
        # (D-107F-1).
        chosen = walk_memory.prefill_set(remembered_sets, block) or latest
        match = match_walk(
            block,
            points,
            remembered=chosen["pairs"] if chosen else None,
            remembered_fingerprint=(
                tuple(chosen["fingerprint"].split("|")) if chosen else None
            ),
        )
        for spelling, verdict in match.by_spelling().items():
            if out.get(spelling, {}).get("proposed_zone_code") is not None:
                continue
            out[spelling] = {
                "proposed_zone_code": verdict.proposed_zone_code,
                "prefilled_zone_code": verdict.prefilled_zone_code,
                "rule": verdict.rule,
                "attention": verdict.attention,
                "reason": verdict.reason,
            }
    return out


def rough_panel_rows(conn: Connection, load_id: int, plant: str) -> list[dict]:
    """T94 Part 1: every **rough** panel label of one sheet, for the row table.

    One entry per (model, spelling), carrying what the highlighted row needs
    and nothing it does not: the long name we propose, why, the colour, the
    full choosable list, the answer already confirmed for this upload, and
    how many rows of the sheet carry the spelling.

    Everything here is read, never decided (D-94-6):

    * **rough / specific** is `panel_walk.classify_against_canonical`, the
      locked D-94-1 rule, over this model's canonical panels;
    * **the proposed long name** is T90's `match_walk` -- rule (a) group +
      ordinal, or rule (b) the walk number -- with its colour and its
      reason, unchanged, run per spelling block (:func:`_walk_verdicts`,
      T96 Part 2) because one sheet can carry two spellings of the same
      32-point walk;
    * **the pre-fill** is the set confirmed last under this same walk
      (`services.walk_memory.confirmed_walk_sets`: the ZONE proposals
      and, since T107, the in-row confirms of committed sheets, D-90-5 /
      D-107-1);
    * **the choosable list** is `panel_pool.offer`, the one list both
      pickers already use (D-89-6);
    * **the confirmed answer** is this batch's own `worksheet_decision`
      rows (revision 0032).

    Read-only, from the persisted projection and the reference tables, like
    every other worksheet read: no workbook is opened.
    """
    # Keyed (model, normalised label), with the model-less fallback a row
    # written before the model was recorded still means (D-94-1).
    stored = worksheet_repo.confirmed_panels_for_batch(conn, load_id)
    confirmed = {
        (model, normalise_alias(raw)): zone
        for (model, raw), zone in stored.items()
    }

    def answer_for(model_code: str, label: str) -> str | None:
        key = normalise_alias(label)
        return confirmed.get((model_code, key), confirmed.get((None, key)))
    out: list[dict] = []
    for model_code, rows in sorted(_sheet_models(conn, load_id, plant).items()):
        pool = panel_pool(
            conn, load_id=load_id, plant_code=plant, model_code=model_code
        )
        canonical = [point.zone_code for point in pool.canonical_points]
        if not canonical:
            # No canonical list to be vague against; T89 Part 1 names the
            # three plant x model pairs where that is true today. Saying
            # nothing is the honest answer, and the held-label path already
            # covers those rows.
            continue
        labels: dict[str, int] = {}
        for row in rows:
            text_value = (row["raw_zone_text"] or "").strip()
            if text_value:
                labels[text_value] = labels.get(text_value, 0) + 1
        verdicts = classify_against_canonical(list(labels), canonical)
        rough = [label for label in labels if verdicts[label] == SPECIFICITY_ROUGH]
        if not rough:
            continue

        walk_by_spelling = _walk_verdicts(
            conn, load_id, plant, model_code, pool.canonical_points
        )
        # T114 (D-114-5): the extra tag travels into review's picker.
        extras = {
            zone for zone, state in ws_points_repo.point_states(
                conn, plant, model_code
            ).items()
            if state["is_extra"] and not state["retired"]
        }
        for label in rough:
            verdict = walk_by_spelling.get(label) or {}
            proposed = verdict.get("proposed_zone_code") or verdict.get(
                "prefilled_zone_code"
            )
            answered = answer_for(model_code, label)
            fits = canonical_named_by(label, canonical)
            shared = sorted(
                other for other in labels
                if other != label and name_core(other) == name_core(label)
            )
            if answered:
                message = ROUGH_ROW_CONFIRMED.format(zone=answered, label=label)
            elif not proposed:
                message = ROUGH_ROW_NO_PROPOSAL.format(label=label)
            elif len(fits) > 1:
                message = ROUGH_ROW_MESSAGE.format(
                    label=label, fits=_fits_words(fits), proposed=proposed
                )
            else:
                message = ROUGH_ROW_SHARED_MESSAGE.format(
                    label=label,
                    shared=", ".join([label, *shared]),
                    proposed=proposed,
                )
            # The Hor/Ver rule is a hard constraint, not a score (D-88-2),
            # and it is read off the NAME by the same rule
            # `ref_checkzone.ck_zone_rule` uses -- so a hood is never
            # offered a box. The list is still wider than the family: these
            # files do spell a roof as a hood, and the person may say so.
            offering = pool.offer(label, [ws_tolerance(label)])
            out.append({
                "raw_zone_text": label,
                "model_code": model_code,
                "rows": labels[label],
                "proposed_zone_code": proposed,
                "prefilled_zone_code": verdict.get("prefilled_zone_code"),
                "confirmed_zone_code": answered,
                "fits_canonical": list(fits),
                "shares_name_with": shared,
                "rule": verdict.get("rule"),
                "attention": (
                    ATTENTION_YELLOW
                    if answered
                    else verdict.get("attention") or ATTENTION_RED
                ),
                "reason": verdict.get("reason") or "",
                "choosable": list(offering.offerable),
                "extra_choices": [
                    zone for zone in offering.offerable if zone in extras
                ],
                "operator_message": message,
            })
    return out


__all__ = [
    "ACCEPT_ALL_WORDS",
    "ACCEPT_PREFILLED_WORDS",
    "CATALOGUE_WARNING",
    "FIRST_WALK_WORDS",
    "MOVED_WORDS",
    "ROUGH_ROW_CONFIRMED",
    "ROUGH_ROW_MESSAGE",
    "ROUGH_ROW_NO_PROPOSAL",
    "ROUGH_ROW_SHARED_MESSAGE",
    "held_models",
    "rename_signals",
    "rough_panel_rows",
    "NOT_MAPPABLE_REASON",
    "OPERATOR_MESSAGE",
    "PanelMatchUnavailable",
    "panel_match_view",
    "walk_view",
]
