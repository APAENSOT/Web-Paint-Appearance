"""Application configuration.

Two rules shape this module, and both come from `docs/03-SECURITY.md`:

* **The API never connects as a privileged role.** `03-SECURITY.md` section 3
  gives the API `app_rw` and nothing else; `postgres` and `migrator` are
  "out of application config entirely". So a DSN naming one of those roles
  is rejected here, before a connection is ever attempted.
* **`AUTH_DEV_BYPASS` is honoured only when `ENV=development`** (L11,
  `03-SECURITY.md` section 4). Setting it anywhere else is not ignored with
  a warning -- it stops the process. A bypass that fails open in production
  is the whole reason the flag is gated.
* **`AUTH_OPEN_ACCESS` is the one deliberate exception, for this version
  only.** The owner decided (2026-10-20) that this release has no sign-in:
  every visitor acts as one named shared account holding every role, so each
  write is still attributed. Sign-in comes later from another team. It is
  allowed in any ENV, so the server must only be reachable from a private
  network (`infra/gcp/README.md`).

Everything is read from the environment. `.env.example` lists the names.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

DEVELOPMENT = "development"

#: Roles the API may never authenticate as. `postgres` is the superuser that
#: T01 removed from the application environment; `migrator` owns the DDL.
FORBIDDEN_DB_ROLES = frozenset(
    {"postgres", "migrator", "wavescan_admin", "cloudsqlsuperuser", "rdsadmin"}
)

#: The three roles in the RBAC matrix (`03-SECURITY.md` section 5).
ROLES = ("viewer", "engineer", "admin")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # `.env.example` says "copy to `.env`", and until T04 nothing read it.
        # Resolved against this file rather than the working directory, so
        # `uvicorn` started from the repo root and pytest started from
        # `backend/` load the same file. OS environment still wins: BaseSettings
        # ranks env vars above the dotenv source.
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
        # .env.example uses blank values as "not set". Without this, a copied
        # `.env` with AUTH_DEV_BYPASS= crashes Settings on bool_parsing, and
        # blank UPN / display-name fields would overwrite the defaults with "".
        env_ignore_empty=True,
    )

    env: str = Field(
        default=DEVELOPMENT,
        validation_alias=AliasChoices("ENV", "APP_ENV"),
        description="development | test | staging | production",
    )

    app_database_url: str = Field(
        default="",
        validation_alias=AliasChoices("APP_DATABASE_URL"),
        description=(
            "SQLAlchemy URL for the app_rw role. Never the migrator or "
            "superuser URL: the variable Alembic reads is a separate name that "
            "this process deliberately never looks up."
        ),
    )
    db_pool_size: int = 5
    db_pool_max_overflow: int = 5
    db_connect_timeout_seconds: int = 5
    db_statement_timeout_ms: int = 15_000

    auth_dev_bypass: bool = Field(default=False, validation_alias=AliasChoices("AUTH_DEV_BYPASS"))
    auth_dev_bypass_upn: str = "dev.bypass@localhost"
    auth_dev_bypass_display_name: str = "Development bypass"
    auth_dev_bypass_oid: str = "00000000-0000-0000-0000-000000000000"
    # Deny by default (03-SECURITY.md section 5). The bypass identity gets the
    # role that can only read; widen it explicitly and per-machine when you
    # need to exercise an Engineer or Admin route.
    auth_dev_bypass_roles_raw: str = Field(
        default="viewer", validation_alias=AliasChoices("AUTH_DEV_BYPASS_ROLES")
    )

    # Owner decision 2026-10-20: no sign-in in this version. One shared
    # account with every role; the role checks stay in the code for the
    # sign-in that another team adds later.
    auth_open_access: bool = Field(default=False, validation_alias=AliasChoices("AUTH_OPEN_ACCESS"))
    auth_open_access_upn: str = "shared.access@paint-appearance"
    auth_open_access_display_name: str = "Shared access"
    auth_open_access_oid: str = "00000000-0000-0000-0000-00000000a11c"

    cors_origins_raw: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        validation_alias=AliasChoices("CORS_ORIGINS"),
        description="Comma-separated allowlist. No wildcard: credentials are sent.",
    )

    # --- ingest (T04) --------------------------------------------------
    #: Where uploaded bytes live. `data/` is gitignored; the repo root is two
    #: levels above `backend/app/core/`.
    raw_store_dir: str = Field(
        default="", description="Defaults to <repo>/data/raw when empty."
    )
    #: `02-PIPELINE.md` §2 door checks.
    upload_max_file_bytes: int = 25 * 1024 * 1024
    upload_max_files: int = 40
    upload_max_uncompressed_bytes: int = 250 * 1024 * 1024
    upload_max_compression_ratio: float = 200.0
    #: `02-PIPELINE.md` §5 L5. 80% is the demo's validated threshold: 255 true
    #: duplicate groups scored 100%, everything else 30% or less.
    duplicate_threshold: float = 80.0
    #: The in-process worker. Turn it off to run `python -m app.workers.ingest_worker`
    #: as a separate process instead; the claim is SKIP LOCKED either way.
    ingest_worker_enabled: bool = True
    ingest_worker_poll_seconds: float = 0.2

    #: The built frontend (`frontend/dist`) to serve from this process, so a
    #: deploy is one service on one origin. Empty: API only.
    static_dir: str = ""

    api_docs_enabled: bool = True
    api_title: str = "WaveScan Paint Appearance API"
    api_version: str = "0.1.0"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_development(self) -> bool:
        return self.env.strip().lower() == DEVELOPMENT

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def auth_dev_bypass_roles(self) -> list[str]:
        return [r.strip().lower() for r in self.auth_dev_bypass_roles_raw.split(",") if r.strip()]

    @model_validator(mode="after")
    def _bypass_only_in_development(self) -> "Settings":
        if self.auth_dev_bypass and not self.is_development:
            raise ValueError(
                "AUTH_DEV_BYPASS is set but ENV is "
                f"{self.env!r}, not 'development'. The bypass hands out an "
                "identity with no credential; outside development that is an "
                "authentication bypass, so the process refuses to start "
                "(docs/03-SECURITY.md section 4, L11)."
            )
        return self

    @model_validator(mode="after")
    def _one_way_in(self) -> "Settings":
        if self.auth_open_access and self.auth_dev_bypass:
            raise ValueError(
                "AUTH_OPEN_ACCESS and AUTH_DEV_BYPASS are both set. Choose one: "
                "they hand out different identities, and audit rows would mix them."
            )
        if self.auth_open_access and self.auth_open_access_oid == self.auth_dev_bypass_oid:
            raise ValueError("AUTH_OPEN_ACCESS_OID must differ from the dev bypass object id.")
        return self

    @model_validator(mode="after")
    def _roles_are_known(self) -> "Settings":
        unknown = [r for r in self.auth_dev_bypass_roles if r not in ROLES]
        if unknown:
            raise ValueError(
                f"AUTH_DEV_BYPASS_ROLES contains unknown role(s) {unknown}. "
                f"The RBAC matrix has exactly {list(ROLES)} "
                "(docs/03-SECURITY.md section 5)."
            )
        return self

    @model_validator(mode="after")
    def _database_role_is_not_privileged(self) -> "Settings":
        if not self.app_database_url.strip():
            return self
        try:
            url = make_url(self.app_database_url)
        except Exception as exc:  # pragma: no cover - malformed URL
            raise ValueError(f"APP_DATABASE_URL is not a valid SQLAlchemy URL: {exc}") from exc
        if (url.username or "").lower() in FORBIDDEN_DB_ROLES:
            raise ValueError(
                f"APP_DATABASE_URL connects as {url.username!r}. The API runs as "
                "app_rw only (docs/03-SECURITY.md section 3). A route that needs a "
                "privilege app_rw lacks is a design question for the architect, not "
                "a reason to raise the connection's rights."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def raw_store_path(self) -> Path:
        if self.raw_store_dir.strip():
            return Path(self.raw_store_dir).expanduser()
        return Path(__file__).resolve().parents[3] / "data" / "raw"

    def safe_database_url(self) -> str:
        """The URL with any password masked, for logs and health payloads."""
        if not self.app_database_url.strip():
            return ""
        return make_url(self.app_database_url).render_as_string(hide_password=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
