"""Load the reference data the domain needs, once per ingest run.

This is the half of the vault's ``ReferenceData`` that talks to PostgreSQL.
The other half -- the lookups -- is ``app/domain/references.py``, which has no
database in it at all, so the cleaning rules can be tested without one
(`00-ARCHITECTURE.md` §5 rule 1).

Only **approved** mappings are read. A `PROPOSED` zone map or an unapproved
column alias must never change what gets written to `wavescan`
(`02-PIPELINE.md` §4: "never auto-apply").
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.domain.reader import DOMAIN_WAVESCAN
from app.domain.references import ReferenceData, normalise_alias
from app.domain.ws_plant_gold import gold_key


def _alias(conn: Connection, table: str, target: str) -> dict[str, str]:
    rows = conn.execute(text(f"SELECT raw_value, {target} FROM {table}")).all()
    return {normalise_alias(raw): value for raw, value in rows}


def _global_alias(conn: Connection, table: str, target: str) -> dict[str, str]:
    """Only the rows that hold everywhere (T26, spec S11).

    A plant-scoped row means "this is what *this* plant writes", so it must
    not leak into the global map -- that is how a bare `P703` at one plant
    would silently become a Ranger at another.
    """
    rows = conn.execute(
        text(
            f"SELECT raw_value, {target} FROM {table} WHERE plant_code IS NULL"
        )
    ).all()
    return {normalise_alias(raw): value for raw, value in rows}


def _plant_alias(conn: Connection, table: str, target: str) -> dict[tuple[str, str], str]:
    """`(plant_code, normalised spelling) -> canonical`, approved rows only."""
    rows = conn.execute(
        text(
            f"SELECT plant_code, raw_value, {target} FROM {table} "
            f"WHERE plant_code IS NOT NULL"
        )
    ).all()
    return {(plant, normalise_alias(raw)): value for plant, raw, value in rows}


def load_reference_data(conn: Connection) -> ReferenceData:
    plant = _alias(conn, "ref_plant_alias", "plant_code")
    model = _global_alias(conn, "ref_model_alias", "model_code")
    checkzone = _alias(conn, "ref_checkzone_alias", "zone_code")
    # T53 (D-53-09): what the global checkzone guard needs to tell a plant's
    # own wording (`01 RRHOOD`, a noted typo) from a compact relabel.
    # T58 (D-58-01..09): each plant x model's live WaveScan gold.
    plant_gold: dict[tuple[str, str], dict[str, str]] = {}
    for p, m, zone in conn.execute(
        text(
            "SELECT plant_code, model_code, zone_code FROM ref_plant_ws_point "
            "WHERE retired_at IS NULL"
        )
    ).all():
        plant_gold.setdefault((p, m), {})[gold_key(zone)] = zone
    # RO16 (D-RO16-1): where each car of a blank-serial sheet starts.
    ws_first_point = {
        (p, m): zone for p, m, zone in conn.execute(
            text(
                "SELECT DISTINCT ON (plant_code, model_code) plant_code, "
                "model_code, point_code FROM v_point_walk_order "
                "WHERE domain='WAVESCAN' ORDER BY plant_code, model_code, walk_rank"
            )
        ).all()
    }
    # RO17 (D-RO17-3): every unretired label, current and earlier, of a live point.
    plant_ws_label = {
        (p, m, normalise_alias(label)): zone
        for p, m, label, zone in conn.execute(
            text(
                "SELECT l.plant_code, l.model_code, l.label, l.zone_code "
                "FROM ref_plant_ws_point_label l "
                "JOIN ref_plant_ws_point p USING (plant_code, model_code, zone_code) "
                "WHERE p.retired_at IS NULL AND l.retired_at IS NULL"
            )
        ).all()
    }
    zone_names = dict(
        conn.execute(text("SELECT zone_code, zone_name FROM ref_checkzone")).all()
    )
    checkzone_documented = frozenset(
        normalise_alias(raw) for (raw,) in conn.execute(
            text(
                "SELECT raw_value FROM ref_checkzone_alias "
                "WHERE nullif(btrim(note), '') IS NOT NULL"
            )
        ).all()
    )
    color = _global_alias(conn, "ref_color_alias", "color_name")
    model_by_plant = _plant_alias(conn, "ref_model_alias", "model_code")
    color_by_plant = _plant_alias(conn, "ref_color_alias", "color_name")
    paintline = _alias(conn, "ref_paintline_alias", "paintline_code")

    model_zone = frozenset(
        (m, z) for m, z in conn.execute(
            text("SELECT model_code, zone_code FROM ref_model_zone")
        ).all()
    )
    # T46: FilmThickness-only models carry expected_zone_count 0 and are no
    # WaveScan vehicle; completeness never counts them.
    expected_zones = dict(
        conn.execute(
            text(
                "SELECT model_code, expected_zone_count FROM ref_model "
                "WHERE wavescan_ok"
            )
        ).all()
    )
    film_only_models = frozenset(
        r[0] for r in conn.execute(
            text("SELECT model_code FROM ref_model WHERE NOT wavescan_ok")
        ).all()
    )

    plants = conn.execute(
        text("SELECT plant_code, requires_serial, is_active FROM ref_plant")
    ).all()
    requires_serial = {code: bool(req) for code, req, _ in plants}
    known_plants = frozenset(code for code, _, _ in plants)
    active_plants = frozenset(code for code, _, active in plants if active)

    # T29 (spec S15): APPROVED is not enough. A zone map reaches the cleaner
    # only when a named plant/quality owner proved it -- a proof hash and a
    # verifier on the row. An Admin visual approve with no proof stays in the
    # table as a record and stops being live. AAT/FTM are unaffected: their
    # labels resolve through ref_checkzone_alias, not this table.
    plant_zone_map = {
        (p, m, normalise_alias(raw)): zone
        for p, m, raw, zone in conn.execute(
            text(
                """
                SELECT plant_code, model_code, raw_zone_text, zone_code
                  FROM ref_plant_zone_map
                 WHERE confidence = 'APPROVED'
                   -- RO17 (D-RO17-13): a retired spelling no longer resolves.
                   AND retired_at IS NULL
                   AND (
                       (proof_hash IS NOT NULL AND verified_by IS NOT NULL)
                       -- T41 (D-31): one Engineer-confirmed spelling onto an
                       -- existing zone of that model. Its author and time are
                       -- approved_by / approved_at; it proves no pack.
                       OR proposal_method = 'ENGINEER_ALIAS'
                       -- T86 (D-86-1/4): one pair of a guided panel-match
                       -- set. Same standing as the T41 row above and, if
                       -- anything, a stronger one: an Engineer proposed the
                       -- whole set, an **Admin** approved it, the person who
                       -- said which panel each name is is named in the note
                       -- and in the audit row, and the set was applied all
                       -- or none. It proves no pack either, so it carries no
                       -- proof hash -- which is why it needs saying here.
                       -- (`repositories.mappings.PANEL_MATCH_METHOD`.)
                       OR proposal_method = 'T86_PANEL_MATCH'
                       -- T88 (G-88-6): the same pair, with the signal that
                       -- proposed it appended -- `T88_PANEL_MATCH_NAME`,
                       -- `_NUMBER`, `_EXHAUSTION`, `_NONE`. Its standing is
                       -- the T86 row's exactly; what changed is that the
                       -- method now records WHICH signal argued for it, so
                       -- a wrong exhaustion can be found again. Without
                       -- this line every pair the screen learns would be
                       -- written and never read -- the silent no-op T87
                       -- hit and guarded against.
                       OR proposal_method LIKE 'T88_PANEL_MATCH%'
                   )
                """
            )
        ).all()
    }

    # T26 (spec S6): only this domain's aliases are injected into the
    # reader. A FilmThickness row, when that domain exists, must not change
    # what `Panel` means to a WaveScan sheet.
    column_alias = {
        normalise_alias(raw): logical
        for raw, logical in conn.execute(
            text(
                "SELECT raw_header, logical_field FROM ref_column_alias "
                "WHERE is_approved AND domain = :domain"
            ),
            {"domain": DOMAIN_WAVESCAN},
        ).all()
    }
    known_color_names = frozenset(
        r[0]
        for r in conn.execute(
            text("SELECT color_name FROM ref_color WHERE is_active")
        ).all()
    )

    merged_colors = dict(
        conn.execute(
            text(
                "SELECT color_name, merged_into FROM ref_color "
                "WHERE merged_into IS NOT NULL"
            )
        ).all()
    )

    offered_colors = {
        (plant, color): bool(offered)
        for plant, color, offered in conn.execute(
            text(
                "SELECT plant_code, color_name, is_offered FROM ref_plant_color"
            )
        ).all()
    }
    color_family_at_plant = {
        (plant, color): family
        for plant, color, family in conn.execute(
            text(
                "SELECT plant_code, color_name, family_name FROM ref_plant_color"
            )
        ).all()
    }
    offered_models = {
        (plant, model): bool(offered)
        for plant, model, offered in conn.execute(
            text(
                "SELECT plant_code, model_code, is_offered FROM ref_plant_model"
            )
        ).all()
    }

    return ReferenceData(
        plant=plant,
        model=model,
        checkzone=checkzone,
        color=color,
        paintline=paintline,
        model_by_plant=model_by_plant,
        color_by_plant=color_by_plant,
        model_zone=model_zone,
        expected_zones=expected_zones,
        requires_serial=requires_serial,
        active_plants=active_plants,
        known_plants=known_plants,
        plant_zone_map=plant_zone_map,
        column_alias=column_alias,
        known_color_names=known_color_names,
        offered_colors=offered_colors,
        offered_models=offered_models,
        color_family_at_plant=color_family_at_plant,
        film_only_models=film_only_models,
        zone_names=zone_names,
        checkzone_documented=checkzone_documented,
        plant_gold=plant_gold,
        ws_first_point=ws_first_point,
        plant_ws_label=plant_ws_label,
        merged_colors=merged_colors,
    )


def plant_requires_serial(conn: Connection, plant_code: str | None) -> bool:
    """Does this plant's vehicle identity need a serial number?

    One column of one row, asked on the review read rather than loading the
    whole reference set: `GET /batches/{id}` needs this to say whether a
    batch is blocked by M7, and nothing else from `ReferenceData`.

    Defaults to True for an unknown or missing plant, the same default
    `Cleaner` uses: a plant added without the column keeps full protection.
    """
    if not plant_code:
        return True
    value = conn.execute(
        text("SELECT requires_serial FROM ref_plant WHERE plant_code = :p"),
        {"p": plant_code},
    ).scalar()
    return True if value is None else bool(value)
