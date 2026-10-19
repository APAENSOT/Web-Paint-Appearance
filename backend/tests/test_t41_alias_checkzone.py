"""T41 -- `ALIAS_CHECKZONE`: an Engineer maps one panel spelling (D-31).

Claims, against the running application, worker and database:

* A held `UNKNOWN_CHECKZONE` spelling is teachable as `ALIAS_CHECKZONE`, with
  that model's existing zone codes as candidates and the model named.
* Proposing it applies in the request: one `ref_plant_zone_map` row
  (`ENGINEER_ALIAS`, APPROVED, no owner proof), audited, and the pending
  sheet replays so the held rows load.
* A zone that is not on the model -- minted, or another model's -- is 422
  and writes nothing. A blank / `(None)` panel is never teachable.
* A spelling written on two models is not teachable until the model is
  settled. The same map again is a no-op; a different zone is 409.
* `ALIAS_PLANT` / `ALIAS_PAINTLINE` stay 501; a Viewer gets 403. T29 ZONE
  sets are untouched (their own tests).
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_t04_ingest import forget_proposals

from tests.conftest import SUITE_STARTED, row_keys

from tests.test_t04_ingest import cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    rows,
    sent,
    viewer,
)

pytestmark = pytest.mark.ingest

PROPOSALS = "/api/v1/mappings/proposals"


def odd_panel() -> str:
    return f"T41 ODD PANEL {uuid.uuid4().hex[:6].upper()}"


def propose(client, payload: dict, load_id: int | None = None):
    body = {"kind": "ALIAS_CHECKZONE", "payload": payload}
    if load_id is not None:
        body["load_id"] = load_id
    return client.post(PROPOSALS, json=body)


def map_rows(admin_conn, raw: str) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, zone_code, confidence, proposal_method, "
            "       approved_by IS NOT NULL, proof_hash, verified_by "
            "  FROM ref_plant_zone_map WHERE raw_zone_text = lower(%s)",
            (raw,),
        )
        return cur.fetchall()


def forget_map(
    admin_conn, plant: str, model: str, raw: str, since=SUITE_STARTED
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    `T41 ODD PANEL <hex>` is a spelling nothing else writes, so this had
    not reached anyone else's row -- but the plant and model are named
    anyway, so the rule holds at every site and the guard needs no
    exception list.

    **T98 (D-98-2):** and bounded at the moment the suite started, so no
    row written before the run can be reached whatever it is spelled.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
            "   AND model_code = %s AND raw_zone_text = lower(%s)"
            "   AND created_at >= %s",
            (plant, model, raw, since),
        )


def held(review: dict, reason: str = "UNKNOWN_CHECKZONE") -> list[dict]:
    return [h for h in review["held_labels"] if h["reason"] == reason]


@pytest.fixture()
def held_panel(engineer, cleanup, admin_conn):
    """A pending AAT U704 sheet: two good rows and one odd panel spelling."""
    raw = odd_panel()
    good = rows(2)
    odd = [{**good[0], "Checkzone": raw}]
    [review] = sent(engineer, cleanup, admin_conn, "t41-panel.xlsx", book(HEADERS, good + odd))
    try:
        yield raw, review
    finally:
        forget_map(admin_conn, "AAT", "U704", raw)


# =====================================================================
# held label
# =====================================================================
def test_an_unknown_panel_is_teachable_onto_that_models_zones(
    held_panel, admin_conn
):
    raw, review = held_panel
    assert review["reject_reasons"] == {"UNKNOWN_CHECKZONE": 1}
    [label] = held(review)
    assert label["raw_value"] == raw
    assert label["teachable_kind"] == "ALIAS_CHECKZONE"
    assert label["model_code"] == "U704"
    assert "RRHOOD" in label["candidates"]
    # T89 (D-89-6): the order is the match screen's -- name-scored
    # suggestions first, then the rest of the choosable list in walk order
    # -- because the per-row picker and the match screen are now one list
    # built by one call. It was alphabetical when this picker had its own
    # list. Every entry is still a panel of this model alone (D-31), and
    # now also one the approval path accepts.
    assert label["candidates"], label
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT p.zone_code FROM ref_plant_ws_point p"
            "  JOIN ref_model_zone z ON z.model_code = p.model_code"
            "   AND z.zone_code = p.zone_code"
            " WHERE p.plant_code = 'AAT' AND p.model_code = 'U704'"
            "   AND p.retired_at IS NULL AND p.tolerance_group = 'Horizontal'"
        )
        allowed = {row[0] for row in cur.fetchall()}
    assert set(label["candidates"]) == allowed


def test_a_none_panel_is_never_teachable(engineer, cleanup, admin_conn):
    good = rows(1)
    none_panel = [{**good[0], "Checkzone": "(None)"}]
    [review] = sent(engineer, cleanup, admin_conn, "t41-none.xlsx", book(HEADERS, good + none_panel))
    labels = [h for h in review["held_labels"] if h["raw_value"] == "(None)"]
    assert labels and labels[0]["teachable_kind"] is None
    assert labels[0]["candidates"] == [] and labels[0]["model_code"] is None

    refused = propose(engineer, {
        "raw_value": "(None)", "zone_code": "RRHOOD",
        "plant_code": "AAT", "model_code": "U704",
    }, review["batch"]["load_id"])
    assert refused.status_code == 422, refused.text


def test_a_spelling_on_two_models_is_two_teachable_questions(
    engineer, cleanup, admin_conn
):
    """T88 (D-88-1) reverses what this test used to assert.

    Until T88 a spelling written on two models was refused outright --
    `teachable_kind`, `model_code` and `candidates` all blanked, with the
    sentence "map it after the model is settled". There is nothing to
    settle: ``X`` on U704 and ``X`` on P703 DBL RANGER are two independent
    pairs with two independent answers, and refusing both is what kept the
    owner's September file (741 held rows, every spelling on both models)
    out of a screen built for it.

    What T41 actually guarantees is unchanged and is asserted below: a pair
    is confirmed against **that** model's own panels, never a union (D-31).
    """
    raw = odd_panel()
    # T89 (D-89-6): the picker is orientation-filtered, and AAT's two models
    # differ only in their VERTICAL block (24 panels against 25) -- their
    # seven horizontal panels are the same seven. So the claim below is
    # asked of a vertical row, where there is something to tell apart.
    vertical = {"Tolerance Group": "Vertical"}
    u704 = rows(1, Checkzone=raw, **vertical)
    ranger = rows(1, Checkzone=raw, Model="P703 DBL RANGER", **vertical)
    [review] = sent(engineer, cleanup, admin_conn, "t41-two.xlsx", book(HEADERS, u704 + ranger))
    labels = held(review)
    assert len(labels) == 2, [(x["raw_value"], x["model_code"]) for x in labels]
    by_model = {x["model_code"]: x for x in labels}
    assert sorted(by_model) == ["P703 DBL RANGER", "U704"]
    for model, label in by_model.items():
        assert label["teachable_kind"] == "ALIAS_CHECKZONE", label
        assert label["candidates"], label
        assert label["count"] == 1, "its own rows, not both models' together"
        assert model in label["operator_message"]
    # D-31: each question offers only its own model's panels.
    assert set(by_model["U704"]["candidates"]) != set(
        by_model["P703 DBL RANGER"]["candidates"]
    )


# =====================================================================
# apply
# =====================================================================
def test_mapping_an_existing_zone_applies_and_the_rows_load(
    engineer, held_panel, admin_conn
):
    raw, review = held_panel
    load_id = review["batch"]["load_id"]
    [label] = held(review)
    zone = next(z for z in label["candidates"] if z not in ("RRHOOD", "RFHOOD"))

    response = propose(engineer, {
        "raw_value": raw, "zone_code": zone, "plant_code": "AAT",
        "model_code": label["model_code"], "note": "T41 test",
    }, load_id)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "APPROVED"

    assert map_rows(admin_conn, raw) == [
        ("AAT", "U704", zone, "APPROVED", "ENGINEER_ALIAS", True, None, None)
    ], "one row, Engineer-approved, no owner proof invented"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_event WHERE action = 'mapping.apply' "
            "AND entity_id = %s",
            (str(response.json()["id"]),),
        )
        assert cur.fetchone()[0] == 1

    after = wait_for(engineer, load_id)
    assert after["reject_reasons"].get("UNKNOWN_CHECKZONE", 0) == 0
    assert after["batch"]["counts"]["rows_loaded"] == 3

    again = propose(engineer, {
        "raw_value": raw, "zone_code": zone, "plant_code": "AAT", "model_code": "U704",
    })
    assert again.status_code == 201, "the same map again is a no-op"
    other = next(z for z in label["candidates"] if z != zone)
    conflict = propose(engineer, {
        "raw_value": raw, "zone_code": other, "plant_code": "AAT", "model_code": "U704",
    })
    assert conflict.status_code == 409, conflict.text
    assert [r[2] for r in map_rows(admin_conn, raw)] == [zone], "never repointed"


@pytest.mark.parametrize("zone", ["T41-MINTED-ZONE", "not-a-zone"])
def test_a_zone_not_on_the_model_is_422_and_writes_nothing(
    engineer, held_panel, admin_conn, zone
):
    raw, review = held_panel
    response = propose(engineer, {
        "raw_value": raw, "zone_code": zone, "plant_code": "AAT", "model_code": "U704",
    }, review["batch"]["load_id"])
    assert response.status_code == 422, response.text
    assert map_rows(admin_conn, raw) == []


def test_another_models_zone_is_422(engineer, held_panel, admin_conn):
    raw, review = held_panel
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code FROM ref_model_zone WHERE model_code = 'P703 DBL RANGER' "
            "EXCEPT SELECT zone_code FROM ref_model_zone WHERE model_code = 'U704' "
            "ORDER BY 1 LIMIT 1"
        )
        found = cur.fetchone()
    if found is None:
        pytest.skip("no P703 zone missing from U704 on this database")
    response = propose(engineer, {
        "raw_value": raw, "zone_code": found[0], "plant_code": "AAT", "model_code": "U704",
    }, review["batch"]["load_id"])
    assert response.status_code == 422, response.text
    assert map_rows(admin_conn, raw) == []


def test_extra_keys_and_the_wrong_plant_are_422(engineer, held_panel, admin_conn):
    raw, review = held_panel
    extra = propose(engineer, {
        "raw_value": raw, "zone_code": "RRHOOD", "plant_code": "AAT",
        "model_code": "U704", "family_name": "Dark Metallics",
    }, review["batch"]["load_id"])
    assert extra.status_code == 422
    wrong_plant = propose(engineer, {
        "raw_value": raw, "zone_code": "RRHOOD", "plant_code": "FTM", "model_code": "U704",
    }, review["batch"]["load_id"])
    assert wrong_plant.status_code == 422
    assert map_rows(admin_conn, raw) == []


# =====================================================================
# roles and reserved kinds
# =====================================================================
def test_a_viewer_cannot_propose_a_panel_map(viewer):
    response = propose(viewer, {
        "raw_value": odd_panel(), "zone_code": "RRHOOD",
        "plant_code": "AAT", "model_code": "U704",
    })
    assert response.status_code == 403


@pytest.mark.parametrize("kind", ["ALIAS_PLANT", "ALIAS_PAINTLINE"])
def test_the_other_reserved_kinds_stay_501(engineer, held_panel, kind):
    _, review = held_panel
    response = engineer.post(PROPOSALS, json={
        "kind": kind, "load_id": review["batch"]["load_id"], "payload": {"x": 1},
    })
    assert response.status_code == 501, response.text


def test_the_contract_names_the_kind_and_the_model(viewer):
    spec = viewer.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert "ALIAS_CHECKZONE" in schemas["ProposalCreate"]["properties"]["kind"]["description"]
    assert "model_code" in schemas["HeldLabelGroup"]["properties"]
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 57, (
        "T48 added three film GETs, T62 two standards paths, T66 one overview, "
        "T79 + T81 four Comparison reads, T86 one panel-match read"
    )


@pytest.fixture(autouse=True)
def _t92_proposal_cleanup(admin_conn):
    """T92 Part 5: this module's own mapping proposals, removed after each test.

    The leak T89, T90 and T91 each reported and none owned: this module
    creates `proposed_mapping` rows and nothing deleted them, so 513 rows of
    test residue accumulated in the owner's live trial database. Snapshot
    first and delete only what this test added (the T76 shape), then fail
    loudly rather than leak (T87 D-87-8).
    """
    before = row_keys(admin_conn, "proposed_mapping", "id")
    yield
    forget_proposals(admin_conn, before, ["T41 ODD PANEL"], 'T41 alias checkzone')
