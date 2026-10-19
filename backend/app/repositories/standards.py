"""Admin catalogue SQL. Append-only cf_standard. No DELETE. No grading_family.

Ford/Min are plant x family (ADR 0012); plant_code NULL rows are the seed
fallback.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.repositories import audit as audit_repo
from app.schemas.standards import PLANTS

WORKBOOK_HASH = "b9f54fcd8c921eb10b834f59ddafcf4c07369857fc3b2dedff45e855640aacd8"


class StandardsConflict(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StandardsNotFound(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StandardsNotThisDomain(Exception):
    """T46 (F5): a FilmThickness-only model on a WaveScan catalogue route."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _require_wavescan_model(conn: Connection, model_code: str) -> None:
    ok = conn.execute(
        text("SELECT wavescan_ok FROM ref_model WHERE model_code = :m"),
        {"m": model_code},
    ).scalar()
    if ok is False:
        raise StandardsNotThisDomain(
            f"model {model_code!r} is a FilmThickness-only model "
            f"(wavescan_ok = false). It is not offered on the WaveScan "
            f"catalogue: not this domain."
        )


def family_by_code(conn: Connection, family_code: str) -> dict | None:
    row = conn.execute(
        text(
            "SELECT family_code, family_name, display_order "
            "FROM ref_color_family WHERE family_code = :c"
        ),
        {"c": family_code.strip().upper()},
    ).mappings().first()
    return dict(row) if row else None


def family_by_name(conn: Connection, family_name: str) -> dict | None:
    row = conn.execute(
        text(
            "SELECT family_code, family_name, display_order "
            "FROM ref_color_family WHERE family_name = :n"
        ),
        {"n": family_name},
    ).mappings().first()
    return dict(row) if row else None


def color_exists(conn: Connection, color_name: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM ref_color WHERE color_name = :n"),
        {"n": color_name},
    ).first() is not None


def _refuse_merged_color(conn: Connection, color_name: str) -> None:
    """T64 (ADR 0014): a merged name is read as its canonical name and is
    never offered or given a family again; edit the canonical name."""
    canonical = conn.execute(
        text("SELECT merged_into FROM ref_color WHERE color_name = :n"),
        {"n": color_name},
    ).scalar()
    if canonical is not None:
        raise StandardsNotThisDomain(
            f"{color_name!r} is merged into {canonical!r}. Set the plant offer "
            f"and family on {canonical!r}."
        )


def model_exists(conn: Connection, model_code: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM ref_model WHERE model_code = :n"),
        {"n": model_code},
    ).first() is not None


def _latest_family_targets(conn: Connection) -> dict[tuple[str | None, str], dict]:
    """Latest FAMILY row per (plant_code, family, orient) by created_at.

    ADR 0012: plant_code NULL is the seed fallback. ``effective_from`` is
    stored for audit and does not choose the row.
    """
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (plant_code, family_name, orient)
                   plant_code, family_name, orient, ford, min, effective_from
              FROM cf_standard
             WHERE scope = 'FAMILY'
             ORDER BY plant_code, family_name, orient,
                      created_at DESC, effective_from DESC
            """
        )
    ).mappings().all()
    latest: dict[tuple[str | None, str], dict] = {}
    for row in rows:
        bucket = latest.setdefault((row["plant_code"], row["family_name"]), {})
        bucket["h" if row["orient"] == "H" else "v"] = row
    return latest


def _targets_out(h: dict | None, v: dict | None) -> dict:
    return {
        "ford_h": int(h["ford"]) if h else None,
        "ford_v": int(v["ford"]) if v else None,
        "min_h": int(h["min"]) if h else None,
        "min_v": int(v["min"]) if v else None,
        "effective_from": (h or v)["effective_from"] if (h or v) else None,
    }


def catalogue(conn: Connection) -> dict:
    families = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT family_code, family_name, display_order "
                "FROM ref_color_family ORDER BY display_order"
            )
        ).mappings().all()
    ]
    targets = _latest_family_targets(conn)
    family_out = []
    for family in families:
        seed = targets.get((None, family["family_name"]), {})
        plants = []
        for plant in PLANTS:
            own = targets.get((plant, family["family_name"]), {})
            h = own.get("h") or seed.get("h")
            v = own.get("v") or seed.get("v")
            plants.append(
                {
                    "plant_code": plant,
                    "plant_specific": bool(own),
                    **_targets_out(h, v),
                }
            )
        family_out.append(
            {
                **family,
                **_targets_out(seed.get("h"), seed.get("v")),
                "plants": plants,
            }
        )

    plant_colors = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT pc.plant_code, pc.color_name, pc.is_offered, "
                "       pc.family_name, f.family_code "
                "  FROM ref_plant_color pc "
                "  LEFT JOIN ref_color_family f ON f.family_name = pc.family_name"
            )
        ).mappings().all()
    ]
    by_color: dict[str, dict[str, dict]] = {}
    for row in plant_colors:
        by_color.setdefault(row["color_name"], {})[row["plant_code"]] = row
    colors = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT color_name, color_group FROM ref_color "
                "WHERE is_active ORDER BY color_name"
            )
        ).mappings().all()
    ]
    color_out = []
    for color in colors:
        plants = []
        for plant in PLANTS:
            hit = by_color.get(color["color_name"], {}).get(plant)
            plants.append(
                {
                    "plant_code": plant,
                    "is_offered": bool(hit["is_offered"]) if hit else False,
                    "family_code": hit["family_code"] if hit else None,
                    "family_name": hit["family_name"] if hit else None,
                }
            )
        color_out.append({**color, "plants": plants})

    series_rows = [
        r[0]
        for r in conn.execute(
            text("SELECT series_code FROM ref_model_series ORDER BY series_code")
        ).all()
    ]
    models = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT model_code, series_code, body_style, expected_zone_count "
                "FROM ref_model WHERE is_active AND wavescan_ok "
                "ORDER BY model_code"
            )
        ).mappings().all()
    ]
    plant_models = {
        (r["plant_code"], r["model_code"]): bool(r["is_offered"])
        for r in conn.execute(
            text("SELECT plant_code, model_code, is_offered FROM ref_plant_model")
        ).mappings().all()
    }
    series_out = []
    for series in series_rows:
        members = []
        for model in models:
            if model["series_code"] != series:
                continue
            members.append(
                {
                    "model_code": model["model_code"],
                    "body_style": model["body_style"],
                    "expected_zone_count": model["expected_zone_count"],
                    "plants": [
                        {
                            "plant_code": plant,
                            "is_offered": plant_models.get((plant, model["model_code"]), False),
                        }
                        for plant in PLANTS
                    ],
                }
            )
        series_out.append({"series_code": series, "models": members})

    return {"families": family_out, "colors": color_out, "series": series_out}



def model_points(conn: Connection, plant_code: str) -> list[dict]:
    """T112 / T112-FIX (D-112F-6): the Model screen's cards for one plant.

    Exactly the active models **offered** here (``ref_plant_model.is_offered``),
    Wave Scan and FilmThickness-only alike: since T112-FIX the offer is the
    gate both domains' ingest reads, so the card is the offer and Remove takes
    it away. Each count is live **and counted** points: Film counted is the
    latest ``film_point_setting``, Wave Scan counted the latest
    ``ws_point_setting`` (T114, D-114-10); no row = counted in both. One
    read, both screens.
    """
    rows = conn.execute(
        text(
            """
            WITH film AS (
                SELECT c.model_code,
                       count(*) FILTER (WHERE COALESCE(s.counted, true)) AS n
                  FROM ref_plant_film_point c
                  LEFT JOIN LATERAL (
                       SELECT counted FROM film_point_setting ps
                        WHERE ps.plant_code = c.plant_code
                          AND ps.model_code = c.model_code
                          AND ps.point_code = c.point_code
                        ORDER BY ps.setting_id DESC LIMIT 1
                       ) s ON true
                 WHERE c.plant_code = :plant AND c.retired_at IS NULL
                 GROUP BY c.model_code
            ), ws AS (
                SELECT p.model_code,
                       count(*) FILTER (WHERE COALESCE(s.counted, true)) AS n
                  FROM ref_plant_ws_point p
                  LEFT JOIN LATERAL (
                       SELECT counted FROM ws_point_setting ws
                        WHERE ws.plant_code = p.plant_code
                          AND ws.model_code = p.model_code
                          AND ws.zone_code = p.zone_code
                        ORDER BY ws.setting_id DESC LIMIT 1
                       ) s ON true
                 WHERE p.plant_code = :plant AND p.retired_at IS NULL
                 GROUP BY p.model_code
            )
            SELECT m.model_code, m.display_name, m.series_code, m.body_style,
                   m.wavescan_ok, ws.n AS ws_n, film.n AS film_n
              FROM ref_model m
              JOIN ref_plant_model pm
                ON pm.plant_code = :plant AND pm.model_code = m.model_code
              LEFT JOIN ws ON ws.model_code = m.model_code
              LEFT JOIN film ON film.model_code = m.model_code
             WHERE m.is_active AND pm.is_offered
             ORDER BY m.series_code, m.model_code
            """
        ),
        {"plant": plant_code},
    ).mappings().all()
    return [
        {
            "model_code": r["model_code"],
            "display_name": r["display_name"],
            "series_code": r["series_code"],
            "body_style": r["body_style"],
            "wavescan_ok": bool(r["wavescan_ok"]),
            "wavescan_offered": bool(r["wavescan_ok"]),
            # None = no live list in that domain at this plant; the card omits it.
            # A Wave Scan count on a Film-only model is never shown (D-112F-6).
            "wavescan_points": (
                None if r["ws_n"] is None or not r["wavescan_ok"] else int(r["ws_n"])
            ),
            "film_points": None if r["film_n"] is None else int(r["film_n"]),
        }
        for r in rows
    ]


def attachable_models(conn: Connection, plant_code: str) -> list[str]:
    """T112-FIX (D-112F-4): every active model not offered here, Film-only too."""
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT m.model_code FROM ref_model m "
                "LEFT JOIN ref_plant_model pm "
                "  ON pm.plant_code = :plant AND pm.model_code = m.model_code "
                "WHERE m.is_active AND NOT COALESCE(pm.is_offered, false) "
                "ORDER BY m.model_code"
            ),
            {"plant": plant_code},
        ).all()
    ]

def mint_color(
    conn: Connection,
    *,
    color_name: str,
    family_code: str,
    plants: list[str],
    color_group: str | None,
    actor_user_id: str,
    correlation_id: str | None,
) -> dict:
    family = family_by_code(conn, family_code)
    if family is None:
        raise StandardsNotFound(f"unknown family code {family_code!r}")
    if color_exists(conn, color_name):
        raise StandardsConflict(f"colour {color_name!r} already exists")
    try:
        conn.execute(
            text(
                "INSERT INTO ref_color (color_name, color_group) "
                "VALUES (:n, :g)"
            ),
            {"n": color_name, "g": color_group},
        )
    except IntegrityError as exc:
        raise StandardsConflict(f"colour {color_name!r} already exists") from exc
    for plant in plants:
        conn.execute(
            text(
                "INSERT INTO ref_plant_color "
                "(plant_code, color_name, family_name, is_offered) "
                "VALUES (:p, :c, :f, true) "
                "ON CONFLICT (plant_code, color_name) DO UPDATE "
                "SET family_name = EXCLUDED.family_name, is_offered = true, "
                "    updated_at = now()"
            ),
            {"p": plant, "c": color_name, "f": family["family_name"]},
        )
    audit_id = audit_repo.record(
        conn,
        action="catalogue.color.mint",
        entity_type="ref_color",
        entity_id=color_name,
        actor_user_id=actor_user_id,
        after={"color_name": color_name, "family_code": family["family_code"], "plants": plants},
        correlation_id=correlation_id,
    )
    return {"color_name": color_name, "audit_id": audit_id}


def set_plant_color(
    conn: Connection,
    *,
    plant_code: str,
    color_name: str,
    is_offered: bool | None,
    family_code: str | None,
    actor_user_id: str,
    correlation_id: str | None,
) -> dict:
    if not color_exists(conn, color_name):
        raise StandardsNotFound(f"unknown colour {color_name!r}")
    _refuse_merged_color(conn, color_name)
    family_name = None
    if family_code:
        family = family_by_code(conn, family_code)
        if family is None:
            raise StandardsNotFound(f"unknown family code {family_code!r}")
        family_name = family["family_name"]
    existing = conn.execute(
        text(
            "SELECT is_offered, family_name FROM ref_plant_color "
            "WHERE plant_code = :p AND color_name = :c"
        ),
        {"p": plant_code, "c": color_name},
    ).mappings().first()
    offered = (
        is_offered
        if is_offered is not None
        else (bool(existing["is_offered"]) if existing else True)
    )
    family_name = family_name if family_name is not None else (
        existing["family_name"] if existing else None
    )
    conn.execute(
        text(
            "INSERT INTO ref_plant_color "
            "(plant_code, color_name, family_name, is_offered) "
            "VALUES (:p, :c, :f, :o) "
            "ON CONFLICT (plant_code, color_name) DO UPDATE "
            "SET family_name = EXCLUDED.family_name, "
            "    is_offered = EXCLUDED.is_offered, updated_at = now()"
        ),
        {"p": plant_code, "c": color_name, "f": family_name, "o": offered},
    )
    audit_id = audit_repo.record(
        conn,
        action="catalogue.plant_color.set",
        entity_type="ref_plant_color",
        entity_id=f"{plant_code}:{color_name}",
        actor_user_id=actor_user_id,
        before=dict(existing) if existing else None,
        after={"is_offered": offered, "family_name": family_name},
        correlation_id=correlation_id,
    )
    return {"audit_id": audit_id, "is_offered": offered, "family_name": family_name}


#: T115 (D-115-4): given the plants where a model has just become offered,
#: reload what its absence held there. Returns `reloaded_load_ids` and
#: `reload_refused`; both are merged into the Attach's own audit row.
Reload = Callable[[list[str]], dict]

#: What an Attach that reloaded nothing says.
NOTHING_RELOADED = {"reloaded_load_ids": [], "reload_refused": []}


def _reload(reload: Reload | None, plants: list[str]) -> dict:
    if reload is None or not plants:
        return dict(NOTHING_RELOADED)
    return {**NOTHING_RELOADED, **reload(plants)}


def attach_models(
    conn: Connection,
    *,
    model_code: str,
    plants: list[str],
    actor_user_id: str,
    correlation_id: str | None,
    reload: Reload | None = None,
) -> dict:
    if not model_exists(conn, model_code):
        raise StandardsNotFound(f"unknown model {model_code!r}")
    # T112-FIX (D-112F-4): an offer is now both domains' gate (Wave Scan and
    # Film ingest both read it), so a FilmThickness-only model is attached and
    # removed here like any other. `_require_wavescan_model` still guards every
    # Wave Scan-only write (standards, catalogue, colour families).
    current = {
        r[0]
        for r in conn.execute(
            text(
                "SELECT plant_code FROM ref_plant_model "
                "WHERE model_code = :m AND is_offered"
            ),
            {"m": model_code},
        ).all()
    }
    if plants and set(plants).issubset(current):
        raise StandardsConflict(
            f"model {model_code!r} is already attached at {', '.join(plants)}"
        )
    attached = []
    for plant in plants:
        conn.execute(
            text(
                "INSERT INTO ref_plant_model (plant_code, model_code, is_offered) "
                "VALUES (:p, :m, true) "
                "ON CONFLICT (plant_code, model_code) DO UPDATE "
                "SET is_offered = true"
            ),
            {"p": plant, "m": model_code},
        )
        attached.append(plant)
    # T115 (D-115-4): only where the offer was off or absent. Re-attaching a
    # plant that already offers the model reloads nothing.
    reloaded = _reload(reload, [p for p in attached if p not in current])
    audit_id = audit_repo.record(
        conn,
        action="catalogue.plant_model.attach",
        entity_type="ref_plant_model",
        entity_id=model_code,
        actor_user_id=actor_user_id,
        after={"model_code": model_code, "plants": attached, **reloaded},
        correlation_id=correlation_id,
    )
    return {"audit_id": audit_id, "plants": attached, **reloaded}


def set_plant_model_offered(
    conn: Connection,
    *,
    plant_code: str,
    model_code: str,
    is_offered: bool,
    actor_user_id: str,
    correlation_id: str | None,
    reload: Reload | None = None,
) -> dict:
    if not model_exists(conn, model_code):
        raise StandardsNotFound(f"unknown model {model_code!r}")
    # T112-FIX (D-112F-4): an offer is now both domains' gate (Wave Scan and
    # Film ingest both read it), so a FilmThickness-only model is attached and
    # removed here like any other. `_require_wavescan_model` still guards every
    # Wave Scan-only write (standards, catalogue, colour families).
    existing = conn.execute(
        text(
            "SELECT is_offered FROM ref_plant_model "
            "WHERE plant_code = :p AND model_code = :m"
        ),
        {"p": plant_code, "m": model_code},
    ).mappings().first()
    conn.execute(
        text(
            "INSERT INTO ref_plant_model (plant_code, model_code, is_offered) "
            "VALUES (:p, :m, :o) "
            "ON CONFLICT (plant_code, model_code) DO UPDATE "
            "SET is_offered = EXCLUDED.is_offered"
        ),
        {"p": plant_code, "m": model_code, "o": is_offered},
    )
    # T115 (D-115-4): false/absent -> true reloads; Remove never does.
    became_offered = is_offered and not (existing and existing["is_offered"])
    reloaded = _reload(reload, [plant_code] if became_offered else [])
    audit_id = audit_repo.record(
        conn,
        action="catalogue.plant_model.offered",
        entity_type="ref_plant_model",
        entity_id=f"{plant_code}:{model_code}",
        actor_user_id=actor_user_id,
        before=dict(existing) if existing else None,
        after={"is_offered": is_offered, **reloaded},
        correlation_id=correlation_id,
    )
    return {"audit_id": audit_id, "is_offered": is_offered, **reloaded}


def publish_family(
    conn: Connection,
    *,
    plant_code: str,
    family_code: str | None,
    family_name: str | None,
    ford_h: int,
    ford_v: int,
    min_h: int,
    min_v: int,
    effective_from: date,
    source_document: str | None,
    source_note: str,
    actor_user_id: str,
    correlation_id: str | None,
) -> dict:
    family = None
    if family_code:
        family = family_by_code(conn, family_code)
    if family is None and family_name:
        family = family_by_name(conn, family_name)
    if family is None:
        raise StandardsNotFound("unknown colour family")
    for orient, ford, minimum in (("H", ford_h, min_h), ("V", ford_v, min_v)):
        conn.execute(
            text(
                "INSERT INTO cf_standard "
                "(scope, plant_code, family_name, orient, ford, min, "
                " effective_from, source_document, source_note, created_by) "
                "VALUES ('FAMILY', :p, :f, :o, :ford, :mn, :eff, :doc, :note, :by)"
            ),
            {
                "p": plant_code,
                "f": family["family_name"],
                "o": orient,
                "ford": ford,
                "mn": minimum,
                "eff": effective_from,
                "doc": source_document,
                "note": source_note,
                "by": actor_user_id,
            },
        )
    audit_id = audit_repo.record(
        conn,
        action="standards.publish",
        entity_type="cf_standard",
        entity_id=f"{plant_code}:{family['family_code']}",
        actor_user_id=actor_user_id,
        after={
            "plant_code": plant_code,
            "family_code": family["family_code"],
            "family_name": family["family_name"],
            "ford_h": ford_h,
            "ford_v": ford_v,
            "min_h": min_h,
            "min_v": min_v,
            "effective_from": str(effective_from),
            "source_document": source_document,
        },
        correlation_id=correlation_id,
    )
    return {
        "plant_code": plant_code,
        "family_code": family["family_code"],
        "family_name": family["family_name"],
        "effective_from": effective_from,
        "audit_id": audit_id,
        "created_at": datetime.now(timezone.utc),
    }
