"""T90 -- the pure half: the walk is the identity, the name is only a label.

No database and no application. These are claims about the rules, which is
where they belong, and every one of them is one of the task's section 5
tests:

* September's labels against the canonical list produce the full 32-pair
  mapping **by rule (a)**, including the four the owner named;
* August's **numbered block** produces its mapping **by rule (b)**,
  including `13LFRDOOR -> LCPILLAR` and `25RTRDOOR -> RCPILLAR` (D-90-10,
  used as given: they are this module's expected values, never re-derived);
* a file engineered so that both rules are available and they **disagree**
  proposes neither and goes red (D-90-2);
* a group walked right-before-left is caught by the side hint (D-90-8);
* a sheet sorted alphabetically gets **no** rule (a) and is not refused
  (D-90-7, D-90-13);
* rough and specific are told apart the way D-90-3 defines them;
* an unchanged fingerprint still needs one confirmation (D-90-5) and a
  changed one turns every row red (D-90-6);
* a group with no side hint is red on first sight and yellow on the second
  (D-90-12).

The canonical list and the three naming schemes below are the real ones,
read from `docs/tasks/reference/ftm-canonical-pairs.csv` and the three real
FTM CF files. `backend/scripts/t90_ftm_walk_verdicts.py` runs the same
rules against the workbooks themselves.
"""

from __future__ import annotations

import pytest

from app.domain.panel_walk import (
    ATTENTION_RED,
    ATTENTION_YELLOW,
    RULE_GROUP_ORDINAL,
    RULE_NONE,
    RULE_WALK_NUMBER,
    SPECIFICITY_ROUGH,
    SPECIFICITY_SPECIFIC,
    CanonicalPoint,
    WalkRow,
    classify_specificity,
    fingerprint,
    fingerprint_initials,
    fingerprint_text,
    group_counts,
    match_walk,
    read_walk,
    rule_group_ordinal,
    rule_walk_number,
    side_hint,
    verify_walk_order,
)

#: FTM P703's canonical 32 -- the long-form names, in walk order (D-89-2 /
#: D-90-10). `point_no` is `ref_plant_ws_point.point_no`.
CANONICAL_NAMES = (
    "RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD",
    "LFFENDER", "LCFENDER", "LRFENDER",
    "LTFDOOR", "LCFDOOR",
    "LCROOF",
    "LCRDOOR", "LCPILLAR",
    "LFBOX", "LCBOX", "LRBOX",
    "LTTAILGATE", "LBTAILGATE", "LCTAILGATE", "RBTAILGATE", "RTTAILGATE",
    "RRBOX", "RCBOX", "RFBOX",
    "RCPILLAR", "RCRDOOR",
    "RCROOF",
    "RCFDOOR", "FTFDOOR",
    "RRFENDER", "RCFENDER", "RFFENDER",
)
CANONICAL = [
    CanonicalPoint(zone_code=name, point_no=index)
    for index, name in enumerate(CANONICAL_NAMES, start=1)
]

#: The real September labels, in the real walk order (load 70201).
SEPTEMBER = (
    "01HOOD", "02HOOD", "03HOOD", "04HOOD", "05HOOD",
    "06LFFENDER", "07LFFENDER", "08LFFENDER",
    "09LFFTDOOR", "10LFFTDOOR",
    "11ROOF", "12LCPILLAR", "13LFRDOOR", "14ROOF", "15RCPILLAR",
    "16RTRDOOR", "17RTFTDOOR", "18RTFTDOOR",
    "19RTFENDER", "20RTFENDER", "21RTFENDER",
    "22LFBOXSD", "23LFBOXSD", "24LFBOXSD",
    "25TGATE", "26TGATE", "27TGATE", "28TGATE", "29TGATE",
    "30RTBOXSD", "31RTBOXSD", "32RTBOXSD",
)

#: The real August **numbered block**, in walk order. The August workbook
#: writes this block *and* the long-form one on the same tab -- 64 names for
#: 32 positions, which is the collision T88's audit found -- so this is the
#: block the task's table and D-90-10 are about.
AUGUST_NUMBERED = (
    "01HOOD", "02HOOD", "03HOOD", "04HOOD", "05HOOD",
    "06LFFFEND", "07LFFENDE", "08LFFENDE",
    "09LFFTDOOR", "10LFFTDOOR",
    "11ROOF",
    "12LFRDOOR", "13LFRDOOR",
    "14LFBOXSD", "15LFBOXSD", "16LFBOXS",
    "17TGATE", "18TGATE", "19TGATE", "20TGATE", "21TGATE",
    "22RTBOXSD", "23RTBOXSD", "24RTBOXSD",
    "25RTRDOOR", "26RTRDOO",
    "27ROOF",
    "28RTFTDOO", "29RTFTDOO",
    "30RTFENDE", "31RTFENDE", "32RTFENDE",
)

#: The real July labels: the canonical names with their walk number in
#: front. The July sheet lists them grouped by family, not in walk order.
JULY_IN_SHEET_ORDER = (
    "01 RRHOOD", "02 RFHOOD", "03 CFHOOD", "04 LFHOOD", "05 LRHOOD",
    "11 LCRoof", "27 RCRoof",
    "06 LFFender", "07 LCFender", "08 LRFender",
    "09 LTFDoor", "10 LCFDoor", "12 LCRDoor",
    "13 LCPillar",
    "14 LFBoox", "15 LCBox", "16 LRBox",
    "17 LTTailagte", "18 LBTailagte", "19 LCTailagate",
    "20 RBTailgate", "21RTTailgate",
    "22 RRBox", "23 RCBox", "24 RFBox",
    "25 RCPillar",
    "26 RCRDoor", "28 RCFDoor", "29 FTFDoor",
    "30 RRFender", "31 RCFender", "32 RFFender",
)

#: **The owner's facts, used as given and never re-derived** (D-90-10).
#: These are the expected values of the August test, not its output.
OWNER_AUGUST_PAIRS = {
    "13LFRDOOR": "LCPILLAR",
    "25RTRDOOR": "RCPILLAR",
    "12LFRDOOR": "LCRDOOR",
    "26RTRDOO": "RCRDOOR",
}

#: Rule (a)'s answer for the four September names the task names in its own
#: section 5, and which three unrelated signals agree about.
SEPTEMBER_NAMED_PAIRS = {
    "11ROOF": "LCROOF",
    "14ROOF": "RCROOF",
    "12LCPILLAR": "LCPILLAR",
    "15RCPILLAR": "RCPILLAR",
}


def walk(labels, *, vehicle="2026-09-01|Arctic White|2005924", start=2):
    """One vehicle's pass, in the order given."""
    return [
        WalkRow(source_row=start + index, raw_zone_text=label, vehicle=vehicle)
        for index, label in enumerate(labels)
    ]


def pairs_of(match):
    return {
        verdict.raw_zone_text: verdict.proposed_zone_code
        for verdict in match.verdicts
    }


# --------------------------------------------------------------------------
# Reading a label: the group, the side, and nothing invented
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, expected",
    [
        # The whole reason a side is not the first letter of the name.
        ("ROOF", None),
        ("11ROOF", None),
        ("LCROOF", "L"),
        ("RCROOF", "R"),
        ("HOOD", None),
        ("01HOOD", None),
        ("RRHOOD", "R"),
        ("LFHOOD", "L"),
        # A letter that is not L or R claims nothing.
        ("CFHOOD", None),
        ("FTFDOOR", None),
        # Nothing in the tailgate group of September's file carries a side.
        ("25TGATE", None),
        ("LTTAILGATE", "L"),
        ("RBTAILGATE", "R"),
        ("06LFFENDER", "L"),
        ("19RTFENDER", "R"),
        ("22LFBOXSD", "L"),
        ("30RTBOXSD", "R"),
        ("12LCPILLAR", "L"),
        ("25RTRDOOR", "R"),
    ],
)
def test_a_side_is_read_from_the_letters_in_front_of_the_family_word(
    label, expected
):
    assert side_hint(label) == expected


def test_the_fingerprint_is_the_groups_and_not_the_spellings():
    """D-90-4: a respelling must not move it; a reshuffle must."""
    september = fingerprint(read_walk(walk(SEPTEMBER)))
    assert fingerprint_initials(september) == (
        "H H H H H F F F D D R P D R P D D D F F F B B B T T T T T B B B"
    )
    # The same walk, every name spelled differently: same fingerprint.
    respelled = [
        label.replace("TGATE", "TAILGATE").replace("BOXSD", "BOXSIDE")
        for label in SEPTEMBER
    ]
    assert fingerprint(read_walk(walk(respelled))) == september
    # One panel moved: a different fingerprint.
    reshuffled = list(SEPTEMBER)
    reshuffled[11], reshuffled[12] = reshuffled[12], reshuffled[11]
    assert fingerprint(read_walk(walk(reshuffled))) != september


def test_septembers_group_multiset_is_the_canonical_one_and_augusts_is_not():
    """The measured table in the task, as an assertion."""
    canonical = group_counts(
        fingerprint(read_walk(walk(CANONICAL_NAMES)))
    )
    assert canonical == {
        "HOOD": 5, "FENDER": 6, "DOOR": 6, "ROOF": 2,
        "PILLAR": 2, "BOX": 6, "TAILGATE": 5,
    }
    assert group_counts(fingerprint(read_walk(walk(SEPTEMBER)))) == canonical
    august = group_counts(fingerprint(read_walk(walk(AUGUST_NUMBERED))))
    assert august["DOOR"] == 8 and "PILLAR" not in august


def test_rough_and_specific_are_told_apart_by_the_shared_name_core():
    """D-90-3, and the counts the task measured on all three schemes."""
    canonical = classify_specificity(read_walk(walk(CANONICAL_NAMES)))
    assert set(canonical.values()) == {SPECIFICITY_SPECIFIC}

    september = classify_specificity(read_walk(walk(SEPTEMBER)))
    assert sorted(
        name for name, kind in september.items()
        if kind == SPECIFICITY_SPECIFIC
    ) == ["12LCPILLAR", "13LFRDOOR", "15RCPILLAR", "16RTRDOOR"]
    assert sum(1 for kind in september.values() if kind == SPECIFICITY_ROUGH) == 28

    august = classify_specificity(read_walk(walk(AUGUST_NUMBERED)))
    assert sorted(
        name for name, kind in august.items() if kind == SPECIFICITY_SPECIFIC
    ) == ["06LFFFEND", "16LFBOXS", "25RTRDOOR", "26RTRDOO"]
    assert sum(1 for kind in august.values() if kind == SPECIFICITY_ROUGH) == 28


# --------------------------------------------------------------------------
# D-90-7 / D-90-13: the precondition is checked, and failing it refuses
# nothing
# --------------------------------------------------------------------------


def test_the_real_september_walk_order_verifies_including_its_repeated_vehicle():
    """The real file walks one vehicle identity twice. That is a pass, not a sort."""
    rows = walk(SEPTEMBER) + walk(SEPTEMBER[:24], start=418)
    ok, reason = verify_walk_order(rows)
    assert ok, reason
    assert "passes" in reason


def test_a_sheet_sorted_by_name_gets_no_group_ordinal_and_is_not_refused():
    """D-90-7 / D-90-13, which is also what the real July sheet does."""
    sorted_by_name = sorted(SEPTEMBER, key=lambda label: label.lstrip("0123456789"))
    ok, reason = verify_walk_order(walk(sorted_by_name))
    assert not ok
    assert "walk order" in reason

    match = match_walk(walk(sorted_by_name), CANONICAL)
    assert not match.rule_a.available
    assert "withheld" in match.rule_a.reason
    # Nothing is refused and nothing is proposed by rule (a).
    assert len(match.verdicts) == 32
    assert all(verdict.attention == ATTENTION_RED for verdict in match.verdicts)
    assert all(
        verdict.rule_a_zone_code is None
        for verdict in match.verdicts
    )


def test_the_real_july_sheet_order_is_refused_and_rule_b_answers_it_instead():
    """July lists its panels by family, so first appearance is not the walk."""
    match = match_walk(walk(JULY_IN_SHEET_ORDER), CANONICAL)
    assert match.multiset_matches
    assert not match.walk_order_verified
    assert not match.rule_a.available
    assert match.rule_b.available
    assert pairs_of(match)["11 LCRoof"] == "LCROOF"
    assert pairs_of(match)["27 RCRoof"] == "RCROOF"
    assert all(verdict.rule == RULE_WALK_NUMBER for verdict in match.verdicts)


def test_a_label_with_no_number_withholds_rule_a_and_gets_no_proposal():
    labels = ("HOOD",) + SEPTEMBER[1:]
    match = match_walk(walk(labels), CANONICAL)
    assert not match.rule_a.available
    assert not match.rule_b.available
    assert all(
        verdict.proposed_zone_code is None for verdict in match.verdicts
    )
    assert all(verdict.rule == RULE_NONE for verdict in match.verdicts)


# --------------------------------------------------------------------------
# Rule (a): September
# --------------------------------------------------------------------------


def test_september_produces_the_full_32_pair_mapping_by_rule_a():
    """The task's first section 5 test, with the four names it names."""
    match = match_walk(walk(SEPTEMBER), CANONICAL)
    assert match.rule_a.available
    assert not match.rule_b.available, match.rule_b.reason
    proposed = pairs_of(match)
    assert len(proposed) == 32
    assert set(proposed.values()) == set(CANONICAL_NAMES)
    for label, zone in SEPTEMBER_NAMED_PAIRS.items():
        assert proposed[label] == zone
    assert all(verdict.rule == RULE_GROUP_ORDINAL for verdict in match.verdicts)
    # 11ROOF -> LCROOF and 14ROOF -> RCROOF is the answer T88 reached by
    # exhaustion, and 12LCPILLAR -> LCPILLAR is what the file's own pillar
    # name says. Three unrelated signals, one answer.
    assert proposed["12LCPILLAR"] == "LCPILLAR"


def test_rule_a_is_refused_when_the_multiset_differs():
    outcome = rule_group_ordinal(
        read_walk(walk(AUGUST_NUMBERED)), CANONICAL, walk_order_ok=True
    )
    assert not outcome.available
    assert "DOOR 8 in the file against 6 canonical" in outcome.reason
    assert outcome.pairs == {}


def test_a_partial_vehicle_does_not_shift_the_multiset():
    """The multiset is over distinct labels of the whole (plant, model)."""
    rows = walk(SEPTEMBER) + walk(SEPTEMBER[:10], vehicle="v2", start=418)
    match = match_walk(rows, CANONICAL)
    assert match.multiset_matches
    assert match.rule_a.available
    assert pairs_of(match) == pairs_of(match_walk(walk(SEPTEMBER), CANONICAL))


# --------------------------------------------------------------------------
# Rule (b): August's numbered block, and the owner's facts
# --------------------------------------------------------------------------


def test_augusts_numbered_block_produces_its_mapping_by_rule_b():
    """The task's second section 5 test. D-90-10 supplies the answers."""
    match = match_walk(walk(AUGUST_NUMBERED), CANONICAL)
    assert not match.rule_a.available
    assert match.rule_b.available, match.rule_b.reason
    proposed = pairs_of(match)
    assert len(proposed) == 32
    assert set(proposed.values()) == set(CANONICAL_NAMES)
    for label, zone in OWNER_AUGUST_PAIRS.items():
        assert proposed[label] == zone
    assert all(verdict.rule == RULE_WALK_NUMBER for verdict in match.verdicts)
    # The two the file's names and the canonical groups disagree about are
    # exactly the two the owner named, and the rule says so in its reason.
    assert "13LFRDOOR" in match.rule_b.reason
    assert "25RTRDOOR" in match.rule_b.reason


def test_the_two_pillars_of_august_still_pass_the_side_hint():
    """D-90-8: a DOOR landing on a PILLAR is still the same side."""
    match = match_walk(walk(AUGUST_NUMBERED), CANONICAL)
    by_spelling = match.by_spelling()
    for label in ("13LFRDOOR", "25RTRDOOR"):
        assert by_spelling[label].side_hint_checked
        assert side_hint(label) == side_hint(
            by_spelling[label].proposed_zone_code
        )


def test_rule_b_is_refused_when_the_numbering_is_not_the_canonical_walk():
    """September's numbering would put 14ROOF on LFBOX. Refused, not argued."""
    outcome = rule_walk_number(read_walk(walk(SEPTEMBER)), CANONICAL)
    assert not outcome.available
    assert "not the canonical walk" in outcome.reason
    assert outcome.pairs == {}


def test_rule_b_is_refused_when_the_numbers_do_not_span_1_to_n():
    labels = ("33HOOD",) + SEPTEMBER[1:]
    outcome = rule_walk_number(read_walk(walk(labels)), CANONICAL)
    assert not outcome.available
    assert "span 1..32" in outcome.reason


def test_rule_b_is_refused_when_a_sheet_writes_both_naming_blocks():
    """The real August tab: 64 names for 32 positions, so nothing aligns."""
    both = list(JULY_IN_SHEET_ORDER) + list(AUGUST_NUMBERED)
    match = match_walk(walk(both), CANONICAL)
    assert not match.rule_a.available
    assert not match.rule_b.available
    assert "64 names against 32 canonical points" in match.rule_b.reason
    assert len(match.verdicts) == 64
    assert all(verdict.attention == ATTENTION_RED for verdict in match.verdicts)


# --------------------------------------------------------------------------
# D-90-2: both rules available and disagreeing
# --------------------------------------------------------------------------

#: Engineered so both rules apply and they answer differently. Two vehicles,
#: each walking in ascending numbers, so D-90-7 passes -- and between them
#: the panels first appear in an order the numbering does not share. The
#: file's group sequence is the canonical one by number, so rule (b) is
#: available; the multiset is the canonical one, so rule (a) is too.
DISAGREE_CANONICAL = [
    CanonicalPoint("LFHOOD", 1),
    CanonicalPoint("RRHOOD", 2),
    CanonicalPoint("LFFENDER", 3),
    CanonicalPoint("RRFENDER", 4),
]


def test_when_both_rules_apply_and_disagree_neither_is_proposed():
    """D-90-2: a disagreement is information, so the person chooses."""
    rows = (
        walk(("01HOODA", "04FENDERB"), vehicle="v1")
        + walk(("02HOODB", "03FENDERA"), vehicle="v2", start=100)
    )
    match = match_walk(rows, DISAGREE_CANONICAL)
    assert match.walk_order_verified, match.walk_order_reason
    assert match.rule_a.available, match.rule_a.reason
    assert match.rule_b.available, match.rule_b.reason
    assert match.disagreements == ("03FENDERA", "04FENDERB")

    by_spelling = match.by_spelling()
    # Both answers are shown, neither is proposed, the row is red.
    for label in ("04FENDERB", "03FENDERA"):
        verdict = by_spelling[label]
        assert verdict.proposed_zone_code is None
        assert verdict.rule == RULE_NONE
        assert verdict.attention == ATTENTION_RED
        assert verdict.rule_a_zone_code is not None
        assert verdict.rule_b_zone_code is not None
        assert (
            verdict.rule_a_zone_code
            != verdict.rule_b_zone_code
        )
    # And no row of the set is taken on trust while they disagree.
    assert all(verdict.attention == ATTENTION_RED for verdict in match.verdicts)


def test_when_both_rules_apply_and_agree_the_answer_is_proposed_once():
    rows = walk(("01HOODA", "02HOODB", "03FENDERA", "04FENDERB"))
    match = match_walk(rows, DISAGREE_CANONICAL)
    assert match.rule_a.available and match.rule_b.available
    assert match.disagreements == ()
    assert pairs_of(match) == {
        "01HOODA": "LFHOOD",
        "02HOODB": "RRHOOD",
        "03FENDERA": "LFFENDER",
        "04FENDERB": "RRFENDER",
    }


# --------------------------------------------------------------------------
# D-90-8: the group walked right before left
# --------------------------------------------------------------------------


def test_a_group_walked_right_before_left_is_caught_by_the_side_hint():
    """The grey area rule (a) cannot see, and the check that sees it."""
    swapped = list(SEPTEMBER)
    # The file walks its three right fenders where the left ones belong.
    for index, label in enumerate(swapped):
        if label.endswith("LFFENDER"):
            swapped[index] = label.replace("LFFENDER", "RTFENDER")
        elif label.endswith("RTFENDER"):
            swapped[index] = label.replace("RTFENDER", "LFFENDER")
    match = match_walk(walk(swapped), CANONICAL)
    assert match.rule_a.available
    by_spelling = match.by_spelling()
    caught = [
        verdict.raw_zone_text
        for verdict in match.verdicts
        if "hand panel" in verdict.reason
    ]
    assert caught == [
        "06RTFENDER", "07RTFENDER", "08RTFENDER",
        "19LFFENDER", "20LFFENDER", "21LFFENDER",
    ]
    for label in caught:
        verdict = by_spelling[label]
        # The rule applied cleanly and the row is red anyway.
        assert verdict.rule == RULE_GROUP_ORDINAL
        assert verdict.proposed_zone_code is not None
        assert verdict.side_hint_checked
        assert verdict.attention == ATTENTION_RED


def test_a_side_the_file_does_not_claim_is_never_cross_checked():
    """`25TGATE` onto `LTTAILGATE` is not a contradiction. It is no evidence."""
    match = match_walk(walk(SEPTEMBER), CANONICAL)
    by_spelling = match.by_spelling()
    for label in ("25TGATE", "26TGATE", "01HOOD", "11ROOF"):
        assert by_spelling[label].side_hint_checked is False
        assert "hand panel" not in by_spelling[label].reason


# --------------------------------------------------------------------------
# D-90-5 / D-90-6 / D-90-12: memory, and the one click
# --------------------------------------------------------------------------


def test_the_first_sight_of_a_walk_is_entirely_red():
    """D-90-6: yellow needs "and it is what was confirmed last"."""
    match = match_walk(walk(SEPTEMBER), CANONICAL)
    assert match.yellow == ()
    assert len(match.red) == 32


def test_an_unchanged_walk_goes_yellow_and_still_needs_one_confirmation():
    """D-90-5: never silence. Every row is yellow and none is applied."""
    first = match_walk(walk(SEPTEMBER), CANONICAL)
    confirmed = pairs_of(first)
    again = match_walk(
        walk(SEPTEMBER),
        CANONICAL,
        remembered=confirmed,
        remembered_fingerprint=first.fingerprint,
    )
    assert not again.fingerprint_moved
    assert len(again.yellow) == 32
    assert again.red == ()
    # Pre-filled, and still only a proposal: the colour is yellow, not green.
    assert all(
        verdict.prefilled_zone_code == confirmed[verdict.raw_zone_text]
        for verdict in again.verdicts
    )
    assert ATTENTION_YELLOW in {verdict.attention for verdict in again.verdicts}
    assert "green" not in {verdict.attention for verdict in again.verdicts}


def test_a_group_with_no_side_hint_is_red_first_and_yellow_second():
    """D-90-12, in the owner's own example: 25TGATE..29TGATE."""
    tailgates = ("25TGATE", "26TGATE", "27TGATE", "28TGATE", "29TGATE")
    first = match_walk(walk(SEPTEMBER), CANONICAL)
    by_spelling = first.by_spelling()
    for label in tailgates:
        assert by_spelling[label].attention == ATTENTION_RED
        assert "no left-against-right check" in by_spelling[label].reason

    again = match_walk(
        walk(SEPTEMBER),
        CANONICAL,
        remembered=pairs_of(first),
        remembered_fingerprint=first.fingerprint,
    )
    for label in again.by_spelling():
        if label in tailgates:
            verdict = again.by_spelling()[label]
            assert verdict.attention == ATTENTION_YELLOW
            assert verdict.prefilled_zone_code == pairs_of(first)[label]


def test_a_changed_fingerprint_turns_every_row_red_again():
    """D-90-6 / D-90-12: the walk moved, so nothing is carried over."""
    first = match_walk(walk(SEPTEMBER), CANONICAL)
    moved_labels = list(SEPTEMBER)
    moved_labels[11], moved_labels[12] = moved_labels[12], moved_labels[11]
    # Renumber so the sheet is still in walk order.
    moved_labels[11] = "12LFRDOOR"
    moved_labels[12] = "13LCPILLAR"
    moved = match_walk(
        walk(moved_labels),
        CANONICAL,
        remembered=pairs_of(first),
        remembered_fingerprint=first.fingerprint,
    )
    assert moved.fingerprint != first.fingerprint
    assert moved.fingerprint_moved
    assert moved.yellow == ()
    assert all(
        verdict.prefilled_zone_code is None for verdict in moved.verdicts
    )
    assert any("walk has changed" in v.reason for v in moved.verdicts)


def test_a_name_that_was_not_in_the_confirmed_set_is_red_as_a_new_pair():
    first = match_walk(walk(SEPTEMBER), CANONICAL)
    remembered = pairs_of(first)
    remembered.pop("01HOOD")
    again = match_walk(
        walk(SEPTEMBER),
        CANONICAL,
        remembered=remembered,
        remembered_fingerprint=first.fingerprint,
    )
    assert again.by_spelling()["01HOOD"].attention == ATTENTION_RED
    assert "pair is new" in again.by_spelling()["01HOOD"].reason
    assert len(again.yellow) == 31


def test_a_confirmed_answer_the_rule_now_contradicts_is_red():
    first = match_walk(walk(SEPTEMBER), CANONICAL)
    remembered = pairs_of(first) | {"01HOOD": "LRHOOD"}
    again = match_walk(
        walk(SEPTEMBER),
        CANONICAL,
        remembered=remembered,
        remembered_fingerprint=first.fingerprint,
    )
    verdict = again.by_spelling()["01HOOD"]
    assert verdict.attention == ATTENTION_RED
    assert "do not agree" in verdict.reason


def test_the_stored_fingerprint_round_trips_through_its_text_form():
    """D-90-11 stores the text and reads it back; it must be the same walk."""
    match = match_walk(walk(SEPTEMBER), CANONICAL)
    stored = fingerprint_text(match.fingerprint)
    assert tuple(stored.split("|")) == match.fingerprint


# --------------------------------------------------------------------------
# D-90-1: per (plant, model), never per sheet
# --------------------------------------------------------------------------


def test_two_models_on_one_sheet_are_two_walks():
    """One tab, two models: the caller splits, and each walk stands alone."""
    ranger = match_walk(walk(SEPTEMBER), CANONICAL)
    raptor = match_walk(walk(AUGUST_NUMBERED), CANONICAL)
    assert ranger.fingerprint != raptor.fingerprint
    assert ranger.rule_a.available and not ranger.rule_b.available
    assert raptor.rule_b.available and not raptor.rule_a.available


def test_a_model_with_no_canonical_list_proposes_nothing():
    """FVL / P703 DBL RANGER and SAP's two pairs, where nothing is mappable."""
    match = match_walk(walk(SEPTEMBER), [])
    assert not match.rule_a.available
    assert not match.rule_b.available
    assert all(verdict.proposed_zone_code is None for verdict in match.verdicts)
    assert all(verdict.attention == ATTENTION_RED for verdict in match.verdicts)
