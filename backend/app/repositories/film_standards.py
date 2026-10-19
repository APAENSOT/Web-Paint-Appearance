"""FilmThickness micron standards SQL (T62). Append-only ``film_standard``.

INSERT and SELECT only: a new number is a new H + V pair, prior rows stay as
history (D-FS-03, D-FS-04). Each publish writes its ``audit_event`` on the
same connection, so both commit or neither does. No grading here.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.repositories import audit as audit_repo


class FilmStandardColorUnknown(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FilmStandardColorNotOffered(Exception):
    """D-FS-08: a per-colour rule needs the colour offered at that plant."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def latest(conn: Connection, plant_code: str) -> dict:
    """The latest row per (layer, colour-or-NULL, orient) at one plant.

    Mirrors ``standards._latest_family_targets``: latest ``created_at`` wins,
    ``id`` breaks a same-instant tie. T64 (ADR 0014): the colour is folded
    through ``ref_color.merged_into`` **before** DISTINCT ON, so the latest
    row across a merged name and its canonical name wins, listed under the
    canonical name. Also the plant's offered colours with
    their family, for context only (D-FS-01: family never selects a number).
    """
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (s.layer_code, folded, s.orient)
                   s.id, s.layer_code, folded AS color_name, s.orient,
                   s.lo, s.hi, s.target, s.source_document, s.source_note,
                   s.created_at
              FROM film_standard s
              LEFT JOIN ref_color rc ON rc.color_name = s.color_name
             CROSS JOIN LATERAL (
                   SELECT COALESCE(rc.merged_into, s.color_name) AS folded
             ) f
             WHERE s.plant_code = :p
             ORDER BY s.layer_code, folded, s.orient, s.created_at DESC, s.id DESC
            """
        ),
        {"p": plant_code},
    ).mappings().all()
    colors = conn.execute(
        text(
            "SELECT color_name, family_name FROM ref_plant_color "
            "WHERE plant_code = :p AND is_offered ORDER BY color_name"
        ),
        {"p": plant_code},
    ).mappings().all()
    return {"rules": [dict(r) for r in rows], "colors": [dict(c) for c in colors]}


def _require_offered(conn: Connection, plant_code: str, color_name: str) -> None:
    known = conn.execute(
        text("SELECT 1 FROM ref_color WHERE color_name = :c"),
        {"c": color_name},
    ).first()
    if known is None:
        raise FilmStandardColorUnknown(f"unknown colour {color_name!r}")
    offered = conn.execute(
        text(
            "SELECT is_offered FROM ref_plant_color "
            "WHERE plant_code = :p AND color_name = :c"
        ),
        {"p": plant_code, "c": color_name},
    ).scalar()
    canonical = conn.execute(
        text("SELECT merged_into FROM ref_color WHERE color_name = :c"),
        {"c": color_name},
    ).scalar()
    if canonical is not None:
        raise FilmStandardColorNotOffered(
            f"colour {color_name!r} is merged into {canonical!r} and is not "
            f"offered at {plant_code}. Publish on {canonical!r}."
        )
    if offered is not True:
        raise FilmStandardColorNotOffered(
            f"colour {color_name!r} is not offered at {plant_code}. A per-colour "
            f"film standard needs ref_plant_color.is_offered = true at that plant."
        )


def publish(
    conn: Connection,
    *,
    plant_code: str,
    layer_code: str,
    color_name: str | None,
    h: dict,
    v: dict,
    source_document: str | None,
    source_note: str,
    actor_user_id: str,
    correlation_id: str | None,
) -> dict:
    """Append the H row and the V row, then the audit event (one transaction)."""
    if color_name is not None:
        _require_offered(conn, plant_code, color_name)
    created_at = None
    for orient, rule in (("H", h), ("V", v)):
        created_at = conn.execute(
            text(
                "INSERT INTO film_standard "
                "(plant_code, layer_code, orient, color_name, lo, hi, target, "
                " source_document, source_note, created_by) "
                "VALUES (:p, :l, :o, :c, :lo, :hi, :t, :doc, :note, :by) "
                "RETURNING created_at"
            ),
            {
                "p": plant_code,
                "l": layer_code,
                "o": orient,
                "c": color_name,
                "lo": rule.get("lo"),
                "hi": rule.get("hi"),
                "t": rule.get("target"),
                "doc": source_document,
                "note": source_note,
                "by": actor_user_id or None,
            },
        ).scalar_one()
    audit_id = audit_repo.record(
        conn,
        action="film_standards.publish",
        entity_type="film_standard",
        entity_id=f"{plant_code}:{layer_code}:{color_name or '*'}",
        actor_user_id=actor_user_id,
        after={
            "plant_code": plant_code,
            "layer_code": layer_code,
            "color_name": color_name,
            "h": h,
            "v": v,
            "source_document": source_document,
            "source_note": source_note,
        },
        correlation_id=correlation_id,
    )
    return {
        "plant_code": plant_code,
        "layer_code": layer_code,
        "color_name": color_name,
        "audit_id": audit_id,
        "created_at": created_at,
    }
