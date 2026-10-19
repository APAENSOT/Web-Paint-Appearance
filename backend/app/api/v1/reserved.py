"""Mutating routes, reserved.

T03 spec item 5: *"`require_role` dependency; all mutating routes reserved
even if unimplemented (403)."* Every named mutation has since moved to its
own module at the original path and required role.

**None remain here.** ``POST /standards`` is implemented in
``api/v1/standards.py`` (plant-scoped D2 / ADR 0010). D1 stays open:
``grading_available`` is still false.

The file stays so a future reserved kind has a home, and so
``test_t09_immutable.test_only_one_mutating_route_stays_reserved`` can
assert the stub list is empty rather than a forgotten 501.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["reserved"])
