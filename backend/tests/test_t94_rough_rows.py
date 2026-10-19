"""T94 -- against the running application and database.

Parts 2, 3 and 4, and the one claim the task turns on:

* **D-94-2**, the claim the owner's screenshot was about: a rough label is
  never ``ready``, *including when the catalogue holds a panel spelled
  exactly like it*. FTM carries a live panel literally called ``01HOOD``
  (the T58 numbered block), and this sheet's ``01HOOD`` still does not load.
  That is why retirement is not needed as the mechanism;
* **D-94-3**: the worksheet read carries the question beside the row --
  outcome ``needs_confirmation``, the proposed long name, its colour, its
  reason and the whole choosable list -- so the table can draw it in the
  row. A specific label on the same sheet is not asked about at all;
* **D-94-6**: nothing auto-applies, and the whole pre-filled set is accepted
  in one call;
* **D-94-4**: after that one call, ``wavescan.checkzone`` is the long name,
  ``src_zone_text`` is the file's own spelling, and Measurement History
  shows the long name.

Every batch and decision is this module's own and is removed again. No
``ref_*`` row is written, read-only or otherwise -- T94 writes none, and a
test that proved it by writing one would be proving the opposite. The
owner's trial batches are never touched and no standard is ever published.
"""

from __future__ import annotations

import pytest

from tests.test_t04_ingest import cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
)

pytestmark = pytest.mark.ingest

PLANT = "FTM"
MODEL_CELL = "P703 DBL"
MODEL = "P703 DBL RANGER"
COLOUR = "Ignite Orange"

#: The real September walk of the owner's own FTM file, in order. Used as
#: given: these are the spellings the owner's screenshot shows. Five of them
#: (`01HOOD`..`05HOOD`, `11ROOF`, `17TGATE`..) were *live gold panels* at
#: FTM when T94 was written, which is what made this sheet the D-94-2 test;
#: T113-FIX (D-113-1): that block was retired 2026-10-11 and the rows below
#: are still asked in the row, which is the claim D-94-2 actually makes.
SEPTEMBER = (
    ("01HOOD", "Horizontal"), ("02HOOD", "Horizontal"), ("03HOOD", "Horizontal"),
    ("04HOOD", "Horizontal"), ("05HOOD", "Horizontal"),
    ("06LFFENDER", "Vertical"), ("07LFFENDER", "Vertical"), ("08LFFENDER", "Vertical"),
    ("09LFFTDOOR", "Vertical"), ("10LFFTDOOR", "Vertical"),
    ("11ROOF", "Horizontal"),
    ("12LCPILLAR", "Vertical"), ("13LFRDOOR", "Vertical"),
    ("14ROOF", "Horizontal"), ("15RCPILLAR", "Vertical"), ("16RTRDOOR", "Vertical"),
    ("17RTFTDOOR", "Vertical"), ("18RTFTDOOR", "Vertical"),
    ("19RTFENDER", "Vertical"), ("20RTFENDER", "Vertical"), ("21RTFENDER", "Vertical"),
    ("22LFBOXSD", "Vertical"), ("23LFBOXSD", "Vertical"), ("24LFBOXSD", "Vertical"),
    ("25TGATE", "Vertical"), ("26TGATE", "Vertical"), ("27TGATE", "Vertical"),
    ("28TGATE", "Vertical"), ("29TGATE", "Vertical"),
    ("30RTBOXSD", "Vertical"), ("31RTBOXSD", "Vertical"), ("32RTBOXSD", "Vertical"),
)

#: What rule (a) proposes for the four the owner named, used as given
#: (D-90-10 / the T93 repair input, which is the owner's own template).
OWNER_PAIRS = {
    "01HOOD": "RRHOOD",
    "11ROOF": "LCROOF",
    "25TGATE": "LTTAILGATE",
    "06LFFENDER": "LFFENDER",
}

#: The names of this sheet that **do** say which panel they are, so they are
#: never asked about (D-94-1). T96 (D-96-1) took `13LFRDOOR` and
#: `16RTRDOOR` out of this set: both lead with a number and name no
#: canonical panel at all, which is the hole that let August's `25RTRDOOR`
#: load under its own number -- and `13LFRDOOR` is the one the owner
#: confirmed as `LCPILLAR`, by its number and against its name.
SPECIFIC = {"12LCPILLAR", "15RCPILLAR"}
#: What T94 measured here, before D-96-1.
SPECIFIC_BEFORE_T96 = SPECIFIC | {"13LFRDOOR", "16RTRDOOR"}


def sheet_bytes(serial: str) -> bytes:
    return book(
        HEADERS,
        [
            {
                "Date": "2026-09-14",
                "Plant": PLANT,
                "Model": MODEL_CELL,
                "Color": COLOUR,
                "Checkzone": label,
                "Tolerance Group": orientation,
                "CF": 55.0 + index,
                "Serial No": serial,
            }
            for index, (label, orientation) in enumerate(SEPTEMBER)
        ],
    )


def worksheet_of(engineer, file_hash: str) -> dict:  # noqa: F811
    response = engineer.get(
        f"/api/v1/plants/{PLANT}/workbooks/{file_hash}/worksheet"
    )
    assert response.status_code == 200, response.text
    return response.json()


def rough_of(sheet: dict) -> dict[str, dict]:
    return {panel["raw_zone_text"]: panel for panel in sheet["rough_panels"]}


def live_panel_spelled(admin_conn, label: str) -> bool:
    """Is there a LIVE panel at this plant x model spelled exactly like this?"""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_ws_point"
            " WHERE plant_code = %s AND model_code = %s"
            "   AND lower(zone_code) = lower(%s) AND retired_at IS NULL",
            (PLANT, MODEL, label),
        )
        return int(cur.fetchone()[0]) > 0


def retired_panel_spelled(admin_conn, label: str) -> bool:
    """T113-FIX (D-113-1): FTM short-name block retired 2026-10-11.

    The panel spelled like the label is still in the catalogue -- retired,
    not deleted (ADR 0005) -- which is the state the row claim below has to
    survive.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_ws_point"
            " WHERE plant_code = %s AND model_code = %s"
            "   AND lower(zone_code) = lower(%s) AND retired_at IS NOT NULL",
            (PLANT, MODEL, label),
        )
        return int(cur.fetchone()[0]) > 0


@pytest.fixture()
def reviewed(engineer, cleanup, admin_conn):  # noqa: F811
    """One September sheet at FTM, parsed and waiting for review."""
    serial = "T94-rough"
    [review] = sent(
        engineer, cleanup, admin_conn, "t94-rough.xlsx", sheet_bytes(serial),
        plant=PLANT,
    )
    file_hash = review["batch"]["file_hash"]
    load_id = int(review["batch"]["load_id"])
    yield {"file_hash": file_hash, "load_id": load_id, "serial": serial}
    # `cleanup` purges the batch, which cascades `worksheet_decision` and
    # `stg_review_row`. Nothing else of this test exists to remove, because
    # T94 writes nothing outside the batch.


def test_a_rough_label_is_never_ready_even_though_a_panel_is_spelled_like_it(
    engineer, admin_conn, reviewed  # noqa: F811
):
    """D-94-2, and the measured bug it replaces.

    Before T94 these rows read ``01HOOD -> 01HOOD, "Ready to add"`` -- not
    because anything knew which hood it was, but because the catalogue
    happens to hold a panel spelled ``01HOOD``. The assertion below states
    that accident is still true of the catalogue and no longer true of the
    row.
    """
    # T113-FIX (D-113-1): FTM short-name block retired 2026-10-11. The
    # accident this test is about was a *live* panel spelled `01HOOD`; the
    # panel is now retired, and the row claim below is what T94 decided and
    # still holds -- a rough label is never ready, whatever the catalogue
    # happens to spell.
    assert retired_panel_spelled(admin_conn, "01HOOD"), (
        "this test reads FTM's own catalogue: `01HOOD` must still be there "
        "as a retired panel (T113 retired it; ADR 0005 deletes nothing)"
    )
    assert not live_panel_spelled(admin_conn, "01HOOD"), (
        "T113 retired it, so no live panel is spelled like the label"
    )
    body = worksheet_of(engineer, reviewed["file_hash"])
    [sheet] = body["sheets"]
    by_label: dict[str, list[dict]] = {}
    for row in sheet["rows"]:
        by_label.setdefault(row["panel_label"], []).append(row)

    for row in by_label["01HOOD"]:
        assert row["outcome"] == "needs_confirmation", row
        assert row["checkzone"] is None, "nothing is resolved until it is answered"
        assert "does not say which panel" in row["operator_message"]

    assert sheet["rows_need_confirmation"] >= 1
    assert body["rows_need_confirmation"] == sheet["rows_need_confirmation"]
    assert "does not say which panel it is" in body["summary_message"]


def test_a_specific_label_on_the_same_sheet_is_not_asked_about(
    engineer, reviewed  # noqa: F811
):
    """D-94-1: the sheet is not all-or-nothing. Four of these 32 names say
    which panel they are, and those are never put to the reviewer."""
    [sheet] = worksheet_of(engineer, reviewed["file_hash"])["sheets"]
    asked = rough_of(sheet)
    assert SPECIFIC.isdisjoint(asked), (
        f"a specific label was asked about: {sorted(SPECIFIC & set(asked))}"
    )
    assert len(asked) == len(SEPTEMBER) - len(SPECIFIC) == 30
    for row in sheet["rows"]:
        if row["panel_label"] in SPECIFIC:
            assert row["outcome"] != "needs_confirmation", row


def test_the_row_carries_the_proposed_long_name_its_reason_and_the_whole_list(
    engineer, reviewed  # noqa: F811
):
    """D-94-3: everything the highlighted row needs, from the server.

    The proposal is T90's rule (a) -- the file walks the canonical groups in
    the canonical order -- reused, not rebuilt (D-94-5).
    """
    [sheet] = worksheet_of(engineer, reviewed["file_hash"])["sheets"]
    asked = rough_of(sheet)
    for label, zone in OWNER_PAIRS.items():
        panel = asked[label]
        assert panel["proposed_zone_code"] == zone, (label, panel)
        assert panel["model_code"] == MODEL
        assert panel["rule"] == "group_ordinal"
        assert panel["confirmed_zone_code"] is None, "nothing auto-applies (D-94-6)"
        assert panel["attention"] in ("red", "yellow")
        assert panel["reason"], "a colour without a reason is a demand"
        assert zone in panel["choosable"], "the proposal is choosable"
        assert len(panel["choosable"]) > 1, "the whole list, not only the proposal"
        assert panel["rows"] >= 1

    # The reason each one is rough is on the row, in the data, not only in
    # the sentence: `01HOOD` by condition (a), `25TGATE` by condition (b).
    assert asked["01HOOD"]["fits_canonical"] == [
        "CFHOOD", "LFHOOD", "LRHOOD", "RFHOOD", "RRHOOD",
    ]
    assert asked["25TGATE"]["fits_canonical"] == []
    assert "26TGATE" in asked["25TGATE"]["shares_name_with"]


def test_only_a_name_this_tab_asks_about_and_only_a_panel_it_offers(
    engineer, reviewed  # noqa: F811
):
    """The two gates on the answer, refused with the list rather than stored."""
    url = f"/api/v1/plants/{PLANT}/workbooks/{reviewed['file_hash']}/panel-confirm"

    refused = engineer.post(url, json={
        "load_id": reviewed["load_id"],
        "pairs": [{"raw_zone_text": "12LCPILLAR", "zone_code": "LCPILLAR"}],
    })
    assert refused.status_code == 422, refused.text
    assert "is not a panel name this tab is asking about" in refused.text

    # `LFBOX` is Vertical and a hood is Horizontal, so it is not on
    # `01HOOD`'s list at all (D-88-2: orientation is a hard constraint).
    refused = engineer.post(url, json={
        "load_id": reviewed["load_id"],
        "pairs": [{"raw_zone_text": "01HOOD", "zone_code": "LFBOX"}],
    })
    assert refused.status_code == 422, refused.text
    assert "can be confirmed as" in refused.text

    # Nothing was written by either refusal.
    [sheet] = worksheet_of(engineer, reviewed["file_hash"])["sheets"]
    assert rough_of(sheet)["01HOOD"]["confirmed_zone_code"] is None


def test_one_click_accepts_the_prefilled_set_and_stores_the_long_name(
    engineer, admin_conn, reviewed  # noqa: F811
):
    """D-94-6 and D-94-4, which is the owner's own test of this task.

    *"If the file say 01HOOD our system should show RRHOOD."*
    """
    [sheet] = worksheet_of(engineer, reviewed["file_hash"])["sheets"]
    asked = rough_of(sheet)
    pairs = [
        {"raw_zone_text": label, "zone_code": panel["proposed_zone_code"]}
        for label, panel in sorted(asked.items())
        if panel["proposed_zone_code"]
    ]
    assert len(pairs) == 30, "rule (a) proposes a panel for every rough name here"

    done = engineer.post(
        f"/api/v1/plants/{PLANT}/workbooks/{reviewed['file_hash']}/panel-confirm",
        json={"load_id": reviewed["load_id"], "pairs": pairs,
              "note": "T94 test: accept the pre-filled set"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["decisions_written"] == 30
    assert done.json()["replayed_load_ids"] == [reviewed["load_id"]]

    wait_for(engineer, reviewed["load_id"])
    [sheet] = worksheet_of(engineer, reviewed["file_hash"])["sheets"]
    assert sheet["rows_need_confirmation"] == 0
    resolved = {
        row["panel_label"]: row for row in sheet["rows"]
        if row["outcome"] == "ready"
    }
    for label, zone in OWNER_PAIRS.items():
        assert resolved[label]["checkzone"] == zone, (label, resolved[label])

    # And the row's question now says it was answered, still for this upload
    # only -- the colour goes yellow, never green (D-90-6).
    asked = rough_of(sheet)
    assert asked["01HOOD"]["confirmed_zone_code"] == "RRHOOD"
    assert asked["01HOOD"]["attention"] == "yellow"


def test_what_is_stored_is_the_long_name_and_history_shows_it(
    engineer, admin_conn, reviewed  # noqa: F811
):
    """D-94-4 end to end: the fact row, and the Measurement History read."""
    [sheet] = worksheet_of(engineer, reviewed["file_hash"])["sheets"]
    pairs = [
        {"raw_zone_text": label, "zone_code": panel["proposed_zone_code"]}
        for label, panel in sorted(rough_of(sheet).items())
        if panel["proposed_zone_code"]
    ]
    engineer.post(
        f"/api/v1/plants/{PLANT}/workbooks/{reviewed['file_hash']}/panel-confirm",
        json={"load_id": reviewed["load_id"], "pairs": pairs},
    ).raise_for_status()
    wait_for(engineer, reviewed["load_id"])

    loaded = engineer.post(
        f"/api/v1/plants/{PLANT}/workbooks/{reviewed['file_hash']}/load-ready",
        json={},
    )
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["readings_added"] >= 30

    # The fact row: the long name is the identity, the file's spelling is
    # provenance, and nothing in between was invented.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT checkzone, src_zone_text, src_zone_no FROM wavescan"
            " WHERE load_id = %s AND src_zone_text = %s"
            "   AND corrects_measurement_id IS NULL",
            (reviewed["load_id"], "01HOOD"),
        )
        stored = cur.fetchall()
    assert stored, "01HOOD loaded no fact row"
    for checkzone, src_zone_text, src_zone_no in stored:
        assert checkzone == "RRHOOD", "D-94-4: the long name is stored"
        assert src_zone_text == "01HOOD", "the file's own spelling is kept"
        assert src_zone_no == 1, "and so is the walk number it wrote"

    # Measurement History: the long name, with the file's words beside it
    # and never in the position column.
    vehicles = engineer.get(
        f"/api/v1/plants/{PLANT}/history/vehicles",
        params={"month": "2026-09", "week": 2, "model": MODEL,
                "color": COLOUR, "limit": 200},
    )
    assert vehicles.status_code == 200, vehicles.text
    mine = [
        v for v in vehicles.json()["items"]
        if v["serial_no"] == reviewed["serial"]
    ]
    assert len(mine) == 1, "this test's own vehicle"
    points = engineer.get(
        f"/api/v1/plants/{PLANT}/history/vehicles/{mine[0]['vehicle_id']}/points"
    )
    assert points.status_code == 200, points.text
    by_spelling = {p["src_zone_text"]: p for p in points.json()["items"]}
    assert by_spelling["01HOOD"]["panel_label"] == "RRHOOD", (
        "the owner's test: if the file say 01HOOD our system should show RRHOOD"
    )
    assert by_spelling["01HOOD"]["checkzone"] == "RRHOOD"
    # And no ROUGH spelling is anywhere in the position column. The four
    # specific names are a different matter: `13LFRDOOR` IS a live panel at
    # FTM (the T58 numbered block, which T94 leaves alone -- D-94-7), so a
    # row filed on it shows that name because it is the position, not
    # because a rough spelling leaked into the column.
    shown = {p["panel_label"] for p in points.json()["items"]}
    rough_spellings = {label for label, _ in SEPTEMBER} - SPECIFIC
    assert not shown & rough_spellings, sorted(shown & rough_spellings)


def test_the_answer_is_recorded_on_the_batch_and_nowhere_a_later_file_reads(
    engineer, admin_conn, reviewed  # noqa: F811
):
    """D-94-2 as a guarantee rather than a promise (and D-90-3, D-91-3).

    A rough answer is a ``worksheet_decision`` row on this ``load_id``.
    ``domain/cleaner.py`` resolves a panel from ``ReferenceData``,
    ``load_reference_data`` builds that from ``ref_*`` tables alone, and
    neither can reach a ``worksheet_decision``. So the month the plant
    reshuffles its walk, ``01HOOD`` cannot silently file as last month's
    hood: nothing on the resolution path can see last month's answer.
    """
    engineer.post(
        f"/api/v1/plants/{PLANT}/workbooks/{reviewed['file_hash']}/panel-confirm",
        json={"load_id": reviewed["load_id"],
              "pairs": [{"raw_zone_text": "01HOOD", "zone_code": "RRHOOD"}]},
    ).raise_for_status()

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT kind, subject FROM worksheet_decision"
            " WHERE load_id = %s AND kind = 'PANEL_CONFIRM'",
            (reviewed["load_id"],),
        )
        # The subject records the model too, because D-94-1 is scoped to
        # `(plant, model)`: one sheet carries two models and a label can be
        # rough on one and specific on the other.
        assert [tuple(r) for r in cur.fetchall()] == [
            ("PANEL_CONFIRM", f"{MODEL}|01HOOD=>RRHOOD")
        ]
        # It did not become an alias, and it was never going to: the whole
        # point of D-94-2 is that the catalogue is not asked.
        cur.execute(
            "SELECT count(*) FROM ref_plant_zone_map"
            " WHERE plant_code = %s AND lower(raw_zone_text) = '01hood'",
            (PLANT,),
        )
        assert int(cur.fetchone()[0]) == 0, (
            "a rough label must never become a permanent alias"
        )

    # And the resolution path cannot see it, by construction.
    from app.domain.references import ReferenceData

    assert not any(
        "worksheet" in name or "decision" in name
        for name in ReferenceData.__dataclass_fields__
    ), "ReferenceData grew a field that could carry a batch answer"
