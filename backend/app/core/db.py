"""Database access for the API.

Driver: **psycopg3 through SQLAlchemy 2.x Core**, the choice T02 recorded
(`01-DATA-MODEL.md` section 9). No ORM and no Prisma.

The interesting part of this module is not the pool, it is the guard on it.
T01's result is a role that cannot delete or rewrite a measurement. That
result is worth nothing if the API is started with a superuser DSN by
accident -- the grants are still correct, and the process simply is not
subject to them. So every physical connection, not just the first, is
interrogated as soon as it is opened:

* is this role a superuser?
* does it hold DELETE or UPDATE on `wavescan`?
* does it hold DELETE on `load_batch`?

Any "yes" aborts the connection. `Settings` already refuses a URL that
*names* postgres or migrator; this catches the case where the name is
innocent and the grants are not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import ServiceUnavailable

log = logging.getLogger("app.db")

#: (table, privilege) pairs the application role must NOT hold.
#: ADR 0005 / docs/03-SECURITY.md section 2.
FORBIDDEN_PRIVILEGES = (
    ("wavescan", "DELETE"),
    ("wavescan", "UPDATE"),
    ("wavescan", "TRUNCATE"),
    ("load_batch", "DELETE"),
    ("audit_event", "UPDATE"),
    ("audit_event", "DELETE"),
)

_IDENTITY_SQL = """
SELECT current_user AS role_name,
       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser
"""


class UnsafeDatabaseRole(RuntimeError):
    """The API is connected as a role that can destroy evidence."""


@dataclass(frozen=True)
class DatabaseIdentity:
    role_name: str
    is_superuser: bool
    forbidden_held: tuple[str, ...]

    @property
    def is_safe(self) -> bool:
        return not self.is_superuser and not self.forbidden_held


def inspect_identity(dbapi_connection) -> DatabaseIdentity:
    """Ask the connection who it is and what it may destroy."""
    with dbapi_connection.cursor() as cur:
        cur.execute(_IDENTITY_SQL)
        role_name, is_superuser = cur.fetchone()

        held: list[str] = []
        for table, privilege in FORBIDDEN_PRIVILEGES:
            cur.execute(
                "SELECT to_regclass(%s) IS NOT NULL "
                "AND has_table_privilege(current_user, %s, %s)",
                (f"public.{table}", f"public.{table}", privilege),
            )
            if cur.fetchone()[0]:
                held.append(f"{table}.{privilege}")

    return DatabaseIdentity(
        role_name=role_name,
        is_superuser=bool(is_superuser),
        forbidden_held=tuple(held),
    )


def _install_identity_guard(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _check(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        identity = inspect_identity(dbapi_connection)
        connection_record.info["identity"] = identity
        if identity.is_safe:
            return
        reasons = []
        if identity.is_superuser:
            reasons.append("it is a SUPERUSER")
        if identity.forbidden_held:
            reasons.append("it holds " + ", ".join(identity.forbidden_held))
        raise UnsafeDatabaseRole(
            f"The API connected to PostgreSQL as {identity.role_name!r} and "
            + " and ".join(reasons)
            + ". T01 removed exactly these privileges from the application role "
            "(docs/03-SECURITY.md section 2, ADR 0005). Point APP_DATABASE_URL "
            "at app_rw. If a route genuinely needs a privilege app_rw lacks, "
            "that is a design question for the architect, not a grant to add."
        )


def create_database_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.app_database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            # A runaway dashboard query must not hold a pooled connection open
            # for ever; the whole dataset is small (01-DATA-MODEL.md section 11).
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
        future=True,
    )
    _install_identity_guard(engine)
    return engine


class Database:
    """Owns the engine and turns driver failures into the documented shape."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine | None = None
        if settings.app_database_url.strip():
            self._engine = create_database_engine(settings)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise ServiceUnavailable(
                "APP_DATABASE_URL is not configured, so no data route can be "
                "served. See backend/.env.example."
            )
        return self._engine

    def connect(self):
        """A read connection. Always rolled back: no route in T03 writes."""
        try:
            return self.engine.connect()
        except UnsafeDatabaseRole as exc:
            raise ServiceUnavailable(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise ServiceUnavailable(f"Database is not reachable: {exc.__class__.__name__}") from exc

    def begin(self):
        """A transaction that commits on success and rolls back on failure.

        `get_connection` deliberately never commits -- T03 was read-only and a
        read route that could write by accident is a bug waiting to happen.
        Write routes ask for this instead, so the difference between "may
        write" and "may not" is visible in the route's own signature.
        """
        try:
            return self.engine.begin()
        except UnsafeDatabaseRole as exc:
            raise ServiceUnavailable(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise ServiceUnavailable(
                f"Database is not reachable: {exc.__class__.__name__}"
            ) from exc

    def check(self) -> dict:
        """Readiness probe payload for one dependency: PostgreSQL.

        Reports the identity guard's verdict as data, so `/health/ready` is
        evidence that the running process holds no destructive privilege --
        not just a claim in a report.
        """
        if self._engine is None:
            return {"status": "not_configured", "detail": "APP_DATABASE_URL is empty"}
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                identity = inspect_identity(conn.connection.dbapi_connection)
        except UnsafeDatabaseRole as exc:
            return {"status": "refused", "detail": str(exc)}
        except SQLAlchemyError as exc:
            return {"status": "down", "detail": exc.__class__.__name__}
        return {
            "status": "ok" if identity.is_safe else "refused",
            "role": identity.role_name,
            "is_superuser": identity.is_superuser,
            "forbidden_privileges_held": list(identity.forbidden_held),
        }

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
