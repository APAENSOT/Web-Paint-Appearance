"""T107 -- against the running application and database.

T98 section 1 measured the gap this closes. Three real FTM months were
worked end to end through the **review screen**, which asks the panel
question in the row and stores the answer as a ``PANEL_CONFIRM``
`worksheet_decision` (T94, D-94-3). The pre-fill read only ``ZONE``
panel-match proposals, so after 140 confirmed answers the memory was still
empty and October would have arrived red again.

So, measured here on this module's own marker walk:

* **D-107-1 / D-107-2**: a committed sheet whose rough names were confirmed
  **in the row** pre-fills the next upload of the identical walk -- every
  rough row yellow, every answer filled in, and still one click. Nothing
  resolved itself: the second upload's rough names are still **held** when
  it lands, which is D-90-11 holding;
* **D-91-1 / D-90-6**: a walk that differs in one label carries nothing
  over, goes red again and says the walk has changed;
* **D-107-4**: a purged sheet's answers are not remembered.

Every batch, decision and fact is this module's own, created through the
API and removed again by `cleanup` (by load_id). No ``ref_*`` row is
written -- an autouse fixture asserts `ref_plant_zone_map`,
`proposed_mapping` and `ref_plant_ws_point` are flat across every test, so
"pre-fill only" is measured rather than promised. The owner's trial batches
are never touched and no standard is ever published.
"""

from __future__ import annotations

import uuid

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
from tests.test_t90_walk_memory import (
    GROUP_WORD,
    MARKER,
    MODEL,
    PLANT,
    canonical_walk,
    forget,
    group_of,
    sheet_bytes,
    walk_labels,
    walk_of,
)

pytestmark = pytest.mark.ingest

#: The three tables a pre-fill may never touch (D-107-2).
REFERENCE_TABLES = ("ref_plant_zone_map", "proposed_mapping", "ref_plant_ws_point")


def ws_url(file_hash: str, tail: str) -> str:
    return f"/api/v1/plants/{PLANT}/workbooks/{file_hash}/{tail}"


def rough_panels(engineer, file_hash: str) -> dict[str, dict]:  # noqa: F811
    """The in-row questions of this upload, by the spelling asked about."""
    response = engineer.get(ws_url(file_hash, "worksheet"))
    assert response.status_code == 200, response.text
    [sheet] = response.json()["sheets"]
    return {panel["raw_zone_text"]: panel for panel in sheet["rough_panels"]}


def answer_in_the_row(
    engineer,  # noqa: F811
    file_hash: str,
    load_id: int,
    note: str,
) -> dict[str, str]:
    """One click: confirm every pre-filled or proposed answer of this sheet.

    Returns what was confirmed, so the next upload's pre-fill can be
    compared against the answers rather than against the proposal it would
    have made for itself anyway.
    """
    asked = rough_panels(engineer, file_hash)
    answers = {
        label: panel["confirmed_zone_code"]
        or panel["prefilled_zone_code"]
        or panel["proposed_zone_code"]
        for label, panel in sorted(asked.items())
    }
    pairs = [
        {"raw_zone_text": label, "zone_code": zone}
        for label, zone in sorted(answers.items())
        if zone
    ]
    assert pairs, "this sheet asked nothing, so there is nothing to confirm"
    done = engineer.post(
        ws_url(file_hash, "panel-confirm"),
        json={"load_id": load_id, "pairs": pairs, "note": f"T107 {note}"},
    )
    assert done.status_code == 200, done.text
    wait_for(engineer, load_id)
    return {label: zone for label, zone in answers.items() if zone}


def load_it(engineer, file_hash: str) -> dict:  # noqa: F811
    loaded = engineer.post(ws_url(file_hash, "load-ready"), json={})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()


def upload_walk(engineer, cleanup, admin_conn, labels, name: str) -> dict:  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t107-{name}-{tag}.xlsx",
        sheet_bytes(labels, f"107{tag}"), PLANT,
    )
    return {
        "review": review,
        "load_id": int(review["batch"]["load_id"]),
        "file_hash": review["batch"]["file_hash"],
    }


def held_zone_values(review: dict) -> set[str]:
    return {
        held["raw_value"]
        for held in review["held_labels"]
        if held["display_group"] == "zone"
    }


@pytest.fixture
def committed(engineer, cleanup, admin_conn):  # noqa: F811
    """One FTM sheet answered **in the row** and loaded, so it is COMMITTED.

    This is the owner's own path: the review screen's one click, not the
    match screen's ``ZONE`` proposal. The batch it leaves behind is the only
    thing T107 asks the memory to read.
    """
    labels = walk_labels(admin_conn)
    assert len(labels) >= 8, "FTM / P703 DBL RANGER has no canonical walk here"
    first = upload_walk(engineer, cleanup, admin_conn, labels, "first")
    try:
        answers = answer_in_the_row(
            engineer, first["file_hash"], first["load_id"], "answered in the row"
        )
        result = load_it(engineer, first["file_hash"])
        assert result["readings_added"] >= len(labels), result
        yield {**first, "labels": labels, "answers": answers}
    finally:
        forget(admin_conn, PLANT, MODEL, [label for label, _z, _o in labels])


@pytest.fixture(autouse=True)
def _reference_tables_stay_flat(admin_conn):
    """D-107-2: the pre-fill reads batches and writes no reference row."""
    def counts() -> dict[str, int]:
        out: dict[str, int] = {}
        with admin_conn.cursor() as cur:
            for table in REFERENCE_TABLES:
                cur.execute(f"SELECT count(*) FROM {table}")
                out[table] = int(cur.fetchone()[0])
        return out

    before = counts()
    yield
    assert counts() == before, (
        "a T107 test changed a reference table; the pre-fill must only read"
    )


def test_a_committed_in_row_confirm_prefills_the_next_identical_walk(
    engineer, cleanup, admin_conn, committed  # noqa: F811
):
    """D-107-1 / D-107-2, and the T98 section 1 gap, measured.

    The first sheet's answers were given in the row and the sheet is
    committed. The second sheet walks the identical labels, so the memory
    must carry them with that batch's own fingerprint -- every row yellow,
    pre-filled with what was confirmed, and still answered by one click.
    """
    second = upload_walk(
        engineer, cleanup, admin_conn, committed["labels"], "same"
    )

    # Nothing resolved itself on the way in: the rough names are still held,
    # which is the D-90-11 guarantee doing its job.
    rough = set(committed["answers"])
    assert rough <= held_zone_values(second["review"]), sorted(
        rough - held_zone_values(second["review"])
    )

    walk = walk_of(engineer, second["load_id"])["walk"]
    assert walk["confirmed_before"] is True, (
        "the in-row confirm of a committed sheet is not remembered; this is "
        "the T98 section 1 gap"
    )
    assert walk["confirmed_load_id"] == committed["load_id"]
    assert walk["confirmed_source_file"]
    assert walk["fingerprint_moved"] is False
    assert walk["red_count"] == 0
    assert walk["yellow_count"] == len(walk["rows"])
    for row in walk["rows"]:
        assert row["attention"] == "yellow", row
        assert row["prefilled_zone_code"] == committed["answers"].get(
            row["raw_zone_text"], row["prefilled_zone_code"]
        ), row

    # The row the operator reads is pre-filled too, and nothing is answered
    # for them: it is still a question until the one click.
    asked = rough_panels(engineer, second["file_hash"])
    assert asked, "the second upload asks nothing, so there is no pre-fill to see"
    for label, panel in asked.items():
        assert panel["confirmed_zone_code"] is None, (label, panel)
        assert panel["prefilled_zone_code"] == committed["answers"][label], (
            label,
            panel,
        )
        assert panel["attention"] == "yellow", (label, panel)

    # One click, and the pre-filled set loads.
    answers = answer_in_the_row(
        engineer, second["file_hash"], second["load_id"], "one click on the pre-fill"
    )
    assert answers == committed["answers"]
    assert load_it(engineer, second["file_hash"])["readings_added"] >= len(
        committed["labels"]
    )


def test_a_walk_that_moved_one_label_carries_nothing_over(
    engineer, cleanup, admin_conn, committed  # noqa: F811
):
    """D-91-1 / D-90-6: August's `13LFRDOOR` must not carry into September.

    The same labels in a different order are a different walk, so the
    fingerprint computed for the remembered batch cannot match and every
    name is open again -- the shape T98 proved by hand on the owner's two
    real months.
    """
    moved = walk_labels(admin_conn, swap=True)
    assert [label for label, _z, _o in moved] != [
        label for label, _z, _o in committed["labels"]
    ], "the swap changed nothing, so this would prove nothing"
    try:
        second = upload_walk(engineer, cleanup, admin_conn, moved, "moved")
        walk = walk_of(engineer, second["load_id"])["walk"]
        assert walk["confirmed_before"] is True
        assert walk["fingerprint_moved"] is True
        assert walk["yellow_count"] == 0
        assert walk["red_count"] == len(walk["rows"])
        assert all(row["prefilled_zone_code"] is None for row in walk["rows"])
        assert "walk has changed" in walk["operator_message"]
        for panel in rough_panels(engineer, second["file_hash"]).values():
            assert panel["prefilled_zone_code"] is None, panel
    finally:
        forget(admin_conn, PLANT, MODEL, [label for label, _z, _o in moved])


def test_a_purged_sheet_is_not_remembered(
    admin, engineer, cleanup, admin_conn, committed  # noqa: F811
):
    """D-107-4: the memory is the plant's committed work, not its history."""
    purged = admin.post(
        ws_url(committed["file_hash"], "purge"),
        json={"reason": "T107: the answers of a purged sheet are not memory."},
    )
    assert purged.status_code == 200, purged.text

    second = upload_walk(
        engineer, cleanup, admin_conn, committed["labels"], "after-purge"
    )
    walk = walk_of(engineer, second["load_id"])["walk"]
    # FTM / P703 DBL RANGER carries the owner's own three committed months,
    # so "this plant has confirmed nothing" is not assertable here and is
    # not the claim. The claim is that the **purged** sheet's answers are
    # not in the memory: it is not what is remembered, and the identical
    # walk it answered is open again.
    assert walk["confirmed_load_id"] != committed["load_id"]
    assert walk["confirmed_source_file"] != committed["review"]["batch"][
        "source_file"
    ]
    assert walk["yellow_count"] == 0
    assert walk["red_count"] == len(walk["rows"])
    assert all(row["prefilled_zone_code"] is None for row in walk["rows"])
    for panel in rough_panels(engineer, second["file_hash"]).values():
        assert panel["prefilled_zone_code"] is None, panel


# =====================================================================
# T107-FIX -- D-107F-1 / D-107F-2: the pre-fill is the newest month that
# walks THIS walk, not simply the newest month
# =====================================================================
def walk_variant(admin_conn, boundary: int) -> list[tuple[str, str, str]]:
    """`walk_labels` with the *n*-th adjacent cross-family pair swapped.

    `walk_labels(swap=True)` is boundary 0. Each boundary moves two families
    past each other and leaves the numbers alone, so every variant is a
    **different walk of the same panels** -- which is the only thing a
    fingerprint is about (D-90-4). Measured on FTM / P703 DBL RANGER:
    boundaries 0, 1 and 2 give three fingerprints, all different from the
    unswapped walk, and all four still propose all 32 names, so each one
    can be confirmed in the row and committed.
    """
    out: list[tuple[str, str, str]] = []
    for point_no, zone_code, orientation in canonical_walk(admin_conn, MODEL):
        group = group_of(admin_conn, zone_code)
        core = zone_code if group == "PILLAR" else GROUP_WORD.get(group, group)
        out.append((f"{point_no:02d}{MARKER}{core}", zone_code, orientation))
    seen = 0
    for index in range(len(out) - 1):
        if group_of(admin_conn, out[index][1]) != group_of(
            admin_conn, out[index + 1][1]
        ):
            if seen == boundary:
                left, right = out[index], out[index + 1]
                head = 2 + len(MARKER)
                out[index] = (left[0][:head] + right[0][head:], right[1], right[2])
                out[index + 1] = (right[0][:head] + left[0][head:], left[1], left[2])
                return out
            seen += 1
    raise AssertionError(f"this walk has no cross-family boundary {boundary}")


def commit_walk(engineer, cleanup, admin_conn, labels, name: str) -> dict:  # noqa: F811
    """Upload one walk, answer it **in the row**, load it: a COMMITTED month."""
    sheet = upload_walk(engineer, cleanup, admin_conn, labels, name)
    answers = answer_in_the_row(
        engineer, sheet["file_hash"], sheet["load_id"], f"{name} answered in the row"
    )
    assert load_it(engineer, sheet["file_hash"])["readings_added"] >= len(labels)
    return {**sheet, "labels": labels, "answers": answers}


@pytest.fixture
def three_months(engineer, cleanup, admin_conn):  # noqa: F811
    """Three committed months on three different walks, newest last.

    A walks X, B walks Y, C walks Z, and C is the last one committed -- the
    shape the owner own FTM carries, where July was committed last and
    walks neither August nor September (T107 section 5.2).
    """
    walks = {
        "A": walk_labels(admin_conn),
        "B": walk_variant(admin_conn, 0),
        "C": walk_variant(admin_conn, 1),
    }
    spellings = {
        key: [label for label, _z, _o in labels] for key, labels in walks.items()
    }
    assert len({tuple(value) for value in spellings.values()}) == 3, (
        "the three walks are not three walks, so this would prove nothing"
    )
    try:
        yield {
            key: commit_walk(engineer, cleanup, admin_conn, walks[key], key.lower())
            for key in ("A", "B", "C")
        }
    finally:
        for labels in spellings.values():
            forget(admin_conn, PLANT, MODEL, labels)


def test_the_prefill_is_the_newest_month_that_walks_the_same_walk(
    engineer, cleanup, admin_conn, three_months  # noqa: F811
):
    """D-107F-1: A is pre-filled from, although C was committed last.

    Before T107-FIX this file arrived **red**: the screen took the newest
    remembered set whatever its walk, that was C, and C walks something
    else. A answers were in the memory the whole time, under A own
    fingerprint.
    """
    first, newest = three_months["A"], three_months["C"]
    again = upload_walk(engineer, cleanup, admin_conn, first["labels"], "same-as-a")

    walk = walk_of(engineer, again["load_id"])["walk"]
    assert walk["confirmed_load_id"] == first["load_id"], (
        "the pre-fill did not come from the month that walks this walk; "
        f"it named {walk['confirmed_source_file']}"
    )
    assert walk["confirmed_load_id"] != newest["load_id"]
    assert walk["fingerprint_moved"] is False
    assert walk["red_count"] == 0
    assert walk["yellow_count"] == len(walk["rows"])
    assert "accept all" in walk["operator_message"].lower()
    for row in walk["rows"]:
        assert row["attention"] == "yellow", row
        assert row["prefilled_zone_code"] == first["answers"].get(
            row["raw_zone_text"], row["prefilled_zone_code"]
        ), row

    # The question in the row is pre-filled and still a question, and one
    # click loads it.
    asked = rough_panels(engineer, again["file_hash"])
    for label, panel in asked.items():
        assert panel["confirmed_zone_code"] is None, (label, panel)
        assert panel["prefilled_zone_code"] == first["answers"][label], (label, panel)
        assert panel["attention"] == "yellow", (label, panel)
    assert (
        answer_in_the_row(
            engineer, again["file_hash"], again["load_id"], "one click on the pre-fill"
        )
        == first["answers"]
    )
    assert load_it(engineer, again["file_hash"])["readings_added"] >= len(
        first["labels"]
    )

    # And "newest" means newest: this sheet is now the most recent month on
    # walk X, so the next file on walk X is pre-filled from it, not from A.
    third = upload_walk(engineer, cleanup, admin_conn, first["labels"], "third-on-x")
    later = walk_of(engineer, third["load_id"])["walk"]
    assert later["confirmed_load_id"] == again["load_id"]
    assert later["fingerprint_moved"] is False
    assert later["yellow_count"] == len(later["rows"])


def test_a_walk_nobody_confirmed_is_red_and_the_sentence_names_the_newest(
    engineer, cleanup, admin_conn, three_months  # noqa: F811
):
    """D-107F-2 / D-107F-3: no match is red, and it says since when.

    A fourth walk, which none of the three months walked. Nothing is
    carried over -- D-91-1 -- and the sentence still names the newest set
    overall, which is C, because that is what "the walk has changed since"
    is about.
    """
    newest = three_months["C"]
    other = walk_variant(admin_conn, 2)
    spellings = [label for label, _z, _o in other]
    assert spellings != [label for label, _z, _o in newest["labels"]]
    try:
        fourth = upload_walk(engineer, cleanup, admin_conn, other, "unconfirmed-walk")
        walk = walk_of(engineer, fourth["load_id"])["walk"]
        assert walk["fingerprint_moved"] is True
        assert walk["confirmed_load_id"] == newest["load_id"]
        assert walk["confirmed_source_file"] == newest["review"]["batch"][
            "source_file"
        ]
        assert walk["yellow_count"] == 0
        assert walk["red_count"] == len(walk["rows"])
        assert all(row["prefilled_zone_code"] is None for row in walk["rows"])
        assert "walk has changed" in walk["operator_message"]
        for panel in rough_panels(engineer, fourth["file_hash"]).values():
            assert panel["prefilled_zone_code"] is None, panel
    finally:
        forget(admin_conn, PLANT, MODEL, spellings)
