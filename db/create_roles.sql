-- Paint Appearance: create the two database roles and the empty application database.
--
-- Run ONCE, as the PostgreSQL admin user (`postgres`), against the `postgres` database:
--
--   psql -h localhost -U postgres -d postgres \
--        -v migrator_password='...' -v app_rw_password='...' \
--        -f db/create_roles.sql
--
--   migrator  owns the database and every object in it; runs `alembic upgrade head`.
--   app_rw    the only role the API may use. The grants it needs come with the
--             data dump and the migrations (no DELETE, no DDL). The API refuses
--             to start as postgres, migrator or any other privileged role.
--
-- On Cloud SQL run it through the Cloud SQL Auth Proxy (infra/gcp/README.md, step 4).
\set ON_ERROR_STOP on

CREATE ROLE migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE app_rw LOGIN PASSWORD :'app_rw_password';

-- Lets this admin create the database owned by migrator. Needed on Cloud SQL and
-- PostgreSQL 16+, where the admin user is not a true superuser; harmless otherwise.
GRANT migrator TO CURRENT_USER;

-- C collation: the database the migrations were verified on uses it, so text
-- ordering and comparisons match.
CREATE DATABASE paint_appearance
    OWNER migrator
    ENCODING 'UTF8'
    LC_COLLATE 'C'
    LC_CTYPE 'C'
    TEMPLATE template0;
