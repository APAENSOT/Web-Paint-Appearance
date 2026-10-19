"""T46: the FilmThickness domain package (spec 2026-09-29, F1-F18).

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-29

Additive only: CREATE TABLE, ADD COLUMN, INSERT seed, GRANT, and two
function bodies re-created with one widened condition each. No DROP of
anything WaveScan owns, no UPDATE of a measurement, no DELETE grant.

1. **`ref_model`** gains ``wavescan_ok`` (existing rows true),
   ``expected_film_point_count`` and ``display_name``. Two FilmThickness-only
   models: ``P703 RAPCAP`` and ``P703 SGL`` (display *Single CAP*), both
   ``wavescan_ok = false`` with ``expected_zone_count = 0``. A CHECK makes 0
   legal only for such rows, so a WaveScan model can never lose its zone set
   by accident (F5).
2. **Point catalogue** ``ref_film_point`` / ``ref_model_film_point``: FVL P703
   gold 94 names for Ranger DBL **and** Raptor, FTM RAPCAP 93, FTM SGL 58
   (``app.domain.film_catalog``; provenance in
   ``docs/reports/evidence/FVL-P703-film-points.json``). Not ``ref_checkzone``.
3. **``ref_film_model_alias (plant_code, raw_token)``** (F4, F6, F7): FTM
   ``DBL``/``RAP``/``SGL``/``RB`` -> Ranger / RAPCAP / SGL / Raptor; AAT, FVL,
   SAP ``P703``/``DBL`` -> Ranger. No RAPCAP or RB row outside FTM. WaveScan's
   ``ref_model_alias`` is not touched: its ``P703 RAP`` stays Raptor.
4. **``ref_film_location_map``** (F10, S15 analog): owner-proved raw location
   -> point. Seeded **empty**; the loader reads only rows with a proof hash
   and a named verifier.
5. **``ref_column_alias``** FILMTHICKNESS rows (F3). WaveScan rows untouched;
   ``(domain, raw_header)`` is already the unique key (0009).
6. **``filmthickness``** facts (F9, F16): one row per (vehicle, point,
   layer), insert-only, the same duplicate / supersede / correction columns
   as ``wavescan``, a BEFORE INSERT refusal of pre-retired rows, and the
   ``filmthickness_active`` view (the one active-data helper for film reads).
7. **``reset_batch_staging``** also refuses a batch with film facts, and
   **``publish_template_profile``** accepts ``FILMTHICKNESS`` as a domain
   (the T26 WAVESCAN-only stop).
8. ``load_batch.domain`` / ``ref_column_alias.domain`` CHECK the two known
   vocabularies.

``app_rw``: SELECT on the new reference tables; SELECT + INSERT on
``filmthickness``; no UPDATE, no DELETE (ADR 0005). ``ck_batch_balance`` is
unchanged and holds for film batches, whose counts are source rows.

Downgrade refuses while any ``filmthickness`` row exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import op
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.film_catalog import MODEL_CATALOGUES  # noqa: E402

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

APP_ROLES = ("app_rw", "wavescan_loader")
DOMAINS = ("WAVESCAN", "FILMTHICKNESS")

#: (model_code, display_name) -- FilmThickness-only catalogue rows (F5).
FILM_ONLY_MODELS = (("P703 RAPCAP", "RAPCAP"), ("P703 SGL", "Single CAP"))

#: (plant, raw token, model) -- F4, F6, F7. FTM tokens are filename tokens;
#: the other plants' are the spelling their file or tab names carry.
FILM_MODEL_ALIASES = (
    ("FTM", "DBL", "P703 DBL RANGER"),
    ("FTM", "RAP", "P703 RAPCAP"),
    ("FTM", "SGL", "P703 SGL"),
    ("FTM", "RB", "P703 DBL RAPTOR"),
    ("AAT", "P703", "P703 DBL RANGER"),
    ("AAT", "DBL", "P703 DBL RANGER"),
    ("FVL", "P703", "P703 DBL RANGER"),
    ("FVL", "DBL", "P703 DBL RANGER"),
    ("SAP", "P703", "P703 DBL RANGER"),
    ("SAP", "DBL", "P703 DBL RANGER"),
)

#: FILMTHICKNESS header vocabulary (F3, D-FT-03a/b/c). Normalised exactly as
#: ``reader.normalise_header``: lower, trimmed, ``_`` -> space. A colour-named
#: Base column is deliberately absent: it is bound from the PELT ``Layer 2``
#: block or stays unreviewed (spec 5.5). ``Mid Grey``, ``EPIC``,
#: ``Ground-coat``, ``Basecoat1/2`` and ``L28 BC1`` are also absent: nobody
#: has said which layer they are, so they stay unreviewed (S9).
FILM_COLUMN_ALIASES = (
    ("location", "location"),
    ("checkzone", "location"),          # AAT July / August tabs
    ("e-coat", "ecoat"),
    ("e coat", "ecoat"),
    ("ecoat", "ecoat"),
    ("ec1", "ecoat"),
    ("ec1 mic", "ecoat"),
    ("prime", "primer"),
    ("primer", "primer"),
    ("mid grey prime", "primer"),
    ("mid grey primer", "primer"),
    ("white prime", "primer"),
    ("lt grey prime", "primer"),
    ("grey prime", "primer"),
    ("bc1", "primer"),
    ("bc1 mic", "primer"),
    ("bc2", "base"),
    ("bc2 mic", "base"),
    ("clearcoat", "clear"),
    ("clear coat", "clear"),
    ("cc1", "clear"),
    ("cc1 mic", "clear"),
    ("date", "date"),
    ("color", "color"),
    ("colour", "color"),
    ("job number", "job"),
    ("job", "job"),
    ("vin", "vin"),
    ("steel", "steel"),
    ("substrate", "steel"),
    ("thickness", "total_thickness"),
    ("total thickness", "total_thickness"),
    ("total mic", "total_thickness"),
    ("status", "status"),
    ("file name", "file_name"),
)

LAYER_CODES = ("ECOAT", "PRIMER", "BASE", "CLEAR")


def _for_each_role(sql: str) -> None:
    for role in APP_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                {sql.format(role=role)}
            END $$;
            """
        )


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# =====================================================================
def upgrade() -> None:
    conn = op.get_bind()
    _ref_model()
    _point_catalogue(conn)
    _film_model_alias(conn)
    _location_map()
    _column_aliases(conn)
    _facts()
    _functions(conn)
    _domain_checks()
    _grants()


def _ref_model() -> None:
    op.execute(
        """
        ALTER TABLE ref_model
            ADD COLUMN IF NOT EXISTS wavescan_ok boolean NOT NULL DEFAULT true,
            ADD COLUMN IF NOT EXISTS expected_film_point_count smallint,
            ADD COLUMN IF NOT EXISTS display_name text
        """
    )
    op.execute(
        "ALTER TABLE ref_model ADD CONSTRAINT ck_model_wavescan_zones CHECK ("
        "(wavescan_ok AND expected_zone_count > 0) OR "
        "(NOT wavescan_ok AND expected_zone_count = 0))"
    )
    op.execute(
        "ALTER TABLE ref_model ADD CONSTRAINT ck_model_film_points CHECK ("
        "expected_film_point_count IS NULL OR expected_film_point_count > 0)"
    )
    op.execute(
        "COMMENT ON COLUMN ref_model.wavescan_ok IS "
        "'T46 (F5). False for FilmThickness-only models (P703 RAPCAP, P703 SGL). "
        "WaveScan ingest holds such a model and the mapping / standards routes "
        "answer 422: it is not this domain.'"
    )
    op.execute(
        "COMMENT ON COLUMN ref_model.expected_film_point_count IS "
        "'T46 (F11, F12). Points a complete FilmBuild walk of this model has "
        "(ref_model_film_point). NULL for a model with no film catalogue.'"
    )
    for code, display in FILM_ONLY_MODELS:
        op.execute(
            "INSERT INTO ref_model (model_code, model_family, body_style, "
            "expected_zone_count, is_active, series_code, wavescan_ok, display_name) "
            f"VALUES ({_q(code)}, 'P703', 'PICKUP', 0, true, 'P703', false, "
            f"{_q(display)}) ON CONFLICT (model_code) DO NOTHING"
        )


def _point_catalogue(conn) -> None:
    op.execute(
        """
        CREATE TABLE ref_film_point (
            point_code  text PRIMARY KEY
                            CHECK (point_code = upper(btrim(point_code))
                                   AND length(point_code) > 0),
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ref_model_film_point (
            model_code  text NOT NULL REFERENCES ref_model (model_code),
            point_code  text NOT NULL REFERENCES ref_film_point (point_code),
            point_no    smallint NOT NULL CHECK (point_no > 0),
            PRIMARY KEY (model_code, point_code),
            CONSTRAINT uq_model_film_point_no UNIQUE (model_code, point_no)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_film_point IS "
        "'T46 (F10). FilmBuild point names. Not ref_checkzone: a film point is "
        "a PELT location label such as 001HOOD, and its identity is the name, "
        "never the walk order.'"
    )
    op.execute(
        "COMMENT ON COLUMN ref_model_film_point.point_no IS "
        "'Catalogue order, for display. Never identity (F10).'"
    )
    names = sorted({p for points in MODEL_CATALOGUES.values() for p in points})
    for name in names:
        conn.execute(
            text("INSERT INTO ref_film_point (point_code) VALUES (:p)"), {"p": name}
        )
    for model, points in MODEL_CATALOGUES.items():
        for number, point in enumerate(points, start=1):
            conn.execute(
                text(
                    "INSERT INTO ref_model_film_point (model_code, point_code, point_no) "
                    "VALUES (:m, :p, :n)"
                ),
                {"m": model, "p": point, "n": number},
            )
        conn.execute(
            text(
                "UPDATE ref_model SET expected_film_point_count = :n "
                "WHERE model_code = :m"
            ),
            {"n": len(points), "m": model},
        )


def _film_model_alias(conn) -> None:
    op.execute(
        """
        CREATE TABLE ref_film_model_alias (
            plant_code  text NOT NULL REFERENCES ref_plant (plant_code),
            raw_token   text NOT NULL
                            CHECK (raw_token = upper(btrim(raw_token))
                                   AND length(raw_token) > 0),
            model_code  text NOT NULL REFERENCES ref_model (model_code),
            note        text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, raw_token)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_film_model_alias IS "
        "'T46 (F4). FilmThickness model spellings, plant-scoped. Never read by "
        "WaveScan. FTM filename RAP is RAPCAP here while WaveScan P703 RAP is "
        "Raptor; RB exists only at FTM.'"
    )
    for plant, token, model in FILM_MODEL_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_film_model_alias (plant_code, raw_token, model_code, note) "
                "VALUES (:p, :t, :m, 'T46 seed (spec F6/F7)')"
            ),
            {"p": plant, "t": token, "m": model},
        )


def _location_map() -> None:
    op.execute(
        """
        CREATE TABLE ref_film_location_map (
            plant_code         text NOT NULL REFERENCES ref_plant (plant_code),
            model_code         text NOT NULL,
            raw_location_norm  text NOT NULL
                                   CHECK (raw_location_norm = upper(raw_location_norm)
                                          AND length(raw_location_norm) > 0),
            point_code         text NOT NULL,
            raw_position       smallint,
            proof_hash         char(64),
            verified_by        text,
            approved_at        timestamptz,
            note               text,
            created_at         timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, model_code, raw_location_norm),
            FOREIGN KEY (model_code, point_code)
                REFERENCES ref_model_film_point (model_code, point_code)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_film_location_map IS "
        "'T46 (F10, S15 analog). A plant location spelling proved to be one "
        "catalogue point by a named owner (proof_hash + verified_by). The "
        "loader reads proved rows only. raw_position is provenance, never the "
        "key. Seeded empty.'"
    )


def _column_aliases(conn) -> None:
    for raw, logical in FILM_COLUMN_ALIASES:
        conn.execute(
            text(
                "INSERT INTO ref_column_alias (raw_header, logical_field, is_approved, domain) "
                "VALUES (:r, :l, true, 'FILMTHICKNESS')"
            ),
            {"r": raw, "l": logical},
        )


def _facts() -> None:
    layers = ", ".join(_q(code) for code in LAYER_CODES)
    op.execute(
        f"""
        CREATE TABLE filmthickness (
            measurement_id          bigserial PRIMARY KEY,
            measured_date           date NOT NULL
                                        CHECK (measured_date BETWEEN '2000-01-01'
                                                             AND '2100-12-31'),
            plant                   text NOT NULL REFERENCES ref_plant (plant_code),
            model                   text NOT NULL REFERENCES ref_model (model_code),
            color                   text NOT NULL REFERENCES ref_color (color_name),
            job_no                  text CHECK (job_no IS NULL OR length(btrim(job_no)) > 0),
            serial_no               text CHECK (serial_no IS NULL OR length(btrim(serial_no)) > 0),
            paintline               text REFERENCES ref_paintline (paintline_code),
            point_code              text NOT NULL,
            src_location_text       text NOT NULL,
            layer_code              text NOT NULL CHECK (layer_code IN ({layers})),
            thickness               numeric NOT NULL CHECK (thickness >= 0),
            logical_vehicle_id      text NOT NULL CHECK (length(logical_vehicle_id) > 0),
            load_id                 bigint NOT NULL
                                        REFERENCES load_batch (load_id) ON DELETE RESTRICT,
            source_sheet            text NOT NULL,
            source_row              integer NOT NULL,
            is_duplicate            boolean NOT NULL DEFAULT false,
            is_superseded           boolean NOT NULL DEFAULT false,
            corrects_measurement_id bigint REFERENCES filmthickness (measurement_id),
            correction_reason       text,
            corrected_by            uuid REFERENCES app_user (id),
            corrected_at            timestamptz,
            loaded_at               timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (model, point_code)
                REFERENCES ref_model_film_point (model_code, point_code)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ft_load_row_layer_original ON filmthickness "
        "(load_id, source_sheet, source_row, layer_code) "
        "WHERE corrects_measurement_id IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_ft_vehicle ON filmthickness (logical_vehicle_id, point_code)"
    )
    op.execute("CREATE INDEX ix_ft_load ON filmthickness (load_id)")
    op.execute(
        "COMMENT ON TABLE filmthickness IS "
        "'T46 (F1, F9, F16). FilmBuild facts: one row per (vehicle, point, "
        "layer), full precision, insert-only. Extra points (095-098, FTWISH) "
        "and unmapped locations are review rows, never facts. Read through "
        "filmthickness_active.'"
    )
    op.execute(
        "COMMENT ON COLUMN filmthickness.logical_vehicle_id IS "
        "'Spec section 6: plant, day, model, colour and the real identity "
        "(VIN, else Job Number). Cab and Box walks of one car share it; two "
        "files keep two load_id.'"
    )
    op.execute(
        """
        CREATE FUNCTION reject_presuperseded_film()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $fn$
        BEGIN
            RAISE EXCEPTION
                'filmthickness.is_superseded cannot be set when the row is inserted'
                USING ERRCODE = 'check_violation',
                HINT = 'Insert the measurement; a retirement is a separate, '
                       'attributed record (ADR 0005).';
        END;
        $fn$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_reject_presuperseded_film BEFORE INSERT ON filmthickness "
        "FOR EACH ROW WHEN (NEW.is_superseded) EXECUTE FUNCTION reject_presuperseded_film()"
    )
    op.execute(
        """
        CREATE VIEW filmthickness_active AS
        SELECT * FROM filmthickness
         WHERE NOT is_duplicate AND NOT is_superseded
        """
    )
    op.execute(
        "COMMENT ON VIEW filmthickness_active IS "
        "'The one active-data predicate for film reads (01-DATA-MODEL.md "
        "section 10). Bypassing it is a correctness bug.'"
    )


_RESET_OLD = """            SELECT count(*) INTO v_facts
              FROM wavescan WHERE load_id = p_load_id;"""
_RESET_NEW = """            SELECT (SELECT count(*) FROM wavescan WHERE load_id = p_load_id)
                 + (SELECT count(*) FROM filmthickness WHERE load_id = p_load_id)
              INTO v_facts;"""
_PUBLISH_OLD = "IF p_domain IS DISTINCT FROM 'WAVESCAN' THEN"
_PUBLISH_NEW = "IF p_domain IS NULL OR p_domain NOT IN ('WAVESCAN', 'FILMTHICKNESS') THEN"


def _rewrite(conn, function: str, old: str, new: str) -> None:
    """Re-create one function with one condition widened, grants kept."""
    source = conn.execute(
        text(f"SELECT pg_get_functiondef('{function}'::regproc)")
    ).scalar_one()
    if old not in source:
        raise RuntimeError(f"{function}: expected text not found; not rewritten")
    conn.execute(text(source.replace(old, new, 1)))


def _functions(conn) -> None:
    _rewrite(conn, "reset_batch_staging", _RESET_OLD, _RESET_NEW)
    _rewrite(conn, "publish_template_profile", _PUBLISH_OLD, _PUBLISH_NEW)


def _domain_checks() -> None:
    listed = ", ".join(_q(d) for d in DOMAINS)
    op.execute(
        f"ALTER TABLE load_batch ADD CONSTRAINT ck_load_batch_domain "
        f"CHECK (domain IS NULL OR domain IN ({listed}))"
    )
    op.execute(
        f"ALTER TABLE ref_column_alias ADD CONSTRAINT ck_column_alias_domain "
        f"CHECK (domain IN ({listed}))"
    )


def _grants() -> None:
    for table in (
        "ref_film_point", "ref_model_film_point", "ref_film_model_alias",
        "ref_film_location_map", "filmthickness", "filmthickness_active",
    ):
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
    _for_each_role(
        """
        GRANT SELECT ON ref_film_point, ref_model_film_point,
                        ref_film_model_alias, ref_film_location_map,
                        filmthickness_active TO {role};
        GRANT SELECT, INSERT ON filmthickness TO {role};
        GRANT USAGE, SELECT ON SEQUENCE filmthickness_measurement_id_seq TO {role};
        """
    )


# =====================================================================
def downgrade() -> None:
    conn = op.get_bind()
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM filmthickness) THEN
                RAISE EXCEPTION 'filmthickness has facts; downgrade would delete measurements (ADR 0005)';
            END IF;
            IF EXISTS (SELECT 1 FROM load_batch WHERE domain = 'FILMTHICKNESS') THEN
                RAISE EXCEPTION 'FILMTHICKNESS batches exist; downgrade would orphan their domain';
            END IF;
        END $$;
        """
    )
    _rewrite(conn, "publish_template_profile", _PUBLISH_NEW, _PUBLISH_OLD)
    _rewrite(conn, "reset_batch_staging", _RESET_NEW, _RESET_OLD)
    op.execute("ALTER TABLE ref_column_alias DROP CONSTRAINT IF EXISTS ck_column_alias_domain")
    op.execute("ALTER TABLE load_batch DROP CONSTRAINT IF EXISTS ck_load_batch_domain")
    op.execute("DROP VIEW IF EXISTS filmthickness_active")
    op.execute("DROP TABLE IF EXISTS filmthickness")
    op.execute("DROP FUNCTION IF EXISTS reject_presuperseded_film()")
    op.execute("DELETE FROM ref_column_alias WHERE domain = 'FILMTHICKNESS'")
    op.execute("DROP TABLE IF EXISTS ref_film_location_map")
    op.execute("DROP TABLE IF EXISTS ref_film_model_alias")
    op.execute("DROP TABLE IF EXISTS ref_model_film_point")
    op.execute("DROP TABLE IF EXISTS ref_film_point")
    op.execute(
        "DELETE FROM ref_model WHERE model_code IN ('P703 RAPCAP', 'P703 SGL')"
    )
    op.execute("ALTER TABLE ref_model DROP CONSTRAINT IF EXISTS ck_model_film_points")
    op.execute("ALTER TABLE ref_model DROP CONSTRAINT IF EXISTS ck_model_wavescan_zones")
    op.execute(
        "ALTER TABLE ref_model DROP COLUMN IF EXISTS display_name, "
        "DROP COLUMN IF EXISTS expected_film_point_count, "
        "DROP COLUMN IF EXISTS wavescan_ok"
    )
