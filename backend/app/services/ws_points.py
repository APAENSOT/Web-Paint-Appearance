"""T114: Point Check, Wave Scan -- counted, extra, retire, add.

The Wave Scan half of Point Check (T109 built the Film half). Per plant x
model: the live list in walk order with its zone code, Hor / Ver, Counted,
the **extra** tag and the last change; the retired points below it.

What a person can do, and what each one writes:

* **Counted** (D-114-2): one new `ws_point_setting` row per point named,
  with the reason and the person. Not counted takes the point's readings off
  the dashboard for every month (`v_wavescan_counted`, D-114-12); History and
  Comparison keep them, tagged (D-114-3).
* **Retire** (D-114-4): the existing `retire_plant_panels` and its audit
  action. The point leaves the live list -- no longer a panel-match target,
  never pre-filled -- and its readings stay in History, tagged, and leave the
  dashboard. No un-retire.
* **Add** (D-114-5, D-114-6): pick any existing zone code or type a new one.
  A new code is kept exactly as typed after trimming its ends; its Hor / Ver
  is read off the name (`ck_zone_rule`), never chosen. The point goes at the
  **end of the walk** and is tagged extra.

RO17 adds: every point shows its **label** (the plant's word, D-RO17-1);
**restore** of a retired point (D-RO17-9); a **first list** on an offered
model with none (D-RO17-10); and an Admin may add a point that **counts in
completeness** (not extra), told first how many stored cars that makes
incomplete (D-RO17-7).

H/V of a Wave Scan point is fixed by its name, so nothing here edits it.
Every write takes the list lock first and carries an `audit_event` in the
same transaction.
"""

from __future__ import annotations

from sqlalchemy import Connection

from app.domain.ws_plant_gold import (
    HORIZONTAL_WORDS,
    gold_key,
    ws_panel_group,
    ws_tolerance,
)
from app.repositories import audit
from app.repositories import mappings as maps
from app.repositories import ws_points as repo
from app.services import point_labels as labels
from app.services import point_walk
from app.services.workbooks import WorkbookError, resolve_plant

#: D-114-4: the audit action T86 set approval writes for the same UPDATE.
RETIRE_ACTION = "catalogue.plant_ws_point.retire"
ADD_ACTION = "catalogue.plant_ws_point.add"
SETTING_ACTION = "catalogue.ws_point_setting.change"
RESTORE_ACTION = "catalogue.plant_ws_point.restore"
DOMAIN = "wavescan"


def _list(
    conn: Connection, plant_code: str, model_code: str, *, first: bool = False
) -> tuple[str, str, list[dict]]:
    """The plant, the model and its live list, or a 404.

    One place, so every write refuses the same way and reads the same list
    Point Check shows. ``first``: an offered Wave Scan model with no live
    list is an empty list, not a 404 (D-RO17-10).
    """
    plant = resolve_plant(conn, plant_code)["plant_code"]
    model = str(model_code).strip()
    live = repo.live_points(conn, plant, model)
    if not live and first and model in repo.offered_models(conn, plant):
        return plant, model, []
    if not live:
        raise WorkbookError(
            404,
            f"{plant} has no live Wave Scan point list for {model!r}, so there "
            f"is nothing to show or change.",
        )
    return plant, model, live


def ws_models(conn: Connection, plant_code: str) -> dict:
    """The Wave Scan models this plant has a live list for."""
    plant = resolve_plant(conn, plant_code)["plant_code"]
    items = repo.models(conn, plant)
    listed = {m["model_code"] for m in items}
    return {
        "plant_code": plant,
        "items": items,
        "offered_without_list": [
            m for m in repo.offered_models(conn, plant) if m not in listed
        ],
    }


def ws_point_list(conn: Connection, plant_code: str, model_code: str) -> dict:
    """D-114-1: what Point Check's Wave Scan section shows for one model."""
    plant, model, live = _list(conn, plant_code, model_code, first=True)
    retired = repo.retired_points(conn, plant, model)
    on_list = {p["zone_code"] for p in live} | {p["zone_code"] for p in retired}
    named = labels.current_labels(conn, DOMAIN, plant, model)
    for p in (*live, *retired):
        p["label"] = named.get(p["zone_code"], p["zone_code"])
    return {
        "plant_code": plant,
        "model_code": model,
        "items": live,
        "retired_items": retired,
        # D-114-6: what Add may pick. A code already on this list -- live or
        # retired -- would be refused, so it is not offered.
        "zone_choices": [
            z for z in repo.zone_choices(conn) if z["zone_code"] not in on_list
        ],
        "horizontal_words": list(HORIZONTAL_WORDS),
    }


def change_ws_point_setting(
    conn: Connection, plant_code: str, model_code: str, *,
    points: list[dict], reason: str, actor: str, correlation_id: str | None,
) -> dict:
    """D-114-2: which points count. Append-only, latest row wins."""
    plant, model, live = _list(conn, plant_code, model_code)
    codes = {p["zone_code"] for p in live}
    rows: list[tuple[str, bool]] = []
    for item in points:
        code = str(item.get("zone_code") or "").strip()
        if code not in codes:
            raise WorkbookError(
                422,
                f"{code or '(blank)'!s} is not a live point of {plant}'s {model} "
                f"Wave Scan list. Nothing was changed.",
            )
        rows.append((code, bool(item.get("counted", True))))
    if not rows:
        raise WorkbookError(422, "Name at least one point. Nothing was changed.")
    written = repo.insert_settings(
        conn, plant_code=plant, model_code=model, rows=rows,
        reason=reason, actor=actor,
    )
    audit.record(
        conn,
        action=SETTING_ACTION,
        entity_type="ws_point_setting",
        entity_id=f"{plant}:{model}",
        actor_user_id=actor or None,
        after={
            "plant_code": plant, "model_code": model, "reason": reason,
            "rows": [{"zone_code": c, "counted": n} for c, n in rows],
            "owner_decision": "T114 D-114-2",
        },
        correlation_id=correlation_id,
    )
    return {
        "rows_written": written,
        "operator_message": (
            f"{written} point(s) of {plant}'s {model} Wave Scan list changed. "
            f"The dashboard counts the new setting from now on, for every "
            f"month; History and Comparison keep every reading."
        ),
    }


def retire_ws_point(
    conn: Connection, plant_code: str, model_code: str, *,
    zone_code: str, reason: str, actor: str, correlation_id: str | None,
) -> dict:
    """D-114-4: off the live list, everything kept. RO17: restore brings it back."""
    plant, model, _ = _list(conn, plant_code, model_code)
    labels.lock_list(conn, DOMAIN, plant, model)
    plant, model, live = _list(conn, plant, model)
    code = str(zone_code or "").strip()
    point = next((p for p in live if p["zone_code"] == code), None)
    if point is None:
        raise WorkbookError(
            409,
            f"{code or '(blank)'} is not a live point of {plant}'s {model} Wave "
            f"Scan list, so there is nothing to retire. Nothing was changed.",
        )
    if len(live) == 1:
        # A plant x model with no live point at all stops being read as a
        # list (`load_reference_data` builds the gold from live rows only),
        # and the cleaner would fall back to the model-wide rules.
        raise WorkbookError(
            409,
            f"{code} is the last live point of {plant}'s {model} list. A list "
            f"with no live point is no list at all, and uploads would fall back "
            f"to the model-wide rules. Nothing was changed.",
        )
    why = f"T114 (D-114-4): retired on Point Check -- {reason}"
    retired = maps.retire_plant_panels(
        conn, plant_code=plant, model_code=model, zone_codes=[code], reason=why,
    )
    if retired != [code]:
        raise WorkbookError(
            409,
            f"{code} was not retired: it may have been retired by somebody "
            f"else a moment ago. Nothing was changed.",
        )
    audit.record(
        conn,
        action=RETIRE_ACTION,
        entity_type="ref_plant_ws_point",
        entity_id=f"{plant}:{model}",
        actor_user_id=actor or None,
        before={"live": [code]},
        after={
            "retired": [code], "retired_reason": why,
            "via": "Point Check", "owner_decision": "T114 D-114-4",
        },
        correlation_id=correlation_id,
    )
    return {
        "zone_code": code,
        "point_no": int(point["point_no"]),
        "tolerance_group": point["tolerance_group"],
        "label": labels.current_labels(conn, DOMAIN, plant, model).get(code, code),
        "incomplete_cars": None,
        "operator_message": (
            f"{code} is off {plant}'s {model} Wave Scan walk. It stops counting "
            f"on the dashboard for every month; the readings cars already have "
            f"on it stay in History, marked retired. A file that writes {code} "
            f"again is asked which point it is."
        ),
    }


def add_ws_point(
    conn: Connection, plant_code: str, model_code: str, *,
    zone_code: str, counted: bool, reason: str, actor: str | None, actor_name: str,
    correlation_id: str | None, counted_in_completeness: bool = False,
    admin: bool = False,
) -> dict:
    """D-114-6 / D-114-7: one point at the end of the walk.

    RO17: extra unless ``counted_in_completeness`` (Admin only, D-RO17-7),
    which counts it in car completeness and reports how many stored cars that
    makes incomplete, measured in this transaction. An offered model with no
    list may take its first point here (D-RO17-10). The word typed is the
    point's first label.
    """
    if counted_in_completeness and not admin:
        raise WorkbookError(
            403,
            "Only an Admin may add a point that counts in car completeness: it "
            "can make stored cars incomplete. Nothing was changed.",
        )
    plant, model, _ = _list(conn, plant_code, model_code, first=True)
    labels.lock_list(conn, DOMAIN, plant, model)
    plant, model, live = _list(conn, plant, model, first=True)
    code = str(zone_code or "").strip()
    if not code:
        raise WorkbookError(422, "Name the point. Nothing was changed.")

    existing = repo.point_row(conn, plant, model, code)
    if existing is not None and existing["retired_at"] is None:
        raise WorkbookError(
            409,
            f"{code} is already point {existing['point_no']} of {plant}'s "
            f"{model} Wave Scan list. Nothing was changed.",
        )
    if existing is not None:
        raise WorkbookError(
            409,
            f"This point was retired; restore it instead. {code} left "
            f"{plant}'s {model} list on {str(existing['retired_at'])[:10]}: "
            f"{existing['retired_reason']}. Nothing was changed.",
        )

    known = repo.checkzone(conn, code)
    if known is None:
        twin = repo.checkzone_twin(conn, code)
        if twin is not None:
            raise WorkbookError(
                409,
                f"{code!r} is the same panel as {twin!r}, spelled differently "
                f"-- pick {twin} instead. Nothing was changed.",
            )
        try:
            panel_group = ws_panel_group(code)
        except ValueError:
            raise WorkbookError(
                422,
                f"{code!r} does not say which panel it is. A new zone code "
                f"needs a panel word in it -- Hood, Roof, Door, Fender, Box, "
                f"Pillar, Tailgate, Liftgate -- so it can be grouped and "
                f"matched. Nothing was changed.",
            ) from None
        tolerance = ws_tolerance(code)
    else:
        panel_group = known["panel_group"]
        tolerance = known["tolerance_group"]

    # D-58-03: at one plant x model `1HOOD` and `01HOOD` are the same point.
    same = next(
        (p["zone_code"] for p in live if gold_key(p["zone_code"]) == gold_key(code)),
        None,
    )
    if same is not None:
        raise WorkbookError(
            409,
            f"{code} and {same} are the same point at {plant}'s {model} (a "
            f"leading zero does not make a new point), and {same} is already "
            f"live. Nothing was changed.",
        )
    # D-RO17-4: the word typed becomes its first label.
    sentence = labels.clash(conn, DOMAIN, plant, model, code, for_code=code)
    if sentence:
        raise WorkbookError(409, f"{sentence} Nothing was changed.")

    zone_no = repo.model_zone_no(conn, model, code)
    new_zone_no = zone_no is None
    if new_zone_no:
        zone_no = repo.next_zone_no(conn, model)
        if zone_no > repo.MAX_ZONE_NO:
            raise WorkbookError(
                409,
                f"{model}'s catalogue already uses position "
                f"{repo.MAX_ZONE_NO}, the last one it has room for, so {code} "
                f"cannot be added to it. Nothing was changed.",
            )
    point_no = repo.next_point_no(conn, plant, model)
    incomplete_before = (
        repo.incomplete_cars(conn, plant, model) if counted_in_completeness else 0
    )

    if known is None:
        repo.insert_checkzone(
            conn, zone_code=code, panel_group=panel_group, tolerance_group=tolerance,
        )
    if new_zone_no:
        repo.insert_model_zone(conn, model_code=model, zone_code=code, zone_no=zone_no)
    repo.insert_point(
        conn, plant_code=plant, model_code=model, zone_code=code,
        point_no=point_no, tolerance_group=tolerance,
        note=f"T114 Point Check add by {actor_name or actor or 'unknown'}",
        is_extra=not counted_in_completeness,
    )
    repo.insert_settings(
        conn, plant_code=plant, model_code=model, rows=[(code, bool(counted))],
        reason=reason, actor=actor,
    )
    label_id = labels.insert_label(
        conn, DOMAIN, plant, model, code, code, reason=reason, actor=actor
    )
    point_walk.record_membership(conn, plant, model, "WAVESCAN", added_code=code,
                                 actor=actor, reason=reason,
                                 correlation_id=correlation_id)
    incomplete = (
        repo.incomplete_cars(conn, plant, model) - incomplete_before
        if counted_in_completeness else None
    )
    audit.record(
        conn,
        action=ADD_ACTION,
        entity_type="ref_plant_ws_point",
        entity_id=f"{plant}:{model}:{code}",
        actor_user_id=actor or None,
        after={
            "plant_code": plant, "model_code": model, "zone_code": code,
            "point_no": point_no, "tolerance_group": tolerance,
            "counted": bool(counted), "is_extra": not counted_in_completeness,
            "incomplete_cars": incomplete, "first_list": not live,
            "label_id": label_id, "reason": reason,
            "new_checkzone": known is None, "new_model_zone_no": (
                zone_no if new_zone_no else None
            ),
            "owner_decision": "T114 D-114-6, RO17 D-RO17-7/-10",
        },
        correlation_id=correlation_id,
    )
    tag = (
        f"counted in car completeness ({incomplete} stored car(s) became "
        f"incomplete)" if counted_in_completeness else "tagged extra"
    )
    first = (
        f" This is the first point of {plant}'s {model} list: from now on "
        f"uploads of {model} at {plant} load only the points on this list."
        if not live else ""
    )
    return {
        "zone_code": code,
        "point_no": point_no,
        "tolerance_group": tolerance,
        "label": code,
        "incomplete_cars": incomplete,
        "operator_message": (
            f"{code} is now point {point_no} of {plant}'s {model} Wave Scan "
            f"walk, the last one, {tolerance}, "
            f"{'counted' if counted else 'not counted'}, {tag}. A file "
            f"that writes this name loads onto it from now on.{first}"
        ),
    }


def completeness_impact(
    conn: Connection, plant_code: str, model_code: str, *, zone_code: str
) -> dict:
    """What an Admin's add with ``counted_in_completeness`` would do (D-RO17-7).

    The very same inserts, inside a savepoint that is always rolled back:
    nothing persists, and a refusal is the add's own refusal.
    """
    plant, model, _ = _list(conn, plant_code, model_code, first=True)
    now = repo.incomplete_cars(conn, plant, model)
    savepoint = conn.begin_nested()
    try:
        found = add_ws_point(
            conn, plant, model, zone_code=zone_code, counted=True,
            reason="RO17 completeness impact, rolled back", actor=None,
            actor_name="", correlation_id=None, counted_in_completeness=True,
            admin=True,
        )
    finally:
        savepoint.rollback()
    become = int(found["incomplete_cars"] or 0)
    return {
        "zone_code": found["zone_code"],
        "cars_incomplete_now": now,
        "cars_incomplete_after": now + become,
        "cars_become_incomplete": become,
        "operator_message": (
            f"Counting {found['zone_code']} in car completeness would make "
            f"{become} stored car(s) of {plant}'s {model} incomplete "
            f"({now} are now, {now + become} after). Nothing was changed."
        ),
    }


def restore_ws_point(
    conn: Connection, plant_code: str, model_code: str, *,
    zone_code: str, reason: str, actor: str | None, correlation_id: str | None,
) -> dict:
    """D-RO17-9: a retired point back on the walk, at its own number."""
    plant = resolve_plant(conn, plant_code)["plant_code"]
    model = str(model_code).strip()
    code = str(zone_code or "").strip()
    labels.lock_list(conn, DOMAIN, plant, model)
    row = repo.point_row(conn, plant, model, code)
    if row is None:
        raise WorkbookError(
            404,
            f"{code or '(blank)'} is not a point of {plant}'s {model} Wave Scan "
            f"list. Nothing was changed.",
        )
    if row["retired_at"] is None:
        raise WorkbookError(
            409,
            f"{code} is live already, so there is nothing to restore. "
            f"Nothing was changed.",
        )
    label = labels.current_labels(conn, DOMAIN, plant, model).get(code, code)
    for word in dict.fromkeys((code, label)):
        sentence = labels.clash(conn, DOMAIN, plant, model, word, for_code=code)
        if sentence:
            raise WorkbookError(409, f"{sentence} Nothing was changed.")
    if repo.restore_point(conn, plant, model, code) != 1:
        raise WorkbookError(
            409,
            f"{code} was not restored: somebody may have changed it a moment "
            f"ago. Nothing was changed.",
        )
    if not labels.has_label(conn, DOMAIN, plant, model, code):
        labels.insert_label(
            conn, DOMAIN, plant, model, code, code,
            reason="restore: the code", actor=actor,
        )
    point_walk.record_membership(conn, plant, model, "WAVESCAN", actor=actor,
                                 reason=reason, correlation_id=correlation_id)
    audit.record(
        conn,
        action=RESTORE_ACTION,
        entity_type="ref_plant_ws_point",
        entity_id=f"{plant}:{model}:{code}",
        actor_user_id=actor or None,
        before={
            "retired_at": row["retired_at"],
            "retired_reason": str(row["retired_reason"])[:300],
        },
        after={"live": [code], "reason": reason, "owner_decision": "RO17 D-RO17-9"},
        correlation_id=correlation_id,
    )
    return {
        "zone_code": code,
        "point_no": int(row["point_no"]),
        "tolerance_group": row["tolerance_group"],
        "label": label,
        "incomplete_cars": None,
        "operator_message": (
            f"{code} is back on {plant}'s {model} Wave Scan walk as point "
            f"{row['point_no']}. A file that writes {label!r} loads onto it "
            f"again; the readings it already has never moved."
        ),
    }


__all__ = [
    "add_ws_point",
    "change_ws_point_setting",
    "completeness_impact",
    "restore_ws_point",
    "retire_ws_point",
    "ws_models",
    "ws_point_list",
]
