"""Run an existing local API for browser tests; no schema or backend file changes.

Uses APP_DATABASE_URL when set, otherwise the existing gitignored T01_APP_DSN.
Credentials stay in process memory. Run with backend's Python and -B.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("role", choices=("engineer", "admin", "viewer"))
parser.add_argument("port", type=int)
args = parser.parse_args()
backend = Path(__file__).resolve().parents[2] / "backend"
if not os.environ.get("APP_DATABASE_URL"):
    dsn = dotenv_values(backend / ".env.test").get("T01_APP_DSN")
    if not dsn:
        parser.error("Set APP_DATABASE_URL to the remediated app_rw connection.")
    parts = conninfo_to_dict(dsn)
    if parts.get("user") != "app_rw":
        parser.error("T01_APP_DSN must use app_rw.")
    os.environ["APP_DATABASE_URL"] = URL.create(
        "postgresql+psycopg", username=parts["user"], password=parts.get("password"),
        host=parts.get("host", "127.0.0.1"), port=int(parts.get("port", 5432)),
        database=parts.get("dbname"),
    ).render_as_string(hide_password=False)
os.environ.update(ENV="development", AUTH_DEV_BYPASS="true",
                  AUTH_DEV_BYPASS_ROLES=args.role,
                  INGEST_WORKER_ENABLED=str(args.role == "engineer").lower())
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175")
# Three API processes share the small existing test cluster.
os.environ.setdefault("DB_POOL_SIZE", "2")
os.environ.setdefault("DB_POOL_MAX_OVERFLOW", "0")
sys.path.insert(0, str(backend))
uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)
