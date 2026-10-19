"""The Compose file is infrastructure, and it is not exercised on this
machine (no Docker installed -- see docs/reports/T02-SCHEMA.md).

So the parts of it that can be checked statically, are: that it parses,
that the database image is pinned to a major version rather than floating
on `latest`, and that the port binding does not expose Ford plant data to
the LAN. These are the mistakes that would otherwise be found only when
someone first runs `docker compose up` -- or, in the port case, not at all.

No database is needed for this module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE.exists(), f"missing {COMPOSE}"
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_file_parses_and_defines_postgres(compose):
    assert "services" in compose, "no services block"
    assert "postgres" in compose["services"], (
        f"no postgres service; found {sorted(compose['services'])}"
    )


def test_postgres_image_pins_a_major_version(compose):
    """D6 is open, but 'unpinned' is not a way to defer it: `postgres:latest`
    would silently change major version under an existing data directory,
    which PostgreSQL refuses to start against."""
    image = compose["services"]["postgres"]["image"]
    assert image.startswith("postgres:"), image
    tag = image.split(":", 1)[1]
    assert tag != "latest", "postgres:latest is not a pin"
    # Either a literal major (16-alpine) or a defaulted variable
    # (${POSTGRES_MAJOR:-16}-alpine) -- both resolve to a fixed major.
    assert any(ch.isdigit() for ch in tag), f"no major version in tag {tag!r}"
    if "POSTGRES_MAJOR" in tag:
        assert ":-" in tag, (
            f"{tag!r} has no default, so `docker compose up` without an env "
            "file would resolve to an empty major"
        )


def test_database_port_is_bound_to_loopback(compose):
    """This database holds Ford plant quality data even locally
    (docs/03-SECURITY.md section 8). A bare "5432:5432" publishes it on
    every interface, including hotel and plant wifi."""
    for mapping in compose["services"]["postgres"].get("ports", []):
        assert str(mapping).startswith("127.0.0.1:"), (
            f"port mapping {mapping!r} is not bound to loopback"
        )


def test_no_secret_looking_literals_are_committed(compose):
    """Local dev defaults are fine; a real credential in git is not
    (docs/03-SECURITY.md section 6)."""
    env = compose["services"]["postgres"].get("environment", {})
    password = str(env.get("POSTGRES_PASSWORD", ""))
    assert password.startswith("${"), (
        "POSTGRES_PASSWORD is a hardcoded literal; it must come from the "
        "environment with a local-only default"
    )
    assert ":-postgres}" in password or ":-" in password, (
        "POSTGRES_PASSWORD has no local default, so compose up would fail"
    )


def test_healthcheck_exists_so_migrations_do_not_race_startup(compose):
    """`alembic upgrade head` against a server still initialising fails in a
    way that looks like a migration bug."""
    assert "healthcheck" in compose["services"]["postgres"], (
        "no healthcheck: dependent services cannot wait for readiness"
    )


def test_data_directory_is_persisted(compose):
    svc = compose["services"]["postgres"]
    assert svc.get("volumes"), "no volume: the database is lost on every down"
    assert "volumes" in compose, "named volume is not declared at top level"
