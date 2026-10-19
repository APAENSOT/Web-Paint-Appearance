"""Held spellings on one sheet, with the existing catalogue names to pick from.

Shared by the batch review (`GET /batches/{id}`) and the T39 worksheet, so
the two can never describe the same held row differently. Read from the
persisted projection: no workbook is opened on a GET.

Candidates are existing catalogue names only. Nothing here invents a colour,
model, zone or plant (`AGENTS.md` rule 6).
"""

from __future__ import annotations

from sqlalchemy import Connection

from app.domain.color_identity import unique_colour_identity
from app.domain.held_label_copy import (
    PANEL_NO_MAPPABLE,
    display_group_for,
    is_empty_identity_sentinel,
    operator_message_for,
)
from app.domain.leftover_models import (
    is_leftover_program,
    leftover_maps_to_own_program,
    leftover_program_prefix,
)
from app.domain.cleaner import Cleaner, RejectReason
from app.domain.film import (
    REASON_FILM_JOB_UNUSUAL,
    REASON_FILM_MODEL_CONFLICT,
    REASON_FILM_MODEL_UNRESOLVED,
    REASON_FILM_POINT_WAITING,
    REASON_FILM_WALK_UNKNOWN,
    film_model_options,
)
from app.domain.reader import MEASURES_HOLE_APPROVABLE, missing_measures
from app.domain.panel_carryover import TaughtPair, carried_over_for
from app.repositories import batches as batch_repo
from app.repositories import filmthickness as film_repo
from app.repositories import mappings as maps
from app.repositories import reference as reference_repo
from app.schemas.ingest import TEACHABLE_HELD_REASONS
from app.services.panel_pool import PANEL_HOLD_REASONS, panel_pool

#: T99. Holds that are about the whole Film sheet. Every row carries the same
#: one and the answer is a button on the tab, not a name to teach.
#: T109-FIX (D-109F-1): a row waiting on **another** row's unanswered label is
#: the same kind of thing -- its own spelling is a live point of the walk, so
#: there is nothing to teach about it, and the answer is in the row that wrote
#: the label nobody has named yet.
FILM_SHEET_HOLD_REASONS = frozenset({
    REASON_FILM_WALK_UNKNOWN, REASON_FILM_JOB_UNUSUAL,
    REASON_FILM_MODEL_CONFLICT, REASON_FILM_POINT_WAITING,
})


def _panel_groups_by_model(
    conn: Connection,
    load_id: int,
    plant_code: str | None,
    group: dict,
) -> list[dict]:
    """T88 (D-88-1): one question per `(model, spelling)`, not one refusal.

    Until T88 a spelling written on two models was treated as unresolvable:
    `teachable_kind`, `model_code` and `candidates` were all blanked and the
    reviewer was told to "map it after the model is settled". There is
    nothing to settle. ``07LFFENDER`` on P703 DBL RANGER and ``07LFFENDER``
    on P703 DBL RAPTOR are two independent pairs with two independent
    answers, and refusing both is what kept the owner's own September file
    -- 741 held rows, every spelling on both models -- out of a screen built
    for it.

    So this returns **one group per resolved model**, each carrying that
    model's own row count, that model's own live panels as candidates, and
    its own orientation as read from the file. The safety that mattered is
    untouched: candidates are still that model's panels alone, never a union
    (T41 / D-31).
    """
    raw = group["raw_value"] or ""
    counts = batch_repo.held_checkzone_model_counts(
        conn, load_id, PANEL_HOLD_REASONS
    )
    orientations = batch_repo.held_checkzone_orientations(
        conn, load_id, PANEL_HOLD_REASONS
    )
    ref = reference_repo.load_reference_data(conn)

    per_model: dict[str, int] = {}
    per_model_orientation: dict[str, set[str]] = {}
    for (zone, raw_model), n in counts.items():
        if zone != raw:
            continue
        model = Cleaner.plant_first(
            ref.model_by_plant, ref.model, plant_code, raw_model
        ) if raw_model else None
        if not model:
            continue
        per_model[model] = per_model.get(model, 0) + n
        per_model_orientation.setdefault(model, set()).update(
            orientations.get((zone, raw_model), set())
        )
    return [
        {
            "model_code": model,
            "count": n,
            "orientations": sorted(per_model_orientation.get(model, set())),
        }
        for model, n in sorted(per_model.items())
    ]


def held_label_items(
    conn: Connection,
    load_id: int,
    *,
    plant_code: str | None = None,
    unreviewed_headers: list[str] | None = None,
) -> list[dict]:
    """One dict per distinct held spelling, shaped as `HeldLabelGroup`."""
    groups = batch_repo.held_label_groups(conn, load_id)
    zone_models = _checkzone_models(conn, load_id, plant_code, groups)
    # T61 (D-78-34): computed once per sheet, because the model is a property
    # of the sheet and not of a row.
    film_model = _film_model_options(conn, load_id, groups)
    catalogs: dict[str, list[str]] = {}
    # Read once per sheet: the panel pool per (plant, model), and what this
    # plant has already been taught (T89).
    pools: dict = {}
    taught_pairs: dict = {}
    items: list[dict] = []
    seen_unreviewed: set[str] = set()
    for group in groups:
        reason = group["reason"]
        # T99: a sheet-wide Film hold is not a held *label*. The walk, the Job
        # Number and the two models the names give are facts about the sheet,
        # every row carries the same one, and there is nothing to teach about
        # the spelling in front of you -- the answer is a button on the tab
        # (`worksheet.answer_film_model` / `answer_film_job` /
        # `confirm_film_walk`), and the sentence is already on every row.
        # Listing them here would put the file's whole walk in the teach list
        # as if each label were a question of its own.
        if reason in FILM_SHEET_HOLD_REASONS:
            continue
        # RO16 (D-RO16-3): a Wave Scan car carrying two days or colours is the
        # same kind of fact about the sheet; its sentence is on every row.
        if reason == RejectReason.OTHER:
            continue
        kind = TEACHABLE_HELD_REASONS.get(reason)
        raw = group["raw_value"] or ""
        if kind == "ALIAS_MODEL" and is_leftover_program(raw):
            catalogs.setdefault("model", maps.known_models(conn))
            own = [
                m for m in catalogs["model"]
                if leftover_maps_to_own_program(raw, m)
            ]
            if own:
                candidates = own
            else:
                kind = None
                candidates = []
        else:
            candidates = []
            if kind == "ALIAS_COLOR":
                catalogs.setdefault("color", maps.known_colors(conn))
                catalogue = catalogs["color"]
                if reason == "COLOR_NOT_OFFERED":
                    # ADR 0013 decision 10 / D-32: asked every time, official
                    # names only, **no default** -- G9Z Absolute Black is not
                    # quietly Shadow Black, and not quietly Absolute Black.
                    candidates = sorted(catalogue)
                else:
                    suggested = unique_colour_identity(raw, catalogue)
                    if suggested:
                        candidates = [suggested] + [
                            c for c in catalogue if c != suggested
                        ]
                    else:
                        candidates = catalogue
            elif kind == "ALIAS_MODEL":
                catalogs.setdefault("model", maps.known_models(conn))
                candidates = [
                    m for m in catalogs["model"]
                    if leftover_program_prefix(m) is None
                ]
        group_name = display_group_for(reason, raw)
        # T98 (D-98-1): what these points are really short of, and whether
        # approving LW/SW holes can load any of them -- a point with no CF
        # refuses either way, so it is neither named as approvable nor
        # offered the button (`worksheet._held_facts`).
        missing_sets = [
            frozenset(missing_measures(d)) for d in (group.get("details") or [])
        ]
        missing = [
            m for m in ("lw", "sw", "cf")
            if any(m in s for s in missing_sets)
        ]
        approvable = any(
            s and s <= frozenset(MEASURES_HOLE_APPROVABLE) for s in missing_sets
        )
        blank_identity = group_name in ("empty_identity", "measure", "date") or (
            is_empty_identity_sentinel(raw) and group_name != "plant"
        )
        if reason == "UNREVIEWED_HEADER":
            seen_unreviewed.add(raw)

        # T88 (D-88-1): a panel hold becomes one entry per model it was
        # written on. One model is the T41 case and is unchanged; two models
        # used to be a refusal and is now two questions.
        per_model: list[dict] = []
        if group_name == "zone" and not blank_identity:
            per_model = _panel_groups_by_model(conn, load_id, plant_code, group)

        for split in per_model or [None]:
            item_kind, item_candidates = kind, candidates
            item_count = int(group["n"])
            model_code = None
            message = None
            orientations: list[str] = []
            blocked: list[dict] = []
            carried: dict | None = None
            if split is not None:
                model_code = split["model_code"]
                item_count = split["count"]
                orientations = split["orientations"]
                if item_kind == "ALIAS_CHECKZONE":
                    # T89 (D-89-6): the SAME list the guided match screen
                    # offers, from the one builder. Until T89 this was
                    # `plant_zone_codes` -- every panel live at this plant x
                    # model, which at FTM is 64, half of them panels
                    # `fk_pzm_model_zone` cannot reference. The approval path
                    # refused them after the fact; now they are not offered.
                    offering = _offering(conn, load_id, plant_code, model_code, raw,
                                         orientations, pools)
                    item_candidates = list(offering.offerable)
                    blocked = [
                        {
                            "zone_code": row.zone_code,
                            "point_no": row.point_no,
                            "tolerance_group": row.tolerance_group,
                            "taken_by": row.taken_by,
                            "label": row.taken_label,
                        }
                        for row in offering.blocked
                    ]
                    carried = _carried_over(
                        conn, plant_code, model_code, raw, offering.offerable,
                        taught_pairs,
                    )
                    if not item_candidates and not blocked:
                        # T89 (D-89-6): nothing can be offered, so the copy
                        # stops promising a pick and says why instead -- the
                        # T86 section 3.8 rule, now reachable at three
                        # plant x models whose live panels are not on their
                        # model's catalogue at all.
                        item_kind = None
                        message = PANEL_NO_MAPPABLE.format(
                            shown=raw.strip() or "(blank)",
                            here=plant_code or "this plant",
                            model=model_code,
                        )
            elif group_name == "zone":
                # A panel hold whose model cell resolved to nothing: there is
                # no model to confirm a pair against, so no pick is offered.
                item_kind = None
                item_candidates = []
            if blank_identity:
                item_kind = None
                item_candidates = []
                model_code = None
                blocked = []
                carried = None

            items.append({
                "reason": reason,
                "column": group["column"] or "",
                "raw_value": raw,
                "count": item_count,
                "teachable_kind": item_kind,
                "candidates": item_candidates,
                "display_group": group_name,
                # T86 section 3.8: the sentence depends on whether a control
                # can actually be offered for this row, which is `kind` -- it
                # is decided a few lines up, so the copy and the control can
                # no longer disagree.
                "operator_message": message or operator_message_for(
                    group_name,
                    raw,
                    column=group["column"],
                    plant=plant_code,
                    teachable=item_kind is not None,
                    model=model_code,
                    orientations=orientations,
                    missing=missing,
                    approvable=approvable if missing else None,
                    reason=reason,
                    details=group.get("details"),
                ),
                "film_model": (
                    film_model if reason == REASON_FILM_MODEL_UNRESOLVED else None
                ),
                "model_code": model_code,
                "orientations": orientations,
                "blocked_candidates": blocked,
                "carried_over": carried,
            })
    for header in unreviewed_headers or []:
        if header in seen_unreviewed:
            continue
        seen_unreviewed.add(header)
        items.append({
            "reason": "UNREVIEWED_HEADER",
            "column": "",
            "raw_value": header,
            "count": 1,
            "teachable_kind": None,
            "candidates": [],
            "display_group": "header",
            "operator_message": operator_message_for("header", header),
            "film_model": None,
            "model_code": None,
            "orientations": [],
            "blocked_candidates": [],
            "carried_over": None,
        })
    return items


def _offering(
    conn: Connection,
    load_id: int,
    plant_code: str | None,
    model_code: str,
    raw_zone_text: str,
    orientations: list[str],
    pools: dict,
):
    """T89 (D-89-6): the one panel list, for one held spelling on one model.

    The pool itself is per `(plant, model)` and is read once per sheet --
    September's tab asks 44 of these questions and the panel list does not
    change between them.
    """
    key = (plant_code or "", model_code)
    if key not in pools:
        pools[key] = panel_pool(
            conn, load_id=load_id, plant_code=key[0], model_code=model_code
        )
    return pools[key].offer(raw_zone_text, orientations)


def _carried_over(
    conn: Connection,
    plant_code: str | None,
    model_code: str,
    raw_zone_text: str,
    offerable,
    cache: dict,
) -> dict | None:
    """T89 (D-89-9): the earlier decision to pre-select, or None.

    Read per plant from `ref_plant_zone_map` and the still-`PROPOSED`
    proposals -- never from the global `ref_checkzone_alias`, which the
    application does not write and T89 does not start writing (D-89-10).
    """
    if not plant_code:
        return None
    if plant_code not in cache:
        cache[plant_code] = [
            TaughtPair(
                raw_zone_text=row["raw_zone_text"],
                zone_code=row["zone_code"],
                model_code=row["model_code"],
                status=row["status"],
                decided_at=row["decided_at"],
                load_id=row["load_id"],
                method=row["method"],
            )
            for row in maps.taught_panel_pairs(conn, plant_code)
        ]
    taught = cache[plant_code]
    found = carried_over_for(raw_zone_text, model_code, taught, offerable)
    if found is None:
        return None
    return {
        "zone_code": found.zone_code,
        "kind": found.kind,
        "reason": found.reason,
        "source_raw_zone_text": found.source_raw_zone_text,
        "source_model_code": found.source_model_code,
        "decided_at": found.decided_at,
        "load_id": found.load_id,
    }


def _checkzone_models(
    conn: Connection, load_id: int, plant_code: str | None, groups: list[dict]
) -> dict[str, set[str]]:
    """Which existing model each held panel spelling was written on (T41).

    **T86** widens this from ``UNKNOWN_CHECKZONE`` to every panel hold, so a
    ``ZONE_NOT_VALID_FOR_MODEL`` group can carry its ``model_code`` too. It
    does not make that reason teachable -- ``TEACHABLE_HELD_REASONS`` still
    leaves it out (D-31) and ``teachable_kind`` stays null. The model is
    what the guided match screen is opened with.

    The raw Model cells of those rows are resolved through the same
    plant-first alias maps the cleaner uses; nothing is guessed. A cell that
    resolves to nothing contributes nothing.
    """
    if not any(g["reason"] in PANEL_HOLD_REASONS for g in groups):
        return {}
    if plant_code is None:
        batch = batch_repo.get_batch(conn, load_id)
        plant_code = batch.get("plant_code") if batch else None
    ref = reference_repo.load_reference_data(conn)
    out: dict[str, set[str]] = {}
    for raw_zone, raw_models in batch_repo.held_checkzone_models(
        conn, load_id, PANEL_HOLD_REASONS
    ).items():
        resolved = {
            model
            for text_value in raw_models
            if text_value
            and (model := Cleaner.plant_first(
                ref.model_by_plant, ref.model, plant_code, text_value
            ))
        }
        out[raw_zone] = resolved
    return out


__all__ = ["held_label_items"]


def _film_model_options(
    conn: Connection, load_id: int, groups: list[dict]
) -> dict | None:
    """T61: the server-derived Film model choices for this sheet, or None.

    Built from the batch's own plant, file name and tab name through the same
    `domain.film` functions ingest resolves with, so the list the Engineer is
    offered and the list the proposal is validated against are one list.
    """
    if not any(g["reason"] == REASON_FILM_MODEL_UNRESOLVED for g in groups):
        return None
    batch = batch_repo.get_batch(conn, load_id)
    if batch is None:
        return None
    film = film_repo.load_film_reference(conn)
    options = film_model_options(
        batch["plant_code"], batch["source_file"], batch["source_sheet"],
        film.model_alias,
    )
    return {
        "load_id": load_id,
        "source_sheet": batch["source_sheet"],
        "plant_code": batch["plant_code"],
        "detail": options.detail,
        "resolution_source": options.resolution_source,
        "candidates": list(options.candidates),
        "choices": list(options.choices),
        "teachable_tokens": list(options.teachable_tokens),
    }
