"""T90 -- against the running application and database.

Part 2's read model and Part 3's memory, plus the one claim this task turns
on:

* the match screen carries a **walk** block for the whole `(plant, model)`,
  with the fingerprint, which rules apply and why, and a colour and a reason
  per name -- not only for the held names;
* **D-90-3**, enforced at the write boundary: a `matches` row the set's own
  walk calls **rough** is refused by name and nothing is written. Only the
  specific pairs become `ref_plant_zone_map` aliases;
* **D-90-11**, the guarantee rather than the promise: a confirmed rough
  mapping lives on the batch, is read back for the pre-fill, and the
  resolution path has **no route to it**. Asserted the way T87 asserted its
  grant -- structurally, not by inspection of behaviour alone;
* **D-90-5 / D-90-6**: an unchanged walk pre-fills and still needs one
  click; a changed one carries nothing over and is red;
* **D-90-14**: the read model reports both counts, so "28 accepted, 4 still
  need you" is the server's number and not the screen's arithmetic.

Every batch, proposal and map row is this module's own and is removed
again. The owner's trial batches are never touched and no standard is ever
published.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.domain.panel_walk import SPECIFICITY_ROUGH, SPECIFICITY_SPECIFIC
from tests.test_t04_ingest import cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
)

from tests.test_t04_ingest import forget_proposals
from tests.conftest import SUITE_STARTED, row_keys

pytestmark = pytest.mark.ingest

PROPOSALS = "/api/v1/mappings/proposals"
PANEL_MATCH = "/api/v1/mappings/panel-match"

PLANT = "FTM"
MODEL_CELL = "P703 DBL"
MODEL = "P703 DBL RANGER"
COLOUR = "Ignite Orange"

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: A marker that keeps every synthetic label off FTM's own live panel
#: list. Without it the labels would BE the T58 numbered block -- `01HOOD`,
#: `11ROOF`, `17TGATE` are live gold panels here -- so they would resolve
#: through the gold list and never be held, and the test would be measuring
#: T58 rather than T90. Letters only, because `name_core` drops digits.
MARKER = "TZ"

#: The word the synthetic file writes instead of the canonical name, per
#: family. A shared word makes the label **rough** (D-90-3): the number is
#: what identifies it, exactly as September's five `HOOD`s do.
GROUP_WORD = {
    "HOOD": "HOOD",
    "FENDER": "FENDER",
    "DOOR": "DOOR",
    "ROOF": "ROOF",
    "BOX": "BOXSD",
    "TAILGATE": "TGATE",
    "PILLAR": "PILLAR",
    "LIFTGATE": "LIFTGATE",
}


def canonical_walk(admin_conn, model: str = MODEL) -> list[tuple[int, str, str]]:
    """The model's canonical walk at FTM: `(point_no, zone_code, orientation)`.

    Every live panel that is also a position on the model's own
    `ref_model_zone` catalogue, which is what a confirmed pair may point at
    -- the same list `services/panel_pool.py` calls mappable.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT p.point_no, p.zone_code, p.tolerance_group"
            "  FROM ref_plant_ws_point p"
            "  JOIN ref_model_zone z"
            "    ON z.model_code = p.model_code AND z.zone_code = p.zone_code"
            " WHERE p.plant_code = %s AND p.model_code = %s"
            "   AND p.retired_at IS NULL"
            " ORDER BY p.point_no",
            (PLANT, model),
        )
        return [(int(r[0]), r[1], r[2]) for r in cur.fetchall()]


def group_of(admin_conn, zone_code: str) -> str:
    from app.domain.ws_plant_gold import ws_panel_group

    return ws_panel_group(zone_code)


def walk_labels(
    admin_conn, model: str = MODEL, *, swap: bool = False
) -> list[tuple[str, str, str]]:
    """A full walk of this model, relabelled: `(label, zone_code, orientation)`.

    Each canonical panel is written as its walk number plus its family word
    -- `01HOOD`, `06FENDER`, `25TGATE` -- so the label is **rough**, with
    two exceptions: the pillars keep their own names, so the sheet has
    specific labels too. That is September's shape exactly, and it is what
    makes both halves of D-90-3 testable on one sheet.

    `swap` moves two adjacent panels of different families, which changes
    the group fingerprint without changing the names (D-90-4).
    """
    walk = canonical_walk(admin_conn, model)
    out: list[tuple[str, str, str]] = []
    for point_no, zone_code, orientation in walk:
        group = group_of(admin_conn, zone_code)
        core = zone_code if group == "PILLAR" else GROUP_WORD.get(group, group)
        out.append((f"{point_no:02d}{MARKER}{core}", zone_code, orientation))
    if swap:
        for index in range(len(out) - 1):
            if group_of(admin_conn, out[index][1]) != group_of(
                admin_conn, out[index + 1][1]
            ):
                # Swap the two labels (keeping each one's own number) so the
                # families change places in the walk.
                left, right = out[index], out[index + 1]
                head = 2 + len(MARKER)
                out[index] = (left[0][:head] + right[0][head:], right[1], right[2])
                out[index + 1] = (right[0][:head] + left[0][head:], left[1], left[2])
                break
    return out


def sheet_bytes(labels, tag: str) -> bytes:
    rows = [
        {
            "Date": "2026-09-14",
            "Plant": PLANT,
            "Model": MODEL_CELL,
            "Color": COLOUR,
            "Checkzone": label,
            "Tolerance Group": orientation,
            "CF": 55.0 + index,
            "Serial No": f"T90-{tag}",
        }
        for index, (label, _zone, orientation) in enumerate(labels)
    ]
    return book(HEADERS, rows)


def forget(
    admin_conn, plant: str, model: str, labels: list[str], since=SUITE_STARTED
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    The `note LIKE 'T90 %'` proposal delete moved to
    `_t92_proposal_cleanup` below: the product writes the same notes, so a
    note prefix is not a scope (D-95-2). It removed a genuine approved
    proposal from the owner's trial.

    **T98 (D-98-2).** Plant and model are not enough on their own: this
    module writes real spellings at a real plant and model, so a row the
    owner taught before the run matched the delete too (the
    `ref_plant_zone_map` row T97 lost). ``since`` floors the delete at the
    moment this suite started, so it reaches only rows this run inserted.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
            "   AND model_code = %s AND raw_zone_text = ANY(%s)"
            "   AND created_at >= %s",
            (plant, model, [label.lower() for label in labels], since),
        )


def walk_of(engineer, load_id: int, model: str = MODEL) -> dict:  # noqa: F811
    response = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": model}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["walk"] is not None, "this sheet produced no walk block"
    return body


def confirm_body(walk: dict, load_id: int, note: str) -> dict:
    """The ZONE set this screen sends: specific pairs in `matches`, all in `walk`."""
    rows = walk["walk"]["rows"]
    return {
        "kind": "ZONE",
        "load_id": load_id,
        "payload": {
            "plant_code": PLANT,
            "model_code": MODEL,
            "load_id": load_id,
            "matches": [
                {
                    "raw_zone_text": row["raw_zone_text"],
                    "zone_code": row["proposed_zone_code"],
                }
                for row in rows
                if row["specificity"] == SPECIFICITY_SPECIFIC
                and row["proposed_zone_code"]
            ],
            "walk": {
                "fingerprint": walk["walk"]["fingerprint"],
                "pairs": [
                    {
                        "raw_zone_text": row["raw_zone_text"],
                        "zone_code": row["proposed_zone_code"],
                        "specificity": row["specificity"],
                        "rule": row["rule"],
                        "attention": row["attention"],
                    }
                    for row in rows
                    if row["proposed_zone_code"]
                ],
            },
            "decided_by": "T90 test operator",
            "method": "T90 structural walk, confirmed on the screen",
            "note": f"T90 {note}",
        },
    }


@pytest.fixture
def walked(engineer, cleanup, admin_conn):  # noqa: F811
    """One FTM tab that walks the whole canonical set under rough labels."""
    labels = walk_labels(admin_conn)
    assert len(labels) >= 8, "FTM / P703 DBL RANGER has no canonical walk here"
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t90-walk-{tag}.xlsx",
        sheet_bytes(labels, tag), PLANT,
    )
    try:
        yield {
            "review": review,
            "load_id": review["batch"]["load_id"],
            "labels": labels,
            "tag": tag,
        }
    finally:
        forget(admin_conn, PLANT, MODEL, [label for label, _z, _o in labels])


# =====================================================================
# Part 2 -- the read model
# =====================================================================
def test_the_match_screen_carries_the_whole_walk_not_only_the_held_names(
    engineer, walked  # noqa: F811
):
    body = walk_of(engineer, walked["load_id"])
    walk = body["walk"]
    expected = [label for label, _z, _o in walked["labels"]]
    assert [row["raw_zone_text"] for row in walk["rows"]] == expected
    assert walk["fingerprint"] == walk["canonical_fingerprint"]
    assert walk["multiset_matches"] is True
    assert walk["walk_order_verified"] is True
    assert walk["rule_group_ordinal_available"] is True
    # Every held row also carries its own verdict, by spelling.
    by_spelling = {row["raw_zone_text"]: row for row in walk["rows"]}
    for held in body["held_panels"]:
        assert held["walk"] == by_spelling[held["raw_zone_text"]]


def test_group_ordinal_proposes_each_label_onto_its_own_canonical_panel(
    engineer, walked  # noqa: F811
):
    """The relabelled walk is the canonical walk, so rule (a) must find it."""
    walk = walk_of(engineer, walked["load_id"])["walk"]
    proposed = {
        row["raw_zone_text"]: row["proposed_zone_code"] for row in walk["rows"]
    }
    assert proposed == {
        label: zone for label, zone, _o in walked["labels"]
    }


def test_the_first_sight_of_a_walk_is_entirely_red_and_says_so(
    engineer, walked  # noqa: F811
):
    """D-90-6: yellow means "and it is what was confirmed last".

    **T107 (D-107-1).** The memory now also carries the in-row confirms of
    this plant's committed sheets, and FTM / P703 DBL RANGER holds the
    owner's own July, August and September. So *whether this plant has ever
    confirmed anything* is data-dependent (`AGENTS.md` section 2) and is not
    what this test is about. What is: a walk nobody has confirmed carries
    **nothing** over -- no yellow, no pre-fill, every name open -- and the
    screen says which of the two reasons it is. Asserting
    ``confirmed_before is False`` alone passed only while the memory was
    empty, which is the gap T98 section 1 reported.
    """
    walk = walk_of(engineer, walked["load_id"])["walk"]
    assert walk["yellow_count"] == 0
    assert walk["red_count"] == len(walk["rows"])
    assert all(row["attention"] == "red" for row in walk["rows"])
    assert all(row["prefilled_zone_code"] is None for row in walk["rows"])
    if walk["confirmed_before"]:
        assert walk["fingerprint_moved"] is True
        assert "walk has changed" in walk["operator_message"]
    else:
        assert "has not been confirmed" in walk["operator_message"]


def test_rough_and_specific_are_classified_on_the_server(
    engineer, walked  # noqa: F811
):
    """D-90-3. The client never decides this."""
    walk = walk_of(engineer, walked["load_id"])["walk"]
    kinds = {row["raw_zone_text"]: row["specificity"] for row in walk["rows"]}
    pillars = [
        label for label, zone, _o in walked["labels"] if "PILLAR" in zone.upper()
    ]
    assert pillars, "this walk has no pillar, so the specific half is untested"
    for label in pillars:
        assert kinds[label] == SPECIFICITY_SPECIFIC
    assert SPECIFICITY_ROUGH in kinds.values()


# =====================================================================
# D-90-3 -- the main safety rule, at the write boundary
# =====================================================================
def test_a_rough_name_offered_as_a_permanent_alias_is_refused_by_name(
    engineer, walked, admin_conn  # noqa: F811
):
    body = walk_of(engineer, walked["load_id"])
    request = confirm_body(body, walked["load_id"], "rough in matches")
    rough = next(
        row for row in body["walk"]["rows"]
        if row["specificity"] == SPECIFICITY_ROUGH and row["proposed_zone_code"]
    )
    request["payload"]["matches"].append(
        {
            "raw_zone_text": rough["raw_zone_text"],
            "zone_code": rough["proposed_zone_code"],
        }
    )
    response = engineer.post(PROPOSALS, json=request)
    assert response.status_code == 422, response.text
    detail = response.json()["message"]
    assert "rough" in detail
    assert rough["raw_zone_text"].lower() in detail.lower()
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_zone_map WHERE raw_zone_text = %s",
            (rough["raw_zone_text"].lower(),),
        )
        assert cur.fetchone()[0] == 0


def test_a_set_that_contradicts_its_own_walk_is_refused(
    engineer, walked  # noqa: F811
):
    body = walk_of(engineer, walked["load_id"])
    request = confirm_body(body, walked["load_id"], "contradiction")
    assert request["payload"]["matches"], "no specific pair to contradict"
    other = next(
        row["proposed_zone_code"]
        for row in body["walk"]["rows"]
        if row["proposed_zone_code"]
        and row["proposed_zone_code"] != request["payload"]["matches"][0]["zone_code"]
    )
    request["payload"]["matches"][0]["zone_code"] = other
    response = engineer.post(PROPOSALS, json=request)
    assert response.status_code == 422, response.text
    assert "disagree" in response.json()["message"]


def test_only_the_specific_pairs_become_permanent_aliases(
    engineer, admin, walked, admin_conn  # noqa: F811
):
    """D-90-3's two halves, in one approval."""
    body = walk_of(engineer, walked["load_id"])
    request = confirm_body(body, walked["load_id"], "specific only")
    specific = [row["raw_zone_text"] for row in request["payload"]["matches"]]
    rough = [
        row["raw_zone_text"]
        for row in body["walk"]["rows"]
        if row["specificity"] == SPECIFICITY_ROUGH
    ]
    assert specific and rough

    created = engineer.post(PROPOSALS, json=request)
    assert created.status_code == 201, created.text
    proposal_id = created.json()["id"]
    approved = admin.post(f"{PROPOSALS}/{proposal_id}/approve", json={})
    assert approved.status_code == 200, approved.text

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw_zone_text FROM ref_plant_zone_map"
            " WHERE plant_code = %s AND model_code = %s"
            "   AND raw_zone_text = ANY(%s)",
            (PLANT, MODEL, [label.lower() for label in specific + rough]),
        )
        learned = {r[0] for r in cur.fetchall()}
    assert learned == {label.lower() for label in specific}
    assert not learned & {label.lower() for label in rough}


# =====================================================================
# D-90-11 -- the guarantee: the cleaner cannot reach a confirmed walk
# =====================================================================
def test_the_reference_loader_reads_only_reference_tables():
    """The cleaner's whole world is ReferenceData, and this is where it comes from.

    `domain/cleaner.resolve_checkzone` reads `self.ref` and nothing else, so
    the only way a confirmed rough mapping could reach automatic resolution
    is if the reference loader read batch data. It does not, and this
    asserts it against the source rather than against behaviour -- the same
    kind of claim T87 made about its column-scoped GRANT.
    """
    source = (BACKEND_ROOT / "app" / "repositories" / "reference.py").read_text(
        encoding="utf-8"
    )
    for table in (
        "load_batch",
        "proposed_mapping",
        "stg_raw",
        "stg_review_row",
        "worksheet_decision",
    ):
        assert table not in source, (
            f"{table!r} appears in the reference loader; a confirmed rough "
            f"mapping could then reach resolve_checkzone"
        )
    # RO19 (D-RO19-1): the loader does read a walk -- the reference view
    # `v_point_walk_order`, which is the measuring order. Walk *memory* is
    # batch-derived, so it could only arrive through a table forbidden above;
    # name the one legitimate walk rather than banning the word.
    walk_lines = {line.strip() for line in source.splitlines() if "walk" in line}
    assert all("v_point_walk_order" in line or "walk_rank" in line for line in walk_lines), (
        f"the reference loader names a walk that is not the measuring-order "
        f"view: {sorted(walk_lines)}"
    )


def test_the_cleaner_imports_no_repository_at_all():
    source = (BACKEND_ROOT / "app" / "domain" / "cleaner.py").read_text(
        encoding="utf-8"
    )
    assert "app.repositories" not in source
    assert "confirmed_walk_sets" not in source
    assert "sqlalchemy" not in source


def test_reference_data_carries_no_confirmed_walk():
    from app.domain.references import ReferenceData

    assert not [
        name for name in ReferenceData.__dataclass_fields__ if "walk" in name
    ]


def test_a_confirmed_rough_mapping_never_resolves_a_later_file(
    engineer, cleanup, walked, admin_conn  # noqa: F811
):
    """The whole point, measured: the same walk, uploaded again, still holds.

    The rough half of the first file's walk is confirmed. A second upload of
    the same labels must still **hold** every rough name, because nothing on
    the resolution path can read what was confirmed on a batch. If this ever
    starts passing silently, `01HOOD` has become a permanent alias and the
    month the plant reshuffles its walk a hood files as the wrong hood.
    """
    body = walk_of(engineer, walked["load_id"])
    created = engineer.post(
        PROPOSALS, json=confirm_body(body, walked["load_id"], "leak check")
    )
    assert created.status_code == 201, created.text

    tag = uuid.uuid4().hex[:6]
    [again] = sent(
        engineer, cleanup, admin_conn, f"t90-walk-again-{tag}.xlsx",
        sheet_bytes(walked["labels"], tag), PLANT,
    )
    rough = {
        row["raw_zone_text"]
        for row in body["walk"]["rows"]
        if row["specificity"] == SPECIFICITY_ROUGH
    }
    held = {
        held["raw_value"]
        for held in again["held_labels"]
        if held["display_group"] == "zone"
    }
    assert rough <= held, sorted(rough - held)


# =====================================================================
# D-90-5 / D-90-6 / D-90-14 -- the memory, and the one click
# =====================================================================
def test_an_unchanged_walk_pre_fills_goes_yellow_and_still_needs_one_click(
    engineer, cleanup, walked, admin_conn  # noqa: F811
):
    body = walk_of(engineer, walked["load_id"])
    created = engineer.post(
        PROPOSALS, json=confirm_body(body, walked["load_id"], "memory")
    )
    assert created.status_code == 201, created.text

    tag = uuid.uuid4().hex[:6]
    [again] = sent(
        engineer, cleanup, admin_conn, f"t90-walk-same-{tag}.xlsx",
        sheet_bytes(walked["labels"], tag), PLANT,
    )
    second = walk_of(engineer, again["batch"]["load_id"])["walk"]

    assert second["confirmed_before"] is True
    assert second["fingerprint_moved"] is False
    assert second["confirmed_load_id"] == walked["load_id"]
    assert second["red_count"] == 0
    assert second["yellow_count"] == len(second["rows"])
    # Pre-filled with the earlier answer, and still only a proposal.
    first_answers = {
        row["raw_zone_text"]: row["proposed_zone_code"]
        for row in body["walk"]["rows"]
    }
    for row in second["rows"]:
        assert row["prefilled_zone_code"] == first_answers[row["raw_zone_text"]]
        assert row["attention"] == "yellow"
    # D-90-5: one click, named, never silence.
    assert "accept all" in second["operator_message"].lower()


def test_a_changed_walk_carries_nothing_over_and_is_red(
    engineer, cleanup, walked, admin_conn  # noqa: F811
):
    """D-90-6 / D-90-12: the fingerprint moved, so every name is open again."""
    body = walk_of(engineer, walked["load_id"])
    created = engineer.post(
        PROPOSALS, json=confirm_body(body, walked["load_id"], "moved")
    )
    assert created.status_code == 201, created.text

    moved_labels = walk_labels(admin_conn, swap=True)
    assert [label for label, _z, _o in moved_labels] != [
        label for label, _z, _o in walked["labels"]
    ], "the swap changed nothing, so this would prove nothing"
    tag = uuid.uuid4().hex[:6]
    try:
        [again] = sent(
            engineer, cleanup, admin_conn, f"t90-walk-moved-{tag}.xlsx",
            sheet_bytes(moved_labels, tag), PLANT,
        )
        second = walk_of(engineer, again["batch"]["load_id"])["walk"]
        assert second["confirmed_before"] is True
        assert second["fingerprint"] != body["walk"]["fingerprint"]
        assert second["fingerprint_moved"] is True
        assert second["yellow_count"] == 0
        assert all(row["prefilled_zone_code"] is None for row in second["rows"])
        assert "walk has changed" in second["operator_message"]
    finally:
        forget(admin_conn, PLANT, MODEL, [label for label, _z, _o in moved_labels])


def test_both_counts_are_the_servers_numbers(engineer, walked):  # noqa: F811
    """D-90-14: "28 accepted, 4 still need you" is reported, not computed."""
    walk = walk_of(engineer, walked["load_id"])["walk"]
    reds = [row for row in walk["rows"] if row["attention"] == "red"]
    yellows = [row for row in walk["rows"] if row["attention"] == "yellow"]
    assert walk["red_count"] == len(reds)
    assert walk["yellow_count"] == len(yellows)
    assert walk["red_count"] + walk["yellow_count"] == len(walk["rows"])
    # There is no green.
    assert {row["attention"] for row in walk["rows"]} <= {"red", "yellow"}


@pytest.fixture(autouse=True)
def _t92_proposal_cleanup(admin_conn):
    """T95 D-95-2: this module's own mapping proposals, removed by **id**.

    Replaces the `payload ->> 'note' LIKE` / `payload::text LIKE` delete
    this module's cleanup used to run. The product writes those same notes
    and payloads, so that statement removed a genuine approved proposal
    from the owner's trial database. Same shape as T88 and T29: snapshot
    first, delete only ids that were not there and that carry one of this
    module's markers, then fail loudly rather than leak (T87 D-87-8).
    """
    before = row_keys(admin_conn, "proposed_mapping", "id")
    yield
    forget_proposals(admin_conn, before, ["T90", MARKER], 'T90 walk memory')
