"""Identity and role checks.

`docs/03-SECURITY.md` section 4 describes Ford ID / Entra OIDC with JWKS
validation. That is not implemented here, and this module does not pretend
otherwise: a request carrying a bearer token is **rejected**, because
accepting an unverified token is worse than having no token path at all.
What T03 delivers is the shape -- a `Principal`, a `require_role`
dependency, and a deny-by-default check on every mutating route -- so the
route table already states its RBAC before any of those routes exist.

Until OIDC lands (T04/T06) the only way to obtain an identity is
`AUTH_DEV_BYPASS`, and `Settings` refuses to start the process if that flag
is set outside `ENV=development`.

**Role ordering.** The RBAC matrix in `03-SECURITY.md` section 5 is
monotone: every capability a Viewer has, an Engineer has, and every
capability an Engineer has, an Admin has. So `require_role("engineer")`
accepts an Admin. That reading is asserted cell by cell in
`tests/test_t03_contract.py` rather than assumed here, so if the matrix ever
gains a capability an Admin should *not* have, a test fails instead of a
privilege quietly widening.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import ROLES, Settings

#: Higher number = strictly more capability. Derived from the section 5 matrix.
ROLE_RANK: dict[str, int] = {"viewer": 0, "engineer": 1, "admin": 2}

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


class Principal(BaseModel):
    """Who is making this request."""

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(
        default=None,
        description=(
            "app_user.id. NULL until the OIDC first-login flow (T04) creates "
            "the row -- the API role holds SELECT on app_user, not INSERT."
        ),
    )
    entra_oid: str | None = Field(default=None, description="Entra object id, when known.")
    upn: str = Field(description="User principal name, e.g. someone@ford.com")
    display_name: str
    roles: list[str] = Field(description="Subset of viewer / engineer / admin.")
    auth_source: Literal["oidc", "dev-bypass", "open-access"] = Field(
        description=(
            "How this identity was established. 'dev-bypass' is development only; "
            "'open-access' is the shared account of a build with no sign-in."
        )
    )

    def has_role(self, required: str) -> bool:
        required_rank = ROLE_RANK[required]
        return any(ROLE_RANK.get(r, -1) >= required_rank for r in self.roles)


def _dev_bypass_principal(settings: Settings) -> Principal:
    return Principal(
        user_id=None,
        entra_oid=settings.auth_dev_bypass_oid,
        upn=settings.auth_dev_bypass_upn,
        display_name=settings.auth_dev_bypass_display_name,
        roles=settings.auth_dev_bypass_roles,
        auth_source="dev-bypass",
    )


def _open_access_principal(settings: Settings) -> Principal:
    return Principal(
        user_id=None,
        entra_oid=settings.auth_open_access_oid,
        upn=settings.auth_open_access_upn,
        display_name=settings.auth_open_access_display_name,
        roles=list(ROLES),
        auth_source="open-access",
    )


def resolve_principal(request: Request) -> Principal:
    """FastAPI dependency: the authenticated caller, or 401."""
    settings: Settings = request.app.state.settings
    if settings.auth_open_access:
        # Before the bearer check: a Cloud Run IAM or proxy token in front of a
        # no-sign-in build is the platform's, not a user identity to refuse.
        return _open_access_principal(settings)

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        # A token is offered and this build cannot verify it. Trusting the
        # claims without checking the JWKS signature, issuer, audience and
        # expiry would be an authentication bypass wearing a token's clothes.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Bearer tokens are not accepted yet: Ford ID / Entra OIDC "
                "validation lands with the ingest slice (docs/03-SECURITY.md "
                "section 4). This build refuses unverified tokens rather than "
                "trusting their claims."
            ),
            headers=BEARER_CHALLENGE,
        )

    if settings.auth_dev_bypass and settings.is_development:
        return _dev_bypass_principal(settings)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Not authenticated. Ford ID sign-in is not wired up in this build; "
            "for local work set ENV=development and AUTH_DEV_BYPASS=true."
        ),
        headers=BEARER_CHALLENGE,
    )


CurrentPrincipal = Annotated[Principal, Depends(resolve_principal)]


def require_role(required: str):
    """Dependency factory. Deny by default: no role, no route."""
    if required not in ROLES:
        raise ValueError(f"unknown role {required!r}; expected one of {ROLES}")

    def _dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.has_role(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This route requires the {required!r} role "
                    f"(docs/03-SECURITY.md section 5). You hold {principal.roles}."
                ),
            )
        return principal

    _dependency.__name__ = f"require_role_{required}"
    return _dependency
