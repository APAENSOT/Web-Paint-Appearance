"""T89 -- the pure half: one picker, normalise at the door, carry a decision.

No database and no application: these are claims about the rules
themselves, which is where they belong.

* **Part 1 / D-89-6.** One builder answers "what may this question be
  answered with": mappable only, orientation-filtered, taken panels last
  and labelled, suggestions first. Every panel it offers is confirmable.
* **D-89-5.** A file written in either naming convention stores the **same**
  checkzone -- and the dependency that makes it true: while the numbered
  panel is still live an alias beside it changes **nothing** (rule 1, the
  gold list, wins), and only retiring it makes the fold take effect. That
  is the test that proves retirement is doing the work rather than being
  tidiness, and it is why D-89-4 fixes the order.
* **D-89-9.** A decision that comes back arrives pre-selected and marked as
  carried over, in all three cases it can come back in -- and never when
  the panel it names is not on offer.
* **Part 5 / D-88-7.** A whole-set rename is named as one event, and every
  condition of the claim is required.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.panel_carryover import (
    CARRY_NEAR_MISS,
    CARRY_OTHER_MODEL,
    CARRY_PENDING,
    TaughtPair,
    carried_over_for,
)
from app.domain.panel_rename import whole_set_rename
from app.domain.references import ReferenceData
from app.domain.cleaner import Cleaner
from app.domain.ws_plant_gold import gold_key
from app.services.panel_pool import PanelPool, PanelRow

PLANT = "FTM"
MODEL = "P703 DBL RANGER"
WHEN = datetime(2026, 10, 8, 14, 37, tzinfo=timezone.utc)


def row(zone, point_no, orientation="Vertical", *, mappable=True, taken_by=None):
    return PanelRow(
        zone_code=zone,
        point_no=point_no,
        tolerance_group=orientation,
        note=None,
        mappable=mappable,
        not_mappable_reason=None if mappable else "not on the model catalogue",
        taken_by=taken_by,
    )


def pool(*rows) -> PanelPool:
    return PanelPool(plant_code=PLANT, model_code=MODEL, rows=tuple(rows))


#: FTM's real shape, in miniature: three long-form fenders a map may point
#: at, and the T58 numbered block beside them, which it may not.
def ftm_like(taken_by=None) -> PanelPool:
    return pool(
        row("LFFENDER", 6, taken_by=taken_by),
        row("LCFENDER", 7),
        row("LRFENDER", 8),
        row("LCROOF", 11, "Horizontal"),
        row("06LFFFEND", 38, mappable=False),
        row("07LFFENDE", 39, mappable=False),
        row("11ROOF", 43, "Horizontal", mappable=False),
    )


# =====================================================================
# Part 1 -- D-89-6: one picker
# =====================================================================
def test_every_panel_offered_is_one_the_approval_path_accepts():
    """The defect the owner hit: 64 offered, 32 of them refusable."""
    offering = ftm_like().offer("07LFFENDER", ["Vertical"])
    assert set(offering.offerable) == {"LFFENDER", "LCFENDER", "LRFENDER"}
    # Not one of the numbered block, which `fk_pzm_model_zone` cannot
    # reference and the approval path therefore refuses.
    assert not [z for z in offering.offerable if z[0].isdigit()]


def test_orientation_is_a_hard_filter_on_the_list_as_well():
    offering = ftm_like().offer("11ROOF", ["Horizontal"])
    assert offering.offerable == ("LCROOF",)
    assert "LFFENDER" in offering.filtered_out


def test_a_file_that_disagrees_with_itself_filters_nothing():
    """G-88-5 kept: two orientations for one spelling is a file problem."""
    offering = ftm_like().offer("07LFFENDER", ["Vertical", "Horizontal"])
    assert "LCROOF" in offering.offerable
    assert offering.filtered_out == ()


def test_a_taken_panel_is_present_disabled_and_says_who_took_it():
    offering = ftm_like(taken_by="06LFFENDER").offer("07LFFENDER", ["Vertical"])
    assert "LFFENDER" not in offering.offerable
    taken = {b.zone_code: b.taken_label for b in offering.blocked}
    assert taken == {"LFFENDER": "already matched to 06LFFENDER"}


def test_the_suggestions_come_first_and_the_rest_follows():
    offering = ftm_like().offer("07LFFENDER", ["Vertical"])
    # The panel carrying the file's own number 7 leads (T87 / D-87-1), and
    # every other choosable panel is still in the list.
    assert offering.offerable[0] == "LCFENDER"
    assert set(offering.offerable[1:]) == {"LFFENDER", "LRFENDER"}


def test_a_spelling_with_no_close_name_still_gets_the_whole_list():
    """An empty candidate list is an answer; an empty picker is not."""
    offering = ftm_like().offer("25TGATE", ["Vertical"])
    assert set(offering.offerable) == {"LFFENDER", "LCFENDER", "LRFENDER"}


def test_the_solver_pool_is_the_same_panels_the_picker_offers():
    """One builder: the proposals and the list cannot drift apart."""
    live = ftm_like(taken_by="06LFFENDER")
    assert {p.zone_code for p in live.open_mappable} == {
        "LCFENDER", "LRFENDER", "LCROOF"
    }


# =====================================================================
# D-89-5 -- normalise at the door, and what makes it work
# =====================================================================
LONG_FORM = {
    "rrhood": "RRHOOD", "lffender": "LFFENDER", "11roof": "LCROOF",
}
NUMBERED = {"1hood": "01HOOD", "11roof": "11ROOF"}


def reference(*, numbered_live: bool, alias: bool) -> ReferenceData:
    """FTM's two blocks, with the numbered one live or retired.

    `plant_gold` is keyed on `gold_key`, exactly as the loader builds it
    from `ref_plant_ws_point`; retiring a panel is the panel leaving that
    mapping, which is what `retired_at IS NULL` does in the real read.
    """
    gold = dict(LONG_FORM)
    if numbered_live:
        gold.update(NUMBERED)
    return ReferenceData(
        model_zone=frozenset(
            {(MODEL, code) for code in ("RRHOOD", "LFFENDER", "LCROOF")}
        ),
        plant_gold={(PLANT, MODEL): gold},
        plant_zone_map=(
            {(PLANT, MODEL, "01hood"): "RRHOOD"} if alias else {}
        ),
        known_plants=frozenset({PLANT}),
        active_plants=frozenset({PLANT}),
    )


def two_hoods(*, alias: bool = False) -> ReferenceData:
    """The same reference with a second canonical hood (T97 / D-97-1).

    ``hood`` is then the tail of two canonical names, so the name names
    neither and D-97-1 resolves nothing -- the real FTM shape.
    """
    ref = reference(numbered_live=False, alias=alias)
    return ReferenceData(
        model_zone=ref.model_zone | frozenset({(MODEL, "LFHOOD")}),
        plant_gold={(PLANT, MODEL): {**ref.plant_gold[(PLANT, MODEL)],
                                     "lfhood": "LFHOOD"}},
        plant_zone_map=dict(ref.plant_zone_map),
        known_plants=ref.known_plants,
        active_plants=ref.active_plants,
    )


def cleaner(ref: ReferenceData) -> Cleaner:
    return Cleaner(ref, frozenset({PLANT}), expected_plant=PLANT)


def test_while_the_numbered_panel_is_live_an_alias_beside_it_changes_nothing():
    """The dependency D-89-4 is about, as its own claim.

    `cleaner.resolve_checkzone` matches the text against the gold list
    first (T58 / D-58-09). So adding `01HOOD -> RRHOOD` while `01HOOD` is
    itself a live panel is a **no-op**, and a silent no-op in this platform
    is a defect. This is why the pairs cannot be "added and we are done".
    """
    without = cleaner(reference(numbered_live=True, alias=False))
    withal = cleaner(reference(numbered_live=True, alias=True))
    assert without.resolve_checkzone(PLANT, MODEL, "01HOOD") == "01HOOD"
    assert withal.resolve_checkzone(PLANT, MODEL, "01HOOD") == "01HOOD"


def test_once_the_numbered_panel_is_retired_the_same_input_folds():
    """Retirement is the mechanism, not tidiness (D-89-5)."""
    folded = cleaner(reference(numbered_live=False, alias=True))
    assert folded.resolve_checkzone(PLANT, MODEL, "01HOOD") == "RRHOOD"


def test_retiring_without_the_alias_stops_the_name_resolving_at_all():
    """Why the order is fixed: retirement first makes the next upload worse.

    **Amended by T97 (D-97-1).** This fixture's model carries exactly one
    hood (`LONG_FORM` is three panels), so ``01HOOD``'s name now names
    exactly one canonical panel and resolves to it as a last resort, with
    no alias row. The T89 claim is unchanged where the name is vague: add a
    second canonical hood and the name names two, so nothing resolves --
    which is the real FTM shape (five hoods), where D-94-1 calls the label
    rough before resolution is reached at all.
    """
    broken = cleaner(reference(numbered_live=False, alias=False))
    assert broken.resolve_checkzone(PLANT, MODEL, "01HOOD") == "RRHOOD"
    assert cleaner(two_hoods()).resolve_checkzone(PLANT, MODEL, "01HOOD") is None


def test_either_convention_stores_the_same_checkzone():
    """The owner's question 1, as one assertion."""
    done = cleaner(reference(numbered_live=False, alias=True))
    assert (
        done.resolve_checkzone(PLANT, MODEL, "01HOOD")
        == done.resolve_checkzone(PLANT, MODEL, "RRHOOD")
        == "RRHOOD"
    )


def test_a_taught_pair_at_ftm_does_not_resolve_at_another_plant():
    """D-89-10: plant separation is a property of the table's key."""
    ref = reference(numbered_live=False, alias=True)
    for other in ("AAT", "FVL", "SAP"):
        scoped = Cleaner(ref, frozenset({PLANT, other}), expected_plant=other)
        assert scoped.resolve_checkzone(other, MODEL, "01HOOD") is None


def test_a_taught_pair_is_matched_on_the_exact_spelling_not_the_zero_pad():
    """Measured, and reported rather than changed.

    The **gold list** is matched on `gold_key`, so `01HOOD` and `1HOOD` are
    one name there (D-58-03). The **learning table** is not: it is keyed on
    `normalise_alias`, so a pair taught for `01HOOD` does not fire for a
    file that writes `1HOOD`. That asymmetry is T53/T58 locked behaviour and
    T89 does not change it -- it is named in the report instead, because it
    means an owner teaching the 32 pairs teaches the spelling the file
    actually uses and not its unpadded twin.
    """
    done = cleaner(reference(numbered_live=False, alias=True))
    assert gold_key("01HOOD") == gold_key("1HOOD")
    assert done.resolve_checkzone(PLANT, MODEL, "01HOOD") == "RRHOOD"
    # Amended by T97 (D-97-1): with one canonical hood on this model the
    # unpadded twin now resolves by its name, not by the taught pair. The
    # asymmetry this test is about is unchanged -- it is still the taught
    # pair that does not fire -- so it is asserted where the name says
    # nothing: two hoods, and neither spelling resolves.
    assert done.resolve_checkzone(PLANT, MODEL, "1HOOD") == "RRHOOD"
    vague = cleaner(two_hoods(alias=True))
    assert vague.resolve_checkzone(PLANT, MODEL, "01HOOD") == "RRHOOD"
    assert vague.resolve_checkzone(PLANT, MODEL, "1HOOD") is None


# =====================================================================
# D-89-9 -- remember, and show what was remembered
# =====================================================================
OFFERABLE = ("LFFENDER", "LCFENDER", "LRFENDER")


def taught(**kw) -> TaughtPair:
    base = dict(
        raw_zone_text="06LFFENDER", zone_code="LFFENDER", model_code=MODEL,
        status="APPROVED", decided_at=WHEN, load_id=None, method="T88_PANEL_MATCH_NAME",
    )
    base.update(kw)
    return TaughtPair(**base)


def test_nothing_is_carried_when_nothing_was_decided():
    assert carried_over_for("06LFFENDER", MODEL, [], OFFERABLE) is None


def test_a_pair_still_waiting_for_an_admin_comes_back_pre_selected():
    found = carried_over_for(
        "06LFFENDER", MODEL,
        [taught(status="PROPOSED", load_id=66219)],
        OFFERABLE,
    )
    assert found is not None
    assert found.kind == CARRY_PENDING
    assert found.zone_code == "LFFENDER"
    assert "2026-10-08" in found.reason
    assert "66219" in found.reason


def test_the_same_spelling_on_another_model_is_shown_as_another_models_decision():
    found = carried_over_for(
        "06LFFENDER", MODEL,
        [taught(model_code="P703 DBL RAPTOR")],
        OFFERABLE,
    )
    assert found is not None
    assert found.kind == CARRY_OTHER_MODEL
    assert found.source_model_code == "P703 DBL RAPTOR"
    assert "per model" in found.reason


def test_a_near_miss_spelling_carries_the_decision_and_says_it_is_a_near_miss():
    found = carried_over_for("06LFFENDE", MODEL, [taught()], OFFERABLE)
    assert found is not None
    assert found.kind == CARRY_NEAR_MISS
    assert found.zone_code == "LFFENDER"
    assert found.source_raw_zone_text == "06LFFENDER"


def test_a_different_panel_whose_name_differs_by_one_digit_is_not_a_near_miss():
    """`07LFFENDER` is not a misspelling of `06LFFENDER`: it is panel 7.

    This is the one that would be dangerous to get wrong, because the whole
    reason T86 exists is that 28 of September's 32 names differ from each
    other only by their number.
    """
    assert carried_over_for("07LFFENDER", MODEL, [taught()], OFFERABLE) is None


def test_a_near_miss_of_another_family_is_never_carried():
    """A typo may not carry a ROOF decision onto a FENDER (D-86-3's gate)."""
    found = carried_over_for(
        "11ROOF", MODEL,
        [taught(raw_zone_text="11ROOE", zone_code="LFFENDER")],
        OFFERABLE,
    )
    assert found is None


def test_a_decision_naming_a_panel_that_is_not_on_offer_is_dropped():
    """Never pre-select something the approval path would refuse."""
    assert carried_over_for(
        "06LFFENDER", MODEL, [taught(zone_code="01HOOD")], OFFERABLE
    ) is None


def test_an_approved_pair_for_this_very_model_is_not_a_pending_carry_over():
    """It resolves at the door, so the question does not come back at all.

    When it *is* asked anyway -- a committed remainder being re-read -- the
    answer shown is the approved pair as the other-model / near-miss cases
    are, never as "waiting for an Admin".
    """
    found = carried_over_for("06LFFENDER", MODEL, [taught()], OFFERABLE)
    assert found is None or found.kind != CARRY_PENDING


# =====================================================================
# Part 5 / D-88-7 -- a renaming is one event
# =====================================================================
SHAPE = {"Horizontal": 2, "Vertical": 2}


def rename(**kw):
    base = dict(
        plant_code=PLANT,
        model_code=MODEL,
        held_spellings=["01HOOD", "02HOOD", "06LFFFEND", "07LFFENDE"],
        file_panel_count=4,
        rows_held=741,
        file_orientations=dict(SHAPE),
        mappable_orientations=dict(SHAPE),
    )
    base.update(kw)
    return whole_set_rename(**base)


def test_a_whole_set_rename_is_named_as_one_event():
    found = rename()
    assert found is not None
    assert found.file_panel_count == 4
    assert found.live_panel_count == 4
    assert "renaming of all 4 panels" in found.message
    assert "741 bad rows" in found.message


def test_one_held_name_among_many_is_not_a_renaming():
    assert rename(held_spellings=["01HOOD"]) is None


def test_a_file_walking_a_different_number_of_panels_is_not_a_renaming():
    assert rename(mappable_orientations={"Horizontal": 2, "Vertical": 3}) is None


def test_a_file_of_a_different_shape_is_not_a_renaming():
    """Same count, different Horizontal / Vertical split."""
    assert rename(
        file_orientations={"Horizontal": 1, "Vertical": 3},
        mappable_orientations={"Horizontal": 2, "Vertical": 2},
    ) is None


def test_nothing_held_is_not_a_renaming():
    assert rename(held_spellings=[], file_panel_count=0) is None


@pytest.mark.parametrize("missing", ["file_orientations", "mappable_orientations"])
def test_no_orientation_at_all_is_not_a_renaming(missing):
    assert rename(**{missing: {}}) is None
