"""RO19 measuring-order snapshots. INSERT only; all identities stay put."""
from __future__ import annotations

from sqlalchemy import Connection, text


def latest(conn: Connection, plant: str, model: str, domain: str) -> dict | None:
    row = conn.execute(text("SELECT version_id,set_by,set_at,reason FROM point_walk_version WHERE plant_code=:p AND model_code=:m AND domain=:d ORDER BY version_id DESC LIMIT 1"), {"p": plant, "m": model, "d": domain}).mappings().first()
    return dict(row) if row else None


def live(conn: Connection, plant: str, model: str, domain: str) -> list[dict]:
    return [dict(r) for r in conn.execute(text("SELECT point_code,point_no,walk_rank FROM v_point_walk_order WHERE plant_code=:p AND model_code=:m AND domain=:d ORDER BY walk_rank"), {"p": plant, "m": model, "d": domain}).mappings().all()]


def members(conn: Connection, version_id: int) -> list[str]:
    return list(conn.execute(text("SELECT point_code FROM point_walk_member WHERE version_id=:v ORDER BY walk_rank"), {"v": version_id}).scalars())


_CATALOGUE = {
    "FILMTHICKNESS": "SELECT point_code FROM ref_plant_film_point WHERE plant_code=:p AND model_code=:m",
    "WAVESCAN": "SELECT zone_code FROM ref_plant_ws_point WHERE plant_code=:p AND model_code=:m",
}


def catalogue_codes(conn: Connection, plant: str, model: str, domain: str) -> set[str]:
    """Every point of the list, retired included: a retired point can be restored."""
    return set(conn.execute(text(_CATALOGUE[domain]), {"p": plant, "m": model}).scalars())


def append_version(conn: Connection, plant: str, model: str, domain: str, codes: list[str], *, actor: str | None, reason: str) -> int:
    """Keep retired members' saved slots, replacing only the live sequence.

    Filtering retirement belongs to the view. Keeping those hidden members
    here means a later restore can recover its saved position, even after
    other live points have been moved in between.
    """
    previous = latest(conn, plant, model, domain)
    # point_walk_member has no FK, so a member whose point is gone would
    # otherwise ride along in every later version, naming nothing.
    known = catalogue_codes(conn, plant, model, domain)
    old = [code for code in (members(conn, previous["version_id"]) if previous else []) if code in known]
    live_set = set(codes)
    remaining = iter(codes)
    complete = [next(remaining) if code in live_set else code for code in old]
    complete.extend(remaining)
    version = int(conn.execute(text("INSERT INTO point_walk_version(plant_code,model_code,domain,set_by,reason) VALUES(:p,:m,:d,CAST(:actor AS uuid),:reason) RETURNING version_id"), {"p": plant, "m": model, "d": domain, "actor": actor or None, "reason": reason}).scalar_one())
    if complete:
        conn.execute(text("INSERT INTO point_walk_member(version_id,point_code,walk_rank) VALUES(:v,:c,:rank)"), [{"v": version, "c": code, "rank": rank} for rank, code in enumerate(complete, 1)])
    return version
