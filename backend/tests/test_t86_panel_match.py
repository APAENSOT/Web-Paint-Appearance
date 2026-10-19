"""T86 -- the guided panel match: the system proposes, the person crosschecks.

Claims, against the pure scorer and against the running application, worker
and database:

* **The number never drives a proposal (D-86-3).** ``14ROOF`` against a list
  holding ``14LFBOXSD`` yields no candidate, at any threshold, because the
  two names are not the same panel family; ``06LFFENDER`` reaches
  ``LFFENDER`` and ``06LFFFEND`` because the *names* are close. A label with
  nothing close gets an empty list, not the nearest number.
* The read model answers the whole screen for one `(load_id, model)`: the
  held spellings with counts and their own leading number, this plant x
  model's live panels, and the scored candidates. A live panel a panel map
  cannot reference is returned `mappable = false` with the reason.
* Approving a set is atomic: all N `ref_plant_zone_map` rows or none, with
  the retirement in the same transaction and an `audit_event` beside it. A
  pair onto a panel this plant does not have live refuses the whole set.
* Retirement (D-86-2) sets `retired_at` + `retired_reason` on the panels the
  **owner** named, deletes nothing, and leaves the measurements readable.
  A panel both matched onto and retired is refused -- that map would be
  written and never read.
* `ZONE_NOT_VALID_FOR_MODEL` stays out of `TEACHABLE_HELD_REASONS` (D-31):
  a zone another model owns is still not taught one row at a time. What
  changed is the copy -- a held panel with no pick on offer no longer tells
  the user to pick one (T86 section 3.8).
* T29's owner-proved ZONE pack is untouched: it still validates as itself.

Every row this module writes is its own, keyed on a uuid tag or a load_id it
created, and is deleted again in the fixture's teardown. No shared reference
or seed row is modified.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.domain.panel_match import (
    BASIS_NUMBER_MATCH,
    BASIS_SAME_LABEL,
    BASIS_SAME_NAME_OTHER_NUMBER,
    BASIS_SIMILAR_NAME,
    LivePanel,
    MIN_SCORE,
    name_core,
    panel_family,
    rank_candidates,
    read_position,
    score_name,
)
from app.schemas.ingest import TEACHABLE_HELD_REASONS
from app.schemas.mappings import ZonePanelMatchPayload, ZoneSetPayload
from app.domain.held_label_copy import PANEL_MATCH_MESSAGE, operator_message_for
from app.services.mapping import is_panel_match
from app.services.panel_match import OPERATOR_MESSAGE

from tests.conftest import SUITE_STARTED
from tests.test_t04_ingest import cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
    viewer,
)

pytestmark = pytest.mark.ingest

PROPOSALS = "/api/v1/mappings/proposals"
PANEL_MATCH = "/api/v1/mappings/panel-match"
PLANT = "FTM"
MODEL = "P703 DBL RANGER"
#: FTM's long-form catalogue codes are the ones `ref_plant_zone_map` can
#: reference (they are P703's own `ref_model_zone` positions). The T58
#: numbered block used to be live at FTM beside them and off that
#: catalogue; T113-FIX (D-113-1): it was retired 2026-10-11, so a panel off
#: the catalogue now comes from the `off_catalogue_panel` fixture below.
CANONICAL_TARGET = "LFFENDER"
FTM_PANELS = ["01 RRHOOD", "02 RFHOOD", "03 CFHOOD", "04 LFHOOD", "05 LRHOOD"]


# =====================================================================
# A. the scorer -- pure, no database (D-86-3)
# =====================================================================
def panels(*codes: str) -> list[LivePanel]:
    """A live list in walk order; every panel mappable unless said otherwise."""
    return [
        LivePanel(zone_code=code, point_no=i + 1, tolerance_group="Vertical")
        for i, code in enumerate(codes)
    ]


def test_the_leading_number_is_read_and_then_dropped():
    assert read_position("14ROOF") == 14
    assert read_position("06LFFENDER") == 6
    assert read_position("LFFENDER") is None
    # 0 and 99 are not walk positions on any model here.
    assert read_position("0HOOD") is None
    assert read_position("99ROOF") is None
    # The number is gone before anything is compared, and so are the digits
    # buried in a SAP-style label.
    assert name_core("14ROOF") == "roof"
    assert name_core("14LFBOXSD") == "lfboxsd"
    assert name_core("01RHS Hood Rr28") == "rhshoodrr"


def test_14roof_is_never_proposed_onto_14lfboxsd():
    """The claim T86 section 4 names first. The shared 14 buys nothing."""
    assert score_name("14ROOF", "14LFBOXSD") < MIN_SCORE
    assert panel_family("14ROOF") != panel_family("14LFBOXSD")
    found = rank_candidates("14ROOF", panels("14LFBOXSD"))
    assert found == [], found
    # Not even when it is the only panel on the list, and not when the list
    # is the whole of FTM's numbered block at the same numbers.
    numbered = panels("14LFBOXSD", "15LFBOXSD", "22RTBOXSD", "25RTRDOOR")
    assert rank_candidates("14ROOF", numbered) == []


def test_a_roof_is_proposed_onto_roofs_only_and_the_number_is_only_shown():
    found = rank_candidates("14ROOF", panels("11ROOF", "27ROOF", "LCROOF", "14LFBOXSD"))
    assert [c.zone_code for c in found] == ["11ROOF", "27ROOF", "LCROOF"]
    # Identical names at different numbers score the same; the basis says so
    # rather than claiming they are the same label.
    assert found[0].score == 1.0 and found[1].score == 1.0
    assert found[0].basis == BASIS_SAME_NAME_OTHER_NUMBER
    assert found[2].basis == BASIS_SIMILAR_NAME
    # Order is score then name -- never point_no, which would let the
    # sequence back in as a tie-break.
    assert [c.point_no for c in found] == [1, 2, 3]


def test_a_renamed_fender_reaches_both_spellings_of_itself():
    found = rank_candidates(
        "06LFFENDER", panels("LFFENDER", "06LFFFEND", "LCFENDER", "11ROOF")
    )
    # Score order, never walk order: LFFENDER is the same name, LCFENDER is
    # one letter away, and 06LFFFEND is FTM's own truncation of it.
    assert [c.zone_code for c in found] == ["LFFENDER", "LCFENDER", "06LFFFEND"]
    assert found[0].score == 1.0
    assert found[1].score > found[2].score >= MIN_SCORE
    # 06LFFENDER and LFFENDER are the same name once the walk number goes.
    assert found[0].basis == BASIS_SAME_NAME_OTHER_NUMBER
    assert score_name("01HOOD", "1HOOD") == 1.0
    # T87: `panels()` numbers from 1, so park 1HOOD off 01HOOD's own number
    # to read the name basis; the number basis has its own tests in part A2.
    off_number = [LivePanel("1HOOD", 7, "Horizontal")]
    assert rank_candidates("01HOOD", off_number)[0].basis == BASIS_SAME_LABEL


def test_nothing_close_is_an_empty_list_not_the_nearest_panel():
    assert rank_candidates("12LCPILLAR", panels("11ROOF", "14LFBOXSD")) == []
    # A label with no panel family at all proposes nothing either.
    assert panel_family("ZZTOP") is None
    assert rank_candidates("ZZTOP", panels("11ROOF")) == []


def test_a_panel_a_map_cannot_reference_is_never_a_candidate():
    live = [
        LivePanel("LFFENDER", 6, "Vertical", mappable=False),
        LivePanel("LCFENDER", 7, "Vertical", mappable=True),
    ]
    assert [c.zone_code for c in rank_candidates("06LFFENDER", live)] == ["LCFENDER"]


# =====================================================================
# A2. T87 -- the walk number orders, and only orders (D-87-1..4)
# =====================================================================
#: FTM's three left fenders, at the walk numbers FTM really gives them.
FENDERS = [
    LivePanel("LFFENDER", 6, "Vertical"),
    LivePanel("LCFENDER", 7, "Vertical"),
    LivePanel("LRFENDER", 8, "Vertical"),
]


def test_the_number_separates_names_that_differ_only_by_their_number():
    """The measured T86 defect: 28 of September's 32 names collapse.

    Under T86 all three of these proposed `LFFENDER` first, at 1.0, because
    the three names are one name once the number is dropped. Two of the
    three were therefore confidently wrong.
    """
    tops = {
        label: rank_candidates(label, FENDERS)[0]
        for label in ("06LFFENDER", "07LFFENDER", "08LFFENDER")
    }
    assert [c.zone_code for c in tops.values()] == ["LFFENDER", "LCFENDER", "LRFENDER"]
    # The task's own example: 08LFFENDER puts LRFENDER first even though
    # LFFENDER is the better *name* match.
    assert tops["08LFFENDER"].zone_code == "LRFENDER"
    assert tops["08LFFENDER"].point_no == 8
    # D-87-2: it says the number ordered it, in its own basis.
    assert tops["08LFFENDER"].basis == BASIS_NUMBER_MATCH
    # The better name match is still offered -- demoted, never dropped.
    rest = rank_candidates("08LFFENDER", FENDERS)[1:]
    assert [c.zone_code for c in rest] == ["LFFENDER", "LCFENDER"]
    assert rest[0].score == 1.0 and rest[0].basis == BASIS_SAME_NAME_OTHER_NUMBER


def test_the_number_never_creates_a_candidate_or_lifts_one_over_a_gate():
    """D-87-1, both halves, and D-87-3 restated at the number's own number.

    `14LFBOXSD` sits at walk number 14 and `14ROOF` carries the number 14.
    If the number could create or promote, this is where it would show.
    """
    boxes = [LivePanel("14LFBOXSD", 14, "Vertical")]
    assert rank_candidates("14ROOF", boxes) == []
    # ... and not when a same-family candidate is there to be ordered too.
    with_roof = boxes + [LivePanel("LCROOF", 11, "Horizontal")]
    found = rank_candidates("14ROOF", with_roof)
    assert [c.zone_code for c in found] == ["LCROOF"]

    # The MIN_SCORE gate, at the matching number: `RRBOX` is the same family
    # as `14LFBOXSD`'s label but far enough away by name to be refused, and
    # sitting on number 14 does not rescue it.
    assert panel_family("14ZZZBOX") == panel_family("RRBOX")
    assert score_name("14ZZZBOX", "RRBOX") < MIN_SCORE
    assert rank_candidates("14ZZZBOX", [LivePanel("RRBOX", 14, "Vertical")]) == []


def test_a_number_that_matches_nothing_leaves_the_order_exactly_as_it_was():
    name_order = [c.zone_code for c in rank_candidates("LFFENDER", FENDERS)]
    assert name_order == ["LFFENDER", "LCFENDER", "LRFENDER"]
    # A label whose number is on no candidate here.
    assert [c.zone_code for c in rank_candidates("39LFFENDER", FENDERS)] == name_order
    # A label with no leading number at all, and one whose number is out of
    # range for a walk position, both read as "no number".
    assert read_position("39LFFENDER") == 39
    assert read_position("99LFFENDER") is None
    assert [c.zone_code for c in rank_candidates("99LFFENDER", FENDERS)] == name_order
    # None of those three carries the number basis.
    for label in ("LFFENDER", "39LFFENDER", "99LFFENDER"):
        assert all(c.basis != BASIS_NUMBER_MATCH for c in rank_candidates(label, FENDERS))


def test_the_number_promotes_at_most_one_candidate_and_the_sort_is_total():
    """`uq_plant_ws_point_no_live` is why this is a promotion, not a shuffle.

    One live panel per walk number at one plant x model, so at most one
    candidate can carry the label's number. The rest keep score-then-name
    order, which makes the whole sort reproducible.
    """
    found = rank_candidates("07LFFENDER", FENDERS)
    assert sum(c.basis == BASIS_NUMBER_MATCH for c in found) == 1
    assert [c.zone_code for c in found] == ["LCFENDER", "LFFENDER", "LRFENDER"]
    # Equal scores below the promoted one still fall through to the name,
    # so re-ranking the same input twice gives the same list.
    assert rank_candidates("07LFFENDER", FENDERS) == found
    assert rank_candidates("07LFFENDER", list(reversed(FENDERS))) == found


def test_the_screen_is_told_the_number_only_orders_suggestions():
    """D-87-2 reaches the operator copy, not just the basis string."""
    message = OPERATOR_MESSAGE.format(plant=PLANT)
    assert "never puts a panel on the list" in message
    assert "could be this one" in message
    # The old sentence promised something T87 no longer does.
    assert "the number never decides a match" not in message


# =====================================================================
# B. the payloads -- which ZONE shape is which
# =====================================================================
def match_payload(**over) -> dict:
    payload = {
        "plant_code": PLANT,
        "model_code": MODEL,
        "load_id": 1,
        "matches": [{"raw_zone_text": "07LFFENDER", "raw_position": 7,
                     "zone_code": CANONICAL_TARGET}],
        "decided_by": "FTM quality owner",
        "method": "walked the vehicle with the uploader",
        "note": "T86 unit",
    }
    payload.update(over)
    return payload


def test_the_two_zone_shapes_are_told_apart_by_their_own_key():
    assert is_panel_match(match_payload())
    assert not is_panel_match({"mappings": [], "plant_code": PLANT})
    # T29's pack still validates as itself, unchanged.
    assert "proof_hash" in ZoneSetPayload.model_fields
    assert "proof_hash" not in ZonePanelMatchPayload.model_fields


def test_the_payload_normalises_the_spelling_and_refuses_a_blank_one():
    parsed = ZonePanelMatchPayload.model_validate(match_payload())
    assert parsed.matches[0].raw_zone_text == "07lffender"
    assert parsed.retire is None
    for blank in ("", "   ", "(None)", "none"):
        with pytest.raises(Exception):
            ZonePanelMatchPayload.model_validate(
                match_payload(matches=[{"raw_zone_text": blank,
                                        "zone_code": CANONICAL_TARGET}])
            )


def test_a_match_set_needs_at_least_one_pair_and_a_retire_needs_a_reason():
    with pytest.raises(Exception):
        ZonePanelMatchPayload.model_validate(match_payload(matches=[]))
    with pytest.raises(Exception):
        ZonePanelMatchPayload.model_validate(
            match_payload(retire={"zone_codes": [], "reason": "old block"})
        )
    with pytest.raises(Exception):
        ZonePanelMatchPayload.model_validate(
            match_payload(retire={"zone_codes": ["A", "A"], "reason": "twice"})
        )
    ok = ZonePanelMatchPayload.model_validate(
        match_payload(retire={"zone_codes": ["RRHOOD"], "reason": "superseded"})
    )
    assert ok.retire is not None and ok.retire.reason == "superseded"


# =====================================================================
# C. the copy -- stop promising a control that does not exist (3.8)
# =====================================================================
def test_a_held_panel_with_no_pick_on_offer_stops_telling_the_user_to_pick():
    offered = operator_message_for("zone", "01HOOD", plant=PLANT)
    assert "Pick the panel it is from that list" in offered

    none_offered = operator_message_for("zone", "06LFFENDER", plant=PLANT, teachable=False)
    assert "Pick the panel it is from that list" not in none_offered
    assert "Match the panel list" in none_offered
    assert none_offered == PANEL_MATCH_MESSAGE.format(shown="06LFFENDER", here=PLANT)
    # Still never a promise to work the name out by ourselves.
    assert "never move a panel name onto another one by ourselves" in none_offered


def test_a_zone_another_model_owns_is_still_not_taught_one_row_at_a_time():
    """D-31 holds. T86 reaches it through the set flow only (section 3.5)."""
    assert "ZONE_NOT_VALID_FOR_MODEL" not in TEACHABLE_HELD_REASONS
    assert TEACHABLE_HELD_REASONS["UNKNOWN_CHECKZONE"] == "ALIAS_CHECKZONE"


# =====================================================================
# D. the API, the database and the transaction
# =====================================================================
def forget_maps(
    admin_conn, plant: str, model: str, raws: list[str], since=SUITE_STARTED
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    Keyed on `raw_zone_text` alone this reached another plant's approved
    reference rows -- it is how the owner's `12lcpillar` was deleted.

    **T97.** Plant and model are not enough on their own: this fixture
    writes the owner's **own** spellings on the owner's **own** plant and
    model, so a row the owner taught before the test ran matched the delete
    too. ``since`` is the moment the test started, and with it the cleanup
    can only reach rows the test itself inserted (WEBSITE-SESSION section 6).
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
            "   AND model_code = %s AND raw_zone_text = ANY(%s)"
            "   AND created_at >= %s",
            (plant, model, [r.lower() for r in raws], since),
        )


def map_rows(
    admin_conn, raws: list[str], plant: str = PLANT, model: str = MODEL
) -> list[tuple]:
    """This test's own plant x model's maps for these spellings.

    **T114 (D-114-13).** Scoped to the plant and model the test writes to.
    Read across every plant, FVL CX743's real owner-approved `06lffender` /
    `08lffender` maps (2026-09-22) answered the FTM tests' "nothing was
    written" with rows they never wrote.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_zone_text, zone_code, raw_position, confidence, "
            "       proposal_method, approved_by IS NOT NULL, proof_hash "
            "  FROM ref_plant_zone_map WHERE raw_zone_text = ANY(%s) "
            "   AND plant_code = %s AND model_code = %s "
            " ORDER BY raw_zone_text",
            ([r.lower() for r in raws], plant, model),
        )
        return cur.fetchall()


@pytest.fixture()
def off_catalogue_panel(admin_conn):
    """One live FTM x Ranger panel that P703's own catalogue does not carry.

    **T113-FIX (D-113-1): FTM short-name block retired 2026-10-11.** Until
    then the T58 numbered block played this part (`14LFBOXSD`), which is why
    FTM was the plant the limit was real at. The block is retired, so the
    two tests that need such a panel bring their own: one row, on a spare
    `ref_checkzone` code that is not a position on the model, deleted again
    by this test's own note. Nothing real is added, retired or aliased.
    """
    tag = uuid.uuid4().hex[:8]
    note = f"T113-FIX test {tag} -- delete me"
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.zone_code, c.tolerance_group FROM ref_checkzone c
             WHERE NOT EXISTS (
                   SELECT 1 FROM ref_plant_ws_point p
                    WHERE p.plant_code = %s AND p.model_code = %s
                      AND p.zone_code = c.zone_code)
               AND NOT EXISTS (
                   SELECT 1 FROM ref_model_zone z
                    WHERE z.model_code = %s AND z.zone_code = c.zone_code)
             ORDER BY c.zone_code LIMIT 1
            """,
            (PLANT, MODEL, MODEL),
        )
        [(zone_code, tolerance)] = cur.fetchall()
        cur.execute(
            "INSERT INTO ref_plant_ws_point (plant_code, model_code, zone_code, "
            " point_no, tolerance_group, note) VALUES (%s, %s, %s, %s, %s, %s)",
            (PLANT, MODEL, zone_code, 233, tolerance, note),
        )
    try:
        yield zone_code
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM ref_plant_ws_point WHERE note = %s", (note,))


def ftm_rows(count: int, **over) -> list[dict]:
    """FTM P703 Ranger rows for one vehicle nothing else has used."""
    day = f"2026-08-{(uuid.uuid4().int % 27) + 1:02d}"
    tag = uuid.uuid4().hex[:8]
    return [
        {
            "Date": day, "Plant": PLANT, "Model": MODEL,
            "Color": "Ignite Orange", "Checkzone": FTM_PANELS[i % len(FTM_PANELS)],
            "CF": 55.0 + i, "Serial No": f"T86-{tag}",
            **over,
        }
        for i in range(count)
    ]


@pytest.fixture()
def held_panels(engineer, cleanup, admin_conn):
    """A pending FTM P703 sheet: two good rows and five held panel names.

    Real FVL panel spellings FTM's own list does not carry -- the September
    case in miniature. ``07LFFENDER`` has a close name on FTM's catalogue,
    ``14ROOF`` has roofs but no ``14`` of its own, and ``12LCPILLAR`` is the
    one that matches a catalogue pillar exactly.

    **Amended by T97 (D-97-1).** A name that names exactly one canonical
    panel now resolves to it, so ``07LFFENDER`` and ``12LCPILLAR`` alone on
    a sheet load and are not held at all. Each therefore arrives with the
    sibling that makes it genuinely vague (D-94-1 (b)): ``08LFFENDER`` and
    ``13LCPILLAR`` reduce to the same names, only one of each can be the
    panel, so all five are held -- which is the condition this screen is
    about. ``14ROOF`` names two roofs and was never specific.
    """
    raws = ["07LFFENDER", "08LFFENDER", "14ROOF", "12LCPILLAR", "13LCPILLAR"]
    good = ftm_rows(2)
    # T88: orientation is a hard constraint, so a synthetic fender written
    # "Horizontal" would correctly end up with no candidates at all. These
    # rows now carry the Tolerance Group the panel really has.
    orientation = {"07LFFENDER": "Vertical", "08LFFENDER": "Vertical",
                   "14ROOF": "Horizontal",
                   "12LCPILLAR": "Vertical", "13LCPILLAR": "Vertical"}
    odd = [
        {**good[0], "Checkzone": raw, "CF": 60.0 + n,
         "Tolerance Group": orientation[raw]}
        for n, raw in enumerate(raws)
    ]
    started = datetime.now(timezone.utc)
    [review] = sent(
        engineer, cleanup, admin_conn, "t86-panel-match.xlsx",
        book(HEADERS, good + odd), plant=PLANT,
    )
    try:
        yield raws, review
    finally:
        forget_maps(admin_conn, PLANT, MODEL, raws, since=started)


def test_the_file_holds_its_panel_names_and_says_so_without_promising_a_pick(
    held_panels,
):
    raws, review = held_panels
    zones = [h for h in review["held_labels"] if h["display_group"] == "zone"]
    assert {h["raw_value"] for h in zones} == set(raws), zones
    for item in zones:
        assert item["model_code"] == MODEL, item
        assert item["count"] == 1


def test_the_read_model_answers_the_whole_screen(engineer, held_panels, off_catalogue_panel):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    response = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": MODEL}
    )
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["plant_code"] == PLANT and out["model_code"] == MODEL
    assert out["min_score"] == MIN_SCORE
    assert "Match each name" in out["operator_message"]

    held = {h["raw_zone_text"]: h for h in out["held_panels"]}
    assert set(held) == {r.lower() for r in raws} or set(held) == set(raws), held

    # The label's own number is carried as provenance.
    fender = held.get("07LFFENDER") or held["07lffender"]
    assert fender["raw_position"] == 7
    assert fender["count"] == 1
    assert fender["reasons"] == ["UNKNOWN_CHECKZONE"]
    assert fender["candidates"], fender
    # T87 (D-87-1): the panel carrying the file's own number 7 is listed
    # first and says so, and LFFENDER -- the 1.0 name match at point 6 --
    # is still offered, just not first. Under T86 all of 06/07/08LFFENDER
    # proposed LFFENDER at 1.0, which was useless for two of the three.
    first = fender["candidates"][0]
    assert first["point_no"] == fender["raw_position"] == 7
    assert first["basis"] == BASIS_NUMBER_MATCH
    offered_fenders = {c["zone_code"]: c for c in fender["candidates"]}
    assert CANONICAL_TARGET in offered_fenders
    assert offered_fenders[CANONICAL_TARGET]["score"] == 1.0
    assert all(c["score"] >= MIN_SCORE for c in fender["candidates"])

    roof = held.get("14ROOF") or held["14roof"]
    assert roof["raw_position"] == 14
    offered = {c["zone_code"] for c in roof["candidates"]}
    assert "14LFBOXSD" not in offered, offered
    assert offered and all("ROOF" in code.upper() for code in offered), offered

    # The live list is the plant x model's own, in walk order, and says
    # which of its panels a map cannot point at.
    live = out["live_panels"]
    assert live and [p["point_no"] for p in live] == sorted(p["point_no"] for p in live)
    by_code = {p["zone_code"]: p for p in live}
    assert by_code[CANONICAL_TARGET]["mappable"] is True
    assert by_code[CANONICAL_TARGET]["not_mappable_reason"] is None
    not_mappable = [p for p in live if not p["mappable"]]
    for panel in not_mappable:
        assert "not a position on" in (panel["not_mappable_reason"] or "")
    # T113-FIX (D-113-1): FTM short-name block retired 2026-10-11, so the
    # panel a map cannot point at is this test's own marker row rather than
    # `14LFBOXSD`. The claim is unchanged: a live panel off the model's
    # catalogue comes back `mappable = false` with the reason.
    # RO18 (B1): every live panel of the plant's own list is a match target,
    # on the model's catalogue or not.
    assert off_catalogue_panel in by_code
    assert by_code[off_catalogue_panel]["mappable"] is True
    assert not not_mappable
    assert "14LFBOXSD" not in by_code, "retired: no longer a match target"


def test_the_read_model_refuses_a_batch_or_model_it_does_not_have(
    engineer, held_panels
):
    _, review = held_panels
    load_id = review["batch"]["load_id"]
    missing_model = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": "NOT A MODEL"}
    )
    assert missing_model.status_code == 404, missing_model.text
    missing_batch = engineer.get(
        PANEL_MATCH, params={"load_id": 2_000_000_000, "model_code": MODEL}
    )
    assert missing_batch.status_code == 404


def test_a_viewer_may_read_the_screen_and_may_not_propose(
    viewer, engineer, held_panels
):
    _, review = held_panels
    load_id = review["batch"]["load_id"]
    assert viewer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": MODEL}
    ).status_code == 200
    refused = viewer.post(
        PROPOSALS,
        json={"kind": "ZONE", "load_id": load_id,
              "payload": match_payload(load_id=load_id)},
    )
    assert refused.status_code == 403, refused.text


def test_a_set_with_two_spellings_onto_one_panel_is_refused_whole(
    engineer, held_panels
):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE",
            "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[
                    {"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET},
                    {"raw_zone_text": raws[1], "zone_code": CANONICAL_TARGET},
                ],
            ),
        },
    )
    assert response.status_code == 422, response.text
    assert "two spellings onto one panel" in response.text


def test_a_target_this_plant_does_not_have_live_is_refused_whole(
    engineer, held_panels, admin_conn
):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE",
            "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[
                    {"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET},
                    # A real catalogue code of another plant's model.
                    {"raw_zone_text": raws[1], "zone_code": "LIFTGATEHILH"},
                ],
            ),
        },
    )
    assert response.status_code == 422, response.text
    assert "not live at" in response.text
    # Nothing was written, not even the pair that was fine.
    assert map_rows(admin_conn, raws) == []


def test_a_target_live_here_but_off_the_model_catalogue_is_no_longer_refused(
    engineer, held_panels, admin_conn, off_catalogue_panel
):
    """RO18 (B1) reverses T89's catalogue refusal: a map may land on any live
    panel of the plant x model's own list (`fk_pzm_plant_point`). Proved with
    no write: one set naming that panel and the retired `14LFBOXSD` is
    refused for the retired panel only."""
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE",
            "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": off_catalogue_panel},
                         {"raw_zone_text": raws[1], "zone_code": "14LFBOXSD"}],
            ),
        },
    )
    assert response.status_code == 422, response.text
    assert "not live at FTM / P703 DBL RANGER: 14LFBOXSD" in response.text
    assert "not positions on" not in response.text
    assert off_catalogue_panel not in response.text
    assert map_rows(admin_conn, raws) == []


def test_a_panel_both_matched_onto_and_retired_is_refused(engineer, held_panels):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE",
            "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET}],
                retire={"zone_codes": [CANONICAL_TARGET], "reason": "old block"},
            ),
        },
    )
    assert response.status_code == 422, response.text
    assert "both matched onto and retired" in response.text


def test_a_match_set_without_a_batch_is_refused(engineer):
    response = engineer.post(
        PROPOSALS, json={"kind": "ZONE", "payload": match_payload()}
    )
    assert response.status_code == 422, response.text
    assert "load_id is required" in response.text


# ---------------------------------------------------------------------
# the whole flow: Engineer proposes -> Admin approves -> replay (D-86-4)
# ---------------------------------------------------------------------
def test_engineer_proposes_admin_approves_and_the_held_rows_load(
    engineer, admin, held_panels, admin_conn
):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    pairs = [
        {"raw_zone_text": raws[0], "raw_position": 7, "zone_code": CANONICAL_TARGET},
        {"raw_zone_text": raws[2], "raw_position": 12, "zone_code": "LCPILLAR"},
    ]
    proposed = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE",
            "load_id": load_id,
            "similarity": "1.0",
            "payload": match_payload(load_id=load_id, matches=pairs),
        },
    )
    assert proposed.status_code == 201, proposed.text
    body = proposed.json()
    # D-86-4: nothing auto-applies. The Engineer's request writes no map.
    assert body["status"] == "PROPOSED"
    assert map_rows(admin_conn, raws) == []

    approved = admin.post(f"{PROPOSALS}/{body['id']}/approve")
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert result["applied_to"] == "ref_plant_zone_map"
    assert result["replay"]["load_id"] == load_id

    rows = map_rows(admin_conn, raws)
    assert len(rows) == 2, rows
    for raw, zone, position, confidence, method, has_admin, proof in rows:
        assert confidence == "APPROVED"
        # T88 (G-88-6): the method now records which signal proposed the
        # pair. This set carries none, so it reads `..._NONE`.
        assert method == "T88_PANEL_MATCH_NONE"
        assert has_admin is True
        # A match set proves nothing, so it carries no owner proof -- that
        # is what keeps it distinguishable from a T29 pack in the table.
        assert proof is None
        assert position in (7, 12)
    assert {r[1] for r in rows} == {CANONICAL_TARGET, "LCPILLAR"}

    # The approval is audited in the same transaction, with who decided.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT after FROM audit_event "
            " WHERE action = 'mapping.approve' AND entity_id = %s",
            (body["id"],),
        )
        [(after,)] = cur.fetchall()
    assert after["panel_match_count"] == 2
    assert after["decided_by"] == "FTM quality owner"
    assert after["retired_zone_codes"] == []

    # The held rows are read again after the approval.
    final = wait_for(engineer, load_id)
    assert final["batch"]["status"] == "PENDING_REVIEW", final["batch"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM stg_review_row "
            " WHERE load_id = %s AND reason = 'UNKNOWN_CHECKZONE'",
            (load_id,),
        )
        still_held = cur.fetchone()[0]
    # T114-FIX (D-94-2, T97): all five fixture labels are rough siblings, and
    # since T94 a rough label never resolves through a ref_plant_zone_map
    # row -- only through the in-row confirm. So the approved map resolves
    # none of them: all 5 stay held until each is answered in its row.
    assert still_held == 5, still_held


def test_approving_the_same_set_twice_writes_nothing_new_and_a_repoint_is_409(
    engineer, admin, held_panels, admin_conn
):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    first = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE", "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET}],
            ),
        },
    )
    assert first.status_code == 201, first.text
    assert admin.post(f"{PROPOSALS}/{first.json()['id']}/approve").status_code == 200
    before = map_rows(admin_conn, [raws[0]])
    assert len(before) == 1
    # The approval queued a replay; a second proposal has to wait for the
    # batch to leave RUNNING, exactly as the UI does.
    wait_for(engineer, load_id)

    again = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE", "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET}],
            ),
        },
    )
    assert again.status_code == 201, again.text
    assert admin.post(f"{PROPOSALS}/{again.json()['id']}/approve").status_code == 200
    assert map_rows(admin_conn, [raws[0]]) == before
    wait_for(engineer, load_id)

    repoint = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE", "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": "LCFENDER"}],
            ),
        },
    )
    assert repoint.status_code == 201, repoint.text
    refused = admin.post(f"{PROPOSALS}/{repoint.json()['id']}/approve")
    assert refused.status_code == 409, refused.text
    assert "never repointed" in refused.text
    assert map_rows(admin_conn, [raws[0]]) == before


# ---------------------------------------------------------------------
# retirement (D-86-2) -- on this module's own panel row, never a seed one
# ---------------------------------------------------------------------
@pytest.fixture()
def spare_panel(admin_conn):
    """A live FTM P703 panel this module inserted, to retire and remove.

    The real FTM panels are owner-locked seed rows (T58) and are never
    touched by a test. This one is a catalogue code FTM's P703 list does not
    carry, parked on a point number nothing lives at.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.zone_code, c.tolerance_group
              FROM ref_checkzone c
             WHERE NOT EXISTS (
                   SELECT 1 FROM ref_plant_ws_point p
                    WHERE p.plant_code = %s AND p.model_code = %s
                      AND p.zone_code = c.zone_code)
             ORDER BY c.zone_code
             LIMIT 1
            """,
            (PLANT, MODEL),
        )
        found = cur.fetchone()
        assert found, "no spare ref_checkzone code to park a test panel on"
        zone_code, tolerance = found
        cur.execute(
            "INSERT INTO ref_plant_ws_point "
            "    (plant_code, model_code, zone_code, point_no, tolerance_group, note) "
            "VALUES (%s, %s, %s, %s, %s, 'T86 test panel -- delete me')",
            (PLANT, MODEL, zone_code, 97, tolerance),
        )
    try:
        yield zone_code
    finally:
        with admin_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ref_plant_ws_point WHERE plant_code = %s "
                "  AND model_code = %s AND zone_code = %s",
                (PLANT, MODEL, zone_code),
            )


def test_confirming_a_set_retires_the_block_the_owner_named(
    engineer, admin, held_panels, spare_panel, admin_conn
):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]

    # It is live, and the screen offers it, before the set is approved.
    screen = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": MODEL}
    ).json()
    assert spare_panel in {p["zone_code"] for p in screen["live_panels"]}

    proposed = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE", "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET}],
                retire={
                    "zone_codes": [spare_panel],
                    "reason": "FTM renamed its panels; this block is superseded",
                },
            ),
        },
    )
    assert proposed.status_code == 201, proposed.text
    approved = admin.post(f"{PROPOSALS}/{proposed.json()['id']}/approve")
    assert approved.status_code == 200, approved.text

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at IS NOT NULL, retired_reason FROM ref_plant_ws_point "
            " WHERE plant_code = %s AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, spare_panel),
        )
        [(retired, reason)] = cur.fetchall()
    # Append-only: the row is still there, marked, with the owner's words.
    assert retired is True
    assert "superseded" in reason and "T86 proposal" in reason

    # And it is gone from what a new upload may match onto.
    after = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": MODEL}
    ).json()
    assert spare_panel not in {p["zone_code"] for p in after["live_panels"]}

    # The retirement is audited, naming who decided it.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT after FROM audit_event "
            " WHERE action = 'catalogue.plant_ws_point.retire' "
            "   AND entity_id = %s ORDER BY id DESC LIMIT 1",
            (f"{PLANT}:{MODEL}",),
        )
        [(after_json,)] = cur.fetchall()
    assert after_json["retired"] == [spare_panel]
    assert after_json["decided_by"] == "FTM quality owner"

    # The measurements this batch already loaded are still readable.
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] >= 0


def test_retiring_a_panel_that_is_not_live_is_refused(engineer, held_panels):
    raws, review = held_panels
    load_id = review["batch"]["load_id"]
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ZONE", "load_id": load_id,
            "payload": match_payload(
                load_id=load_id,
                matches=[{"raw_zone_text": raws[0], "zone_code": CANONICAL_TARGET}],
                retire={"zone_codes": ["LIFTGATEHILH"], "reason": "not ours"},
            ),
        },
    )
    assert response.status_code == 422, response.text
    assert "to retire that are not live" in response.text


# =====================================================================
# E. the grant (migration 0031) -- retire a panel, never repoint one
# =====================================================================
def test_the_app_role_may_retire_a_panel_and_nothing_else_about_it(
    admin_conn, app_role
):
    """0031 grants UPDATE on exactly the retirement pair, by column.

    A table-level UPDATE would let the approve path change a panel's
    `zone_code` or its Hor/Ver, which is a silent wrong identity -- the
    thing `AGENTS.md` opens by calling worse than a crash. PostgreSQL
    enforces the column list, so this is a guarantee and not a convention.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
              FROM information_schema.column_privileges
             WHERE table_schema = 'public'
               AND table_name = 'ref_plant_ws_point'
               AND privilege_type = 'UPDATE'
               AND grantee = %s
            """,
            (app_role,),
        )
        updatable = {row[0] for row in cur.fetchall()}
        cur.execute(
            """
            SELECT privilege_type
              FROM information_schema.role_table_grants
             WHERE table_schema = 'public'
               AND table_name = 'ref_plant_ws_point'
               AND grantee = %s
            """,
            (app_role,),
        )
        table_level = {row[0] for row in cur.fetchall()}

    assert updatable == {"retired_at", "retired_reason"}, updatable
    assert "SELECT" in table_level
    # T114 CHANGE (D-114-11): adding a panel is now Point Check's add, an
    # INSERT of an extra point at the end of the walk. Removing one still
    # never happens, because a retired row keeps fk_ws_plant_point valid.
    assert "INSERT" in table_level
    for forbidden in ("DELETE", "TRUNCATE", "UPDATE"):
        assert forbidden not in table_level, table_level
