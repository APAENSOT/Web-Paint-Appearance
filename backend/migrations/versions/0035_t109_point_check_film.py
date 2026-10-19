"""T109: Point Check phase 1 (Film) -- an extra tag, a live alias store, and
the one grant a retire needs.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-11

Point Check is one page where a person can see a plant x model's Film walk
and change it: switch **counted**, set **H/V**, **add** a point, **retire**
one. T99 (0033) already built the first two and the append-only setting they
write to. This revision adds the three things the other two need, and
nothing else.

**1. The extra tag** (D-109-3). A point is *extra* when it is beyond the
plant's standard list. ``is_extra`` is a column of the plant's own list row
because that is where the fact lives: `095RBXFLOOR` and `096-098TGATEIN` are
extra **at FTM on the two DBL lists**, and the same names on another plant's
list would be its own question. The seed is exactly the 8 rows the owner
named (2026-10-10), and every point added from now on -- on Point Check or
through the in-review confirm (D-99-14) -- is written extra by the
application, not by a rule here.

**2. A live alias store** (D-109-6, D-109-8). An upload that writes a label
the list does not hold is asked about **in the row**: pick a live point of
that plant x model and the answer is remembered for every later upload. The
old `ref_film_location_map` cannot hold that answer:

* its primary key is ``(plant_code, model_code, raw_location_norm)`` and
  **all 118 FTM rows are retired** (T47 mapped FTM labels onto FVL names,
  T54 retired them). A new live FTM alias for a label one of them holds --
  ``029LTFTDOOR`` is the real example -- would collide with a row that must
  never be updated or deleted: it is the record for the facts that were
  mapped through it (ADR 0005);
* its foreign key points at ``ref_model_film_point``, the model-wide
  catalogue, which does not hold ``095RBXFLOOR`` at all. A plant's live
  point is a row of ``ref_plant_film_point``, and an alias has to be allowed
  to name one.

So the alias lives in its own table, read **before** the old one, with a
surrogate key and a partial unique index on live rows. The 118 retired rows
are not read, not updated, not deleted; the post-assert below checksums them
before and after to prove it.

**3. The retire grant** (D-109-9). A retire sets ``retired_at`` and
``retired_reason`` on a list row, once. ``app_rw`` gets column-scoped UPDATE
on **those two columns only** -- no other column, no DELETE anywhere -- so
the application cannot move a point, rename one, or unname one even by
accident. Un-retiring is out of scope, which is why there is no grant that
would allow it to be written as a correction either (the two columns are the
same two, so an un-retire would be refused by
``ck_plant_film_point_retired``'s pairing rather than by a privilege; the
application has no code path for it).

**Nothing is retired, added or aliased here.** This revision adds two
structures, one tag on 8 rows, and three grants. The FTM live lists are
98 / 98 / 93 / 58 before and after.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

APP_ROLE = "app_rw"

PLANT = "FTM"
DBL = ("P703 DBL RANGER", "P703 DBL RAPTOR")
MODELS = (*DBL, "P703 RAPCAP", "P703 SGL")

#: What T99 (0033) left, re-checked here before anything is written.
LIVE = {
    "P703 DBL RANGER": 98, "P703 DBL RAPTOR": 98,
    "P703 RAPCAP": 93, "P703 SGL": 58,
}

#: D-109-3, owner 2026-10-10: the points beyond FTM's 94-point standard.
#: Four names on each of the two DBL lists -- 8 rows.
EXTRA_POINTS = ("095RBXFLOOR", "096TGATEIN", "097TGATEIN", "098TGATEIN")
EXTRA_ROWS = len(EXTRA_POINTS) * len(DBL)

#: The retired FTM alias rows that must come out of this revision untouched.
RETIRED_ALIAS_ROWS = 118

ALIAS_TABLE = "ref_film_point_alias"
ALIAS_SEQ = "ref_film_point_alias_alias_id_seq"
ALIAS_INDEX = "uq_film_point_alias_live"

#: D-109-9: the only columns of a list row the application may ever write
#: after the row exists.
RETIRE_COLUMNS = ("retired_at", "retired_reason")

NEW_KINDS = ("FILM_POINT_ALIAS",)
OLD_KINDS = (
    "IGNORE_HEADER", "PLANT_CONFIRM", "HOLE_APPROVAL", "PANEL_CONFIRM",
    "FILM_MODEL_CONFLICT", "FILM_JOB_UNUSUAL", "FILM_WALK_CONFIRM",
)
KIND_CONSTRAINT = "worksheet_decision_kind_check"

ACTION = "catalogue.film_point.point_check_p1"


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


def _alias_checksum(conn) -> tuple[int, str]:
    """The 118 retired FTM rows of the **old** map, as one number and one hash.

    Every column, in key order, so an UPDATE of any field would change the
    hash even where the row count did not.
    """
    row = conn.execute(
        text(
            """
            SELECT count(*),
                   coalesce(md5(string_agg(line, E'\\n' ORDER BY line)), '')
              FROM (SELECT concat_ws('|', plant_code, model_code,
                                     raw_location_norm, point_code,
                                     raw_position, proof_hash, verified_by,
                                     approved_at, note, created_at,
                                     retired_at, retired_reason) AS line
                      FROM ref_film_location_map
                     WHERE plant_code = :plant) x
            """
        ),
        {"plant": PLANT},
    ).one()
    return int(row[0]), str(row[1])


# =====================================================================
# DDL
# =====================================================================
def _ddl() -> None:
    op.execute(
        "ALTER TABLE ref_plant_film_point "
        "ADD COLUMN is_extra boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN ref_plant_film_point.is_extra IS "
        "'T109 (D-109-3). This point is beyond the plant''s standard list "
        "for the model. Seeded true for FTM''s 095RBXFLOOR and "
        "096-098TGATEIN on the two DBL lists (owner, 2026-10-10); every "
        "point added after T109 -- on Point Check or by the in-review "
        "appended-walk confirm -- is written extra. Shown as a tag on Point "
        "Check, in History''s point grid and in review. It is not a grade "
        "and it changes no reading.'"
    )
    op.execute(
        f"""
        CREATE TABLE {ALIAS_TABLE} (
            alias_id          bigserial PRIMARY KEY,
            plant_code        text NOT NULL,
            model_code        text NOT NULL,
            raw_location_norm text NOT NULL
                              CHECK (raw_location_norm
                                     = upper(btrim(raw_location_norm))
                                     AND length(raw_location_norm) > 0),
            point_code        text NOT NULL,
            reason            text NOT NULL
                              CHECK (length(btrim(reason)) > 0),
            created_by        uuid        REFERENCES app_user (id),
            created_at        timestamptz NOT NULL DEFAULT now(),
            retired_at        timestamptz,
            retired_reason    text,
            CONSTRAINT ck_film_point_alias_retired
                CHECK ((retired_at IS NULL) = (retired_reason IS NULL)),
            CONSTRAINT {ALIAS_TABLE}_point_fkey
                FOREIGN KEY (plant_code, model_code, point_code)
                REFERENCES ref_plant_film_point
                           (plant_code, model_code, point_code)
        )
        """
    )
    # The key the old map has as its primary key, here as a **partial**
    # unique index: one live alias per label per plant x model, while any
    # number of retired rows may hold the same label. That is the whole
    # reason this table exists (D-109-8).
    op.execute(
        f"CREATE UNIQUE INDEX {ALIAS_INDEX} ON {ALIAS_TABLE} "
        f"(plant_code, model_code, raw_location_norm) WHERE retired_at IS NULL"
    )
    op.execute(
        f"COMMENT ON TABLE {ALIAS_TABLE} IS "
        f"'T109 (D-109-6, D-109-8). A label an upload wrote that the plant x "
        f"model''s live Film list does not hold, and the live point a person "
        f"said it is. Read **before** ref_film_location_map, whose primary "
        f"key cannot hold a live FTM alias (all 118 FTM rows there are "
        f"retired and must never be updated or deleted, ADR 0005) and whose "
        f"foreign key points at the model-wide catalogue rather than at a "
        f"plant''s own point. INSERT-only for the application; the answer is "
        f"written with its reason, the person and an audit_event.'"
    )
    op.execute(f"REVOKE ALL ON {ALIAS_TABLE} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON {ALIAS_TABLE} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {ALIAS_SEQ} TO {APP_ROLE}")
    # D-109-9. The one write a retire is: two columns, set together, once.
    op.execute(
        f"GRANT UPDATE ({', '.join(RETIRE_COLUMNS)}) "
        f"ON ref_plant_film_point TO {APP_ROLE}"
    )
    op.execute(_kind_check((*OLD_KINDS, *NEW_KINDS)))
    op.execute(
        "COMMENT ON COLUMN worksheet_decision.subject IS "
        "'What was decided: a column header (IGNORE_HEADER), a Plant cell "
        "(PLANT_CONFIRM), a source row (HOLE_APPROVAL), T94''s pair "
        "''<panel as written>=><canonical zone_code>'' (PANEL_CONFIRM), "
        "T99''s sheet answer: the chosen model_code (FILM_MODEL_CONFLICT), "
        "the Job Number read as written (FILM_JOB_UNUSUAL), "
        "''<point_code>|<counted>|<H|V>'' for one appended walk point "
        "(FILM_WALK_CONFIRM), or T109''s row answer "
        "''<label as written>=><live point_code>'' (FILM_POINT_ALIAS).'"
    )


# =====================================================================
# guards
# =====================================================================
def _guard(conn) -> None:
    live = {
        m: n for (p, m), n in _live_counts(conn).items()
        if p == PLANT and m in MODELS
    }
    if live != LIVE:
        raise RuntimeError(
            f"T109 refused: FTM's live Film lists are {live}, expected {LIVE} "
            f"(what T99 / 0033 left and T101 measured). Nothing was changed. "
            f"Re-measure and explain it in "
            f"docs/reports/T109-POINT-CHECK-P1-FILM.md before changing this."
        )
    found = conn.execute(
        text(
            "SELECT count(*) FROM ref_plant_film_point "
            "WHERE plant_code = :plant AND model_code = ANY(:models) "
            "  AND point_code = ANY(:codes) AND retired_at IS NULL"
        ),
        {"plant": PLANT, "models": list(DBL), "codes": list(EXTRA_POINTS)},
    ).scalar_one()
    if int(found) != EXTRA_ROWS:
        raise RuntimeError(
            f"T109 refused: {found} of the {EXTRA_ROWS} extra points the "
            f"owner named ({', '.join(EXTRA_POINTS)} on {', '.join(DBL)}) are "
            f"live on FTM's lists. The extra tag would be seeded onto a "
            f"different set than the one that was decided. Nothing was "
            f"changed."
        )
    rows, _ = _alias_checksum(conn)
    if rows != RETIRED_ALIAS_ROWS:
        raise RuntimeError(
            f"T109 refused: ref_film_location_map holds {rows} FTM rows, "
            f"measured as {RETIRED_ALIAS_ROWS} (all retired). This revision "
            f"must leave every one of them exactly as it is, and it checksums "
            f"them to prove it. Nothing was changed."
        )


# =====================================================================
# upgrade
# =====================================================================
def upgrade() -> None:
    conn = op.get_bind()
    before_live = _live_counts(conn)
    before_alias = _alias_checksum(conn)
    _guard(conn)
    _ddl()

    tagged = conn.execute(
        text(
            "UPDATE ref_plant_film_point SET is_extra = true "
            "WHERE plant_code = :plant AND model_code = ANY(:models) "
            "  AND point_code = ANY(:codes) AND retired_at IS NULL"
        ),
        {"plant": PLANT, "models": list(DBL), "codes": list(EXTRA_POINTS)},
    ).rowcount

    # --- post-asserts ---------------------------------------------------
    if tagged != EXTRA_ROWS:
        raise RuntimeError(
            f"T109 refused: {tagged} rows were tagged extra, expected "
            f"{EXTRA_ROWS}. The transaction is rolled back."
        )
    total = conn.execute(
        text("SELECT count(*) FROM ref_plant_film_point WHERE is_extra")
    ).scalar_one()
    if int(total) != EXTRA_ROWS:
        raise RuntimeError(
            f"T109 refused: {total} point(s) carry the extra tag platform-wide, "
            f"expected exactly the {EXTRA_ROWS} FTM rows the owner named. The "
            f"transaction is rolled back."
        )
    after_live = _live_counts(conn)
    if after_live != before_live:
        moved = {
            f"{p}|{m}": (n, after_live.get((p, m)))
            for (p, m), n in before_live.items() if after_live.get((p, m)) != n
        }
        raise RuntimeError(
            f"T109 refused: it changed a live Film list: {moved}. This "
            f"revision retires nothing and adds nothing. The transaction is "
            f"rolled back."
        )
    after_alias = _alias_checksum(conn)
    if after_alias != before_alias:
        raise RuntimeError(
            f"T109 refused: the retired FTM ref_film_location_map rows changed "
            f"({before_alias} -> {after_alias}). Those 118 rows are the record "
            f"for the facts that were mapped through them and must never be "
            f"updated or deleted (ADR 0005). The transaction is rolled back."
        )
    # D-109-9, read back off the catalog rather than trusted: UPDATE on the
    # two retire columns and on nothing else, and no DELETE anywhere.
    updatable = sorted(
        r[0] for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.column_privileges "
                "WHERE table_name = 'ref_plant_film_point' AND grantee = :role "
                "  AND privilege_type = 'UPDATE'"
            ),
            {"role": APP_ROLE},
        ).all()
    )
    if updatable != sorted(RETIRE_COLUMNS):
        raise RuntimeError(
            f"T109 refused: {APP_ROLE} may UPDATE {updatable} of "
            f"ref_plant_film_point, expected exactly "
            f"{sorted(RETIRE_COLUMNS)} (D-109-9). The transaction is rolled "
            f"back."
        )
    deletes = conn.execute(
        text(
            "SELECT table_name FROM information_schema.table_privileges "
            "WHERE grantee = :role AND privilege_type = 'DELETE' "
            "  AND table_name IN ('ref_plant_film_point', "
            "      'ref_film_point_alias', 'ref_film_location_map', "
            "      'film_point_setting', 'filmthickness') ORDER BY 1"
        ),
        {"role": APP_ROLE},
    ).all()
    if deletes:
        raise RuntimeError(
            f"T109 refused: {APP_ROLE} holds DELETE on "
            f"{[r[0] for r in deletes]}. Nothing Point Check does is a delete "
            f"(ADR 0005). The transaction is rolled back."
        )

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_plant_film_point', :entity, "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "entity": f"{PLANT}:{','.join(DBL)}",
            # Counts only: this cluster's audit_event TOAST files are missing
            # (T77), so an out-of-line value raises UndefinedFile.
            "before": json.dumps(
                {"live_per_model": LIVE, "extra_tagged": 0,
                 "retired_alias_rows": before_alias[0]}
            ),
            "after": json.dumps(
                {
                    "revision": "0035",
                    "extra_tagged": tagged,
                    "alias_table": ALIAS_TABLE,
                    "retire_grant": list(RETIRE_COLUMNS),
                    "live_per_model": LIVE,
                    "retired_alias_rows_untouched": after_alias[0],
                    "owner_decision": "T109 D-109-1..D-109-9, 2026-10-11",
                }
            ),
        },
    )


# =====================================================================
# downgrade
# =====================================================================
def downgrade() -> None:
    conn = op.get_bind()
    kept = conn.execute(
        text("SELECT count(*) FROM worksheet_decision WHERE kind = ANY(:kinds)"),
        {"kinds": list(NEW_KINDS)},
    ).scalar_one()
    if kept:
        raise RuntimeError(
            f"{kept} T109 worksheet_decision row(s) exist. Downgrading would "
            f"make them violate the kind constraint, and they are answers a "
            f"person gave about an upload (ADR 0005). Remove the uploads they "
            f"belong to first."
        )
    retired = conn.execute(
        text(
            "SELECT count(*) FROM ref_plant_film_point "
            "WHERE retired_at IS NOT NULL AND retired_reason LIKE :like"
        ),
        {"like": "T109%"},
    ).scalar_one()
    if retired:
        raise RuntimeError(
            f"{retired} point(s) were retired through Point Check. Dropping "
            f"the grant that wrote them is safe, but the extra tag and the "
            f"alias rows are not re-derivable, and a retire is a decision a "
            f"person made (ADR 0005). Decide what to do with them first."
        )
    op.execute(f"DROP TABLE {ALIAS_TABLE}")
    op.execute("ALTER TABLE ref_plant_film_point DROP COLUMN is_extra")
    op.execute(
        f"REVOKE UPDATE ({', '.join(RETIRE_COLUMNS)}) "
        f"ON ref_plant_film_point FROM {APP_ROLE}"
    )
    op.execute(_kind_check(OLD_KINDS))
