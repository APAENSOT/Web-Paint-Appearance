"""Model Studio 3D inspection-point profiles.

One reusable **default** layout per plant x exact canonical model x
measurement domain (``wavescan`` | ``film``), shared by every colour and
month at that plant. Different plants, models and domains never share or
inherit anchors.

Writes are **one point at a time** and append-only: placing or removing a
location is a new row with that point's next revision; a removal is a
tombstone. Optimistic concurrency is **per anchor**: ``expected_revision`` is
the revision of *that point* the editor loaded (null = never saved). Two
people editing different points both succeed and neither loses the other's
change; two writes to the same point cannot both land (UNIQUE), so the loser
gets 409 and reloads. A retry of a write already persisted by the same person
with the same content answers ``replayed: true`` and writes nothing.

Nothing here touches measurements, counted flags, grading, uploads, colour
appearance or the Point Check lists. Removing a location never retires or
changes the Standard point.
"""

from __future__ import annotations

from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from app.domain import model_assets as assets
from app.repositories import audit as audit_repo
from app.repositories import filmthickness as film_repo
from app.repositories import point_profiles as repo
from app.repositories import point_labels as label_repo
from app.repositories import ws_points as ws_repo
from app.services.history import resolve_plant

DOMAINS = ("wavescan", "film")
DOMAIN_LABEL = {"wavescan": "Wave Scan", "film": "Film Thickness"}
PLACE_ACTION = "model_studio.point_anchor.place"
REMOVE_ACTION = "model_studio.point_anchor.remove"
UNIQUE_VIOLATION = "23505"


class PointProfileError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ------------------------------------------------------------------ identity
def _identity(domain: str, point_key: str, point_no: int | None, **extra) -> dict:
    return {
        "point_key": point_key,
        "zone_code": point_key if domain == "wavescan" else None,
        "point_code": point_key if domain == "film" else None,
        "point_no": point_no,
        "label": point_key,
        "counted": extra.get("counted"),
        "is_extra": extra.get("is_extra"),
        "unavailable_reason": extra.get("unavailable_reason"),
        "retired_at": extra.get("retired_at"),
    }


def _lists(conn: Connection, plant: str, model: str, domain: str) -> tuple[dict, dict]:
    """``(live, retired)`` Point Check identities, each ``{point_key: identity}``,
    live in walk order. The same reads Point Check shows."""
    if domain == "wavescan":
        live_rows, retired_rows, key = (ws_repo.live_points(conn, plant, model),
                                        ws_repo.retired_points(conn, plant, model), "zone_code")
    else:
        live_rows, retired_rows, key = (film_repo.point_setting(conn, plant, model),
                                        film_repo.retired_points(conn, plant, model), "point_code")
    live = {r[key]: _identity(domain, r[key], r["point_no"], counted=bool(r["counted"]),
                              is_extra=bool(r["is_extra"]))
            for r in live_rows}
    retired = {r[key]: _identity(domain, r[key], r["point_no"], is_extra=bool(r["is_extra"]),
                                 unavailable_reason="retired", retired_at=r["retired_at"])
               for r in retired_rows}
    labels = {r["code"]: r["label"] for r in label_repo.points(conn, domain, plant, model)}
    for code, identity in (*live.items(), *retired.items()):
        identity["label"] = labels.get(code, code)
    return live, retired


def _resolve(conn: Connection, plant_code: str, model_code: str, domain: str) -> tuple[str, str]:
    plant = resolve_plant(conn, plant_code)["plant_code"]
    if domain not in DOMAINS:  # pragma: no cover - the route's enum refuses first
        raise PointProfileError(422, f"domain must be one of {DOMAINS}.")
    if not repo.model_exists(conn, model_code):
        raise PointProfileError(
            404,
            f"No canonical model {model_code!r}. Use the exact ref_model code; "
            f"aliases and similar names are not matched.",
        )
    return plant, model_code


# ------------------------------------------------------------------ shapes
def _anchor(row: dict, model: str) -> dict | None:
    if row is None or row["action"] != "place":
        return None
    supported = assets.supported_asset(model)
    return {
        "asset_version": row["asset_version"],
        "mesh_name": row["mesh_name"],
        "position": [row["pos_x"], row["pos_y"], row["pos_z"]],
        "normal": [row["nrm_x"], row["nrm_y"], row["nrm_z"]],
        "body_zone": row["body_zone"],
        "asset_compatible": supported is not None
        and row["asset_version"] == supported.asset_version,
    }


def _item(identity: dict, row: dict | None, model: str) -> dict:
    return {
        **identity,
        "revision": row["revision"] if row else None,
        "saved_at": row["saved_at"] if row else None,
        "saved_by": row["saved_by"] if row else None,
        "anchor": _anchor(row, model),
    }


def asset_descriptor(model: str) -> dict | None:
    asset = assets.supported_asset(model)
    if asset is None:
        return None
    return {
        "asset_version": asset.asset_version,
        "model_code": asset.model_code,
        "asset_path": asset.asset_path,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "coordinate_system": asset.coordinate_system,
        "meshes": [
            {"mesh_name": m.name, "bounds_min": list(m.bounds_min),
             "bounds_max": list(m.bounds_max), "body_zones": list(m.zones)}
            for m in asset.meshes
        ],
    }


# ------------------------------------------------------------------ read
def read(conn: Connection, plant_code: str, model_code: str, domain: str) -> dict:
    """The default layout. ``points``: every live Standard point in walk
    order, ``anchor: null`` when it has no location. ``unavailable``: saved
    locations whose point is retired or no longer on this list -- disclosed,
    never dropped, never remapped."""
    plant, model = _resolve(conn, plant_code, model_code, domain)
    live, retired = _lists(conn, plant, model, domain)
    latest = {r["point_key"]: r for r in repo.latest_per_point(conn, plant, model, domain)}
    count, last_saved_at = repo.profile_stats(conn, plant, model, domain)

    points = [_item(identity, latest.get(key), model) for key, identity in live.items()]
    unavailable = [
        _item(retired.get(key) or _identity(domain, key, None, unavailable_reason="not_on_list"),
              row, model)
        for key, row in sorted(latest.items())
        if key not in live and row["action"] == "place"
    ]
    return {
        "plant_code": plant,
        "model_code": model,
        "domain": domain,
        "state": "configured" if count else "unconfigured",
        "profile_revision": count,
        "last_saved_at": last_saved_at,
        "asset": asset_descriptor(model),
        "points": points,
        "unavailable": unavailable,
    }


# ------------------------------------------------------------------ writes
def _point(conn, plant, model, domain, point_key, point_no, *, live_only: bool) -> dict:
    live, retired = _lists(conn, plant, model, domain)
    where = f"{plant}'s {model} {DOMAIN_LABEL[domain]} list"
    identity = live.get(point_key)
    if identity is None and point_key in retired:
        if live_only:
            raise PointProfileError(
                422, f"{point_key} is retired from {where}; it cannot be placed. Nothing was saved."
            )
        identity = retired[point_key]
    if identity is None:
        raise PointProfileError(
            422, f"{point_key!r} is not a point of {where}. Nothing was saved."
        )
    if point_no is not None and point_no != identity["point_no"]:
        raise PointProfileError(
            422,
            f"{point_key} is point {identity['point_no']} on {where}, not {point_no}. "
            f"Reload the Point Check list. Nothing was saved.",
        )
    return identity


def save(
    conn: Connection, plant_code: str, model_code: str, domain: str, *,
    point_key: str, point_no: int | None, expected_revision: int | None,
    anchor: dict, actor: str, correlation_id: str | None,
) -> dict:
    """Place (or move) one live point. One transaction (the caller's)."""
    plant, model = _resolve(conn, plant_code, model_code, domain)
    identity = _point(conn, plant, model, domain, point_key, point_no, live_only=True)
    try:
        assets.validate_anchor(model_code=model, **anchor)
    except assets.AnchorError as exc:
        raise PointProfileError(422, f"{exc} Nothing was saved.") from exc
    return _write(conn, plant, model, domain, identity, expected_revision, anchor,
                  actor, correlation_id)


def remove(
    conn: Connection, plant_code: str, model_code: str, domain: str, *,
    point_key: str, point_no: int | None, expected_revision: int,
    actor: str, correlation_id: str | None,
) -> dict:
    """Remove one point's location (tombstone). The Standard point stays. A
    retired point's leftover location may be removed too."""
    plant, model = _resolve(conn, plant_code, model_code, domain)
    identity = _point(conn, plant, model, domain, point_key, point_no, live_only=False)
    return _write(conn, plant, model, domain, identity, expected_revision, None,
                  actor, correlation_id)


def _same(taken: dict, anchor: dict | None, actor: str) -> bool:
    """Is the row at the contested revision this caller's own earlier write?"""
    if str(taken["created_by"] or "") != (actor or ""):
        return False
    if anchor is None:
        return taken["action"] == "remove"
    return taken["action"] == "place" and (
        taken["asset_version"], taken["mesh_name"], taken["body_zone"],
        [taken["pos_x"], taken["pos_y"], taken["pos_z"]],
        [taken["nrm_x"], taken["nrm_y"], taken["nrm_z"]],
    ) == (
        anchor["asset_version"], anchor["mesh_name"], anchor.get("body_zone"),
        [float(v) for v in anchor["position"]], [float(v) for v in anchor["normal"]],
    )


def _write(conn, plant, model, domain, identity, expected, anchor, actor, correlation_id) -> dict:
    key = identity["point_key"]
    before = None
    if expected is not None:
        before = repo.at_revision(conn, plant, model, domain, key, expected)
        if before is None:
            raise _conflict(conn, plant, model, domain, key, expected)
    if anchor is None and (before is None or before["action"] == "remove"):
        latest = repo.at_revision(conn, plant, model, domain, key)
        if latest is not None and latest["revision"] != expected:
            raise _conflict(conn, plant, model, domain, key, expected)
        raise PointProfileError(422, f"{key} has no saved location to remove. Nothing was changed.")

    revision = (expected or 0) + 1
    try:
        # The savepoint keeps the request's transaction usable after the
        # UNIQUE violation, so the retry check below can still read.
        with conn.begin_nested():
            row = repo.insert(conn, plant=plant, model=model, domain=domain, point_key=key,
                              revision=revision, anchor=anchor, actor_user_id=actor)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != UNIQUE_VIOLATION:
            raise
        taken = repo.at_revision(conn, plant, model, domain, key, revision)
        if taken is not None and _same(taken, anchor, actor):
            return _written(plant, model, domain, identity, taken, replayed=True)
        raise _conflict(conn, plant, model, domain, key, expected) from exc

    audit_repo.record(
        conn,
        action=PLACE_ACTION if anchor else REMOVE_ACTION,
        entity_type="point_profile_anchor",
        entity_id=f"{plant}:{model}:{domain}:{key}",
        actor_user_id=actor or None,
        before=_audited(before),
        after=_audited(row),
        correlation_id=correlation_id,
    )
    return _written(plant, model, domain, identity, row, replayed=False)


def _audited(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {"revision": row["revision"], "action": row["action"],
            "asset_version": row["asset_version"], "mesh_name": row["mesh_name"],
            "body_zone": row["body_zone"],
            "position": [row["pos_x"], row["pos_y"], row["pos_z"]],
            "normal": [row["nrm_x"], row["nrm_y"], row["nrm_z"]]}


def _written(plant, model, domain, identity, row, *, replayed: bool) -> dict:
    return {"plant_code": plant, "model_code": model, "domain": domain,
            **_item(identity, row, model), "replayed": replayed}


def _conflict(conn, plant, model, domain, key, expected) -> PointProfileError:
    current = repo.at_revision(conn, plant, model, domain, key)
    if current is None:
        now = "it has no saved revision"
    else:
        state = "placed" if current["action"] == "place" else "location removed"
        now = f"the saved profile has revision {current['revision']} ({state})"
    return PointProfileError(
        409,
        f"{key} in {plant}'s {model} {DOMAIN_LABEL[domain]} layout changed: you sent "
        f"expected_revision {expected}, {now}. Reload it before saving. Nothing was written.",
    )
