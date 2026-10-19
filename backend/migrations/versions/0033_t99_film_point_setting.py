"""T99: FTM Film point lists, a remembered "counted + H/V" setting, and a walk guard.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-10

The owner's words: stop rejecting FTM's real points automatically ("from 98
to 94"); let the data say which points exist, remember which ones count, and
store them so the dashboard shows them as Horizontal and Vertical.

**What is measured, and where it comes from.** Nothing here is typed from a
document. T54 (0019) cross-joined one 94-name model catalogue onto every
plant, so FTM's four Film lists all carry the same 94 names -- while the real
FTM walks are 98 (DBL / RB), 93 (RAPCAP) and 58 (SGL). The 93 and the 58 are
already in ``ref_model_film_point``, name and order equal to every full RAP
and SGL file the owner has (T89 walk, 2026-10-10), so this revision takes
them from that table rather than retyping them. The four names the 98-walk
adds -- ``095RBXFLOOR``, ``096TGATEIN``, ``097TGATEIN``, ``098TGATEIN`` --
are the only names written out below, because no table holds them yet.

**Horizontal / Vertical comes from one rule** (D-99-5, measured): ``H`` iff
the name with its leading digits removed is ``HOOD``, ``ROOF``, ``LBXFLOOR``
or ``RBXFLOOR``, else ``V``. It agrees with every one of the 658 live
``P703`` rows in ``ref_plant_film_point`` at every plant, and the post-assert
below re-checks that on the rows this revision leaves behind.

**Append-only.** ``film_point_setting`` is INSERT-only, latest row per point
wins (D-99-4): changing which points count changes past months' Hor/Ver by
design, and the row that said so before is never overwritten. A list name
that the real walk does not contain is **retired**, never deleted (ADR 0005),
and retire runs **before** insert so ``uq_plant_film_point_no_live`` never
sees two live rows on one ``point_no``.

**FTM data only** (D-99-12). Every rule T99 adds switches on a ``(plant,
model)`` that has ``film_point_setting`` rows, and only FTM gets them here,
so AAT, FVL and SAP Film behave exactly as they did -- including
``EXTRA_POINT`` there. No row of any other plant is read or written; the
post-assert compares their live counts before and after.

**Guarded.** Nothing changes unless the live FTM counts are 94/94/94/94, the
retire and insert sets are exactly 42/41 (RAPCAP) and 67/31 (SGL), and
``filmthickness`` holds no FTM fact -- a walked list is not a T54 leftover,
and a retire under a fact would hide a point a car was measured on.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"

PLANT = "FTM"
DBL = ("P703 DBL RANGER", "P703 DBL RAPTOR")
WALKED = ("P703 RAPCAP", "P703 SGL")
MODELS = (*DBL, *WALKED)

#: What T54's cross-join left on every FTM list.
LIVE_BEFORE = 94
#: What the real walks are (T89, measured on all 179 Jul-Oct files).
LIVE_AFTER = {
    "P703 DBL RANGER": 98, "P703 DBL RAPTOR": 98,
    "P703 RAPCAP": 93, "P703 SGL": 58,
}
SETTING_ROWS = sum(LIVE_AFTER.values())  # 347

#: The only point names this revision types out: the four the 98-walk adds
#: past T54's 94, with the ``point_no`` the file writes them at.
BOX_TAIL = (("095RBXFLOOR", 95), ("096TGATEIN", 96), ("097TGATEIN", 97),
            ("098TGATEIN", 98))

#: D-99-5, measured: the H/V rule, as one SQL expression used everywhere.
HV = (
    "CASE WHEN regexp_replace({col}, '^[0-9]+', '') "
    "IN ('HOOD', 'ROOF', 'LBXFLOOR', 'RBXFLOOR') THEN 'H' ELSE 'V' END"
)

#: D-99-8: where a **complete** walk may end. A no-box truck is a whole
#: vehicle, not a short one, so History must not call it incomplete.
STOPS = {
    "P703 DBL RANGER": ("064RAPILLAR", "098TGATEIN"),
    "P703 DBL RAPTOR": ("064RAPILLAR", "098TGATEIN"),
    "P703 RAPCAP": ("059RTFEND", "093TGATEIN"),
    "P703 SGL": ("058RTFEND",),
}

#: D-99-6: the known tail of an FTM walk. Never a fact, never a hold.
TAIL_LABELS = (
    "001FTWISH", "002FTWISH", "003FTWISH", "004FTWISH", "005FTWISH",
    "006FTWISH", "BOOTH_1",
)

#: D-99-10: the Job Number shape FTM writes (``AW_RB_1943641``).
FTM_JOB_PATTERN = "^([A-Z]{2})_([A-Z]+)_([0-9]{7})$"

RETIRE_REASON = (
    "T99 (owner D-99-5, 2026-10-10): T54 copy of the 94-name model "
    "catalogue; FTM's real walk of this model does not contain this name"
)
SEED_REASON = "T99 seed (owner D-99-5, 2026-10-10)"
INSERT_NOTE = "T99 (D-99-5): FTM's real walk, measured on the Jul-Oct files"
ACTION = "catalogue.film_point_setting.seed_ftm"

NEW_KINDS = ("FILM_MODEL_CONFLICT", "FILM_JOB_UNUSUAL", "FILM_WALK_CONFIRM")
OLD_KINDS = ("IGNORE_HEADER", "PLANT_CONFIRM", "HOLE_APPROVAL", "PANEL_CONFIRM")
KIND_CONSTRAINT = "worksheet_decision_kind_check"


def _kind_check(kinds: tuple[str, ...]) -> str:
    allowed = ", ".join("'" + kind + "'" for kind in kinds)
    return (
        f"ALTER TABLE worksheet_decision DROP CONSTRAINT IF EXISTS {KIND_CONSTRAINT}; "
        f"ALTER TABLE worksheet_decision ADD CONSTRAINT {KIND_CONSTRAINT} "
        f"CHECK (kind IN ({allowed}))"
    )


def _live_counts(conn) -> dict[tuple[str, str], int]:
    return {
        (r[0], r[1]): r[2]
        for r in conn.execute(
            text(
                "SELECT plant_code, model_code, count(*) FROM ref_plant_film_point "
                "WHERE retired_at IS NULL GROUP BY 1, 2"
            )
        ).all()
    }


# =====================================================================
# DDL
# =====================================================================
def _ddl() -> None:
    op.execute(
        """
        CREATE TABLE film_point_setting (
            setting_id  bigserial PRIMARY KEY,
            plant_code  text    NOT NULL,
            model_code  text    NOT NULL,
            point_code  text    NOT NULL,
            counted     boolean NOT NULL,
            orientation char(1) NOT NULL
                        CHECK (orientation IN ('H', 'V')),
            reason      text    NOT NULL
                        CHECK (length(btrim(reason)) > 0),
            created_by  uuid        REFERENCES app_user (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT film_point_setting_point_fkey
                FOREIGN KEY (plant_code, model_code, point_code)
                REFERENCES ref_plant_film_point
                           (plant_code, model_code, point_code)
        )
        """
    )
    # The read is always "the latest row of this point", so the index is the
    # one that answers it without a sort.
    op.execute(
        "CREATE INDEX ix_film_point_setting_latest ON film_point_setting "
        "(plant_code, model_code, point_code, setting_id DESC)"
    )
    op.execute(
        "COMMENT ON TABLE film_point_setting IS "
        "'T99 (D-99-2, D-99-4). Per plant x model x point: does this point "
        "count towards the dashboard, and is it Horizontal or Vertical. "
        "INSERT-only; the latest setting_id per point wins. Anyone who can "
        "upload may add a row, with a reason and an audit_event.'"
    )
    op.execute(
        """
        CREATE TABLE ref_plant_film_tail_label (
            plant_code text NOT NULL REFERENCES ref_plant (plant_code),
            model_code text NOT NULL REFERENCES ref_model (model_code),
            label_norm text NOT NULL
                       CHECK (label_norm = upper(btrim(label_norm))
                              AND length(label_norm) > 0),
            note       text,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plant_code, model_code, label_norm)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE ref_plant_film_tail_label IS "
        "'T99 (D-99-6). Labels that are the known tail of a plant x model "
        "Film walk (FTM 001FTWISH-006FTWISH, BOOTH_1). Shown in review as "
        "not stored: never a fact, never a hold, never a reason to block a "
        "file.'"
    )
    op.execute(
        "ALTER TABLE ref_plant_film_point "
        "ADD COLUMN is_complete_stop boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_film_point.is_complete_stop IS "
        "'T99 (D-99-8). A walk that ends exactly here is a complete vehicle, "
        "not a short one: FTM RAPCAP 059RTFEND (no box), DBL 064RAPILLAR (no "
        "box), and each list''s own last point.'"
    )
    op.execute("ALTER TABLE ref_plant ADD COLUMN film_job_no_pattern text")
    op.execute(
        "COMMENT ON COLUMN ref_plant.film_job_no_pattern IS "
        "'T99 (D-99-10). The Job Number shape this plant writes on a Film "
        "sheet, as a POSIX regex. NULL means no check -- the shape of every "
        "plant but FTM today.'"
    )
    op.execute(_kind_check((*OLD_KINDS, *NEW_KINDS)))
    op.execute(
        "COMMENT ON COLUMN worksheet_decision.subject IS "
        "'What was decided: a column header (IGNORE_HEADER), a Plant cell "
        "(PLANT_CONFIRM), a source row (HOLE_APPROVAL), T94''s pair "
        "''<panel as written>=><canonical zone_code>'' (PANEL_CONFIRM), or "
        "T99''s sheet answer: the chosen model_code (FILM_MODEL_CONFLICT), "
        "the Job Number read as written (FILM_JOB_UNUSUAL), or "
        "''<point_code>|<counted>|<H|V>'' for one appended walk point "
        "(FILM_WALK_CONFIRM).'"
    )
    op.execute("REVOKE ALL ON film_point_setting FROM PUBLIC")
    op.execute("REVOKE ALL ON ref_plant_film_tail_label FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON film_point_setting TO {APP_ROLE}")
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE film_point_setting_setting_id_seq "
        f"TO {APP_ROLE}"
    )
    op.execute(f"GRANT SELECT ON ref_plant_film_tail_label TO {APP_ROLE}")
    # D-99-14: the uploader's confirm of an appended walk point writes the
    # catalogue name and the plant's list row. INSERT only -- no UPDATE, no
    # DELETE, so a confirm can add a point and can never move or unname one.
    op.execute(f"GRANT INSERT ON ref_film_point TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON ref_plant_film_point TO {APP_ROLE}")


# =====================================================================
# guards
# =====================================================================
def _guard(conn) -> dict[str, dict]:
    live = {
        m: n for (p, m), n in _live_counts(conn).items()
        if p == PLANT and m in MODELS
    }
    if sorted(live) != sorted(MODELS) or set(live.values()) != {LIVE_BEFORE}:
        raise RuntimeError(
            f"T99 refused: FTM's four Film lists are {live}, expected "
            f"{LIVE_BEFORE} live rows each on {list(MODELS)}. Nothing was "
            f"changed. Re-measure and explain it in "
            f"docs/reports/T99-FTM-FILM-POINT-LISTS.md before changing this."
        )
    facts = conn.execute(
        text(
            "SELECT model, count(*) FROM filmthickness "
            "WHERE plant = :plant GROUP BY 1 ORDER BY 1"
        ),
        {"plant": PLANT},
    ).all()
    if facts:
        raise RuntimeError(
            f"T99 refused: filmthickness holds FTM facts "
            f"{[tuple(r) for r in facts]}. Retiring a list name under a fact "
            f"would hide a point a car was measured on (ADR 0005). Nothing "
            f"was changed."
        )
    plan: dict[str, dict] = {}
    for model in WALKED:
        row = conn.execute(
            text(
                """
                SELECT (SELECT count(*) FROM ref_plant_film_point
                         WHERE plant_code = :plant AND model_code = :model
                           AND retired_at IS NULL
                           AND point_code NOT IN (SELECT point_code
                                                    FROM ref_model_film_point
                                                   WHERE model_code = :model)),
                       (SELECT count(*) FROM ref_model_film_point
                         WHERE model_code = :model
                           AND point_code NOT IN (SELECT point_code
                                                    FROM ref_plant_film_point
                                                   WHERE plant_code = :plant
                                                     AND model_code = :model
                                                     AND retired_at IS NULL))
                """
            ),
            {"plant": PLANT, "model": model},
        ).one()
        plan[model] = {"retire": int(row[0]), "insert": int(row[1])}
    expected = {
        "P703 RAPCAP": {"retire": 42, "insert": 41},
        "P703 SGL": {"retire": 67, "insert": 31},
    }
    if plan != expected:
        raise RuntimeError(
            f"T99 refused: the retire/insert plan against ref_model_film_point "
            f"is {plan}, measured 2026-10-10 as {expected}. Nothing was changed."
        )
    # A point_no this revision inserts must not already be live on the list.
    clash = conn.execute(
        text(
            "SELECT model_code, point_no, point_code FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND model_code = ANY(:models) "
            "  AND retired_at IS NULL AND point_no > :last ORDER BY 1, 2"
        ),
        {"plant": PLANT, "models": list(DBL), "last": LIVE_BEFORE},
    ).all()
    if clash:
        raise RuntimeError(
            f"T99 refused: FTM's DBL lists already hold live rows past "
            f"{LIVE_BEFORE}: {[tuple(r) for r in clash]}. Nothing was changed."
        )
    return plan


# =====================================================================
# upgrade
# =====================================================================
def upgrade() -> None:
    conn = op.get_bind()
    before = _live_counts(conn)
    plan = _guard(conn)
    _ddl()

    # --- 1. the four catalogue names the 98-walk adds -------------------
    added_points = 0
    for code, _ in BOX_TAIL:
        added_points += conn.execute(
            text(
                "INSERT INTO ref_film_point (point_code) VALUES (:code) "
                "ON CONFLICT (point_code) DO NOTHING"
            ),
            {"code": code},
        ).rowcount

    # --- 2. retire before insert (uq_plant_film_point_no_live) ---------
    retired = 0
    inserted = 0
    for model in WALKED:
        retired += conn.execute(
            text(
                """
                UPDATE ref_plant_film_point
                   SET retired_at = now(), retired_reason = :why
                 WHERE plant_code = :plant AND model_code = :model
                   AND retired_at IS NULL
                   AND point_code NOT IN (SELECT point_code
                                            FROM ref_model_film_point
                                           WHERE model_code = :model)
                """
            ),
            {"plant": PLANT, "model": model, "why": RETIRE_REASON},
        ).rowcount
        inserted += conn.execute(
            text(
                f"""
                INSERT INTO ref_plant_film_point
                    (plant_code, model_code, point_code, point_no,
                     orientation, note)
                SELECT :plant, :model, m.point_code, m.point_no,
                       {HV.format(col='m.point_code')}, :note
                  FROM ref_model_film_point m
                 WHERE m.model_code = :model
                   AND m.point_code NOT IN (SELECT point_code
                                              FROM ref_plant_film_point
                                             WHERE plant_code = :plant
                                               AND model_code = :model
                                               AND retired_at IS NULL)
                ON CONFLICT (plant_code, model_code, point_code) DO UPDATE
                   SET point_no = EXCLUDED.point_no,
                       orientation = EXCLUDED.orientation,
                       note = EXCLUDED.note,
                       retired_at = NULL,
                       retired_reason = NULL
                """
            ),
            {"plant": PLANT, "model": model, "note": INSERT_NOTE},
        ).rowcount

    # --- 3. DBL RANGER and DBL RAPTOR: 095-098 -------------------------
    for model in DBL:
        for code, point_no in BOX_TAIL:
            inserted += conn.execute(
                text(
                    f"""
                    INSERT INTO ref_plant_film_point
                        (plant_code, model_code, point_code, point_no,
                         orientation, note)
                    VALUES (:plant, :model, :code, :no,
                            {HV.format(col=':code')}, :note)
                    ON CONFLICT (plant_code, model_code, point_code) DO NOTHING
                    """
                ),
                {"plant": PLANT, "model": model, "code": code,
                 "no": point_no, "note": INSERT_NOTE},
            ).rowcount

    # --- 4. where a complete walk may end (D-99-8) ---------------------
    stops = 0
    for model, codes in STOPS.items():
        stops += conn.execute(
            text(
                "UPDATE ref_plant_film_point SET is_complete_stop = true "
                "WHERE plant_code = :plant AND model_code = :model "
                "  AND retired_at IS NULL AND point_code = ANY(:codes)"
            ),
            {"plant": PLANT, "model": model, "codes": list(codes)},
        ).rowcount
    want_stops = sum(len(c) for c in STOPS.values())
    if stops != want_stops:
        raise RuntimeError(
            f"T99 refused: {stops} of {want_stops} complete-stop points were "
            f"found live on FTM's lists. The seed is incomplete; the "
            f"transaction is rolled back."
        )

    # --- 5. the setting: one row per live FTM point (D-99-2, D-99-5) ---
    settings = conn.execute(
        text(
            f"""
            INSERT INTO film_point_setting
                (plant_code, model_code, point_code, counted, orientation,
                 reason, created_by)
            SELECT plant_code, model_code, point_code, true,
                   {HV.format(col='point_code')}, :why, NULL
              FROM ref_plant_film_point
             WHERE plant_code = :plant AND model_code = ANY(:models)
               AND retired_at IS NULL
            """
        ),
        {"plant": PLANT, "models": list(MODELS), "why": SEED_REASON},
    ).rowcount

    # --- 6. the never-stored tail (D-99-6) -----------------------------
    tails = 0
    for model in MODELS:
        for label in TAIL_LABELS:
            tails += conn.execute(
                text(
                    "INSERT INTO ref_plant_film_tail_label "
                    "(plant_code, model_code, label_norm, note) "
                    "VALUES (:plant, :model, :label, :note) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"plant": PLANT, "model": model, "label": label,
                 "note": "T99 (D-99-6): the known tail of an FTM walk"},
            ).rowcount

    # --- 7. the Job Number shape (D-99-10) -----------------------------
    conn.execute(
        text(
            "UPDATE ref_plant SET film_job_no_pattern = :p "
            "WHERE plant_code = :plant"
        ),
        {"p": FTM_JOB_PATTERN, "plant": PLANT},
    )

    # --- post-asserts ---------------------------------------------------
    after = _live_counts(conn)
    live_ftm = {m: after.get((PLANT, m)) for m in MODELS}
    if live_ftm != LIVE_AFTER:
        raise RuntimeError(
            f"T99 refused: FTM's live lists are {live_ftm} after the seed, "
            f"expected {LIVE_AFTER}. The transaction is rolled back."
        )
    if settings != SETTING_ROWS:
        raise RuntimeError(
            f"T99 refused: {settings} film_point_setting rows were written, "
            f"expected {SETTING_ROWS}. The transaction is rolled back."
        )
    moved = {
        f"{key[0]}|{key[1]}": (n, after.get(key))
        for key, n in before.items()
        if key[0] != PLANT and after.get(key) != n
    }
    if moved:
        raise RuntimeError(
            f"T99 refused: it changed a non-FTM live Film list: {moved}. "
            f"AAT, FVL and SAP Film must behave exactly as today (D-99-12). "
            f"The transaction is rolled back."
        )
    broken = conn.execute(
        text(
            f"""
            SELECT point_code, btrim(orientation), s
              FROM (SELECT point_code, orientation,
                           {HV.format(col='point_code')} AS s
                      FROM ref_plant_film_point
                     WHERE plant_code = :plant AND retired_at IS NULL) x
             WHERE btrim(orientation) IS DISTINCT FROM s
             ORDER BY 1
            """
        ),
        {"plant": PLANT},
    ).all()
    if broken:
        raise RuntimeError(
            f"T99 refused: {len(broken)} live FTM point(s) carry an "
            f"orientation the D-99-5 rule does not give: "
            f"{[tuple(r) for r in broken[:10]]}. The transaction is rolled back."
        )
    gaps = conn.execute(
        text(
            "SELECT model_code, count(*), max(point_no) FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND model_code = ANY(:models) "
            "  AND retired_at IS NULL GROUP BY 1 HAVING count(*) <> max(point_no)"
        ),
        {"plant": PLANT, "models": list(MODELS)},
    ).all()
    if gaps:
        raise RuntimeError(
            f"T99 refused: an FTM list has a gap in point_no: "
            f"{[tuple(r) for r in gaps]}. D-99-8 reads a complete walk as "
            f"'count equals the point_no it ended at', which a gap breaks. "
            f"The transaction is rolled back."
        )

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'film_point_setting', :entity, "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "entity": f"{PLANT}:{','.join(MODELS)}",
            # Counts only: this cluster's audit_event TOAST files are missing
            # (T77), so an out-of-line value raises UndefinedFile. Every row
            # this revision wrote is reproducible from the predicates above.
            "before": json.dumps(
                {"live_per_model": {m: LIVE_BEFORE for m in MODELS},
                 "plan": plan}
            ),
            "after": json.dumps(
                {
                    "revision": "0033",
                    "ref_film_point_inserted": added_points,
                    "plant_points_retired": retired,
                    "plant_points_inserted": inserted,
                    "complete_stops": stops,
                    "setting_rows": settings,
                    "tail_labels": tails,
                    "live_per_model": LIVE_AFTER,
                    "job_no_pattern": FTM_JOB_PATTERN,
                    "owner_decision": "T99 D-99-1..D-99-14, 2026-10-10",
                }
            ),
        },
    )


# =====================================================================
# downgrade
# =====================================================================
def downgrade() -> None:
    conn = op.get_bind()
    # A FILM_* worksheet answer is a thing a person said about a real upload.
    kept = conn.execute(
        text("SELECT count(*) FROM worksheet_decision WHERE kind = ANY(:kinds)"),
        {"kinds": list(NEW_KINDS)},
    ).scalar_one()
    if kept:
        raise RuntimeError(
            f"{kept} T99 worksheet_decision row(s) exist. Downgrading would "
            f"make them violate the kind constraint, and they are answers a "
            f"person gave about an upload (ADR 0005). Remove the uploads they "
            f"belong to first."
        )
    # Only what 0033 added, and only what 0033 retired.
    op.execute("DROP TABLE film_point_setting")
    op.execute("DROP TABLE ref_plant_film_tail_label")
    conn.execute(
        text(
            "DELETE FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND note = :note"
        ),
        {"plant": PLANT, "note": INSERT_NOTE},
    )
    conn.execute(
        text(
            "UPDATE ref_plant_film_point "
            "SET retired_at = NULL, retired_reason = NULL "
            "WHERE retired_reason = :why"
        ),
        {"why": RETIRE_REASON},
    )
    conn.execute(
        text("DELETE FROM ref_film_point WHERE point_code = ANY(:codes)"),
        {"codes": [code for code, _ in BOX_TAIL]},
    )
    op.execute("ALTER TABLE ref_plant_film_point DROP COLUMN is_complete_stop")
    op.execute("ALTER TABLE ref_plant DROP COLUMN film_job_no_pattern")
    op.execute(_kind_check(OLD_KINDS))
    op.execute(f"REVOKE INSERT ON ref_film_point FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT ON ref_plant_film_point FROM {APP_ROLE}")
