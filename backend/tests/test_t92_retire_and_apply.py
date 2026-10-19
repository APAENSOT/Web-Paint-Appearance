"""T92 -- a confirmed walk states a name's meaning, and retirement stays safe.

T91 built the apply and the repair and dry-ran both. The retirement guard
then refused the last step, correctly: 28 of FTM's 32 numbered names can
never be permanent aliases (D-90-3), and the guard only recognised a
meaning stated in `matches`. A rough name's meaning lives in the set's
**walk**, recorded on the batch (D-90-11), by design -- and the guard did
not look there, so 28 points could never retire and audit finding 3 could
never reach 0.

Four claims:

* **D-92-1.** A panel retires when its own name is paired in (a) the set's
  `matches`, (b) the set's own `walk` block, or (c) a prior confirmed walk
  of this `(plant, model)` naming the same panel. Refused otherwise, and
  the message says **which** path was missing;
* **D-92-2.** A *contradicted* name is not stated: if prior walks name
  different panels for one spelling -- FTM's `13LFRDOOR`, a pillar in
  August and a door in September -- path (c) does not apply, and only this
  set can state it;
* **D-92-3**, the safety the guard exists for. Retirement may never make a
  file resolve **wrongly**. After a point is retired, a file writing its
  name is **held**, pre-filled from the last confirmed walk, and never
  re-pointed to another panel. Held is safe; silently resolving is not;
* **D-92-4.** The order is unchanged: retirement before aliasing is still
  refused.

Every panel row, batch, proposal and map row is this module's own and is
removed again. The real FTM panels are owner-locked seed rows (T58) and no
test here touches one: the point that gets retired is a spare this module
inserted and deletes, the way T86's retirement test does.
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
from tests.test_t89_one_picker import (  # noqa: F401
    _zone_set,
    held_sheet,
)
from tests.test_t90_walk_memory import (  # noqa: F401
    MODEL,
    MODEL_CELL,
    PANEL_MATCH,
    PLANT,
    PROPOSALS,
    canonical_walk,
)

from tests.test_t04_ingest import forget_proposals
from tests.conftest import SUITE_STARTED, row_keys

pytestmark = pytest.mark.ingest

COLOUR = "Ignite Orange"

#: Synthetic held labels, marked so they are not FTM's own live gold (the
#: same reason T90 marks its labels): they exist only so the sheet has a
#: walk around the panel being retired.
MARKER = "TX"


def sheet_bytes(rows: list[tuple[str, str]], tag: str) -> bytes:
    """One FTM tab: `(checkzone, tolerance_group)` in file order."""
    return book(
        HEADERS,
        [
            {
                "Date": "2026-09-14",
                "Plant": PLANT,
                "Model": MODEL_CELL,
                "Color": COLOUR,
                "Checkzone": checkzone,
                "Tolerance Group": tolerance,
                "CF": 55.0 + index,
                "Serial No": f"T92-{tag}",
            }
            for index, (checkzone, tolerance) in enumerate(rows)
        ],
    )


@pytest.fixture()
def spare_point(admin_conn):
    """A live FTM P703 panel this module inserted, to retire and remove.

    A catalogue code FTM's P703 list does not carry, parked on a point
    number nothing lives at -- T86's `spare_panel` exactly. The seed rows
    stay untouched, and the teardown deletes the row rather than
    un-retiring it, so nothing of this test survives either outcome.
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
            "VALUES (%s, %s, %s, %s, %s, 'T92 test panel -- delete me')",
            (PLANT, MODEL, zone_code, 96, tolerance),
        )
    try:
        yield {"zone_code": zone_code, "tolerance_group": tolerance}
    finally:
        with admin_conn.cursor() as cur:
            # T98 (D-98-2): bounded to rows this run inserted, like every
            # other reference cleanup -- the spare code is spare now, but a
            # live row is not this fixture's to delete.
            cur.execute(
                "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
                "   AND model_code = %s AND zone_code = %s"
                "   AND created_at >= %s",
                (PLANT, MODEL, zone_code, SUITE_STARTED),
            )
            cur.execute(
                "DELETE FROM ref_plant_ws_point WHERE plant_code = %s "
                "  AND model_code = %s AND zone_code = %s"
                "  AND created_at >= %s",
                (PLANT, MODEL, zone_code, SUITE_STARTED),
            )


def _forget(
    admin_conn, plant: str, model: str, labels: list[str], since=SUITE_STARTED
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    The `note LIKE 'T92 %'` proposal delete moved to
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


@pytest.fixture()
def writes_the_point(engineer, cleanup, admin_conn, spare_point):  # noqa: F811
    """A sheet that writes the spare panel's own name, so it resolves today.

    This is the shape the guard is about: the file uses that panel's name,
    so retiring the panel takes the name's meaning away unless something
    says what it means instead. Two synthetic held labels ride along so the
    sheet has a walk at all.
    """
    walk = canonical_walk(admin_conn)
    assert len(walk) >= 2, "FTM / P703 DBL RANGER has no canonical walk here"
    targets = [zone for _no, zone, _o in walk]
    labels = [
        (spare_point["zone_code"], spare_point["tolerance_group"]),
        (f"01{MARKER}HOOD", walk[0][2]),
        (f"02{MARKER}HOOD", walk[1][2]),
    ]
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t92-{tag}.xlsx",
        sheet_bytes(labels, tag), PLANT,
    )
    try:
        yield {
            "review": review,
            "load_id": review["batch"]["load_id"],
            "point": spare_point["zone_code"],
            "tolerance": spare_point["tolerance_group"],
            "labels": [label for label, _t in labels],
            "orientations": [walk[0][2], walk[1][2]],
            "targets": targets,
            "tag": tag,
        }
    finally:
        _forget(admin_conn, PLANT, MODEL, [label for label, _t in labels])


def _set(
    load_id: int,
    note: str,
    *,
    matches: list[dict],
    walk_pairs: list[dict],
    retire: list[str] | None = None,
    fingerprint: str | None = None,
) -> dict:
    payload: dict = {
        "plant_code": PLANT,
        "model_code": MODEL,
        "load_id": load_id,
        "matches": matches,
        "decided_by": "T92 test operator",
        "method": "T92 guard test",
        "note": f"T92 {note}",
    }
    if walk_pairs:
        payload["walk"] = {
            "fingerprint": fingerprint
            or "|".join("HOOD" for _ in walk_pairs),
            "pairs": walk_pairs,
        }
    if retire:
        payload["retire"] = {
            "zone_codes": retire,
            "reason": "T92 test: superseded by the canonical names",
        }
    return {"kind": "ZONE", "load_id": load_id, "payload": payload}


def _pair(raw: str, zone: str, specificity: str = "rough") -> dict:
    return {
        "raw_zone_text": raw,
        "zone_code": zone,
        "specificity": specificity,
        "rule": "none",
        "attention": "red",
    }


# =====================================================================
# D-92-1 -- the three ways a meaning is stated
# =====================================================================
def test_a_name_paired_only_in_the_walk_may_now_retire_its_panel(
    engineer, admin, writes_the_point, admin_conn  # noqa: F811
):
    """D-92-1 (b): the change this task is. Nothing is in `matches`.

    The pair rides in the set's `walk` block, which is where a rough name's
    meaning has lived since T90 -- and before T92 this exact set was
    refused, which is why FTM's 28 numbered points could never retire.
    """
    point = writes_the_point["point"]
    canonical = writes_the_point["targets"][0]
    created = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "retire with the meaning in the walk",
            matches=[],
            walk_pairs=[_pair(point, canonical)],
            retire=[point],
        ),
    )
    assert created.status_code == 201, created.text
    approved = admin.post(f"{PROPOSALS}/{created.json()['id']}/approve", json={})
    assert approved.status_code == 200, approved.text

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at IS NOT NULL, retired_reason FROM ref_plant_ws_point"
            " WHERE plant_code = %s AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, point),
        )
        [(retired, reason)] = cur.fetchall()
    # ADR 0005: the row is still there, marked, with the owner's words.
    assert retired is True
    assert "superseded" in reason
    # And nothing was learned forever: the walk is not a permanent alias.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_zone_map WHERE plant_code = %s"
            "   AND model_code = %s AND raw_zone_text = %s",
            (PLANT, MODEL, point.lower()),
        )
        assert cur.fetchone()[0] == 0


def test_a_name_paired_nowhere_is_still_refused_and_the_message_names_the_gap(
    engineer, writes_the_point, admin_conn  # noqa: F811
):
    """D-92-1: widened, not removed. Three paths missing is still a refusal."""
    point = writes_the_point["point"]
    response = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "retire with nothing stating it",
            matches=[],
            walk_pairs=[_pair(f"01{MARKER}HOOD", writes_the_point["targets"][0])],
            retire=[point],
        ),
    )
    assert response.status_code == 422, response.text
    message = response.json()["message"]
    assert point in message
    # The reader is told which of the three ways was missing.
    assert "none in this set's walk" in message
    assert "D-92-1" in message
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at FROM ref_plant_ws_point WHERE plant_code = %s"
            "   AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, point),
        )
        assert cur.fetchone()[0] is None, "a refused set retired a panel"


def test_an_earlier_confirmed_walk_states_the_meaning_on_its_own(
    engineer, admin, writes_the_point, admin_conn  # noqa: F811
):
    """D-92-1 (c): the plant answered this name once and has not disagreed."""
    point = writes_the_point["point"]
    canonical = writes_the_point["targets"][0]
    first = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "the walk, confirmed and nothing retired",
            matches=[],
            walk_pairs=[_pair(point, canonical)],
        ),
    )
    assert first.status_code == 201, first.text

    # A second set says nothing about this name at all, and may still
    # retire it: history explains it.
    second = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "retire on history alone",
            matches=[],
            walk_pairs=[_pair(f"01{MARKER}HOOD", writes_the_point["targets"][0])],
            retire=[point],
        ),
    )
    assert second.status_code == 201, second.text
    approved = admin.post(f"{PROPOSALS}/{second.json()['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at IS NOT NULL FROM ref_plant_ws_point"
            " WHERE plant_code = %s AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, point),
        )
        assert cur.fetchone()[0] is True


# =====================================================================
# D-92-2 -- a name the plant disagrees with itself about is not stated
# =====================================================================
def test_a_contradicted_name_is_not_explained_by_history(
    engineer, admin, writes_the_point, admin_conn  # noqa: F811
):
    """D-92-2, the `13LFRDOOR` case: two earlier answers, so path (c) is out.

    Each file is believed about itself (D-91-1), which is exactly why the
    name on its own explains nothing -- so only the set in hand may state
    what it means here, and a set that says nothing about it is refused.
    """
    point = writes_the_point["point"]
    first, second = writes_the_point["targets"][0], writes_the_point["targets"][1]
    for note, target in (("first answer", first), ("second answer", second)):
        created = engineer.post(
            PROPOSALS,
            json=_set(
                writes_the_point["load_id"],
                note,
                matches=[],
                walk_pairs=[_pair(point, target)],
            ),
        )
        assert created.status_code == 201, created.text

    refused = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "retire a contradicted name on history",
            matches=[],
            walk_pairs=[_pair(f"01{MARKER}HOOD", first)],
            retire=[point],
        ),
    )
    assert refused.status_code == 422, refused.text
    message = refused.json()["message"]
    assert point in message
    assert "confirmed as a different panel by an earlier upload" in message
    assert "D-92-2" in message

    # Said in this set's own walk, it retires -- (b) is still open to it.
    allowed = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "retire a contradicted name this set states",
            matches=[],
            walk_pairs=[_pair(point, first)],
            retire=[point],
        ),
    )
    assert allowed.status_code == 201, allowed.text
    approved = admin.post(f"{PROPOSALS}/{allowed.json()['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at IS NOT NULL FROM ref_plant_ws_point"
            " WHERE plant_code = %s AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, point),
        )
        assert cur.fetchone()[0] is True


# =====================================================================
# D-92-3 -- the safety the guard exists for, stated directly
# =====================================================================
def test_after_retirement_the_name_is_held_and_never_re_pointed(
    engineer, admin, cleanup, writes_the_point, admin_conn  # noqa: F811
):
    """D-92-3. Held is safe. Silently resolving to another panel is not.

    The point is retired with its meaning in the walk, then the same file is
    uploaded again. What must happen to that name:

    * it must **hold** -- no gold entry and no permanent alias, so nothing
      on the resolution path can answer it (D-90-11);
    * it must be **pre-filled** on the match screen from the last confirmed
      walk, so the owner answers it in one click (D-90-5);
    * it must **never** load onto some other panel. That is the one outcome
      retirement is not allowed to cause, and it is what the guard is for.
    """
    point = writes_the_point["point"]
    canonical = writes_the_point["targets"][0]
    # The walk is confirmed under the fingerprint the SERVER reads from this
    # sheet, not a hand-made one: a pre-fill only carries over while the
    # fingerprint is unchanged (D-90-6), so a test that invented one would
    # be proving nothing.
    screen = engineer.get(
        PANEL_MATCH,
        params={"load_id": writes_the_point["load_id"], "model_code": MODEL},
    )
    assert screen.status_code == 200, screen.text
    walk = screen.json()["walk"]
    assert walk, "this sheet produced no walk block"
    pairs = [
        _pair(
            row["raw_zone_text"],
            canonical
            if row["raw_zone_text"].strip().casefold() == point.casefold()
            else writes_the_point["targets"][index + 1],
        )
        for index, row in enumerate(walk["rows"])
    ]
    created = engineer.post(
        PROPOSALS,
        json=_set(
            writes_the_point["load_id"],
            "retire for the safety proof",
            matches=[],
            walk_pairs=pairs,
            retire=[point],
            fingerprint=walk["fingerprint"],
        ),
    )
    assert created.status_code == 201, created.text
    assert (
        admin.post(
            f"{PROPOSALS}/{created.json()['id']}/approve", json={}
        ).status_code
        == 200
    )

    # The same labels again, after the retirement: same walk, same
    # fingerprint, so the answer that was confirmed is carried over.
    tag = uuid.uuid4().hex[:6]
    [again] = sent(
        engineer, cleanup, admin_conn, f"t92-after-{tag}.xlsx",
        sheet_bytes(
            [
                (point, writes_the_point["tolerance"]),
                (f"01{MARKER}HOOD", writes_the_point["orientations"][0]),
                (f"02{MARKER}HOOD", writes_the_point["orientations"][1]),
            ],
            tag,
        ),
        PLANT,
    )
    load_id = again["batch"]["load_id"]

    held = {
        entry["raw_value"]
        for entry in again["held_labels"]
        if entry["display_group"] == "zone"
    }
    assert point in held, sorted(held)

    # Nothing loaded onto any panel under that name, and in particular not
    # onto the panel the walk says it is.
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,)
        )
        assert cur.fetchone()[0] == 0, "a retired name still loaded a fact"
        cur.execute(
            "SELECT count(*) FROM stg_review_row"
            " WHERE load_id = %s AND disposition = 'LOAD'",
            (load_id,),
        )
        assert cur.fetchone()[0] == 0

    # And the screen pre-fills it from the walk that was confirmed.
    screen = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": MODEL}
    )
    assert screen.status_code == 200, screen.text
    body = screen.json()
    row = next(
        (
            entry
            for entry in (body["walk"] or {}).get("rows", [])
            if entry["raw_zone_text"].strip().casefold() == point.casefold()
        ),
        None,
    )
    assert row is not None, "the retired name is not even on the walk"
    assert row["prefilled_zone_code"] == canonical, row
    # Pre-filled is not applied: it is still a question (D-90-5).
    assert row["attention"] in {"yellow", "red"}


# =====================================================================
# D-92-4 -- the order is unchanged
# =====================================================================
def test_retirement_before_aliasing_is_still_refused(
    engineer, held_sheet, admin_conn  # noqa: F811
):
    """D-89-4's gate, re-run because T92 is the task that touched the guard.

    The sheet has loaded rows onto `zone`, this set says nothing about that
    panel's own name in either place, and no earlier walk here has either.
    """
    mappable = [row[0] for row in held_sheet["live"] if row[3]]
    target = next(zone for zone in mappable if zone != held_sheet["zone"])
    response = engineer.post(
        PROPOSALS,
        json=_zone_set(
            held_sheet["load_id"],
            [{"raw_zone_text": held_sheet["panel"], "zone_code": target}],
            [held_sheet["zone"]],
        ),
    )
    assert response.status_code == 422, response.text
    assert "D-89-4" in response.text
    assert "this set's walk" in response.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at FROM ref_plant_ws_point WHERE plant_code = %s"
            "   AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, held_sheet["zone"]),
        )
        assert cur.fetchone()[0] is None, "a refused set retired a panel"


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
    forget_proposals(admin_conn, before, ["T92", MARKER], 'T92 retire and apply')
