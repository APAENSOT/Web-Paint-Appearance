"""T94 -- the pure half: a rough label is one that does not name a panel.

No database and no application. These are claims about the rule, which is
where they belong, and every one of them is one of the task's section 5
tests:

* ``01HOOD`` on a model with five hoods is **rough** -- and rough *alone on
  a sheet*, which is the case T90's per-sheet test could not see and the one
  the owner's screenshot was about;
* ``LCPILLAR`` is **specific** and asks nothing;
* ``06LFFENDER`` alone is **specific**; with ``07`` and ``08LFFENDER``
  present all three are **rough**;
* the rule is computed per ``(plant, model)``, so the same spelling can be
  rough against one canonical list and specific against another;
* a name the canonical list has no name for at all is **specific** -- it is
  unknown, not vague, and the honest answer to it is the existing hold.

The canonical list and the September labels below are the real ones, the
same values `test_t90_panel_walk.py` reads from
`docs/tasks/reference/ftm-canonical-pairs.csv` and the real FTM CF files.
"""

from __future__ import annotations

from app.domain.panel_walk import (
    SPECIFICITY_ROUGH,
    SPECIFICITY_SPECIFIC,
    canonical_named_by,
    classify_against_canonical,
    is_canonical_panel,
    names_canonical_panel,
)

#: FTM P703's canonical 32 -- the long-form names a position can be named by.
CANONICAL = (
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

#: The real September labels, in the real walk order.
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

#: The four names of the real September sheet that **do** say which panel
#: they are. Measured, and the same four the T94 context's section 3 names:
#: "28 of its 32 names differ from each other only by that number".
SEPTEMBER_SPECIFIC = {"12LCPILLAR", "13LFRDOOR", "15RCPILLAR", "16RTRDOOR"}


def test_01hood_names_five_hoods_so_it_names_none_of_them():
    """D-94-1 (a), and the whole reason T94 exists.

    The name with its leading number dropped is ``hood``, and five canonical
    panels are a hood. Five positions is not a near-miss; it is a family and
    a position, and the position is not in the name.
    """
    assert canonical_named_by("01HOOD", CANONICAL) == (
        "CFHOOD", "LFHOOD", "LRHOOD", "RFHOOD", "RRHOOD",
    )
    # Rough **alone on a sheet**. T90's `classify_specificity` is per sheet,
    # so a sheet carrying only `01HOOD` came out specific and loaded as
    # `01HOOD` -- the bug. This is the case that stops it.
    assert classify_against_canonical(["01HOOD"], CANONICAL) == {
        "01HOOD": SPECIFICITY_ROUGH
    }


def test_a_name_that_names_one_panel_is_specific_and_asks_nothing():
    """``LCPILLAR`` and ``12LCPILLAR`` are the same claim about a position.

    T96 (D-96-1) leaves this one alone on purpose: the name still names
    exactly one canonical panel, so the number in front of it is
    provenance and not the identity.
    """
    for label in ("LCPILLAR", "12LCPILLAR", "lcpillar"):
        assert canonical_named_by(label, CANONICAL) == ("LCPILLAR",), label
        assert classify_against_canonical([label], CANONICAL) == {
            label: SPECIFICITY_SPECIFIC
        }, label


def test_06lffender_is_specific_alone_and_rough_beside_07_and_08():
    """D-94-1 (b): the sheet's own names can make a good name ambiguous.

    ``06LFFENDER`` names exactly one panel, so on its own it loads. With
    ``07`` and ``08LFFENDER`` on the same sheet all three reduce to
    ``lffender`` and only one of them can be ``LFFENDER`` -- so the number
    is doing the identifying and none of the three may be taken on trust.
    """
    assert classify_against_canonical(["06LFFENDER"], CANONICAL) == {
        "06LFFENDER": SPECIFICITY_SPECIFIC
    }
    three = ["06LFFENDER", "07LFFENDER", "08LFFENDER"]
    assert classify_against_canonical(three, CANONICAL) == {
        label: SPECIFICITY_ROUGH for label in three
    }


def test_the_real_september_sheet_is_30_rough_and_2_specific():
    """The measured shape of the owner's own file.

    T94 measured 28 rough and 4 specific. **T96 (D-96-1) makes it 30 and
    2:** ``13LFRDOOR`` and ``16RTRDOOR`` lead with a number and name no
    canonical panel at all -- the same shape as the four August labels that
    loaded under their own number -- and ``13LFRDOOR`` is the one the owner
    confirmed as ``LCPILLAR``, by its number. ``12LCPILLAR`` and
    ``15RCPILLAR`` still name one panel each and stay specific.
    """
    verdicts = classify_against_canonical(list(SEPTEMBER), CANONICAL)
    specific = {
        label for label, verdict in verdicts.items()
        if verdict == SPECIFICITY_SPECIFIC
    }
    assert specific == {"12LCPILLAR", "15RCPILLAR"}
    assert specific < SEPTEMBER_SPECIFIC
    assert len(SEPTEMBER) - len(specific) == 30


#: FVL's ``CX743`` catalogue, read live: the model's own 32 positions, and
#: at this plant the walk number IS part of the name.
FVL_CX743 = (
    "1HOOD", "2HOOD", "3HOOD", "4HOOD", "5HOOD",
    "06LFFENDER", "07LFFENDER", "08LFFENDER",
    "09LFFTDOOR", "10LFFTDOOR", "11LFRTDOOR", "12LFRTDOOR",
    "13LFRQTR", "14LFRQTR", "15LFRQTR",
    "16ROOF",
    "17LIFGATE", "18LIFTGATE", "19LIFTGATE", "20LIFTGATE", "21LIFTGATE",
    "22RTRQTR", "23RTRQTR", "24RTRQTR",
    "25RTRDOOR", "26RTRDOOR", "27RTFTDOOR", "28RTFTDOOR",
    "29RTFENDER", "30RTFENDER", "31RTFENDER", "32ROOF",
)


def test_a_label_that_is_one_of_the_models_own_names_is_always_specific():
    """At some plants the number **is** the name, and that must not be read
    off and then called vague.

    FVL's ``CX743`` catalogue is ``1HOOD``..``5HOOD``, ``11LFRTDOOR``,
    ``12LFRTDOOR``. Those are the model's own positions, so each one names
    exactly one panel -- there is nothing to disambiguate it to, and holding
    a whole FVL file to ask would be asking a question with no answer.

    This is also the line D-94-2 draws. FTM has a **live** panel spelled
    ``01HOOD`` and it saves nothing, because it is not a position on the
    model's catalogue: it is the T58 numbered block, the accident that made
    the owner's rows read "Ready to add".
    """
    assert all(
        verdict == SPECIFICITY_SPECIFIC
        for verdict in classify_against_canonical(
            list(FVL_CX743), FVL_CX743
        ).values()
    )
    # The pair that shares every letter but its number: specific at FVL,
    # because both ARE positions on this model.
    assert classify_against_canonical(["11LFRTDOOR", "12LFRTDOOR"], FVL_CX743) == {
        "11LFRTDOOR": SPECIFICITY_SPECIFIC,
        "12LFRTDOOR": SPECIFICITY_SPECIFIC,
    }
    # Up to the leading-zero pad the gold list already treats as one point.
    assert is_canonical_panel("01HOOD", FVL_CX743) == "1HOOD"
    assert is_canonical_panel("1hood", FVL_CX743) == "1HOOD"
    # And the same spelling against FTM's canonical list is not on it.
    assert is_canonical_panel("01HOOD", CANONICAL) is None
    assert classify_against_canonical(["01HOOD"], CANONICAL) == {
        "01HOOD": SPECIFICITY_ROUGH
    }


def test_a_tail_match_needs_the_family_to_agree():
    """``ROOF`` is never a near-miss of ``LFBOXSD`` at any spelling.

    The family gate is T86's, so nothing here can make two names the same
    panel because their letters happen to end alike.
    """
    assert names_canonical_panel("11ROOF", "LCROOF")
    assert names_canonical_panel("01HOOD", "RRHOOD")
    assert not names_canonical_panel("14ROOF", "LFBOX")
    # One-directional: a name LONGER than the canonical one is a spelling
    # question for the match screen, not the rough/specific question.
    assert not names_canonical_panel("16RTRDOOR", "RCRDOOR")
    assert not names_canonical_panel("LFFENDER", "RFFENDER"), "the L is part of the name"


def test_a_name_the_list_cannot_name_at_all_is_specific_not_rough():
    """It is unknown, not vague.

    ``25TGATE`` fits no canonical name, so condition (a) says nothing about
    it. On its own it is specific and takes the ordinary hold, which already
    has a screen. It becomes rough only through condition (b) -- which is
    what the real sheet does, with five of them.
    """
    assert canonical_named_by("25TGATE", CANONICAL) == ()
    # T96 (D-96-1): the exception survives only for a label with NO leading
    # number. `25TGATE` has one and names nothing, so it is rough on its
    # own now -- that is the T96 defect, and it is the shape of August's
    # `25RTRDOOR`. A bare `TGATE` is what the branch still covers, and it
    # still takes the ordinary hold rather than a confirmation with nothing
    # to propose.
    assert classify_against_canonical(["25TGATE"], CANONICAL) == {
        "25TGATE": SPECIFICITY_ROUGH
    }
    assert canonical_named_by("TGATE", CANONICAL) == ()
    assert classify_against_canonical(["TGATE"], CANONICAL) == {
        "TGATE": SPECIFICITY_SPECIFIC
    }
    five = ["25TGATE", "26TGATE", "27TGATE", "28TGATE", "29TGATE"]
    assert classify_against_canonical(five, CANONICAL) == {
        label: SPECIFICITY_ROUGH for label in five
    }


def test_the_rule_is_per_plant_and_model_not_per_sheet():
    """D-94-1: the canonical list is half the question.

    The same spelling, the same sheet, two different models: against a list
    with five hoods ``01HOOD`` is rough, and against a list with one it is
    specific. Nothing about the sheet changed.
    """
    one_hood = ("RRHOOD", "LFFENDER", "LCPILLAR")
    assert classify_against_canonical(["01HOOD"], one_hood) == {
        "01HOOD": SPECIFICITY_SPECIFIC
    }
    assert classify_against_canonical(["01HOOD"], CANONICAL) == {
        "01HOOD": SPECIFICITY_ROUGH
    }


def test_no_canonical_list_means_no_claim_either_way():
    """A model with nothing to be vague against asks nothing.

    Three plant x model pairs are in exactly this state today (T89 Part 1).
    Saying "specific" there is not a promise that the name is good; it is
    the absence of a claim, and the held-label path still covers the rows.
    """
    assert classify_against_canonical(["01HOOD"], ()) == {
        "01HOOD": SPECIFICITY_SPECIFIC
    }
    assert canonical_named_by("01HOOD", ()) == ()


def test_the_verdict_is_keyed_by_the_label_as_written():
    """The caller matches rows by what the file wrote, so that is the key."""
    labels = ["01HOOD", " 02hood ", "12LCPILLAR"]
    verdicts = classify_against_canonical(labels, CANONICAL)
    assert set(verdicts) == set(labels)
    assert verdicts[" 02hood "] == SPECIFICITY_ROUGH
