"""T89 -- against the running application and database.

* **Part 1 / D-89-6.** The per-row picker and the guided match screen offer
  the **same list in the same order**, and every panel in it is one a
  confirmed pair may point at. Before T89 the per-row picker offered FTM's
  raw live list -- 64 panels, 32 of them refusable, which is the list the
  owner's screenshots show.
* A pick naming a panel that is live here but not a position on the model's
  own catalogue is refused **by name**, not by a foreign key after the fact.
* A panel this file has already used is shown, disabled, and labelled with
  the spelling that took it.
* **D-89-4.** Retiring a panel whose own name the same set does not teach is
  refused: retirement before aliasing would stop the name resolving.
* **D-89-9.** A pair still waiting for an Admin comes back **pre-selected**
  and marked as carried over, naming when and from which batch.
* **D-89-10.** Nothing writes the global `ref_checkzone_alias`, and the
  audit lists every one of its rows that reaches more than one plant.
* **Part 5 / D-88-7.** A sheet whose whole panel set is renamed says so once
  in the worksheet summary.

Every batch, proposal and map row is this module's own and is removed
again. The owner's trial batches are never touched, and no standard is ever
published.
"""

from __future__ import annotations

import uuid

import pytest

from app.repositories.mappings import ALIAS_TABLE_BY_KIND
from tests.test_t04_ingest import acknowledge_required, cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
    viewer,
    ws_url,
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


# =====================================================================
# helpers
# =====================================================================
def odd_panel(prefix: str = "T89ODDHOOD") -> str:
    return f"{prefix}{uuid.uuid4().hex[:4].upper()}"


def live_rows(admin_conn, model: str = MODEL) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT p.zone_code, p.point_no, p.tolerance_group,"
            "       (z.zone_code IS NOT NULL) AS mappable"
            "  FROM ref_plant_ws_point p"
            "  LEFT JOIN ref_model_zone z"
            "    ON z.model_code = p.model_code AND z.zone_code = p.zone_code"
            " WHERE p.plant_code = %s AND p.model_code = %s"
            "   AND p.retired_at IS NULL"
            " ORDER BY p.point_no",
            (PLANT, model),
        )
        return cur.fetchall()


def forget(
    admin_conn, plant: str, model: str, raws: list[str], since=SUITE_STARTED
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    The proposal half moved to `_t92_proposal_cleanup` below: a
    `payload::text LIKE` is not a scope, because the product writes the
    same payloads (D-95-2).

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
            (plant, model, [r.lower() for r in raws], since),
        )


def sheet_rows(panel: str, zone: str, orientation: str, n: int, tag: str,
               model_cell: str = MODEL_CELL) -> list[dict]:
    day = "2026-08-05"
    out = [
        {"Date": day, "Plant": PLANT, "Model": model_cell, "Color": COLOUR,
         "Checkzone": zone, "Tolerance Group": orientation,
         "CF": 55.0 + i, "Serial No": f"{tag}-{i}"}
        for i in range(n)
    ]
    out.append(
        {"Date": day, "Plant": PLANT, "Model": model_cell, "Color": COLOUR,
         "Checkzone": panel, "Tolerance Group": orientation,
         "CF": 61.0, "Serial No": f"{tag}-odd"}
    )
    return out


@pytest.fixture
def held_sheet(engineer, cleanup, admin_conn):  # noqa: F811
    """One FTM tab whose odd panel spelling holds, with two good rows."""
    rows = live_rows(admin_conn)
    assert rows, "FTM / P703 DBL RANGER has no live panel list here"
    zone, _point, orientation, mappable = next(r for r in rows if r[3])
    panel = odd_panel()
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t89-held-{tag}.xlsx",
        book(HEADERS, sheet_rows(panel, zone, orientation, 2, tag)), PLANT,
    )
    try:
        yield {
            "review": review,
            "load_id": review["batch"]["load_id"],
            "file_hash": review["batch"]["file_hash"],
            "panel": panel,
            "zone": zone,
            "orientation": orientation,
            "live": rows,
        }
    finally:
        forget(admin_conn, PLANT, MODEL, [panel])


def zone_group(review: dict, panel: str, model: str = MODEL) -> dict:
    found = [
        h for h in review["held_labels"]
        if h["display_group"] == "zone"
        and h["raw_value"] == panel
        and h["model_code"] == model
    ]
    assert len(found) == 1, [
        (h["raw_value"], h["model_code"]) for h in review["held_labels"]
    ]
    return found[0]


def held_panel(engineer, load_id: int, panel: str, model: str = MODEL) -> dict:  # noqa: F811
    response = engineer.get(
        PANEL_MATCH, params={"load_id": load_id, "model_code": model}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    found = [h for h in body["held_panels"] if h["raw_zone_text"] == panel]
    assert len(found) == 1, [h["raw_zone_text"] for h in body["held_panels"]]
    return found[0]


# =====================================================================
# Part 1 -- D-89-6: one picker
# =====================================================================
def test_the_two_pickers_offer_the_same_list_in_the_same_order(
    engineer, held_sheet  # noqa: F811
):
    """The claim, as one assertion: there is one list, not two."""
    group = zone_group(held_sheet["review"], held_sheet["panel"])
    screen = held_panel(engineer, held_sheet["load_id"], held_sheet["panel"])
    assert group["candidates"] == screen["choosable"]
    assert group["candidates"], "an empty picker would prove nothing"


def test_the_per_row_picker_no_longer_offers_a_refusable_panel(
    engineer, held_sheet  # noqa: F811
):
    """FTM's shape, measured: the picker was the live list, which is wider.

    The whole defect in one comparison -- what is live at this plant x
    model, against what a confirmed pair may actually point at.
    """
    live = held_sheet["live"]
    mappable = [r[0] for r in live if r[3]]
    refusable = [r[0] for r in live if not r[3]]
    group = zone_group(held_sheet["review"], held_sheet["panel"])
    offered = set(group["candidates"])
    assert offered <= set(mappable)
    assert not offered & set(refusable)
    if refusable:
        # This is FTM today: 64 live, 32 of them unusable as a target.
        assert len(mappable) < len(live)


def test_the_picker_is_filtered_by_the_orientation_the_file_wrote(
    engineer, held_sheet  # noqa: F811
):
    group = zone_group(held_sheet["review"], held_sheet["panel"])
    wanted = held_sheet["orientation"]
    by_code = {r[0]: r[2] for r in held_sheet["live"]}
    assert group["orientations"] == [wanted]
    assert {by_code[z] for z in group["candidates"]} == {wanted}


def test_a_panel_live_here_but_off_the_model_catalogue_is_refused_by_name(
    engineer, held_sheet  # noqa: F811
):
    """The refusal arrives as a sentence, not as a foreign-key error."""
    refusable = [r[0] for r in held_sheet["live"] if not r[3]]
    if not refusable:
        pytest.skip(f"{PLANT} / {MODEL} has no live panel off its catalogue")
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ALIAS_CHECKZONE",
            "load_id": held_sheet["load_id"],
            "payload": {
                "raw_value": held_sheet["panel"],
                "zone_code": refusable[0],
                "plant_code": PLANT,
                "model_code": MODEL,
            },
        },
    )
    assert response.status_code == 422, response.text
    assert "not a position on" in response.text
    assert "Nothing was written" in response.text


def test_a_panel_this_file_already_used_is_shown_disabled_and_labelled(
    engineer, admin, cleanup, admin_conn  # noqa: F811
):
    """D-89-6's taken half, on a batch that really loaded onto a panel."""
    rows = live_rows(admin_conn)
    zone, _p, orientation, _m = next(r for r in rows if r[3])
    panel = odd_panel()
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t89-taken-{tag}.xlsx",
        book(HEADERS, sheet_rows(panel, zone, orientation, 2, tag)), PLANT,
    )
    load_id = review["batch"]["load_id"]
    try:
        acknowledge_required(admin, review)
        commit = engineer.post(f"/api/v1/batches/{load_id}/commit")
        assert commit.status_code == 200, commit.text

        screen = held_panel(engineer, load_id, panel)
        blocked = {b["zone_code"]: b for b in screen["blocked"]}
        assert zone in blocked, screen["blocked"]
        assert blocked[zone]["label"] == f"already matched to {zone}"
        assert blocked[zone]["taken_by"] == zone
        # And it is out of the list a person may choose from.
        assert zone not in screen["choosable"]

        # The per-row picker says exactly the same thing.
        again = engineer.get(f"/api/v1/batches/{load_id}")
        assert again.status_code == 200, again.text
        group = zone_group(again.json(), panel)
        assert group["candidates"] == screen["choosable"]
        assert [b["zone_code"] for b in group["blocked_candidates"]] == [
            b["zone_code"] for b in screen["blocked"]
        ]
    finally:
        forget(admin_conn, PLANT, MODEL, [panel])


# =====================================================================
# D-89-4 -- the order is fixed
# =====================================================================
def _zone_set(load_id: int, matches: list[dict], retire: list[str]) -> dict:
    return {
        "kind": "ZONE",
        "load_id": load_id,
        "payload": {
            "plant_code": PLANT,
            "model_code": MODEL,
            "load_id": load_id,
            "matches": matches,
            **(
                {"retire": {"zone_codes": retire,
                            "reason": "T89 test: superseded by the new names"}}
                if retire
                else {}
            ),
            "decided_by": "T89 test",
            "method": "the test said so",
            "note": "T89 D-89-4",
        },
    }


def test_retiring_a_panel_this_set_does_not_teach_is_refused(
    engineer, held_sheet, admin_conn  # noqa: F811
):
    """Retirement before aliasing: refused, and told why (D-89-4).

    The sheet has loaded rows onto `zone`, so that panel's own name is a
    name this file uses. Retiring it while saying nothing about what the
    name means instead would stop it resolving on the next upload.
    """
    mappable = [r[0] for r in held_sheet["live"] if r[3]]
    target = next(z for z in mappable if z != held_sheet["zone"])
    response = engineer.post(
        PROPOSALS,
        json=_zone_set(
            held_sheet["load_id"],
            [{"raw_zone_text": held_sheet["panel"], "zone_code": target}],
            [held_sheet["zone"]],
        ),
    )
    assert response.status_code == 422, response.text
    assert "nothing here says the meaning of" in response.text  # T92 reworded; the claim is unchanged
    assert "D-89-4" in response.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at FROM ref_plant_ws_point WHERE plant_code = %s"
            "   AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, held_sheet["zone"]),
        )
        assert cur.fetchone()[0] is None, "a refused set retired a panel"


def test_retiring_a_panel_no_name_of_this_file_depends_on_is_allowed(
    engineer, held_sheet, admin_conn  # noqa: F811
):
    """The complement, so the refusal is a rule and not a blanket.

    Nothing is applied here -- a ZONE set is PROPOSED and waits for an
    Admin -- so the proposal being accepted is the whole claim.
    """
    mappable = [r[0] for r in held_sheet["live"] if r[3]]
    spare = [z for z in mappable if z != held_sheet["zone"]]
    target, retire = spare[0], spare[1]
    response = engineer.post(
        PROPOSALS,
        json=_zone_set(
            held_sheet["load_id"],
            [{"raw_zone_text": held_sheet["panel"], "zone_code": target}],
            [retire],
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PROPOSED"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at FROM ref_plant_ws_point WHERE plant_code = %s"
            "   AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, retire),
        )
        assert cur.fetchone()[0] is None, "a PROPOSED set retired a panel"
        cur.execute(
            "DELETE FROM proposed_mapping WHERE id = %s",
            (response.json()["id"],),
        )


# =====================================================================
# D-89-9 -- the decision comes back pre-selected
# =====================================================================
def test_a_pair_waiting_for_an_admin_comes_back_pre_selected(
    engineer, held_sheet, admin_conn  # noqa: F811
):
    """The case the owner asked about: it has not been approved yet."""
    mappable = [r[0] for r in held_sheet["live"] if r[3]]
    target = next(z for z in mappable if z != held_sheet["zone"])
    panel = held_sheet["panel"]
    proposed = engineer.post(
        PROPOSALS,
        json=_zone_set(
            held_sheet["load_id"],
            [{"raw_zone_text": panel, "zone_code": target}],
            [],
        ),
    )
    assert proposed.status_code == 201, proposed.text
    try:
        screen = held_panel(engineer, held_sheet["load_id"], panel)
        carried = screen["carried_over"]
        assert carried is not None, screen
        assert carried["kind"] == "pending"
        assert carried["zone_code"] == target
        assert str(held_sheet["load_id"]) in carried["reason"]
        assert "waiting for an Admin" in carried["reason"]
        # Pre-selected, never applied: no map row exists yet.
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ref_plant_zone_map WHERE raw_zone_text = %s",
                (panel.lower(),),
            )
            assert cur.fetchone()[0] == 0

        # The per-row picker carries the same pre-fill.
        review = engineer.get(f"/api/v1/batches/{held_sheet['load_id']}")
        group = zone_group(review.json(), panel)
        assert group["carried_over"] == carried
    finally:
        with admin_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM proposed_mapping WHERE id = %s",
                (proposed.json()["id"],),
            )


def test_a_taught_spelling_does_not_come_back_as_a_held_row_at_all(
    engineer, held_sheet, admin_conn  # noqa: F811
):
    """D-89-9's first sentence: normally the question does not return.

    Teaching the pair and re-reading the sheet loads the row, so there is
    no held group left to pre-fill.
    """
    panel = held_sheet["panel"]
    taught = engineer.post(
        PROPOSALS,
        json={
            "kind": "ALIAS_CHECKZONE",
            "load_id": held_sheet["load_id"],
            "payload": {
                "raw_value": panel, "zone_code": held_sheet["zone"],
                "plant_code": PLANT, "model_code": MODEL,
            },
        },
    )
    assert taught.status_code == 201, taught.text
    review = wait_for(engineer, held_sheet["load_id"])
    remaining = [
        h for h in review["held_labels"]
        if h["display_group"] == "zone" and h["raw_value"] == panel
    ]
    assert remaining == [], remaining


# =====================================================================
# D-89-10 -- plant separation stays a property of the table
# =====================================================================
def test_the_application_has_no_write_path_for_the_global_alias_table():
    """It is read-only to the app, and T89 does not change that."""
    assert "ref_checkzone_alias" not in set(ALIAS_TABLE_BY_KIND.values())


def test_the_audit_lists_every_global_alias_reaching_more_than_one_plant(
    admin_conn,
):
    """D-89-10: the shared layer is listed, not assumed."""
    from sqlalchemy import create_engine

    from scripts.audit_panel_identities import shared_global_aliases
    from scripts.run_standing_8012 import keyword_dsn_to_url, load_env_test
    import os

    load_env_test()
    engine = create_engine(keyword_dsn_to_url(os.environ["T01_ADMIN_DSN"]))
    try:
        rows = shared_global_aliases(engine, None)
    finally:
        engine.dispose()
    assert rows, "the 83 pre-existing global rows reach several plants"
    for row in rows:
        assert int(row["plants"]) > 1
        assert "," in row["which_plants"]


# =====================================================================
# Part 5 / D-88-7 -- a renaming is one event
# =====================================================================
def test_a_whole_set_rename_is_named_once_in_the_worksheet(
    engineer, cleanup, admin_conn  # noqa: F811
):
    """The sheet the owner actually uploaded, in miniature.

    Every panel name is new, the count matches the panels a match may point
    at, and the Horizontal / Vertical split is the same -- so the worksheet
    says "this looks like a renaming" instead of listing one complaint per
    row.
    """
    live = live_rows(admin_conn)
    mappable = [r for r in live if r[3]]
    if not mappable:
        pytest.skip(f"{PLANT} / {MODEL} has no mappable panel list here")
    tag = uuid.uuid4().hex[:6]
    day = "2026-08-06"
    names: list[str] = []
    rows: list[dict] = []
    for i, (_zone, _point, orientation, _m) in enumerate(mappable):
        name = f"T89REN{i:02d}HOOD{tag[:3].upper()}"
        names.append(name)
        rows.append({
            "Date": day, "Plant": PLANT, "Model": MODEL_CELL, "Color": COLOUR,
            "Checkzone": name, "Tolerance Group": orientation,
            "CF": 55.0 + (i % 7), "Serial No": f"{tag}-{i}",
        })
    [review] = sent(
        engineer, cleanup, admin_conn, f"t89-rename-{tag}.xlsx",
        book(HEADERS, rows), PLANT,
    )
    try:
        sheet = engineer.get(
            ws_url(PLANT, review["batch"]["file_hash"])
        )
        assert sheet.status_code == 200, sheet.text
        body = sheet.json()
        signals = [
            s for tab in body["sheets"] for s in tab["panel_rename"]
        ]
        assert len(signals) == 1, signals
        signal = signals[0]
        assert signal["model_code"] == MODEL
        assert signal["file_panel_count"] == len(mappable)
        assert signal["live_panel_count"] == len(mappable)
        assert "looks like a renaming" in signal["operator_message"]
        # It is in the summary a reviewer reads before the row table.
        assert any(
            "looks like a renaming" in line for line in body["checklist"]
        )
    finally:
        forget(admin_conn, PLANT, MODEL, names)


def test_a_sheet_with_one_odd_name_is_not_called_a_renaming(
    engineer, held_sheet  # noqa: F811
):
    """The claim stays narrow: one unknown name is a typo, not an event."""
    sheet = engineer.get(ws_url(PLANT, held_sheet["file_hash"]))
    assert sheet.status_code == 200, sheet.text
    for tab in sheet.json()["sheets"]:
        assert tab["panel_rename"] == [], tab["panel_rename"]


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
    forget_proposals(admin_conn, before, ["T89"], 'T89 one picker')
