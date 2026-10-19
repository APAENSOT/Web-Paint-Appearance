"""CF grading — the single implementation (`AGENTS.md` §5).

Ported from the prototype's CFCore, not from a markdown table.
`Paint Appearance/Component/CF and Pelt/Prototype.html`,
sha256 ``5da8455dbe93f502883cac2c55143100beafc3c0f2a4fb1d88403e578ee084ad``,
CFCore in the ``<script>`` block at lines 1779–2937. Every function below
names the prototype line it came from. The golden master that proves the two
agree is ``backend/tests/test_t05_grading.py`` against the frozen fixtures in
``backend/tests/golden/fixtures/``; when the two disagree, ``04-ANALYSIS.md``
§9 says the fixture wins until the owner signs a rule change.

**What this module is not.** It grades one reading against one target pair.
It does not decide what a *product* pass rate groups by — that is **D1**, and
it is open. It does not map a colour to a family — that is plant-scoped **D2**
(ADR 0010). ``ref_color.grading_family`` stays unused; callers pass family
from ``ref_plant_color``. There is deliberately no ``COLOR_FAMILY`` table
in this file. ``ref_color.color_group`` is hue (GREEN, SILVER, …) and is
**not** the grading taxonomy (`AGENTS.md` §4). Product pass-rate is **D1**
and stays open.

`00-ARCHITECTURE.md` §5: no FastAPI, no psycopg, no SQLAlchemy in here.
`04-ANALYSIS.md` §8: SQL holds no Ford/Min thresholds either.
"""

from __future__ import annotations

import math
from typing import Literal, Mapping, Optional

Status = Literal["PASS", "WARNING", "FAIL"]
Orientation = Literal["H", "V"]

#: Prototype ~1930, ``var EPS = 1e-9``. The band comparisons below are the
#: only place it is used, and it is the prototype's number — not a rounder one
#: chosen here. T05's brief is explicit: "EPS matches the prototype. Do not
#: pick a nicer epsilon."
EPS = 1e-9

#: Prototype ~1798–1805, ``DEFAULT_STANDARDS``. Wavescan target values (Ford
#: Production + Minimums) per colour family, from the "Color Family - IMG
#: Plants" document (prototype comment ~1816). These are the *fallback* inside
#: :func:`targets_for`, exactly as in the prototype. `04-ANALYSIS.md` §10 says
#: to seed ``cf_standard`` from this map once and then let the table be the
#: source of truth; that seed is a later task, and until it happens this is
#: where the fallback lives — in one module, not in SQL and not in the UI.
DEFAULT_STANDARDS: Mapping[str, Mapping[str, float]] = {
    "Light Metallics": {"fordH": 57, "fordV": 44, "minH": 50, "minV": 37},
    "Medium Metallics": {"fordH": 60, "fordV": 47, "minH": 53, "minV": 40},
    "Dark Metallics": {"fordH": 62, "fordV": 49, "minH": 55, "minV": 42},
    "Light Solids": {"fordH": 62, "fordV": 49, "minH": 55, "minV": 42},
    "Medium Solids": {"fordH": 65, "fordV": 52, "minH": 58, "minV": 45},
    "Dark Solids": {"fordH": 67, "fordV": 54, "minH": 60, "minV": 47},
}

#: Prototype ~1807–1814, ``COLOR_FAMILY_ORDER``. Display/chart order only.
#: `04-ANALYSIS.md` §3: persist as ``ref_color_family.display_order``. It is
#: not a grading input and nothing in this module reads it.
COLOR_FAMILY_ORDER: tuple[str, ...] = (
    "Light Metallics",
    "Medium Metallics",
    "Dark Metallics",
    "Light Solids",
    "Medium Solids",
    "Dark Solids",
)

#: What :func:`std_pair` returns when there is no usable spec. Named because
#: "no spec" is a real answer here, distinct from a zero threshold.
NO_TARGETS: tuple[Optional[float], Optional[float]] = (None, None)


def _to_float(value: object) -> Optional[float]:
    """The Python reading of JavaScript's ``isFinite`` coercion, for one value.

    ``isFinite`` in the prototype coerces its argument, and is fed something
    CFCore's own ``toNum`` has already turned into a number or ``null``. So the
    honest port is: coerce what can be coerced, and answer ``None`` for what
    cannot — which :func:`status_of` then reports as "not graded", the same as
    ``!isFinite(value)``. ``Decimal`` passes through here, so a value read
    straight out of ``wavescan`` needs no conversion at the call site.

    ``bool`` is refused deliberately. ``True`` is an ``int`` in Python and a
    measurement is not a flag; silently grading ``True`` as ``1.0`` is the kind
    of quiet wrong answer this repository treats as worse than a crash.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def status_of(
    value: Optional[float],
    ford: Optional[float],
    min_std: Optional[float],
) -> Optional[Status]:
    """Prototype ~2754–2759, ``statusOf``. The v3 Ford-standard banded rule.

    .. code-block:: javascript

        function statusOf(value, ford, minStd) {
          if (value === null || !isFinite(value)) return null;
          if (value < minStd - EPS) return 'FAIL';
          if (ford != null && value < ford - EPS) return 'WARNING';
          return 'PASS';
        }

    ================================  =========
    Condition                         Status
    ================================  =========
    ``value < min``                   ``FAIL``
    ``min <= value < ford``           ``WARNING``
    ``value >= ford``                 ``PASS``
    non-finite value                  ``None``
    ================================  =========

    Higher is better, and there is **no OVER band** — PELT has one, WaveScan
    does not (`04-ANALYSIS.md` §2). The v2 "proximity to minimum" rule this
    supersedes graded on ``Min + 2`` and ignored the Ford target; do not
    reintroduce it, and do not add a band, a tolerance, or a rounding step.

    Two ported behaviours that look like bugs and are not:

    * With ``min_std`` absent the FAIL test reads ``value < -EPS`` in the
      prototype, because JavaScript coerces ``null`` to ``0``. A reading with
      no spec at all therefore comes back ``PASS`` from this function alone.
      That is why the call site guards — see :func:`status_for_reading`, which
      is the composition the prototype actually uses. The guard belongs there,
      not here, or the port stops matching the oracle.
    * ``ford != null`` in the prototype is loose, so it screens ``undefined``
      too. ``None`` is the single Python equivalent of both.

    The comparison is on the value as given. T04 stores CF unrounded
    (`AGENTS.md` §4), and nothing here rounds it before comparing — a
    ``Decimal`` from the database and a ``float`` from a fixture take the same
    path. Mixed ``Decimal``/``float`` arithmetic would raise, so the operands
    are floated first, which is what the prototype compares anyway.
    """
    v = _to_float(value)
    if v is None or not math.isfinite(v):
        return None
    # `null - EPS` is `-EPS` in JavaScript: a missing minimum is a floor of
    # zero, not an absent test. Ported, not corrected.
    floor = 0.0 if min_std is None else float(min_std)
    if v < floor - EPS:
        return "FAIL"
    if ford is not None and v < float(ford) - EPS:
        return "WARNING"
    return "PASS"


def targets_for(
    family: Optional[str],
    standards: Optional[Mapping[str, object]] = None,
    color_name: Optional[str] = None,
) -> Optional[Mapping[str, float]]:
    """Prototype ~2773–2788, ``targetsFor``. The resolution chain.

    1. a per-colour override in ``standards['colors'][color_name]``, **only if
       it carries real targets** (``fordH`` present);
    2. otherwise ``standards['families'][family]``;
    3. otherwise ``DEFAULT_STANDARDS[family]``;
    4. otherwise ``None`` — this reading cannot be graded.

    Step 1's condition is the whole point of the Phase 6 comment in the
    prototype: a colour taught for import but given no targets yet must fall
    *through* to its family, not blank out grading. `04-ANALYSIS.md` §4:
    "Port this exactly."

    A ``standards`` mapping with no ``families`` key is the legacy flat shape
    (``{'Light Solids': {...}}``) and is still accepted, as in the prototype.

    Passing ``standards=None`` — which is what the golden master does — means
    DEFAULT_STANDARDS and no colour overrides at all.
    """
    if not standards:
        families: Mapping[str, object] = DEFAULT_STANDARDS
    elif "families" in standards:
        colors = standards.get("colors") or {}
        if color_name and isinstance(colors, Mapping):
            override = colors.get(color_name)
            if isinstance(override, Mapping) and override.get("fordH") is not None:
                return override  # type: ignore[return-value]
        families = standards.get("families") or {}  # type: ignore[assignment]
    else:
        families = standards  # legacy flat shape

    row = families.get(family) if isinstance(families, Mapping) and family is not None else None
    if isinstance(row, Mapping):
        return row  # type: ignore[return-value]
    return DEFAULT_STANDARDS.get(family) if family is not None else None


def std_pair(
    std: Optional[Mapping[str, float]],
    orient: Optional[str],
) -> tuple[Optional[float], Optional[float]]:
    """Prototype ~2792–2797, ``stdPair``. Returns ``(ford, min)``.

    Orientation ``'H'`` takes ``fordH``/``minH``; anything else takes
    ``fordV``/``minV`` — the prototype's ``else`` is unguarded, so ``'V'``,
    ``None`` and a typo all land on the vertical pair. Ported as written.

    **Defined once, on purpose.** The prototype defines this function twice —
    ~2792 in CFCore and again, identically, ~2982 in CFLogic, under a comment
    claiming it exists once. `04-ANALYSIS.md` §4 records duplicated resolution
    as a recurring production bug, and `AGENTS.md` §4 lists "copying
    ``stdPair`` into two Python modules" as a defect. This is the only copy in
    this repository. Anything that needs an H/V target pair — charts, the
    detail table, a future KPI — imports it from here.

    ``orient`` is the ``H``/``V`` axis of ``wavescan.tolerance_group``, which
    `04-ANALYSIS.md` §5 requires be derived in exactly one place
    (``domain.cleaner.derive_tolerance``, at ingest). :func:`orientation_of`
    converts, and does not re-derive.
    """
    if not std:
        return NO_TARGETS
    if orient == "H":
        return _maybe(std.get("fordH")), _maybe(std.get("minH"))
    return _maybe(std.get("fordV")), _maybe(std.get("minV"))


def _maybe(value: object) -> Optional[float]:
    return None if value is None else float(value)  # type: ignore[arg-type]


def orientation_of(tolerance_group: Optional[str]) -> Optional[Orientation]:
    """``wavescan.tolerance_group`` -> the ``H``/``V`` axis :func:`std_pair` routes on.

    A translation, **not** a second orientation rule. The rule itself —
    HOOD/ROOF is horizontal, everything else vertical — lives once, in
    ``domain.cleaner.derive_tolerance``, and runs at ingest
    (`04-ANALYSIS.md` §5). This function only shortens what that already
    decided, and it accepts the prototype's own ``'H'``/``'V'`` so a fixture
    row and a database row can take the same call.
    """
    if tolerance_group is None:
        return None
    key = tolerance_group.strip().upper()
    if key in ("H", "HORIZONTAL"):
        return "H"
    if key in ("V", "VERTICAL"):
        return "V"
    return None


def status_for_reading(
    value: Optional[float],
    family: Optional[str],
    tolerance_group: Optional[str],
    standards: Optional[Mapping[str, object]] = None,
    color_name: Optional[str] = None,
) -> tuple[Optional[Status], Optional[float], Optional[float]]:
    """Grade one reading. Returns ``(status, ford, min)``.

    This is the prototype's ``zoneStatuses`` (~2864–2877) status line, which is
    the only place the prototype grades a single reading rather than a group
    average, and therefore the composition the golden master freezes:

    .. code-block:: javascript

        var pair   = stdPair(targetsFor(rec.family, standards, rec.color), rec.orient);
        var hasStd = pair.ford !== null;
        status: hasStd ? statusOf(rec.cf, pair.ford, pair.min) : null

    The ``hasStd`` guard is the reason a family with no spec reports "not
    graded" instead of the bare ``PASS`` that :func:`status_of` alone would
    return. The guard is on ``ford`` only — again, as written.

    ``standards=None`` and ``color_name=None`` are the defaults because that is
    the grain T05 froze: family defaults, no colour overrides, while **D2** is
    open. The parameters exist so an approved per-colour standard can arrive
    later without a second grading path.
    """
    ford, minimum = std_pair(targets_for(family, standards, color_name), orientation_of(tolerance_group))
    if ford is None:
        return None, ford, minimum
    return status_of(value, ford, minimum), ford, minimum


# =====================================================================
# T67: FilmThickness box status, graded on the box MEAN (D-67-01..03).
# =====================================================================
FilmBoxStatus = Literal["PASS", "WARNING", "FAIL", "OVER"]


def film_box_status(
    layer_code: str,
    mean: object,
    lo: object,
    hi: object,
    target: object,
) -> Optional[FilmBoxStatus]:
    """Status of one Film box from its **mean** (T67-CONTEXT table). Never per point.

    ======================  ==============================================
    Layer                   Status
    ======================  ==============================================
    ``CLEAR``               needs ``lo`` and ``target``, else ``None``:
                            ``mean < lo`` FAIL, ``lo <= mean < target``
                            WARNING, ``mean >= target`` PASS. Never OVER;
                            a stray ``hi`` is ignored (D-67-07).
    ``ECOAT/PRIMER/BASE``   ``mean < lo`` FAIL, ``mean > hi`` OVER, else
                            PASS; each bound only if present. No bound at
                            all (no rule) -> ``None``.
    ======================  ==============================================

    Edges are inside the line (D-67-03): ``mean == lo`` is not FAIL,
    ``mean == hi`` is not OVER, ``mean == target`` is PASS, with the
    prototype's :data:`EPS`. WARNING exists only on Clear, OVER only where a
    Maximum exists. This is not a pass rate: D1 stays open.
    """
    m = _to_float(mean)
    if m is None or not math.isfinite(m):
        return None
    low, high, goal = _to_float(lo), _to_float(hi), _to_float(target)
    if layer_code == "CLEAR":
        if low is None or goal is None:
            return None
        if m < low - EPS:
            return "FAIL"
        if m < goal - EPS:
            return "WARNING"
        return "PASS"
    if low is None and high is None:
        return None
    if low is not None and m < low - EPS:
        return "FAIL"
    if high is not None and m > high + EPS:
        return "OVER"
    return "PASS"
