"""Alembic environment for the WaveScan platform.

The connection URL comes from ``MIGRATOR_DATABASE_URL`` only. It is never
read from alembic.ini and never from the application's own configuration:
DDL is the ``migrator`` role's job, run from CI, and the application role
has no DDL rights at all (docs/01-DATA-MODEL.md section 8).

T01 bootstraps this file; T02 adds the SQLAlchemy metadata for
autogenerate. Until then ``target_metadata`` is None and every revision is
hand-written SQL, which is what a grant/privilege migration has to be
anyway -- Alembic cannot autogenerate GRANT statements.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# T02: point this at the declarative Base metadata to enable autogenerate.
target_metadata = None

_URL_ENV = "MIGRATOR_DATABASE_URL"


def _database_url() -> str:
    url = os.environ.get(_URL_ENV, "").strip()
    if not url:
        raise RuntimeError(
            f"{_URL_ENV} is not set.\n"
            "  Alembic runs as the migrator role, not as the application role.\n"
            "  Example (local):\n"
            f"    export {_URL_ENV}='postgresql+psycopg://migrator@localhost:5432/paint_appearance'\n"
            "  Never put this value in alembic.ini or in the application .env."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
