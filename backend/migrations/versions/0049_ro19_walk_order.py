"""RO19: append-only measuring orders, and workbook-level skipped sheets.

The order belongs to a plant/model/domain, independently of point identity.
Every version retains its entire member set. Existing catalogues are seeded
in point-number order, with one audit event per version. No kept row or
existing view changes. Number uniqueness is removed: restoring a retired
identity must not change its original number merely because it was reused.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def snapshot(conn):
    """Exact kept-table digests and view definitions/counts for the dry run."""
    tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")).scalars().all()
    excluded = {"audit_event", "alembic_version", "point_walk_version", "point_walk_member", "workbook_upload"}
    kept = {}
    for name in tables:
        if name in excluded:
            continue
        kept[name] = tuple(conn.execute(text(
            f'SELECT count(*), md5(string_agg(md5(to_jsonb(t)::text), \'\' ORDER BY md5(to_jsonb(t)::text))) FROM "{name}" t'
        )).one())
    views = {}
    for name in conn.execute(text("SELECT viewname FROM pg_views WHERE schemaname='public' AND viewname<>'v_point_walk_order' ORDER BY 1")).scalars():
        views[name] = (conn.execute(text("SELECT pg_get_viewdef(CAST(:name AS regclass))"), {"name": name}).scalar_one(),
                       conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one())
    return {"kept": kept, "views": views}


def upgrade():
    conn = op.get_bind()
    before = snapshot(conn)
    op.execute("""
        CREATE TABLE point_walk_version (
          version_id bigserial PRIMARY KEY,
          plant_code text NOT NULL REFERENCES ref_plant(plant_code),
          model_code text NOT NULL REFERENCES ref_model(model_code),
          domain text NOT NULL CHECK(domain IN ('FILMTHICKNESS','WAVESCAN')),
          set_by uuid REFERENCES app_user(id),
          set_at timestamptz NOT NULL DEFAULT now(),
          reason text NOT NULL CHECK(length(btrim(reason))>0)
        );
        CREATE INDEX ix_point_walk_scope ON point_walk_version(plant_code,model_code,domain,version_id DESC);
        CREATE TABLE point_walk_member (
          version_id bigint NOT NULL REFERENCES point_walk_version(version_id),
          point_code text NOT NULL,
          walk_rank integer NOT NULL CHECK(walk_rank>0),
          PRIMARY KEY(version_id,point_code), UNIQUE(version_id,walk_rank)
        );
        CREATE TABLE workbook_upload (
          plant_code text NOT NULL REFERENCES ref_plant(plant_code),
          file_hash char(64) NOT NULL,
          source_file text NOT NULL,
          raw_store_key text NOT NULL,
          loaded_by uuid REFERENCES app_user(id),
          uploaded_at timestamptz NOT NULL DEFAULT now(),
          skipped_sheets jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(skipped_sheets)='array'),
          PRIMARY KEY(plant_code,file_hash)
        );
        DROP INDEX uq_plant_film_point_no_live;
        DROP INDEX uq_plant_ws_point_no_live;
        INSERT INTO point_walk_version(plant_code,model_code,domain,reason)
        SELECT DISTINCT plant_code,model_code,'FILMTHICKNESS','RO19 0049: preserve existing point-number order'
        FROM ref_plant_film_point WHERE retired_at IS NULL
        UNION ALL
        SELECT DISTINCT plant_code,model_code,'WAVESCAN','RO19 0049: preserve existing point-number order'
        FROM ref_plant_ws_point WHERE retired_at IS NULL;
        INSERT INTO point_walk_member(version_id,point_code,walk_rank)
        SELECT v.version_id,p.point_code,row_number() OVER(PARTITION BY v.version_id ORDER BY p.point_no,p.point_code)
        FROM point_walk_version v JOIN ref_plant_film_point p USING(plant_code,model_code)
        WHERE v.domain='FILMTHICKNESS' AND p.retired_at IS NULL
        UNION ALL
        SELECT v.version_id,p.zone_code,row_number() OVER(PARTITION BY v.version_id ORDER BY p.point_no,p.zone_code)
        FROM point_walk_version v JOIN ref_plant_ws_point p USING(plant_code,model_code)
        WHERE v.domain='WAVESCAN' AND p.retired_at IS NULL;
        CREATE VIEW v_point_walk_order AS
        WITH catalog AS (
          SELECT plant_code,model_code,'FILMTHICKNESS'::text AS domain,point_code,point_no FROM ref_plant_film_point WHERE retired_at IS NULL
          UNION ALL
          SELECT plant_code,model_code,'WAVESCAN',zone_code,point_no FROM ref_plant_ws_point WHERE retired_at IS NULL
        ), latest AS (
          SELECT DISTINCT ON(plant_code,model_code,domain) * FROM point_walk_version
          ORDER BY plant_code,model_code,domain,version_id DESC
        )
        SELECT c.plant_code,c.model_code,c.domain,c.point_code,c.point_no,v.version_id,
          row_number() OVER(PARTITION BY c.plant_code,c.model_code,c.domain ORDER BY m.walk_rank NULLS LAST,c.point_no,c.point_code)::integer AS walk_rank
        FROM catalog c LEFT JOIN latest v USING(plant_code,model_code,domain)
        LEFT JOIN point_walk_member m ON m.version_id=v.version_id AND m.point_code=c.point_code;
        GRANT SELECT,INSERT ON point_walk_version,point_walk_member,workbook_upload TO app_rw;
        DO $$ BEGIN
          IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='app_ro') THEN
            GRANT SELECT ON point_walk_version,point_walk_member,workbook_upload,v_point_walk_order TO app_ro;
          END IF;
        END $$;
        GRANT SELECT ON v_point_walk_order TO app_rw;
        GRANT USAGE,SELECT ON SEQUENCE point_walk_version_version_id_seq TO app_rw;
        INSERT INTO audit_event(actor_type,action,entity_type,entity_id,after)
        SELECT 'system','migration.ro19.walk_order.seed','point_walk_version',version_id::text,
          jsonb_build_object('plant_code',plant_code,'model_code',model_code,'domain',domain,'reason',reason)
        FROM point_walk_version;
    """)
    if snapshot(conn) != before:
        raise RuntimeError("RO19 refused: a kept table or view changed; roll back")
    mismatches = conn.execute(text("""
        SELECT count(*) FROM (
          SELECT *,row_number() OVER(PARTITION BY plant_code,model_code,domain ORDER BY point_no,point_code) AS old_rank
          FROM v_point_walk_order
        ) x WHERE walk_rank<>old_rank
    """)).scalar_one()
    if mismatches:
        raise RuntimeError("RO19 refused: seeded order differs from today's order; roll back")


def non_seed_versions(conn) -> int:
    """Orders this migration did not write: a version with no actor is still
    not a seed version, so `set_by IS NOT NULL` alone would drop it silently."""
    return conn.execute(text("""
        SELECT count(*) FROM point_walk_version v
        WHERE v.set_by IS NOT NULL OR NOT EXISTS (
          SELECT 1 FROM audit_event a
          WHERE a.action='migration.ro19.walk_order.seed'
            AND a.entity_type='point_walk_version' AND a.entity_id=v.version_id::text
        )
    """)).scalar_one()


def shared_live_numbers(conn) -> int:
    """Live points sharing one `point_no`: 0049 dropped the unique indexes,
    so a restore may have left a pair the downgrade cannot re-index."""
    return conn.execute(text("""
        SELECT count(*) FROM (
          SELECT 1 FROM ref_plant_film_point WHERE retired_at IS NULL
          GROUP BY plant_code,model_code,point_no HAVING count(*)>1
          UNION ALL
          SELECT 1 FROM ref_plant_ws_point WHERE retired_at IS NULL
          GROUP BY plant_code,model_code,point_no HAVING count(*)>1
        ) d
    """)).scalar_one()


def refuse_edited_order(conn) -> None:
    """Downgrade guard (RO19 F7).

    A downgrade must never erase an order somebody has edited, or evidence of
    a skipped workbook. Refuse rather than silently destroy that history.
    """
    uploads = conn.execute(text("SELECT count(*) FROM workbook_upload")).scalar_one()
    if non_seed_versions(conn) or uploads:
        raise RuntimeError("RO19 downgrade refused: user order or workbook evidence exists")
    if shared_live_numbers(conn):
        raise RuntimeError("RO19 downgrade refused: live points share a point_no; the unique indexes cannot be re-created")


def downgrade():
    conn = op.get_bind()
    refuse_edited_order(conn)
    op.execute("""
      DROP VIEW v_point_walk_order;
      DROP TABLE point_walk_member;
      DROP TABLE point_walk_version;
      DROP TABLE workbook_upload;
      CREATE UNIQUE INDEX uq_plant_film_point_no_live ON ref_plant_film_point(plant_code,model_code,point_no) WHERE retired_at IS NULL;
      CREATE UNIQUE INDEX uq_plant_ws_point_no_live ON ref_plant_ws_point(plant_code,model_code,point_no) WHERE retired_at IS NULL;
    """)
