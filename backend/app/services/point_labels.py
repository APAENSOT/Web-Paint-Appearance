"""RO17: every plant names its points in its own words (both domains).

A point keeps its code and its key, and every stored fact keeps the code it
has (D-RO17-1, ADR 0005). Its **label** is the word its plant uses: the
newest row of the domain's label table (D-RO17-2). A rename is a new row, so
History, Comparison and every reading stay under the one code (D-RO17-6).

The label resolves on upload **after** every existing route (D-RO17-3), so
`clash` refuses a label that would collide with anything that resolves
today (D-RO17-4). The aliases screen (D-RO17-13) lists every spelling that
resolves to a point of one list and lets an Admin retire one, unless that
would leave stored readings of a committed batch with a spelling that no
longer resolves.

Every write takes `lock_list` first and writes its `audit_event` in the same
transaction. Never a plant code in a rule (D-RO17-15).
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import Connection

from app.domain.cleaner import Cleaner
from app.domain.film import normalise_location
from app.domain.references import normalise_alias
from app.domain.ws_plant_gold import gold_key
from app.repositories import audit
from app.repositories import filmthickness as film_repo
from app.repositories import point_labels as repo
from app.repositories.reference import load_reference_data
from app.services.workbooks import WorkbookError, resolve_plant

DOMAINS = ("wavescan", "film")
RENAME_ACTION = "catalogue.point_label.rename"
ALIAS_RETIRE_ACTION = "catalogue.point_alias.retire"
_WORD = {"wavescan": "Wave Scan", "film": "Film"}
#: The kinds of the aliases screen, per domain.
KINDS = {
    "wavescan": ("zone_map", "global_alias", "earlier_label"),
    "film": ("film_alias", "location_map", "earlier_label", "not_a_point"),
}


def _domain(domain: str) -> str:
    if domain not in DOMAINS:
        raise WorkbookError(422, f"{domain!r} is not a domain; use wavescan or film.")
    return domain


def lock_list(conn: Connection, domain: str, plant: str, model: str) -> None:
    """Every point / label write of a list takes this first."""
    repo.lock_list(conn, _domain(domain), plant, model)


def norm(domain: str, label: str) -> str:
    """The domain's own normaliser: `normalise_alias` / `normalise_location`."""
    return normalise_alias(label) if _domain(domain) == "wavescan" else normalise_location(label)


def current_labels(conn: Connection, domain: str, plant: str, model: str) -> dict[str, str]:
    """``{code: current label}`` for every point (live and retired) of a list."""
    return {p["code"]: p["label"] for p in repo.points(conn, _domain(domain), plant, model)}


def resolver(conn: Connection, domain: str, plant: str) -> Callable[[str, str], str | None]:
    """``(model, raw label) -> code`` the way an upload at ``plant`` resolves today."""
    if domain == "wavescan":
        cleaner = Cleaner(load_reference_data(conn), (plant,), expected_plant=plant)
        return lambda model, raw: cleaner.resolve_checkzone(plant, model, raw)
    ref = film_repo.load_film_reference(conn)
    return lambda model, raw: ref.resolve_point(plant, model, raw)


def clash(
    conn: Connection, domain: str, plant: str, model: str, label: str, *, for_code: str
) -> str | None:
    """D-RO17-4. None when ``label`` may be ``for_code``'s; else one sentence.

    Within this plant x model x domain only: another plant's word that
    differs by case or spaces is no clash (labels are per plant).

    D-RO17F-3: a label may be another point's code only when that spelling
    already resolves here to ``for_code`` (an approved map or alias answers
    before the code), e.g. SAP's shifted Film numbering.
    """
    key = norm(domain, label)
    word = _WORD[domain]
    found = repo.points(conn, domain, plant, model)
    live = {p["code"]: p for p in found if p["live"]}
    target = resolver(conn, domain, plant)(model, label)
    mapped = target == for_code and norm(domain, label) != norm(domain, for_code)
    for code, p in live.items():
        if code == for_code:
            continue
        if norm(domain, code) == key or (
            domain == "wavescan" and gold_key(code) == gold_key(label)
        ):
            if mapped:
                continue
            return (
                f"{label!r} is the code of point {code} on {plant}'s {model} "
                f"{word} list."
            )
    for row in repo.label_rows(conn, domain, plant, model):
        if (
            row["code"] != for_code and row["code"] in live
            and row["retired_at"] is None and row["label_norm"] == key
        ):
            if mapped and norm(domain, row["code"]) == key:
                continue  # that point's own code as its label, see above
            which = "label" if row["is_current"] else "earlier label"
            return (
                f"{label!r} is the {which} {row['label']!r} of point "
                f"{row['code']} on {plant}'s {model} {word} list."
            )
    if domain == "wavescan" and gold_key(label) == gold_key(for_code):
        # A live Wave Scan point's own code is gold, answered before every
        # other route (T58), so nothing else can take it (T114 add of an
        # existing code that today resolves by name elsewhere).
        return None
    if target is not None and target != for_code:
        return (
            f"A file that writes {label!r} at {plant} already loads onto point "
            f"{target} of the {model} {word} list."
        )
    return None


def insert_label(
    conn: Connection, domain: str, plant: str, model: str, code: str, label: str,
    *, reason: str, actor: str | None,
) -> int:
    """A new label row (INSERT only). Returns its ``label_id``."""
    written = str(label).strip()
    return repo.insert_label(
        conn, _domain(domain), plant=plant, model=model, code=code, label=written,
        label_norm=norm(domain, written), reason=reason, actor=actor,
    )


def has_label(conn: Connection, domain: str, plant: str, model: str, code: str) -> bool:
    """Does this point have any label row? (Not one added or restored by old code.)"""
    return any(r["code"] == code for r in repo.label_rows(conn, _domain(domain), plant, model))


def plant_labels(conn: Connection, plant_code: str, domain: str | None = None) -> dict:
    """Route #1: every point of every list of the plant, with its label."""
    plant = resolve_plant(conn, plant_code)["plant_code"]
    items = []
    for d in ([_domain(domain)] if domain else DOMAINS):
        items += [
            {"domain": d, "model_code": p["model_code"], "code": p["code"],
             "label": p["label"], "live": bool(p["live"])}
            for p in repo.points(conn, d, plant)
        ]
    return {"plant_code": plant, "items": items}


def rename(
    conn: Connection, domain: str, plant_code: str, model_code: str, *,
    code: str, label: str, reason: str, actor: str | None,
    correlation_id: str | None,
) -> dict:
    """D-RO17-6: a new label row. Nothing else moves."""
    domain = _domain(domain)
    plant = resolve_plant(conn, plant_code)["plant_code"]
    model = str(model_code).strip()
    code = str(code).strip()
    word = _WORD[domain]
    lock_list(conn, domain, plant, model)
    found = repo.points(conn, domain, plant, model)
    if not found:
        raise WorkbookError(
            404, f"{plant} has no {word} point list for {model!r}. Nothing was changed."
        )
    point = next((p for p in found if p["code"] == code), None)
    if point is None:
        raise WorkbookError(
            404,
            f"{code or '(blank)'} is not a point of {plant}'s {model} {word} "
            f"list. Nothing was changed.",
        )
    if not point["live"]:
        raise WorkbookError(
            409,
            f"{code} is retired at {plant}'s {model}; restore it first. "
            f"Nothing was changed.",
        )
    written = str(label).strip()
    if not written:
        raise WorkbookError(422, "Write the label. Nothing was changed.")
    previous = point["label"]
    if written == previous:
        raise WorkbookError(
            409, f"{code} is already labelled {written!r}. Nothing was changed."
        )
    sentence = clash(conn, domain, plant, model, written, for_code=code)
    if sentence:
        raise WorkbookError(409, f"{sentence} Nothing was changed.")
    label_id = insert_label(
        conn, domain, plant, model, code, written, reason=reason, actor=actor
    )
    audit_id = audit.record(
        conn,
        action=RENAME_ACTION,
        entity_type=repo.TABLES[domain][0],
        entity_id=f"{plant}:{model}:{code}",
        actor_user_id=actor or None,
        after={
            "label": written, "previous_label": previous, "label_id": label_id,
            "reason": reason, "owner_decision": "RO17 D-RO17-6",
        },
        correlation_id=correlation_id,
    )
    return {
        "domain": domain, "model_code": model, "code": code, "label": written,
        "previous_label": previous, "label_id": label_id, "audit_id": audit_id,
        "operator_message": (
            f"Point {code} of {plant}'s {model} {word} list is now labelled "
            f"{written!r}. Its readings stay under {code}, so History and "
            f"Comparison keep one series; {previous!r} still loads onto it."
        ),
    }


# =====================================================================
# the aliases screen (D-RO17-13)
# =====================================================================
def _alias_rows(conn: Connection, domain: str, plant: str, model: str) -> list[dict]:
    """Every spelling that names a point of this list, by kind, unsorted."""
    labels = current_labels(conn, domain, plant, model)
    out: list[dict] = []

    def add(kind, alias_id, spelling, key, code, *, shared=False, note=None,
            created_at=None, retired_at=None, retired_reason=None, live=None):
        live = retired_at is None if live is None else live
        out.append({
            "kind": kind, "alias_id": str(alias_id), "spelling": spelling,
            "key": key, "code": code, "code_label": labels.get(code, code),
            "shared": shared, "retirable": not shared and retired_at is None,
            "live": live, "note": note, "created_at": created_at,
            "not_a_point": kind == "not_a_point",
            "retired_at": retired_at, "retired_reason": retired_reason,
        })

    if domain == "wavescan":
        for r in repo.zone_map_rows(conn, plant, model):
            add("zone_map", r["map_id"], r["raw_zone_text"],
                normalise_alias(r["raw_zone_text"]), r["zone_code"],
                note=r["note"], created_at=r["created_at"],
                retired_at=r["retired_at"], retired_reason=r["retired_reason"])
        for r in repo.global_alias_rows(conn, plant, model):
            add("global_alias", r["raw_value"], r["raw_value"],
                normalise_alias(r["raw_value"]), r["zone_code"], shared=True,
                note=r["note"])
    else:
        for r in repo.film_alias_rows(conn, plant, model):
            add("film_alias", r["alias_id"], r["raw_location_norm"],
                r["raw_location_norm"], r["point_code"], note=r["note"],
                created_at=r["created_at"], retired_at=r["retired_at"],
                retired_reason=r["retired_reason"])
        for r in repo.location_map_rows(conn, plant, model):
            add("location_map", r["raw_location_norm"], r["raw_location_norm"],
                r["raw_location_norm"], r["point_code"], note=r["note"],
                created_at=r["created_at"], retired_at=r["retired_at"],
                retired_reason=r["retired_reason"])
        # RO18 (B5): "Not a point of this list" -- a spelling kept and never
        # loaded. It names no point, so ``code`` is empty.
        for r in film_repo.tail_labels(conn, plant, model, not_a_point=True):
            add("not_a_point", r["label_norm"], r["label_norm"], r["label_norm"],
                "", note=r["note"], created_at=r["created_at"],
                retired_at=r["retired_at"], retired_reason=r["retired_reason"])
    for r in repo.label_rows(conn, domain, plant, model):
        if r["is_current"]:
            continue  # the current label is on Point Check, renamed not retired
        add("earlier_label", r["label_id"], r["label"], r["label_norm"], r["code"],
            note=r["reason"], created_at=r["set_at"], retired_at=r["retired_at"],
            retired_reason=r["retired_reason"],
            live=r["retired_at"] is None and bool(r["point_live"]))
    return out


def _list_scope(conn: Connection, domain: str, plant_code: str, model_code: str):
    domain = _domain(domain)
    plant = resolve_plant(conn, plant_code)["plant_code"]
    model = str(model_code).strip()
    if not repo.points(conn, domain, plant, model):
        raise WorkbookError(
            404, f"{plant} has no {_WORD[domain]} point list for {model!r}."
        )
    return domain, plant, model


def aliases(conn: Connection, plant_code: str, domain: str, model_code: str) -> dict:
    """Route #3: every alias of one list, with the stored readings each names."""
    domain, plant, model = _list_scope(conn, domain, plant_code, model_code)
    facts: dict[str, int] = {}
    for raw, n in repo.raw_label_counts(conn, domain, plant, model):
        facts[norm(domain, raw)] = facts.get(norm(domain, raw), 0) + n
    items = []
    for row in _alias_rows(conn, domain, plant, model):
        row["stored_facts"] = facts.get(row.pop("key"), 0)
        items.append(row)
    return {"plant_code": plant, "domain": domain, "model_code": model, "items": items}


def retire_alias(
    conn: Connection, plant_code: str, domain: str, model_code: str, *,
    kind: str, alias_id: str, reason: str, actor: str | None,
    correlation_id: str | None,
) -> dict:
    """Route #4 (Admin). Append-only retire of one spelling; repoint = retire
    + teach again."""
    domain, plant, model = _list_scope(conn, domain, plant_code, model_code)
    if kind not in KINDS[domain]:
        raise WorkbookError(
            422, f"{kind!r} is not an alias kind of {_WORD[domain]}. Nothing was changed."
        )
    if kind == "global_alias":
        raise WorkbookError(
            409,
            f"{alias_id!r} is a global alias, shared by all plants: it is "
            f"read-only here. Nothing was changed.",
        )
    lock_list(conn, domain, plant, model)
    alias_id = str(alias_id).strip()
    row = next(
        (r for r in _alias_rows(conn, domain, plant, model)
         if r["kind"] == kind and r["alias_id"] == alias_id),
        None,
    )
    if row is None:
        if kind == "earlier_label" and any(
            str(r["label_id"]) == alias_id and r["is_current"]
            for r in repo.label_rows(conn, domain, plant, model)
        ):
            raise WorkbookError(
                409,
                "That is the point's current label; rename it instead. "
                "Nothing was changed.",
            )
        raise WorkbookError(
            404,
            f"No {kind} {alias_id!r} on {plant}'s {model} {_WORD[domain]} list. "
            f"Nothing was changed.",
        )
    if row["retired_at"] is not None:
        raise WorkbookError(
            409, f"{row['spelling']!r} is already retired. Nothing was changed."
        )
    table_kind = f"earlier_label:{domain}" if kind == "earlier_label" else kind
    why = f"RO17 (D-RO17-13): retired on the aliases screen -- {reason}"

    # D-RO17-13: rebuild the reference without this one entry (inside a
    # savepoint that is always rolled back) and count the stored readings of
    # committed batches that resolve now and would resolve to nothing after.
    facts = repo.raw_label_counts(conn, domain, plant, model)
    before = resolver(conn, domain, plant)
    savepoint = conn.begin_nested()
    try:
        repo.retire_row(conn, table_kind, plant=plant, model=model,
                        alias_id=alias_id, reason=why)
        after = resolver(conn, domain, plant)
        orphaned = sum(
            n for raw, n in facts
            if before(model, raw) is not None and after(model, raw) is None
        )
    finally:
        savepoint.rollback()
    if orphaned:
        raise WorkbookError(
            409,
            f"Retiring it would leave {orphaned} stored reading(s) of {plant}'s "
            f"{model} with a spelling that no longer resolves. Teach that "
            f"spelling another way first. Nothing was changed.",
        )
    if repo.retire_row(conn, table_kind, plant=plant, model=model,
                       alias_id=alias_id, reason=why) != 1:
        raise WorkbookError(
            409,
            f"{row['spelling']!r} was not retired: somebody may have retired "
            f"it a moment ago. Nothing was changed.",
        )
    audit_id = audit.record(
        conn,
        action=ALIAS_RETIRE_ACTION,
        entity_type=repo.TABLES[domain][0] if kind == "earlier_label" else kind,
        entity_id=f"{plant}:{model}:{kind}:{alias_id}"[:200],
        actor_user_id=actor or None,
        before={"spelling": row["spelling"], "code": row["code"]},
        after={"retired_reason": why[:300], "owner_decision": "RO17 D-RO17-13"},
        correlation_id=correlation_id,
    )
    return {
        "kind": kind, "alias_id": alias_id, "audit_id": audit_id,
        "operator_message": (
            f"{row['spelling']!r} no longer loads onto {row['code']} at "
            f"{plant}'s {model}. The record stays. To point it at another "
            f"point, teach it again from the review."
        ),
    }


__all__ = [
    "DOMAINS",
    "aliases",
    "clash",
    "current_labels",
    "has_label",
    "insert_label",
    "lock_list",
    "norm",
    "plant_labels",
    "rename",
    "resolver",
    "retire_alias",
]
