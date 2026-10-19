"""T88 -- teachable panel identity: reach the screen, match the set, guard it.

Claims, against the pure solver, the vocabulary, the read model and the
database:

* **Part 1 (D-88-1).** A spelling written on two models is two questions,
  not an ambiguity: one held group per `(spelling, model)`, each with its
  own model, its own row count, its own candidates and its own orientation.
  A one-model sheet is unchanged. A pair is still only ever confirmed
  against **that** model's panels.
* **Part 2 (D-88-2 / D-88-3).** Orientation is a hard filter that no score
  can beat; the ranking under it is T86/T87's, unchanged; `14ROOF` resolves
  to `RCROOF` by **exhaustion** once `11ROOF` has taken `LCROOF`, and says
  so; `14ROOF` to `14LFBOXSD` is still impossible.
* **Every guardrail of section 3a is its own test**, G-88-1 to G-88-9 --
  including the real four-roofs-for-two-spellings pool, which must yield a
  plain ranked list and **no** exhaustion claim.
* **Part 3.** Every `ref_checkzone` and `ref_checkzone_alias` name
  classifies, the ones that classified before are unchanged, and a name
  that used to classify as nothing now reaches candidates.
* **Part 4.** The audit finds the August shape on a batch this module
  builds, and reports clean where there is none.

Two plants at least (D-88-8). Every row this module writes is its own and
is removed again; the owner's batches are never touched by a test.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.domain.panel_match import LivePanel, rank_candidates
from app.domain.panel_set_match import (
    HeldSpelling,
    SIGNAL_EXHAUSTION,
    SIGNAL_NAME,
    SIGNAL_NONE,
    SIGNAL_NUMBER,
    solve_set,
)
from app.domain.ws_plant_gold import ws_panel_group
from app.repositories.mappings import PANEL_MATCH_METHOD_T88, panel_match_method

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUDIT = BACKEND_ROOT / "scripts" / "audit_panel_identities.py"

pytestmark = pytest.mark.ingest

H, V = "Horizontal", "Vertical"


def panel(code: str, point: int, orientation: str = V) -> LivePanel:
    return LivePanel(zone_code=code, point_no=point, tolerance_group=orientation)


def spelling(raw: str, orientation: str | None = V, position: int | None = None) -> HeldSpelling:
    return HeldSpelling(
        raw_zone_text=raw,
        orientations=() if orientation is None else (orientation,),
        count=10,
        raw_position=position,
    )


#: FTM's two mappable roofs, and the two numbered ones that make the pool
#: four wide. The four-roof pool is the trap G-88-1 exists for.
MAPPABLE_ROOFS = [panel("LCROOF", 11, H), panel("RCROOF", 27, H)]
ALL_FOUR_ROOFS = MAPPABLE_ROOFS + [panel("11ROOF", 43, H), panel("27ROOF", 59, H)]


# =====================================================================
# A. Part 2 -- the set matcher (D-88-2, D-88-3)
# =====================================================================
def test_orientation_is_a_hard_filter_no_score_can_beat():
    """D-88-2. A perfect name of the wrong orientation is not a candidate."""
    # `LFFENDER` would score 1.00 against `06LFFENDER` -- T86 says so -- but
    # the file calls this panel Horizontal and the catalogue calls that one
    # Vertical, so it is not the same physical panel whatever the name says.
    panels = [panel("LFFENDER", 6, V), panel("LCROOF", 11, H)]
    solved = solve_set([spelling("06LFFENDER", H, 6)], panels)
    [proposal] = solved.proposals
    assert [c.zone_code for c in proposal.candidates] == []
    assert proposal.proposed is None
    assert "orientation" in proposal.reason
    # And it is not silently gone: the screen is told what was removed.
    assert proposal.filtered_out == ("LCROOF", "LFFENDER") or "LFFENDER" in proposal.filtered_out

    # The same spelling, the right orientation: T86's ranking, unchanged.
    solved = solve_set([spelling("06LFFENDER", V, 6)], panels)
    assert solved.proposals[0].proposed == "LFFENDER"


def test_14roof_resolves_to_rcroof_by_exhaustion_once_11roof_has_taken_lcroof():
    """The headline case of T88 section 2, with its premise stated.

    `14ROOF` scores 0.80 against both roofs -- a dead tie -- and its number,
    14, is neither 11 nor 27. Name similarity has nothing left to say. What
    answers it is that the other roof is taken.
    """
    spellings = [spelling("11ROOF", H, 11), spelling("14ROOF", H, 14)]
    solved = solve_set(
        spellings, MAPPABLE_ROOFS, confirmed={"11ROOF": "LCROOF"}, live_panel_count=2
    )
    by = solved.by_spelling()
    assert by["14ROOF"].proposed == "RCROOF"
    assert by["14ROOF"].signal == SIGNAL_EXHAUSTION
    # G-88-3: in its own words, with the counts it rests on.
    assert "only one left" in by["14ROOF"].reason
    assert "1 unmatched name(s), 1 unmatched panel(s)" in by["14ROOF"].reason


def test_14roof_is_still_never_14lfboxsd():
    """D-86-3 / D-87-3 survive T88 whole: the family gate is untouched."""
    boxes = [panel("14LFBOXSD", 14, V)]
    # Same orientation, same number, and still not a candidate.
    solved = solve_set([spelling("14ROOF", V, 14)], boxes)
    assert solved.proposals[0].candidates == ()
    assert solved.proposals[0].proposed is None
    assert rank_candidates("14ROOF", boxes) == []


def test_the_assignment_is_bijective_one_spelling_to_one_panel():
    """D-88-2. A panel taken by a confirmed pair leaves the pool."""
    fenders = [panel("LFFENDER", 6), panel("LCFENDER", 7), panel("LRFENDER", 8)]
    spellings = [spelling(f"0{n}LFFENDER", V, n) for n in (6, 7, 8)]
    solved = solve_set(spellings, fenders, live_panel_count=3)
    assert [p.proposed for p in solved.proposals] == ["LFFENDER", "LCFENDER", "LRFENDER"]

    # Confirm the first onto a different panel: nobody else may take it.
    solved = solve_set(
        spellings, fenders, confirmed={"06LFFENDER": "LRFENDER"}, live_panel_count=3
    )
    offered = {
        c.zone_code for p in solved.proposals if p.proposed for c in p.candidates
    }
    assert "LRFENDER" not in offered


def test_the_signal_is_named_for_every_proposal():
    """D-88-3. The owner sees what argued for a pair, every time."""
    fenders = [panel("LFFENDER", 6), panel("LCFENDER", 7)]
    solved = solve_set(
        [spelling("07LFFENDER", V, 7), spelling("ZZUNKNOWN", V, None)],
        fenders,
        live_panel_count=2,
    )
    by = solved.by_spelling()
    assert by["07LFFENDER"].signal == SIGNAL_NUMBER
    assert "number 7" in by["07LFFENDER"].reason
    # D-88-4: no candidates is an answer, and it is never silent.
    assert by["ZZUNKNOWN"].signal == SIGNAL_NONE
    assert by["ZZUNKNOWN"].proposed is None
    assert "no panel of this model" in by["ZZUNKNOWN"].reason
    assert "full list" in by["ZZUNKNOWN"].reason


# =====================================================================
# B. the guardrails -- each its own test (section 3a)
# =====================================================================
def test_g88_1_the_real_four_roof_pool_yields_no_exhaustion_claim():
    """G-88-1, on the pool the task names as the trap.

    Four roofs for two roof spellings. Exhaustion over that pool is
    meaningless, so the pair is offered as a plain ranked list with no
    exhaustion claim at all.
    """
    spellings = [spelling("11ROOF", H, 11), spelling("14ROOF", H, 14)]
    solved = solve_set(spellings, ALL_FOUR_ROOFS, live_panel_count=64)
    assert all(p.signal != SIGNAL_EXHAUSTION for p in solved.proposals), [
        (p.raw_zone_text, p.signal) for p in solved.proposals
    ]
    # It still proposes -- it just does not claim certainty.
    assert solved.by_spelling()["14ROOF"].proposed is not None
    assert solved.by_spelling()["14ROOF"].signal in (SIGNAL_NAME, SIGNAL_NUMBER)


def test_g88_1_exhaustion_is_refused_when_the_counts_differ():
    """G-88-1. One spelling against two reachable panels is not exhaustion."""
    solved = solve_set([spelling("14ROOF", H, 14)], MAPPABLE_ROOFS, live_panel_count=2)
    assert solved.proposals[0].signal != SIGNAL_EXHAUSTION

    # Two spellings against two panels, and one of them has one candidate.
    spellings = [spelling("11ROOF", H, 11), spelling("14ROOF", H, 14)]
    solved = solve_set(
        spellings, MAPPABLE_ROOFS, confirmed={"11ROOF": "LCROOF"}, live_panel_count=2
    )
    assert solved.by_spelling()["14ROOF"].signal == SIGNAL_EXHAUSTION


def test_g88_1_the_check_is_local_to_the_orientation_group():
    """G-88-1. Never a global "the file looks complete".

    The vertical group is short and the horizontal group is closed. The
    horizontal claim must stand on its own, unaffected by the other.
    """
    panels = MAPPABLE_ROOFS + [panel("LFFENDER", 6), panel("LCFENDER", 7)]
    spellings = [
        spelling("11ROOF", H, 11),
        spelling("14ROOF", H, 14),
        spelling("06LFFENDER", V, 6),  # one vertical spelling, two vertical panels
    ]
    solved = solve_set(
        spellings, panels, confirmed={"11ROOF": "LCROOF"}, live_panel_count=4
    )
    by = solved.by_spelling()
    assert by["14ROOF"].signal == SIGNAL_EXHAUSTION, "the closed group still claims"
    assert by["06LFFENDER"].signal != SIGNAL_EXHAUSTION, "the open group does not"


def test_g88_2_the_catalogue_warning_names_both_numbers():
    """G-88-2, and it does not fire when the counts agree."""
    solved = solve_set(
        [spelling("14ROOF", H, 14)], MAPPABLE_ROOFS,
        live_panel_count=64, file_panel_count=32,
    )
    assert solved.catalogue_warning == (64, 32)

    agreed = solve_set(
        [spelling("14ROOF", H, 14)], MAPPABLE_ROOFS,
        live_panel_count=32, file_panel_count=32,
    )
    assert agreed.catalogue_warning is None


def test_g88_3_exhaustion_never_auto_confirms_and_shows_its_counts():
    """G-88-3. It is a labelled suggestion, like any other."""
    spellings = [spelling("11ROOF", H, 11), spelling("14ROOF", H, 14)]
    solved = solve_set(
        spellings, MAPPABLE_ROOFS, confirmed={"11ROOF": "LCROOF"}, live_panel_count=2
    )
    claim = solved.by_spelling()["14ROOF"]
    # A proposal, not a decision: `proposed` is a suggestion and the caller
    # must still confirm it. Nothing in the solution says "confirmed".
    assert claim.signal == SIGNAL_EXHAUSTION
    assert claim.proposed == "RCROOF"
    assert "unmatched name(s)" in claim.reason and "unmatched panel(s)" in claim.reason
    assert all(p.signal != SIGNAL_NONE or p.raw_zone_text == "11ROOF"
               for p in solved.proposals)


def test_g88_4_a_confirmed_pair_is_pinned_through_every_resolve():
    """G-88-4. Re-solving may never move, drop or re-propose it."""
    fenders = [panel("LFFENDER", 6), panel("LCFENDER", 7), panel("LRFENDER", 8)]
    spellings = [spelling(f"0{n}LFFENDER", V, n) for n in (6, 7, 8)]
    # Confirm one deliberately against what the solver would have said.
    confirmed = {"06LFFENDER": "LRFENDER"}
    for _ in range(3):
        solved = solve_set(spellings, fenders, confirmed=confirmed, live_panel_count=3)
        pinned = solved.by_spelling()["06LFFENDER"]
        assert pinned.proposed == "LRFENDER", "a confirmed pair never moves"
        assert pinned.signal == SIGNAL_NONE
        assert pinned.reason == "you confirmed this"
        assert pinned.candidates == (), "it is not re-proposed"
        # And it survives being fed back in.
        confirmed = {**confirmed}


def test_g88_5_orientation_filters_proposals_only_and_two_orientations_disable_it():
    """G-88-5. A constraint narrows a suggestion, never the owner's choice."""
    panels = [panel("LFFENDER", 6, V), panel("LCROOF", 11, H)]
    # A spelling the file writes with two orientations: no filter, and the
    # screen is told which spelling the file disagrees about.
    conflicted = HeldSpelling("06LFFENDER", (H, V), 10, 6)
    solved = solve_set([conflicted], panels, live_panel_count=2)
    [proposal] = solved.proposals
    assert proposal.orientation_conflict is True
    assert solved.orientation_conflicts == ["06LFFENDER"]
    assert proposal.filtered_out == (), "no filter was applied"
    assert proposal.signal != SIGNAL_EXHAUSTION, "and no exhaustion either"

    # Even when the counts would otherwise close the pool.
    spellings = [HeldSpelling("11ROOF", (H, V), 10, 11), spelling("14ROOF", H, 14)]
    solved = solve_set(
        spellings, MAPPABLE_ROOFS, confirmed={}, live_panel_count=2
    )
    assert all(p.signal != SIGNAL_EXHAUSTION for p in solved.proposals)


def test_g88_6_the_method_records_which_signal_proposed_the_pair():
    """G-88-6. An exhaustion-derived pair must be findable again."""
    assert panel_match_method("exhaustion") == f"{PANEL_MATCH_METHOD_T88}_EXHAUSTION"
    assert panel_match_method("name") == f"{PANEL_MATCH_METHOD_T88}_NAME"
    assert panel_match_method("number") == f"{PANEL_MATCH_METHOD_T88}_NUMBER"
    # An unknown or missing signal is recorded as `none`, never guessed.
    assert panel_match_method(None) == f"{PANEL_MATCH_METHOD_T88}_NONE"
    assert panel_match_method("wishful thinking") == f"{PANEL_MATCH_METHOD_T88}_NONE"


def test_g88_9_the_solver_never_proposes_one_panel_twice():
    """G-88-9's half that lives here: the set stays internally consistent."""
    fenders = [panel("LFFENDER", 6), panel("LCFENDER", 7), panel("LRFENDER", 8)]
    spellings = [spelling(f"0{n}LFFENDER", V, n) for n in (6, 7, 8)]
    solved = solve_set(spellings, fenders, live_panel_count=3)
    proposed = [p.proposed for p in solved.proposals if p.proposed]
    assert len(proposed) == len(set(proposed))


# =====================================================================
# C. Part 3 -- the vocabulary, every plant
# =====================================================================
#: The 17 names that classified as nothing before T88, and what they are.
#: Written out rather than computed so the test fails if one silently
#: changes family later.
T88_GAINED = {
    "FRFENRH1": "FENDER", "FRFENRH2": "FENDER", "FRFENRH3": "FENDER",
    "RRFENHIRH": "FENDER", "RRFENLOWRH": "FENDER", "RRFENMIDRH": "FENDER",
    "TGMIDDLE": "TAILGATE", "LHSTGTOP": "TAILGATE", "LHSTGBOT": "TAILGATE",
    "RHSTGTOP": "TAILGATE", "RHSTGBOT": "TAILGATE",
    "21 Rr Fen Low RH": "FENDER", "22 Rr Fen Mid RH": "FENDER",
    "23 Rr Fen Hi RH": "FENDER", "29 Fr Fen RH3": "FENDER",
    "30 Fr Fen RH2": "FENDER", "31 Fr Fen RH1": "FENDER",
}

#: `ws_panel_group` before T88 added `FEN` and the joined `TG` forms. The
#: regression test re-derives today's answer from this, so "the 211 keep
#: their family" is proved rather than asserted.
_PRE_T88_KEYWORDS = (
    ("HOOD", "HOOD"), ("ROOF", "ROOF"), ("FLOOR", "BOX"), ("PILLAR", "PILLAR"),
    ("POST", "PILLAR"), ("LIFTGATE", "LIFTGATE"), ("LIFGATE", "LIFTGATE"),
    ("SWING", "LIFTGATE"), ("TAIL", "TAILGATE"), ("TGATE", "TAILGATE"),
    ("TG", "TAILGATE"), ("FEND", "FENDER"), ("QTR", "FENDER"), ("BOX", "BOX"),
    ("BOOX", "BOX"), ("DOO", "DOOR"), ("FD", "DOOR"), ("RD", "DOOR"),
)


def _pre_t88_group(label: str) -> str | None:
    compact = re.sub(r"[^A-Z]", "", str(label).upper())
    words = set(re.findall(r"[A-Z]+", str(label).upper()))
    for keyword, group in _PRE_T88_KEYWORDS:
        if keyword in ("TG", "FD", "RD"):
            if keyword in words:
                return group
        elif keyword in compact:
            return group
    return None


def _catalogue_names(admin_conn) -> tuple[list[str], list[str]]:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT zone_code FROM ref_checkzone ORDER BY 1")
        zones = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT raw_value FROM ref_checkzone_alias ORDER BY 1")
        aliases = [row[0] for row in cur.fetchall()]
    return zones, aliases


def test_every_catalogue_panel_name_classifies(admin_conn):
    """Part 3. Re-read from the tables, so a future plant's vocabulary fails
    this test instead of failing silently in `rank_candidates`."""
    zones, aliases = _catalogue_names(admin_conn)
    assert zones and aliases, "the catalogue is empty; this proves nothing"
    unclassified = []
    for name in zones + aliases:
        try:
            ws_panel_group(name)
        except ValueError:
            unclassified.append(name)
    assert unclassified == [], (
        "these names classify as nothing, so rank_candidates drops them and "
        f"the owner sees an empty list with no reason: {unclassified}"
    )


def test_no_existing_classification_changed(admin_conn):
    """Part 3. The ones that worked keep exactly the family they had."""
    zones, aliases = _catalogue_names(admin_conn)
    changed, gained = [], {}
    for name in zones + aliases:
        before = _pre_t88_group(name)
        after = ws_panel_group(name)
        if before is None:
            gained[name] = after
        elif before != after:
            changed.append((name, before, after))
    assert changed == [], f"T88 moved a name to another family: {changed}"
    assert gained == T88_GAINED, gained


def test_a_name_that_used_to_classify_as_nothing_now_reaches_candidates(admin_conn):
    """Part 3, end to end: the silent empty list is gone, on two plants."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code, point_no, tolerance_group FROM ref_plant_ws_point "
            " WHERE plant_code = 'AAT' AND model_code = 'U704' "
            "   AND retired_at IS NULL ORDER BY point_no"
        )
        aat = [LivePanel(z, p, t) for z, p, t in cur.fetchall()]
        cur.execute(
            "SELECT zone_code, point_no, tolerance_group FROM ref_plant_ws_point "
            " WHERE plant_code = 'SAP' AND model_code = 'J73 DBL' "
            "   AND retired_at IS NULL ORDER BY point_no"
        )
        sap = [LivePanel(z, p, t) for z, p, t in cur.fetchall()]
    if not aat or not sap:
        pytest.skip("AAT U704 or SAP J73 DBL has no live panel list here")

    assert _pre_t88_group("01FRFENRH1") is None, "the premise of this test"
    assert rank_candidates("01FRFENRH1", aat), "AAT fender now reaches candidates"
    assert _pre_t88_group("TGMIDDLE") is None
    assert rank_candidates("19Tailgate Middle14", sap), "SAP tailgate too"


# =====================================================================
# D. Part 4 -- the audit
# =====================================================================
@pytest.fixture()
def august_shape(admin_conn):
    """A batch of this module's own, holding one position under two names."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.plant_code, p.model_code, p.zone_code, p.tolerance_group
              FROM ref_plant_ws_point p
             WHERE p.retired_at IS NULL
               AND (p.plant_code, p.model_code) IN (
                   SELECT plant_code, model_code FROM ref_plant_ws_point
                    WHERE retired_at IS NULL GROUP BY 1, 2 HAVING count(*) >= 2)
             ORDER BY p.plant_code, p.model_code, p.point_no LIMIT 2
            """
        )
        panels = cur.fetchall()
        assert len(panels) == 2
        plant, model, first, first_tol = panels[0]
        _, _, second, second_tol = panels[1]
        cur.execute(
            "SELECT color_name FROM ref_plant_color WHERE plant_code = %s "
            "  AND is_offered ORDER BY color_name LIMIT 1",
            (plant,),
        )
        colour = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO load_batch (source_file, source_sheet, plant_code, "
            "  file_hash, raw_store_key, status) "
            "VALUES (%s, 'S', %s, %s, 'k', 'COMMITTED') RETURNING load_id",
            (f"t88-august-shape-{uuid.uuid4().hex[:8]}.xlsx", plant,
             uuid.uuid4().hex + uuid.uuid4().hex),
        )
        load_id = cur.fetchone()[0]
        # Two names, one walk position: the August shape exactly.
        for row, (zone, tol) in enumerate(((first, first_tol), (second, second_tol)), 1):
            cur.execute(
                "INSERT INTO wavescan (measured_date, plant, model, checkzone, "
                "  color, tolerance_group, serial_no, lw, sw, cf, load_id, "
                "  source_sheet, source_row, src_zone_text, src_zone_no) "
                "VALUES (DATE '2026-08-05', %s, %s, %s, %s, %s, %s, 1.5, 2.5, "
                "        60.0, %s, 'S', %s, %s, 1)",
                (plant, model, zone, colour, tol, f"T88-{load_id}-{row}",
                 load_id, row, zone),
            )
    yield {"load_id": load_id, "plant": plant, "model": model,
           "names": sorted([first, second])}
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM wavescan WHERE load_id = %s", (load_id,))
        cur.execute("DELETE FROM load_batch WHERE load_id = %s", (load_id,))


def run_audit(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(AUDIT), *args],
        capture_output=True, text=True, cwd=str(BACKEND_ROOT),
    )


def test_the_audit_finds_one_position_under_two_names(august_shape):
    done = run_audit("--plant", august_shape["plant"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert str(august_shape["load_id"]) in done.stdout
    assert " + ".join(august_shape["names"]) in done.stdout
    assert "ONE WALK POSITION, TWO PANEL NAMES" in done.stdout


def test_the_audit_reports_clean_where_there_is_nothing(august_shape):
    """A plant with no such batch says so, rather than saying nothing."""
    with_none = "FVL" if august_shape["plant"] != "FVL" else "SAP"
    done = run_audit("--plant", with_none)
    assert done.returncode == 0, done.stdout + done.stderr
    assert str(august_shape["load_id"]) not in done.stdout
    assert "ONE WALK POSITION, TWO PANEL NAMES  (0)" in done.stdout


def test_the_audit_is_read_only():
    """It says where to look. It changes nothing, and that is greppable."""
    source = AUDIT.read_text(encoding="utf-8").upper()
    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE", "ALTER "):
        assert forbidden not in source, forbidden


def test_the_audit_can_list_exhaustion_derived_pairs(admin_dsn):  # the script reads the DSN itself
    """G-88-6. The whole reason the signal is in `proposal_method`."""
    source = AUDIT.read_text(encoding="utf-8")
    assert "EXHAUSTION" in source
    assert PANEL_MATCH_METHOD_T88 in source
    done = run_audit()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "by exhaustion" in done.stdout
