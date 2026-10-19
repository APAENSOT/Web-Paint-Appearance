"""T05 — the golden master for CF grading.

`04-ANALYSIS.md` §9: "CF has no JS unit suite. Python grading is untrusted
until it matches the prototype, measurement by measurement." This file is the
match. It compares ``app.domain.grading`` against JSON frozen from the
executed prototype by ``backend/tests/golden/build_fixtures.js``.

Nothing here needs a database, a network, or Node — the fixtures are the
oracle, already answered. Regenerating them needs all three; that is a
separate, deliberate step recorded in ``docs/reports/T05-GOLDEN.md``.

Grain, restated so a reader of this file alone is not misled: **one case per
measurement row**, ``statusOf(cf, ford, min)`` with targets from
``DEFAULT_STANDARDS`` and no colour overrides. It is a regression oracle. It
is **not** the product KPI — **D1** (what the dashboard groups by) and **D2**
(colour → family) are both still open, and this suite asserts that T05 left
them open.
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Mapping

import pytest

from app.domain import grading
from app.domain.cleaner import derive_tolerance

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
FIXTURE_DIR = GOLDEN_DIR / "fixtures"

#: The prototype the fixtures were generated from. Every fixture repeats it,
#: and the first test below proves they agree with each other.
PROTOTYPE_SHA256 = "5da8455dbe93f502883cac2c55143100beafc3c0f2a4fb1d88403e578ee084ad"


def _fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    assert path.is_file(), (
        f"missing fixture {name}. Regenerate with: node {GOLDEN_DIR.as_posix()}/build_fixtures.js"
    )
    return json.loads(path.read_text(encoding="utf-8"))


ROWS = _fixture("wavescan_rows.json")
BOUNDARY = _fixture("boundary.json")
ORIENTATION = _fixture("orientation.json")

#: ``'H'``/``'V'`` is the prototype's axis; the database column says the word.
#: Grading takes either, so the fixtures are fed through the word form — the
#: shape a real ``wavescan`` row has.
AS_TOLERANCE_GROUP = {"H": "Horizontal", "V": "Vertical"}


def _number(value):
    """Fixture JSON cannot hold NaN or Infinity, so the builder wrote them as
    strings. Turn them back into the floats the prototype actually graded."""
    if isinstance(value, str):
        return {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}[value]
    return value


# =====================================================================
# 1. The fixtures are what they claim to be
# =====================================================================
def test_every_fixture_names_the_same_prototype():
    """A fixture regenerated against a different prototype, or half-regenerated,
    would silently change what "correct" means. The hash is the tell."""
    for name, fixture in (("wavescan_rows", ROWS), ("boundary", BOUNDARY),
                          ("orientation", ORIENTATION)):
        assert fixture["prototype"]["sha256"] == PROTOTYPE_SHA256, f"{name} is stale"
        assert fixture["prototype"]["path"].endswith("Prototype.html")


def test_the_module_docstring_names_that_same_prototype():
    """`grading.py` cites a hash in prose. Prose drifts; this makes it not."""
    assert PROTOTYPE_SHA256 in (REPO_ROOT / "backend/app/domain/grading.py").read_text(
        encoding="utf-8"
    )


def test_no_workbook_was_committed_with_the_fixtures():
    """`03-SECURITY.md` §8. The fixtures carry each workbook's SHA-256 and its
    numbers; the workbook itself stays in the read-only vault."""
    strays = sorted(p.name for p in GOLDEN_DIR.rglob("*") if p.suffix.lower() in {".xlsx", ".xlsm", ".xls"})
    assert strays == [], f"workbooks under tests/golden: {strays}"


def test_the_freeze_covers_the_vault_workbooks():
    """Eight workbooks are named in `04-ANALYSIS.md` §9. If the vault is not
    reachable the fixture would be empty, and this suite would be vacuous."""
    assert len(ROWS["files"]) == 8, [f["file"] for f in ROWS["files"]]
    assert ROWS["totals"]["rows"] == 5195
    assert len(ROWS["rows"]) == ROWS["totals"]["rows"]
    for entry in ROWS["files"]:
        assert len(entry["sha256"]) == 64, entry["file"]


def test_one_workbook_is_recorded_as_unparsed_rather_than_quietly_dropped():
    """`CF_Aug_FVL.xlsx` uses Panel/Orientation headers where every other file
    uses Checkzone/Tolerance Group, so the prototype's own `looksFlat` does not
    recognise it and reads nothing. That is the prototype's answer, and T05
    freezes the prototype's answers. It is recorded, not patched around: T05
    is not allowed to invent a template the prototype cannot read."""
    empty = [f["file"] for f in ROWS["files"] if f["rows"] == 0]
    assert empty == ["CF_Aug_FVL.xlsx"]


# =====================================================================
# 2. The oracle: Python must reproduce the prototype, row for row
# =====================================================================
def test_python_grades_every_frozen_measurement_row_exactly_as_the_prototype_did():
    """The T05 acceptance test. 5195 real readings out of seven WaveScan
    workbooks; every ford, every min, every status."""
    mismatches = []
    for row in ROWS["rows"]:
        status, ford, minimum = grading.status_for_reading(
            row["cf"], row["family"], AS_TOLERANCE_GROUP[row["orient"]]
        )
        actual = {"ford": ford, "min": minimum, "status": status}
        expected = {"ford": row["ford"], "min": row["min"], "status": row["status"]}
        if actual != expected:
            mismatches.append((row["row"], row["family"], row["orient"], row["cf"], expected, actual))
    assert mismatches == [], f"{len(mismatches)} of {len(ROWS['rows'])} rows differ: {mismatches[:5]}"


def test_the_frozen_rows_are_not_all_one_answer():
    """A suite that only ever sees PASS would not notice a broken band. The
    counts are asserted, not just their presence, so a regenerated fixture that
    quietly loses a band fails here rather than passing everything."""
    assert ROWS["totals"]["status"] == {"FAIL": 471, "PASS": 3008, "WARNING": 1716}
    assert set(ROWS["totals"]["orient"]) == {"H", "V"}
    assert len(ROWS["totals"]["family"]) == 5


def test_python_matches_the_prototype_at_the_band_edges():
    """Real readings sit nowhere near an edge — 336 synthetic probes do, an EPS
    step either side of every min and every ford in the table."""
    for case in BOUNDARY["cases"]:
        cf = _number(case["cf"])
        tolerance_group = AS_TOLERANCE_GROUP[case["orient"]]
        status, ford, minimum = grading.status_for_reading(cf, case["family"], tolerance_group)
        where = f"case {case['case']}: {case['family']}/{case['orient']} cf={case['cf']!r}"
        assert ford == case["ford"], where
        assert minimum == case["min"], where
        assert status == case["status"], where
        # …and `statusOf` on its own, unguarded, which is what the guard exists
        # to wrap. Freezing both is what stops the guard migrating into
        # `status_of` and changing the rule.
        assert grading.status_of(cf, case["ford"], case["min"]) == case["statusOfRaw"], where


def test_python_matches_the_prototype_on_the_resolution_chain():
    """`targetsFor`'s four steps, including the Phase 6 fall-through that a
    colour taught without targets must take."""
    for case in BOUNDARY["resolution"]:
        std = grading.targets_for(case["family"], case["standards"], case["color"])
        where = f"resolution case {case['case']}: {case['label']}"
        if case["targets"] is None:
            assert std is None, where
        else:
            assert std is not None, where
            for key, value in case["targets"].items():
                assert std.get(key) == value, f"{where}: {key}"
        for orient, expected in (("H", case["pairH"]), ("V", case["pairV"])):
            ford, minimum = grading.std_pair(std, orient)
            assert ford == expected["ford"], f"{where} [{orient}]"
            assert minimum == expected["min"], f"{where} [{orient}]"


def test_the_default_standards_table_matches_the_prototypes_byte_for_byte():
    """`04-ANALYSIS.md` §3 prints this table too. The prototype is the source
    of truth (`AGENTS.md` §4); the markdown is not a second original."""
    assert dict(grading.DEFAULT_STANDARDS) == BOUNDARY["defaultStandards"]
    assert list(grading.COLOR_FAMILY_ORDER) == BOUNDARY["colorFamilyOrder"]
    assert grading.EPS == BOUNDARY["eps"]


# =====================================================================
# 3. One rule, one place
# =====================================================================
def test_orientation_is_derived_once_and_grading_only_translates_it():
    """`04-ANALYSIS.md` §5: `wavescan.tolerance_group` is the orientation, and
    grading must not carry a second implementation of it. Proven over all 155
    distinct checkzone strings in the vault: T04's `derive_tolerance` and the
    prototype's `orientationOf` reach the same answer every time."""
    for entry in ORIENTATION["zones"]:
        derived = derive_tolerance(entry["zone"].upper())
        assert grading.orientation_of(derived) == entry["orient"], entry["zone"]
    assert ORIENTATION["totals"]["zones"] == 155
    assert ORIENTATION["totals"]["orient"] == {"H": 26, "V": 129}


def test_std_pair_is_defined_exactly_once_in_the_backend():
    """`AGENTS.md` §4 lists "copying `stdPair` into two Python modules" as a
    defect, and the prototype itself defines it twice (~2792 and ~2982) under a
    comment claiming otherwise. One copy here, and it is in `domain/`."""
    definitions = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in (REPO_ROOT / "backend" / "app").rglob("*.py")
        if re.search(r"^def std_pair\b", path.read_text(encoding="utf-8"), re.M)
    )
    assert definitions == ["backend/app/domain/grading.py"], definitions


def test_only_the_grading_module_carries_a_threshold_in_application_code():
    """`04-ANALYSIS.md` §8: grades are computed in `domain/grading.py`, and SQL
    holds no Ford/Min thresholds. One application module names them."""
    thresholds = re.compile(r"\bford[HV]\b|\bmin[HV]\b", re.I)
    offenders = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in (REPO_ROOT / "backend" / "app").rglob("*.py")
        if thresholds.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == ["backend/app/domain/grading.py"], offenders


def test_the_ported_table_and_the_seeded_table_cannot_drift():
    """T02 already seeded `cf_standard` from the same prototype constant, which
    is what `04-ANALYSIS.md` §10 asks for: seed once, then the table is the
    source of truth. That leaves the numbers written down twice in this repo —
    the migration's seed and the fallback inside `targets_for` — so this test
    pins them to each other. If they ever disagree, one of them is wrong and
    nobody would otherwise find out.

    The remaining work is recorded in `docs/reports/T05-GOLDEN.md`: a later task
    should read `cf_standard` and inject it through the `standards` argument, at
    which point `DEFAULT_STANDARDS` is a fallback only. T05 does not do that,
    because the frozen oracle was generated with `standards = null` and a
    database-backed lookup would be grading against something the prototype
    never saw."""
    source = (REPO_ROOT / "backend/migrations/versions/0002_t02_target_schema.py").read_text(
        encoding="utf-8"
    )
    block = re.search(r"^DEFAULT_STANDARDS = \{$(.+?)^\}$", source, re.M | re.S)
    assert block, "T02 no longer seeds cf_standard from a DEFAULT_STANDARDS literal"
    seeded = dict(
        (family, tuple(int(n) for n in numbers.split(",")))
        for family, numbers in re.findall(r'"([^"]+)":\s*\(([^)]+)\)', block.group(1))
    )
    ported = {
        family: (row["fordH"], row["fordV"], row["minH"], row["minV"])
        for family, row in grading.DEFAULT_STANDARDS.items()
    }
    assert seeded == ported


def test_grading_imports_no_framework():
    """`00-ARCHITECTURE.md` §5 rule 1, the same check T03 applies to the whole
    package. Repeated here so the failure names grading when grading is why."""
    code = (REPO_ROOT / "backend/app/domain/grading.py").read_text(encoding="utf-8")
    for banned in ("import fastapi", "from fastapi", "import psycopg", "import sqlalchemy"):
        assert banned not in code


# =====================================================================
# 4. The rule itself — a mutant must not survive
#
# The fixtures above would catch a wholesale rewrite. These catch the small
# plausible edits: a flipped comparison, a dropped band, a nicer epsilon, an
# OVER band borrowed from PELT, a rounding step before the comparison.
# =====================================================================
@pytest.mark.parametrize(
    "cf, expected",
    [
        (54.9, "FAIL"),      # below min
        (55.0, "WARNING"),   # exactly min -> not a FAIL
        (58.0, "WARNING"),   # between
        (61.99999, "WARNING"),
        (62.0, "PASS"),      # exactly ford -> PASS
        (200.0, "PASS"),     # no OVER band; PELT has one, WaveScan does not
    ],
)
def test_the_v3_ford_band_is_inclusive_at_both_edges(cf, expected):
    """Light Solids horizontal: min 55, ford 62 (`04-ANALYSIS.md` §2 and §3)."""
    assert grading.status_for_reading(cf, "Light Solids", "Horizontal")[0] == expected


def test_a_reading_a_hair_under_a_threshold_still_counts_as_reaching_it():
    """That is what EPS is for. The numbers here are written out rather than
    expressed as multiples of `grading.EPS`, because an assertion phrased in
    terms of the constant it is testing moves with it: 1e-6 would pass such a
    test unchanged. 1e-7 is inside a 1e-6 tolerance and outside a 1e-9 one, so
    it is the value that actually pins the epsilon to the prototype's."""
    assert grading.EPS == 1e-9
    assert grading.status_of(62 - 5e-10, 62, 55) == "PASS"      # half an EPS under
    assert grading.status_of(62 - 1e-7, 62, 55) == "WARNING"    # a hundred EPS under
    assert grading.status_of(55 - 5e-10, 62, 55) == "WARNING"
    assert grading.status_of(55 - 1e-7, 62, 55) == "FAIL"


def test_cf_is_not_rounded_before_it_is_graded():
    """T04 stores CF unrounded (`AGENTS.md` §4 calls rounding it a defect), and
    the prototype's own comment at ~2848 says every digit participates. A
    grader that rounded to one decimal first would call this PASS."""
    assert grading.status_for_reading(61.96, "Light Solids", "Horizontal")[0] == "WARNING"
    assert grading.status_for_reading(54.96, "Light Solids", "Horizontal")[0] == "FAIL"


def test_a_decimal_straight_out_of_the_database_grades_like_a_float():
    """`wavescan.cf` is NUMERIC, so psycopg hands back `Decimal`. Mixing that
    with a float threshold raises unless the port converts, and T04's stored
    values carry the source file's full float32 tail."""
    assert grading.status_for_reading(Decimal("50.2000007629395"), "Light Metallics", "Horizontal")[0] == "WARNING"
    assert grading.status_for_reading(Decimal("49.9"), "Light Metallics", "Horizontal")[0] == "FAIL"
    assert grading.status_of(Decimal("62.0"), 62, 55) == "PASS"


def test_an_ungradeable_reading_says_so_instead_of_guessing():
    """Non-finite, absent, or not a number at all — `None`, never a band."""
    for value in (None, math.nan, math.inf, -math.inf, "not a number", object()):
        assert grading.status_of(value, 62, 55) is None, value


def test_a_flag_is_not_a_measurement():
    """`True` is an `int` in Python. Grading it as 1.0 would be a silent wrong
    answer, which this system treats as worse than a crash."""
    assert grading.status_of(True, 62, 55) is None
    assert grading.status_of(False, 62, 55) is None


def test_a_family_with_no_spec_is_not_graded_rather_than_passed():
    """The `hasStd` guard at the `zoneStatuses` call site. Without it the bare
    `statusOf` would answer PASS, because JavaScript reads a missing minimum as
    zero — which is exactly what the second assertion pins down."""
    status, ford, minimum = grading.status_for_reading(60.0, "Aluminium Metallic", "Horizontal")
    assert (status, ford, minimum) == (None, None, None)
    assert grading.status_of(60.0, None, None) == "PASS"
    assert grading.status_of(-1.0, None, None) == "FAIL"


def test_an_unknown_orientation_takes_the_vertical_pair():
    """The prototype's `stdPair` has an unguarded `else`. Ported as written, so
    a mis-typed tolerance group is graded vertically rather than crashing —
    and this test is where a reviewer finds that out."""
    assert grading.std_pair(grading.DEFAULT_STANDARDS["Light Solids"], "sideways") == (49.0, 42.0)
    assert grading.std_pair(grading.DEFAULT_STANDARDS["Light Solids"], None) == (49.0, 42.0)
    assert grading.std_pair(None, "H") == (None, None)


# =====================================================================
# 5. T05 answered no deferred question
# =====================================================================
def test_grading_holds_no_colour_map():
    """**D2**. `ref_color.grading_family` is NULL on all 21 colours and stays
    that way. The prototype's `COLOR_FAMILY` was *used* to generate the
    fixtures and was deliberately **not** copied into this repository as data —
    a family reaches grading as an argument or nothing is graded."""
    tables = {
        name: value
        for name, value in vars(grading).items()
        if isinstance(value, Mapping) and not name.startswith("_")
    }
    assert set(tables) == {"DEFAULT_STANDARDS"}, sorted(tables)
    assert set(tables["DEFAULT_STANDARDS"]) == set(grading.COLOR_FAMILY_ORDER)
    assert "COLOR_FAMILY = " not in (REPO_ROOT / "backend/app/domain/grading.py").read_text(
        encoding="utf-8"
    )


def test_the_fixtures_were_frozen_without_colour_overrides():
    """The freeze passed `standards = null`, so `targetsFor` took its
    DEFAULT_STANDARDS branch for every one of the 5195 rows. Anything else
    would have been a colour map frozen by the back door."""
    assert "no colour overrides" in ROWS["standards"]
    assert ROWS["grain"].endswith("zoneStatuses(parseSheets(book).records, null)")
    families = set(ROWS["totals"]["family"])
    assert families <= set(grading.DEFAULT_STANDARDS), families


def test_t05_added_no_grading_field_to_the_api():
    """**D1**. T05 blocks any API field named status / passRate / ribbon; it
    does not unblock one. T03's banned-key tests cover the live responses —
    this covers the source, so a DTO field added alongside grading is caught
    even before a route returns it.

    `status` itself is not in this list: T04's batch lifecycle legitimately owns
    that word (QUEUED, PENDING_REVIEW, COMMITTED), and T03's banned-key tests
    already prove no *measurement* response carries one. The names below have
    no meaning except a grade."""
    banned = re.compile(
        r"^\s*(grade|grades|grading_status|cf_status|pass_rate|passrate|pass_count"
        r"|fail_count|warn_count|ribbon|verdict)\s*:",
        re.M,
    )
    offenders = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in (REPO_ROOT / "backend/app/schemas").rglob("*.py")
        if banned.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], offenders


def test_nothing_outside_the_domain_imports_grading_yet():
    """T05 delivered the rule. Monthly Overview's service is the first allowed
    caller: it grades one model×colour×orientation mean for the plant month.
    That is not the product pass-rate — D1 stays open."""
    importers = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in (REPO_ROOT / "backend/app").rglob("*.py")
        if re.search(r"\bimport +grading\b|\bfrom +\.?grading\b|domain\.grading\b",
                     path.read_text(encoding="utf-8"))
        and path.name != "grading.py"
    )
    # T67 CHANGE: the Film overview service grades one box mean with
    # film_box_status (D-67-10). Still no pass rate -- D1 stays open.
    assert importers == [
        # T105: IMG imports only orientation_of (canonical H/V, the plant
        # Overview's own resolution) -- never a status; checked in test_t105.
        "backend/app/domain/img_overview.py",
        "backend/app/services/film_overview.py",
        "backend/app/services/img_overview.py",
        # Monthly Detail: owner-requested status of one point's monthly mean,
        # Overview's own rules; no per-reading grade, no pass rate -- D1 stays
        # open (docs/tasks/MONTHLY-DETAIL-inspection.md).
        "backend/app/services/monthly_detail.py",
        "backend/app/services/overview.py",
    ], importers
