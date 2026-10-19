"""Standing FastAPI on 8012 for owner trial (engineer+admin bypass)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ENV_TEST = BACKEND / ".env.test"


def load_env_test() -> None:
    if not ENV_TEST.exists():
        raise SystemExit(f"missing {ENV_TEST}")
    for line in ENV_TEST.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def keyword_dsn_to_url(dsn: str) -> str:
    parts: dict[str, str] = {}
    for token in dsn.split():
        if "=" in token:
            k, v = token.split("=", 1)
            parts[k] = v
    user = parts.get("user", "")
    host = parts.get("host", "127.0.0.1")
    port = parts.get("port", "5432")
    name = parts.get("dbname", "")
    password = parts.get("password", "")
    credential = user + (f":{password}" if password else "")
    return f"postgresql+psycopg://{credential}@{host}:{port}/{name}"


def app_url() -> str:
    load_env_test()
    explicit = os.environ.get("APP_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    dsn = os.environ.get("T01_APP_DSN", "").strip()
    if not dsn:
        raise SystemExit("T01_APP_DSN is not set")
    return keyword_dsn_to_url(dsn)


def main() -> None:
    url = app_url()
    settings = Settings(
        env="development",
        app_database_url=url,
        auth_dev_bypass=True,
        auth_dev_bypass_roles_raw="engineer,admin",
        ingest_worker_enabled=True,
        ingest_worker_poll_seconds=0.05,
        cors_origins_raw=(
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:3000,http://127.0.0.1:3000"
        ),
    )
    app = create_app(settings)
    import uvicorn

    print("starting uvicorn 8012 as engineer,admin")
    uvicorn.run(app, host="127.0.0.1", port=8012, log_level="info")


if __name__ == "__main__":
    main()
