"""Colour appearance profiles for Model Studio (T116).

One shade per plant x canonical colour, shared by every model and month.
Append-only: a save is a new revision; the latest wins (D-116-4). A merged
name passes its shade on by being *read* through its canonical colour, never
by copying (D-116-2). Nothing here touches facts, standards, families,
uploads or points (D-116-8). No grading.
"""

from __future__ import annotations

from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from app.repositories import audit as audit_repo
from app.repositories import color_appearance as repo
from app.services.history import resolve_plant

ACTION = "appearance.color.save"
UNIQUE_VIOLATION = "23505"


class ColorAppearanceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _appearance(row: dict, inherited_from: str | None = None) -> dict:
    return {
        "hex": row["hex"],
        "revision": row["revision"],
        "saved_at": row["saved_at"],
        "saved_by": row["saved_by"],
        "inherited_from": inherited_from,
    }


def read(conn: Connection, plant_code: str) -> dict:
    """D-116-6. ``items``: canonical colours offered here, each with its own
    latest shade, else the newest shade of a name merged into it. ``unavailable``:
    every other saved profile at this plant, so nothing saved is hidden."""
    plant = resolve_plant(conn, plant_code)["plant_code"]
    colors = repo.plant_colors(conn, plant)
    family = {c["color_name"]: c["family_name"] for c in colors}
    latest = {r["color_name"]: r for r in repo.latest_per_color(conn, plant)}

    items, shown = [], set()
    for c in colors:
        if not c["is_offered"] or c["merged_into"] is not None:
            continue
        name = c["color_name"]
        appearance = None
        if name in latest:
            appearance = _appearance(latest[name])
            shown.add(name)
        else:
            merged = [r for r in latest.values() if r["merged_into"] == name]
            if merged:
                newest = max(merged, key=lambda r: (r["saved_at"], r["appearance_id"]))
                appearance = _appearance(newest, inherited_from=newest["color_name"])
                shown.add(newest["color_name"])
        items.append({"color_name": name, "family_name": c["family_name"],
                      "appearance": appearance})

    unavailable = [
        {"color_name": name, "family_name": family.get(name),
         "appearance": _appearance(row)}
        for name, row in sorted(latest.items()) if name not in shown
    ]
    return {"plant_code": plant, "items": items, "unavailable": unavailable}


def save(
    conn: Connection,
    plant_code: str,
    color_name: str,
    *,
    hex_value: str,
    expected_revision: int | None,
    actor: str,
    correlation_id: str | None,
) -> dict:
    """D-116-7. One transaction (the caller's): validate, append, audit."""
    plant = resolve_plant(conn, plant_code)["plant_code"]
    found = repo.color(conn, color_name)
    if found is None:
        raise ColorAppearanceError(404, f"Unknown colour {color_name!r}.")
    if found["merged_into"] is not None:
        canonical = found["merged_into"]
        raise ColorAppearanceError(
            422, f"{color_name} is merged into {canonical}; save {canonical}."
        )
    if not repo.is_offered(conn, plant, color_name):
        raise ColorAppearanceError(
            422, f"{color_name} is not offered at {plant}; its appearance cannot be saved here."
        )

    before = None
    if expected_revision is not None:
        before = repo.at_revision(conn, plant, color_name, expected_revision)
        if before is None:
            raise _conflict(conn, plant, color_name, expected_revision)

    revision = (expected_revision or 0) + 1
    try:
        # The savepoint keeps the request's transaction usable after the
        # UNIQUE violation, so the retry check below can still read.
        with conn.begin_nested():
            row = repo.insert(conn, plant_code=plant, color_name=color_name,
                              revision=revision, hex_value=hex_value,
                              actor_user_id=actor)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != UNIQUE_VIOLATION:
            raise
        taken = repo.at_revision(conn, plant, color_name, revision)
        if (taken is not None and taken["hex"] == hex_value
                and str(taken["created_by"] or "") == (actor or "")):
            return {**_out(taken), "replayed": True}
        raise _conflict(conn, plant, color_name, expected_revision) from exc

    audit_repo.record(
        conn,
        action=ACTION,
        entity_type="color_appearance",
        entity_id=f"{plant}:{color_name}",
        actor_user_id=actor or None,
        before={"hex": before["hex"], "revision": before["revision"]} if before else None,
        after={"hex": row["hex"], "revision": row["revision"]},
        correlation_id=correlation_id,
    )
    return {**_out(row), "replayed": False}


def _out(row: dict) -> dict:
    return {"color_name": row["color_name"], "hex": row["hex"],
            "revision": row["revision"], "saved_at": row["saved_at"],
            "saved_by": row["saved_by"]}


def _conflict(
    conn: Connection, plant: str, color_name: str, expected: int | None
) -> ColorAppearanceError:
    current = repo.at_revision(conn, plant, color_name)
    now = (f"revision {current['revision']} ({current['hex']})" if current
           else "no saved revision")
    return ColorAppearanceError(
        409,
        f"{color_name} at {plant} changed: you sent expected_revision "
        f"{expected}, the saved profile is {now}. Reload it before saving.",
    )
