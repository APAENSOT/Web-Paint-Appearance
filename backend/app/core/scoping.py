"""Plant visibility -- the single seam for D3.

**D3 is OPEN** (`docs/DEFERRED.md`): nobody has decided whether FTM staff may
see AAT data. `docs/03-SECURITY.md` section 5 states the stand-in and calls
it temporary: *all plants visible to all authenticated roles*, and T03 "must
not invent a third scheme".

So the rule lives here, in one function, returning `None` for "no filter".
When D3 closes, this function reads a claim and returns a list of plant
codes; no repository or router changes. Anything that filters by plant
outside this function is a second scheme, which is exactly what the task
forbids.
"""

from __future__ import annotations

from app.core.security import Principal

#: Text surfaced in `/api/v1/auth/me`, so a client can see the rule is
#: temporary rather than inferring a policy from an empty filter.
D3_TEMPORARY_RULE = (
    "D3 open: all plants are visible to every authenticated role "
    "(docs/03-SECURITY.md section 5, temporary)."
)


def visible_plants(principal: Principal) -> list[str] | None:
    """Plant codes this principal may read, or ``None`` for all of them."""
    return None
