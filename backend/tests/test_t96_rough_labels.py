"""T96 -- a label that leads with a number does not say which panel it is.

The hole T94 left open, measured on the owner's real August file
``08 Aug2026 CF data FTM.xlsx``: four of its labels came out **specific**
and loaded under their own number --

    06LFFFEND    16LFBOXS    25RTRDOOR    26RTRDOO

-- because FTM's numbered block is stored with *truncated* spellings and
the file writes the same ones. The truncation defeats both halves of
D-94-1 at once: the name matches no canonical panel, so (a) never reaches
"more than one"; and the siblings are truncated differently, so (b) finds
nothing sharing the core. Declared specific, each one fell through to
ordinary resolution and matched the live T58 panel spelled exactly like it.

So **D-96-1**: a label that leads with a number and is not one of this
model's own canonical names is rough, full stop. **D-96-2** keeps D-94-1's
first check first, and the FVL tests here are its regression guard -- at
``CX743`` and ``V363`` all 32 canonical names lead with a digit, and
without that check the whole FVL catalogue would go rough.

Part 2's fix is pinned here too: :func:`_spelling_blocks` reads one sheet
as the walks it really contains, because the August sheet writes each
model's 32-point walk twice over in two different spellings.

Pure, no application, with one read-only database check that FTM really
does carry live panels spelled like those four labels. No row is written or
deleted anywhere (D-96-5).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.domain.panel_walk import (
    SPECIFICITY_ROUGH,
    SPECIFICITY_SPECIFIC,
    classify_against_canonical,
    is_canonical_panel,
    leads_with_number,
    match_walk,
)
from app.schemas.history import HistoryPointOut
from app.services.panel_match import _spelling_blocks
from tests.test_t04_ingest import cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
)
from tests.test_t90_panel_walk import CANONICAL as CANONICAL_POINTS
from tests.test_t90_panel_walk import CANONICAL_NAMES, walk

#: The four labels of the owner's August file that loaded under their own
#: number, each of which was also a live FTM panel (the T58 numbered block)
#: -- T113-FIX (D-113-1): retired 2026-10-11, so each is a *retired* panel.
AUGUST_FOUR = ("06LFFFEND", "16LFBOXS", "25RTRDOOR", "26RTRDOO")

#: The real August numbered block, in the real walk order, as both FTM P703
#: models write it. 32 labels; the four above are inside it.
AUGUST_NUMBERED = (
    "01HOOD", "02HOOD", "03HOOD", "04HOOD", "05HOOD",
    "06LFFFEND", "07LFFENDE", "08LFFENDE",
    "09LFFTDOOR", "10LFFTDOOR",
    "11ROOF", "12LFRDOOR", "13LFRDOOR",
    "14LFBOXSD", "15LFBOXSD", "16LFBOXS",
    "17TGATE", "18TGATE", "19TGATE", "20TGATE", "21TGATE",
    "22RTBOXSD", "23RTBOXSD", "24RTBOXSD",
    "25RTRDOOR", "26RTRDOO",
    "27ROOF", "28RTFTDOO", "29RTFTDOO",
    "30RTFENDE", "31RTFENDE", "32RTFENDE",
)

#: The spaced long-name block of the **same** August sheet: the walk the
#: other vehicles of that one file write, in their own spelling.
AUGUST_SPACED = (
    "01 RRHOOD", "02 RFHOOD", "03 CFHOOD", "04 LFHOOD", "05 LRHOOD",
    "06 LFFender", "07 LCFender", "08 LRFender",
    "09 LTFDoor", "10 LCFDoor", "11 LCRoof", "12 LCRDoor", "13 LCPillar",
    "14 LFBoox", "15 LCBox", "16 LRBox",
    "17 LTTailagte", "18 LBTailagte", "19 LCTailagate",
    "20 RBTailgate", "21RTTailgate",
    "22 RRBox", "23 RCBox", "24 RFBox",
    "25 RCPillar", "26 RCRDoor", "27 RCRoof", "28 RCFDoor", "29 FTFDoor",
    "30 RRFender", "31 RCFender", "32 RFFender",
)

#: FVL ``CX743``'s own catalogue, read live from ``ref_model_zone``. Every
#: one of the 32 leads with a digit, and every one of them IS a position.
FVL_CX743 = (
    "1HOOD", "2HOOD", "3HOOD", "4HOOD", "5HOOD",
    "06LFFENDER", "07LFFENDER", "08LFFENDER",
    "09LFFTDOOR", "10LFFTDOOR", "11LFRTDOOR", "12LFRTDOOR",
    "13LFRQTR", "14LFRQTR", "15LFRQTR", "16ROOF",
    "17LIFGATE", "18LIFTGATE", "19LIFTGATE", "20LIFTGATE", "21LIFTGATE",
    "22RTRQTR", "23RTRQTR", "24RTRQTR",
    "25RTRDOOR", "26RTRDOOR", "27RTFTDOOR", "28RTFTDOOR",
    "29RTFENDER", "30RTFENDER", "31RTFENDER", "32ROOF",
)

#: FVL ``V363``'s own catalogue, read live. Same shape, other spellings.
FVL_V363 = (
    "1HOOD", "2HOOD", "3HOOD", "4HOOD", "5HOOD",
    "06LFFTFENDER", "07LFFTFENDER", "08LFFTFENDER",
    "09LFFTDOOR", "10LFFTDOOR", "11LFROOF", "12LFRDOOR",
    "13LFRQTR", "14LFRQTR", "15LFRQTR", "16LFRQTR",
    "17SWINGGAT", "18SWINGGAT", "19SWINGGAT", "20SWINGGAT", "21SWINGGAT",
    "22RTRQTR", "23RTRQTR", "24RTRQTR", "25RTRQTR",
    "26RTRDOOR", "27RTROOF", "28RTRDOOR", "29RTRDOOR",
    "30RTFTFENDER", "31RTFTFENDER", "32RTFTFENDER",
)


def test_the_four_august_labels_are_rough_although_a_panel_is_spelled_so():
    """D-96-1, label by label, on the real spellings.

    Each of the four names no canonical panel at all and shares its core
    with nothing else in the block -- which is exactly why T94 called it
    specific. The leading number is sufficient on its own, so each one is
    rough with no sibling anywhere near it as well.
    """
    verdicts = classify_against_canonical(
        list(AUGUST_NUMBERED), CANONICAL_NAMES
    )
    for label in AUGUST_FOUR:
        assert is_canonical_panel(label, CANONICAL_NAMES) is None, label
        assert verdicts[label] == SPECIFICITY_ROUGH, label
        assert classify_against_canonical([label], CANONICAL_NAMES) == {
            label: SPECIFICITY_ROUGH
        }, label


def test_the_whole_august_block_is_32_rough_and_0_specific():
    """Both FTM P703 models carry the same canonical 32, so one claim."""
    assert len(AUGUST_NUMBERED) == 32
    assert classify_against_canonical(
        list(AUGUST_NUMBERED), CANONICAL_NAMES
    ) == {label: SPECIFICITY_ROUGH for label in AUGUST_NUMBERED}


def test_the_four_match_a_retired_ftm_panel_spelled_exactly_like_them(app_conn):
    """The accident D-96-1 closes, read from the owner's own catalogue.

    Read-only. **T113-FIX (D-113-1): FTM short-name block retired
    2026-10-11.** The numbered block is still spelled this way -- retired,
    never deleted (ADR 0005) -- which is what let the four resolve silently
    while it was live. None of the four is on the model's canonical list,
    then or now, which is the half of the accident D-96-1 actually closes.
    """
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code, retired_at IS NOT NULL FROM ref_plant_ws_point"
            " WHERE plant_code = 'FTM'"
        )
        panels = cur.fetchall()
    live = {code for code, is_retired in panels if not is_retired}
    retired = {code for code, is_retired in panels if is_retired}
    for label in AUGUST_FOUR:
        # T113-FIX (D-113-1): retired, so no longer a silent match target.
        assert label in retired, label
        assert label not in live, label
        assert label not in CANONICAL_NAMES, label


def test_fvl_cx743_and_v363_stay_32_specific():
    """D-96-2, the regression guard, and the thing most likely to break.

    At both FVL models **the number is the name**: all 32 canonical names
    lead with a digit. D-94-1's first check runs first, so each one is the
    panel it names and nothing here is rough -- although ``25RTRDOOR`` and
    ``26RTRDOOR`` share a core at ``CX743``, and three names share
    ``rtrdoor`` at ``V363``, which (b) and D-96-1 would otherwise catch.
    """
    for catalogue in (FVL_CX743, FVL_V363):
        assert len(catalogue) == 32
        assert all(leads_with_number(name) for name in catalogue)
        assert classify_against_canonical(list(catalogue), catalogue) == {
            name: SPECIFICITY_SPECIFIC for name in catalogue
        }


def test_a_label_with_no_leading_number_keeps_the_d_94_1_branch():
    """"Names none -> specific" survives, for a label with no number.

    ``TGATE`` names no canonical panel of FTM P703. It is unknown rather
    than vague, it takes the ordinary hold, and D-96-1 does not reach it.
    The two older conditions still work without a number in front: ``HOOD``
    names five hoods.
    """
    assert not leads_with_number("TGATE")
    assert classify_against_canonical(["TGATE"], CANONICAL_NAMES) == {
        "TGATE": SPECIFICITY_SPECIFIC
    }
    assert classify_against_canonical(["HOOD"], CANONICAL_NAMES) == {
        "HOOD": SPECIFICITY_ROUGH
    }


def test_a_pair_with_no_canonical_list_still_claims_nothing():
    """T89 Part 1's three pairs are out of scope and must stay silent.

    ``FVL / P703 DBL RANGER``, ``SAP / J73 DBL`` and ``SAP / P703 DBL
    RANGER`` have 32 live numbered points and no canonical list at all.
    With nothing to be vague against, D-96-1 makes no claim either -- the
    held-label path still covers those rows (T96 section 5).
    """
    # D-96-1 is guarded by the list, so these four -- rough against FTM's
    # canonical 32 by the leading number alone -- claim nothing without
    # one. (b) still applies, because a sheet that writes `17TGATE` and
    # `18TGATE` says so by itself and needs no catalogue to say it; that is
    # T94 behaviour and T96 does not touch it.
    assert classify_against_canonical(list(AUGUST_FOUR), ()) == {
        label: SPECIFICITY_SPECIFIC for label in AUGUST_FOUR
    }
    assert classify_against_canonical(["17TGATE", "18TGATE"], ()) == {
        "17TGATE": SPECIFICITY_ROUGH,
        "18TGATE": SPECIFICITY_ROUGH,
    }


def test_leads_with_number_reads_the_text_and_nothing_else():
    assert leads_with_number("06LFFFEND")
    assert leads_with_number("01 RRHOOD")
    assert leads_with_number(" 7LFFENDER")
    assert leads_with_number("99FOO"), "outside 1..40 is still a number"
    assert not leads_with_number("LCPILLAR")
    assert not leads_with_number("")
    assert not leads_with_number("LFFENDER06")


def test_one_sheet_two_spellings_is_two_walks_and_both_get_proposals():
    """T96 Part 2: the measured cause of the missing proposal, and its fix.

    The August sheet writes each model's 32-point walk **twice over**, one
    spelling per vehicle. Deduplicated across the whole sheet that is 64
    labels against 32 canonical points, so rule (a) refuses itself on the
    group counts and rule (b) on the count -- which is why every rough row
    offered "Choose panel" with no proposal at all. Split into the walks
    the sheet really contains, rule (b) applies to each and every label
    gets its long name, including the owner's own confirmed answers.
    """
    rows = walk(AUGUST_SPACED, vehicle="2026-08-04|Arctic White|1960130") + walk(
        AUGUST_NUMBERED, vehicle="2026-08-19|Command Grey|1965294", start=34
    )

    whole_sheet = match_walk(rows, CANONICAL_POINTS)
    assert not whole_sheet.rule_a.available
    assert not whole_sheet.rule_b.available
    assert "64 names against 32 canonical points" in whole_sheet.rule_b.reason
    assert all(v.proposed_zone_code is None for v in whole_sheet.verdicts)

    blocks = _spelling_blocks(rows)
    assert [len(block) for block in blocks] == [32, 32]
    proposed: dict[str, str | None] = {}
    for block in blocks:
        match = match_walk(block, CANONICAL_POINTS)
        assert match.rule_b.available, match.rule_b.reason
        for spelling, verdict in match.by_spelling().items():
            proposed[spelling] = verdict.proposed_zone_code
    assert len(proposed) == 64
    assert all(proposed.values())
    assert proposed["13LFRDOOR"] == "LCPILLAR"
    assert proposed["25RTRDOOR"] == "RCPILLAR"
    assert proposed["17TGATE"] == "LTTAILGATE"
    assert proposed["22RTBOXSD"] == "RRBOX"
    assert proposed["27ROOF"] == "RCROOF"
    assert proposed["06LFFFEND"] == "LFFENDER"
    assert proposed["16LFBOXS"] == "LRBOX"
    assert proposed["26RTRDOO"] == "RCRDOOR"
    assert proposed["01 RRHOOD"] == "RRHOOD"


def test_a_vehicle_with_readings_missing_cannot_take_a_proposal_away():
    """The partial vehicle of the real file, which is why order matters.

    One Ranger vehicle carries only its first six readings. On its own that
    is 6 names against 32 points and no rule applies -- so blocks are read
    largest first and a label keeps the first verdict that proposes
    something.
    """
    rows = walk(AUGUST_SPACED, vehicle="2026-08-04|Arctic White|1960130") + walk(
        AUGUST_SPACED[:6], vehicle="2026-08-12|Meteor Grey|1962744", start=34
    )
    blocks = _spelling_blocks(rows)
    assert [len(block) for block in blocks] == [32, 6]
    proposed: dict[str, str | None] = {}
    for block in blocks:
        for spelling, verdict in match_walk(
            block, CANONICAL_POINTS
        ).by_spelling().items():
            if proposed.get(spelling) is None:
                proposed[spelling] = verdict.proposed_zone_code
    assert proposed["01 RRHOOD"] == "RRHOOD"
    assert proposed["06 LFFender"] == "LFFENDER"


def test_one_spelling_is_one_block_and_reads_as_it_did_before():
    """A sheet whose vehicles all write one walk is one block."""
    rows = walk(
        AUGUST_NUMBERED, vehicle="2026-08-19|Command Grey|1965294"
    ) + walk(
        AUGUST_NUMBERED, vehicle="2026-08-25|Shadow Black|1965350", start=34
    )
    blocks = _spelling_blocks(rows)
    assert len(blocks) == 1
    assert set(
        match_walk(blocks[0], CANONICAL_POINTS).by_spelling()
    ) == set(AUGUST_NUMBERED)


# --------------------------------------------------------------------------
# One click answers every model the spelling is rough on (T96, Part 3)
# --------------------------------------------------------------------------

#: The real August numbered walk with the Tolerance Group the file writes,
#: so the orientation filter (D-88-2) offers each one its own panels. The
#: whole 32 are needed for rule (b) to apply at all.
AUGUST_ORIENTATION = {
    "01HOOD": "Horizontal", "02HOOD": "Horizontal", "03HOOD": "Horizontal",
    "04HOOD": "Horizontal", "05HOOD": "Horizontal", "11ROOF": "Horizontal",
    "27ROOF": "Horizontal",
}


@pytest.mark.ingest
def test_one_click_answers_both_models_of_a_two_model_sheet(
    engineer, cleanup, admin_conn  # noqa: F811
):
    """The dead end the owner's August file walked into.

    That sheet writes the same 32 spellings for `P703 DBL` (Ranger) **and**
    `P703 RAPTOR`, and the rough set is keyed per model (D-94-1). Keeping
    one entry per spelling meant one click answered one model and left the
    other's rows asking with no way to answer them: a second identical call
    recorded the same model again. Measured live on 2026-10-10 --
    `P703 DBL RAPTOR` resolved, `P703 DBL RANGER` could not. Now one pair
    writes one decision per model the spelling is rough on.
    """
    serial = "T96-two-model"
    rows = [
        {
            "Date": "2026-08-14",
            "Plant": "FTM",
            "Model": model_cell,
            "Color": "Ignite Orange",
            "Checkzone": label,
            "Tolerance Group": orientation,
            "CF": 55.0 + index,
            "Serial No": f"{serial}-{model_cell}",
        }
        for model_cell in ("P703 DBL", "P703 RAPTOR")
        for index, (label, orientation) in enumerate(
            (name, AUGUST_ORIENTATION.get(name, "Vertical"))
            for name in AUGUST_NUMBERED
        )
    ]
    [review] = sent(
        engineer, cleanup, admin_conn, "t96-two-model.xlsx",
        book(HEADERS, rows), plant="FTM",
    )
    file_hash = review["batch"]["file_hash"]
    load_id = int(review["batch"]["load_id"])

    def sheet_now() -> dict:
        response = engineer.get(
            f"/api/v1/plants/FTM/workbooks/{file_hash}/worksheet"
        )
        assert response.status_code == 200, response.text
        [sheet] = response.json()["sheets"]
        return sheet

    sheet = sheet_now()
    asked = sheet["rough_panels"]
    models = {panel["model_code"] for panel in asked}
    assert models == {"P703 DBL RANGER", "P703 DBL RAPTOR"}, models
    # Every spelling is asked about once per model, and the four of T96 are
    # among them although FTM carries a live panel spelled like each.
    spellings = {panel["raw_zone_text"] for panel in asked}
    assert set(AUGUST_FOUR) <= spellings, spellings
    assert len(asked) == 2 * len(spellings)

    pairs = {}
    for panel in asked:
        if panel["proposed_zone_code"]:
            pairs.setdefault(panel["raw_zone_text"], panel["proposed_zone_code"])
    assert pairs, "nothing to accept; the proposal is the point of Part 2"

    done = engineer.post(
        f"/api/v1/plants/FTM/workbooks/{file_hash}/panel-confirm",
        json={
            "load_id": load_id,
            "pairs": [
                {"raw_zone_text": raw, "zone_code": zone}
                for raw, zone in sorted(pairs.items())
            ],
            "note": "T96 test: one click, two models",
        },
    )
    assert done.status_code == 200, done.text
    # One decision per (model, spelling), not per spelling.
    assert done.json()["decisions_written"] == 2 * len(pairs)
    wait_for(engineer, load_id)

    after = sheet_now()
    answered = {
        (panel["model_code"], panel["raw_zone_text"]): panel["confirmed_zone_code"]
        for panel in after["rough_panels"]
    }
    for model in ("P703 DBL RANGER", "P703 DBL RAPTOR"):
        for raw, zone in pairs.items():
            assert answered[(model, raw)] == zone, (model, raw)
    assert after["rows_need_confirmation"] == 0, [
        row for row in after["rows"] if row["outcome"] == "needs_confirmation"
    ]


def test_measurement_history_accepts_a_reading_with_no_doi():
    """The latent 500 T96 surfaced on the owner's own August file.

    `wavescan` allows a null measure and the August truncated block uses
    it: 320 of its 870 readings carry no DoI. `HistoryPointOut` required
    all ten, so one such reading made that whole vehicle's Measurement
    History a 500 (`decimal_type`, input None) -- and before T96 those rows
    never loaded, so nothing had read them. The screen already renders
    "Not recorded" for a null.
    """
    row = {
        "measurement_id": 1,
        "load_id": 2,
        "source_sheet": "PasteData",
        "source_row": 362,
        "source_file": "08 Aug2026 CF data FTM.xlsx",
        "checkzone": "RRHOOD",
        "panel_label": "RRHOOD",
        "src_zone_text": "01HOOD",
        "measured_date": date(2026, 8, 19),
        "model": "P703 DBL RAPTOR",
        "color": "Arctic White",
        "serial_no": "1965595",
        "tolerance_group": "Horizontal",
        "paintline": None,
        "lw": "6.1", "sw": "12.2", "cf": "61",
        "doi": None,
        "du": None, "wa": "22.3", "wb": None, "wc": None, "wd": None,
        "we": "10", "b": None,
        "loaded_at": datetime(2026, 10, 10, 11, 0, tzinfo=timezone.utc),
    }
    point = HistoryPointOut(**row)
    assert point.doi is None
    assert point.panel_label == "RRHOOD"
    assert point.src_zone_text == "01HOOD"
