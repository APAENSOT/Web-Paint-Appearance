"""Does the golden master actually notice a broken rule?

    python backend/tests/golden/mutation_check.py

T05's brief asks for one thing beyond "the tests pass": *"A mutation that
changes the Ford-band rule must fail the suite."* A suite of 5195 rows that all
agree is easy to write and easy to fool — every real reading in the vault sits
far from a band edge, so a wrong epsilon or a missing guard can hide inside a
green run. This script proves the suite is not fooled: it edits
``app/domain/grading.py`` one plausible defect at a time, runs
``tests/test_t05_grading.py``, and restores the file.

A mutant is KILLED when the suite fails and SURVIVED when it passes. A
survivor is a hole in the suite, not a curiosity — the two this script found
on its first run (an epsilon "tidied" to 1e-6, and an edge test phrased in
terms of the very constant it was testing) are both fixed, and the probes that
close them are in ``fixtures/boundary.json`` and in
``test_a_reading_a_hair_under_a_threshold_still_counts_as_reaching_it``.

This is not a pytest module and is not collected. It shells out to pytest, it
rewrites a source file, and it takes a few seconds per mutant — none of which
belongs in a suite that has to stay fast and side-effect free. It is run by
hand when the rule or the suite changes, and its output is quoted in
``docs/reports/T05-GOLDEN.md``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
TARGET = BACKEND / "app" / "domain" / "grading.py"
SUITE = "tests/test_t05_grading.py"

#: (label, find, replace). Each is a defect somebody could plausibly introduce
#: while "improving" the rule — the exact list `04-ANALYSIS.md` §2 and
#: `AGENTS.md` §4 warn about, plus the ones this port's own shape invites.
MUTANTS: list[tuple[str, str, str]] = [
    (
        "FAIL edge becomes inclusive",
        "if v < floor - EPS:",
        "if v <= floor - EPS:",
    ),
    (
        "WARNING band removed (two bands, not three)",
        '    if ford is not None and v < float(ford) - EPS:\n        return "WARNING"\n',
        "",
    ),
    (
        "PASS gate moved to the minimum (the superseded v2 rule)",
        "if ford is not None and v < float(ford) - EPS:",
        "if ford is not None and v < floor + 2:",
    ),
    # Anchored on the newline either side: `EPS = 1e-9` also appears inside the
    # docstring that quotes the prototype, and a mutant that only edits prose
    # would "survive" for the wrong reason.
    (
        "EPS tidied up to 1e-6",
        "\nEPS = 1e-9\n",
        "\nEPS = 1e-6\n",
    ),
    (
        "EPS dropped altogether",
        "\nEPS = 1e-9\n",
        "\nEPS = 0.0\n",
    ),
    (
        "PELT's OVER band borrowed",
        '        return "WARNING"\n    return "PASS"',
        '        return "WARNING"\n    if ford is not None and v > float(ford) * 1.2:\n'
        '        return "OVER"\n    return "PASS"',
    ),
    (
        "CF rounded to 1dp before it is graded",
        "    floor = 0.0 if min_std is None else float(min_std)",
        "    v = round(v, 1)\n    floor = 0.0 if min_std is None else float(min_std)",
    ),
    (
        "the no-spec guard moved into status_of",
        "    floor = 0.0 if min_std is None else float(min_std)",
        "    if min_std is None:\n        return None\n    floor = float(min_std)",
    ),
    (
        "the no-spec guard dropped from the call site",
        "    if ford is None:\n        return None, ford, minimum",
        "    if False:\n        return None, ford, minimum",
    ),
    (
        "stdPair returns (min, ford) for horizontal",
        'return _maybe(std.get("fordH")), _maybe(std.get("minH"))',
        'return _maybe(std.get("minH")), _maybe(std.get("fordH"))',
    ),
    (
        "orientation routing inverted",
        'if orient == "H":',
        'if orient == "V":',
    ),
    (
        "orientation defaults to horizontal instead of vertical",
        '    if orient == "H":\n        return _maybe(std.get("fordH")), _maybe(std.get("minH"))\n'
        '    return _maybe(std.get("fordV")), _maybe(std.get("minV"))',
        '    if orient == "V":\n        return _maybe(std.get("fordV")), _maybe(std.get("minV"))\n'
        '    return _maybe(std.get("fordH")), _maybe(std.get("minH"))',
    ),
    (
        "targetsFor: a colour taught without targets stops falling through",
        'if isinstance(override, Mapping) and override.get("fordH") is not None:',
        "if isinstance(override, Mapping):",
    ),
    (
        "targetsFor: the DEFAULT_STANDARDS fallback removed",
        "    return DEFAULT_STANDARDS.get(family) if family is not None else None",
        "    return None",
    ),
    (
        "one number in DEFAULT_STANDARDS changed",
        '"Light Solids": {"fordH": 62',
        '"Light Solids": {"fordH": 63',
    ),
    (
        "a non-finite reading graded instead of refused",
        "    if v is None or not math.isfinite(v):\n        return None",
        "    if v is None:\n        return None",
    ),
]


def run_suite() -> tuple[bool, str]:
    """True when the suite passes. Returns pytest's last line as evidence."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    tail = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    return proc.returncode == 0, (tail[-1] if tail else "(no output)")


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")

    ok, summary = run_suite()
    print(f"baseline: {summary}")
    if not ok:
        print("the suite is already failing; fix that before mutating anything")
        return 2

    survived: list[str] = []
    try:
        for label, find, replace in MUTANTS:
            if original.count(find) != 1:
                print(f"  SKIPPED  {label}\n           anchor matched {original.count(find)} times")
                survived.append(label + " (anchor drifted)")
                continue
            TARGET.write_text(original.replace(find, replace), encoding="utf-8")
            passed, summary = run_suite()
            verdict = "SURVIVED" if passed else "KILLED  "
            print(f"  {verdict} {label:<58} {summary}")
            if passed:
                survived.append(label)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        # Restore unconditionally: a Ctrl-C here would otherwise leave a
        # deliberately broken grading rule on disk.
        TARGET.write_text(original, encoding="utf-8")

    print()
    if survived:
        print(f"{len(survived)} of {len(MUTANTS)} mutants survived - the suite has a hole:")
        for label in survived:
            print(f"  - {label}")
        return 1
    print(f"all {len(MUTANTS)} mutants killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
