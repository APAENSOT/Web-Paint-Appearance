"""Finish-batch held labels: colour identity alias, then replay PENDING only.

ALIAS_COLOR is identity (S12 / H6): a plant-scoped spelling maps onto an
existing `ref_color.color_name`. Colour-family / D2 stays closed. Replay of
a batch that already has `wavescan` rows stays refused (ADR 0005). Identical
live bytes stay 409 (T25 / H1). No Excel, serials or CF values are committed
to git; fixtures are synthetic.
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

import pytest

from tests.test_t04_ingest import forget_proposals

from tests.test_t04_ingest import (
    acknowledge,
    acknowledge_required,
    ingest,
    make_workbook,
    unique_rows,
    upload,
    wait_for,
)
from tests.test_t04_ingest import (  # noqa: F401
    cleanup,
    engineer,
    ingest_apps,
)
from tests.conftest import delete_rows_created_since, row_keys
from tests.test_t04_ingest import forget_bytes
from tests.test_t08_mapping import (  # noqa: F401
    admin,
    approve,
    count,
    propose,
)
from tests.test_t26_semantic_clean_layer import published_profiles, sheet_bytes

pytestmark = pytest.mark.ingest

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_COLOR = "Traction Green"


@pytest.fixture()
def color_alias_cleanup(admin_conn):
    """Remove colour aliases a test approved. The application cannot DELETE.

    T76 CHANGE: only aliases created during the test -- an existing row with
    the same spelling (an owner's) is never removed.
    """
    before = row_keys(admin_conn, "ref_color_alias", "alias_id")
    raws: list[str] = []
    yield raws
    if raws:
        delete_rows_created_since(
            admin_conn, "ref_color_alias", "alias_id", before,
            "raw_value = ANY(%s)", (raws,),
        )


def _unknown_color() -> str:
    return f"3HC Traction {uuid.uuid4().hex[:8]}"


def test_an_unknown_colour_spelling_becomes_loadable_after_an_approved_alias(
    engineer, admin, cleanup, color_alias_cleanup, admin_conn
):
    """PENDING fixture: confirm spelling → replay → LOAD → commit (done bar)."""
    raw = _unknown_color()
    color_alias_cleanup.append(raw)
    other = _unknown_color()
    color_alias_cleanup.append(other)

    rows = unique_rows(3)
    rows[0]["Color"] = raw
    rows[1]["Color"] = raw
    rows[2]["Color"] = other
    data = make_workbook(rows)
    review = ingest(engineer, cleanup, "held-color.xlsx", data)
    load_id = review["batch"]["load_id"]
    assert review["reject_reasons"] == {"UNKNOWN_COLOR": 3}

    held = { (h["raw_value"], h["reason"]): h for h in review["held_labels"] }
    assert held[(raw, "UNKNOWN_COLOR")]["count"] == 2
    assert held[(other, "UNKNOWN_COLOR")]["count"] == 1
    assert held[(raw, "UNKNOWN_COLOR")]["teachable_kind"] == "ALIAS_COLOR"
    assert held[(raw, "UNKNOWN_COLOR")]["column"] == "color"
    assert CANONICAL_COLOR in held[(raw, "UNKNOWN_COLOR")]["candidates"]

    colour_held = held[(raw, "UNKNOWN_COLOR")]
    assert colour_held["display_group"] == "colour"
    assert colour_held["operator_message"]
    assert "catalogue colour" in colour_held["operator_message"]

    created = propose(
        engineer, "ALIAS_COLOR", load_id,
        {"raw_value": raw, "color_name": CANONICAL_COLOR, "plant_code": "AAT",
         "note": "same colour, plant spelling"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "APPROVED"
    already = approve(admin, created.json()["id"])
    assert already.status_code == 409, already.text

    replayed = wait_for(engineer, load_id)
    assert replayed["batch"]["status"] == "PENDING_REVIEW"
    assert replayed["batch"]["counts"]["rows_rejected"] == 1
    assert replayed["batch"]["counts"]["rows_loaded"] == 2
    assert replayed["reject_reasons"] == {"UNKNOWN_COLOR": 1}
    held_after = {h["raw_value"]: h["count"] for h in replayed["held_labels"]}
    assert held_after == {other: 1}
    assert count(admin_conn, "wavescan", load_id) == 0

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, color_name FROM ref_color_alias "
            "WHERE raw_value = %s",
            (raw,),
        )
        alias = cur.fetchone()
        cur.execute(
            "SELECT grading_family FROM ref_color WHERE color_name = %s",
            (CANONICAL_COLOR,),
        )
        family = cur.fetchone()[0]
        cur.execute(
            "SELECT action FROM audit_event WHERE entity_id = %s "
            "AND action = 'mapping.apply'",
            (created.json()["id"],),
        )
        apply_audit = cur.fetchone()
    assert alias == ("AAT", CANONICAL_COLOR)
    assert family is None
    assert apply_audit is not None

    created_b = propose(
        engineer, "ALIAS_COLOR", load_id,
        {"raw_value": other, "color_name": CANONICAL_COLOR, "plant_code": "AAT"},
    )
    assert created_b.status_code == 201, created_b.text
    assert created_b.json()["status"] == "APPROVED"

    ready = wait_for(engineer, load_id)
    assert ready["batch"]["counts"]["rows_rejected"] == 0
    assert ready["batch"]["counts"]["rows_loaded"] == 3
    assert ready["held_labels"] == []
    assert ready["committable"] is True

    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["measurements_inserted"] == 3
    assert count(admin_conn, "wavescan", load_id) == 3

    again = upload(engineer, "held-color-again.xlsx", data)
    assert again.status_code == 409, again.text
    assert f"load_id {load_id}" in again.json()["message"]


def test_compact_hood_is_zone_not_empty(engineer, cleanup):
    rows = unique_rows(1, **{"Checkzone": "01HOOD"})
    review = ingest(engineer, cleanup, "held-compact-zone.xlsx", make_workbook(rows))
    held = [h for h in review["held_labels"] if h["raw_value"] == "01HOOD"]
    assert held, review["held_labels"]
    assert held[0]["display_group"] == "zone"
    # T41 CHANGE (D-31): a real panel spelling is teachable onto that
    # model's existing zones -- never a colour, never a minted zone.
    assert held[0]["teachable_kind"] == "ALIAS_CHECKZONE"
    assert held[0]["model_code"] == "U704"
    assert "RRHOOD" in held[0]["candidates"]
    assert "Not a colour" in held[0]["operator_message"]


def test_none_model_is_empty_identity_not_teachable(engineer, cleanup):
    rows = unique_rows(1, **{"Model": "(None)"})
    review = ingest(engineer, cleanup, "held-none-model.xlsx", make_workbook(rows))
    held = review["held_labels"]
    none_rows = [h for h in held if h["raw_value"].strip().lower() in {"(none)", "none"}]
    assert none_rows, held
    for h in none_rows:
        assert h["display_group"] == "empty_identity"
        assert h["teachable_kind"] is None
        assert "will not load" in h["operator_message"].lower()


def test_a_family_field_on_alias_color_is_refused(engineer, cleanup):
    """D2 stays closed: extra keys on the identity payload are 422."""
    review = ingest(engineer, cleanup, "held-d2.xlsx", make_workbook(unique_rows(2)))
    response = propose(
        engineer, "ALIAS_COLOR", review["batch"]["load_id"],
        {
            "raw_value": "anything",
            "color_name": CANONICAL_COLOR,
            "plant_code": "AAT",
            "grading_family": "metallic",
        },
    )
    assert response.status_code == 422, response.text


def test_a_colour_name_that_does_not_exist_is_refused(engineer, cleanup):
    review = ingest(engineer, cleanup, "held-new-colour.xlsx", make_workbook(unique_rows(2)))
    response = propose(
        engineer, "ALIAS_COLOR", review["batch"]["load_id"],
        {
            "raw_value": _unknown_color(),
            "color_name": "Not A Catalogue Colour",
            "plant_code": "AAT",
        },
    )
    assert response.status_code == 422, response.text
    assert CANONICAL_COLOR in response.json()["message"]


def test_alias_color_without_a_batch_still_needs_a_plant(engineer):
    response = engineer.post(
        "/api/v1/mappings/proposals",
        json={
            "kind": "ALIAS_COLOR",
            "payload": {"raw_value": "x", "color_name": CANONICAL_COLOR},
        },
    )
    assert response.status_code == 422, response.text


def test_alias_color_without_a_batch_teaches_future_files(
    engineer, admin, cleanup, color_alias_cleanup, admin_conn
):
    """Committed remainder cannot replay; omit load_id and the next file LOADs."""
    raw = _unknown_color()
    color_alias_cleanup.append(raw)
    rows = unique_rows(3)
    rows[0]["Color"] = raw
    data = make_workbook(rows)
    review = ingest(engineer, cleanup, "held-remainder.xlsx", data)
    load_id = review["batch"]["load_id"]
    assert review["reject_reasons"]["UNKNOWN_COLOR"] == 1

    ack = acknowledge(admin, review, "REJECTED_ROWS")
    assert ack.status_code == 201, ack.text
    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text
    facts = count(admin_conn, "wavescan", load_id)
    assert facts == 2

    remainder = engineer.get(f"/api/v1/batches/{load_id}").json()
    assert remainder["batch"]["status"] == "COMMITTED"
    held = [h for h in remainder["held_labels"] if h["raw_value"] == raw]
    assert len(held) == 1
    assert held[0]["count"] == 1
    assert held[0]["teachable_kind"] == "ALIAS_COLOR"

    created = engineer.post(
        "/api/v1/mappings/proposals",
        json={
            "kind": "ALIAS_COLOR",
            "payload": {
                "raw_value": raw,
                "color_name": CANONICAL_COLOR,
                "plant_code": "AAT",
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "APPROVED"
    assert count(admin_conn, "wavescan", load_id) == facts

    next_rows = unique_rows(2)
    next_rows[0]["Color"] = raw
    next_review = ingest(engineer, cleanup, "held-next-month.xlsx", make_workbook(next_rows))
    assert next_review["batch"]["counts"]["rows_rejected"] == 0
    assert next_review["batch"]["counts"]["rows_loaded"] == 2
    assert next_review["held_labels"] == []


def test_a_plant_mismatch_on_alias_color_is_refused(engineer, cleanup):
    review = ingest(engineer, cleanup, "held-plant.xlsx", make_workbook(unique_rows(2)))
    response = propose(
        engineer, "ALIAS_COLOR", review["batch"]["load_id"],
        {
            "raw_value": _unknown_color(),
            "color_name": CANONICAL_COLOR,
            "plant_code": "FVL",
        },
    )
    assert response.status_code == 422, response.text
    assert "plant" in response.json()["message"].lower()


def test_there_is_no_fuzzy_auto_bind():
    """H5: no silent Levenshtein / keyword activation in the mapping service."""
    source = (
        REPO_ROOT / "backend/app/services/mapping.py"
    ).read_text(encoding="utf-8")
    for banned in ("levenshtein", "Levenshtein", "SequenceMatcher", "fuzzy",
                   "rapidfuzz", "difflib"):
        assert banned not in source, banned
    for line in source.splitlines():
        if "similarity" in line and re.search(
            r"(if|elif|while|assert).*similarity", line
        ):
            raise AssertionError(f"similarity is branched on: {line.strip()}")


def test_a_leftover_model_is_not_teachable_onto_p703(engineer, cleanup):
    """CX743 / V363 / J73 / U704 are not Ranger aliases (G1 D-07 / H7)."""
    rows = unique_rows(2)
    rows[0]["Model"] = "CX743"
    review = ingest(engineer, cleanup, "held-leftover.xlsx", make_workbook(rows))
    held = [h for h in review["held_labels"] if h["raw_value"] == "CX743"]
    assert held, review["held_labels"]
    assert held[0]["reason"] == "UNKNOWN_MODEL"
    assert "P703 DBL RANGER" not in held[0]["candidates"]
    if held[0]["teachable_kind"] == "ALIAS_MODEL":
        assert "CX743" in held[0]["candidates"]
    else:
        assert held[0]["teachable_kind"] is None
        assert held[0]["candidates"] == []

    refused = propose(
        engineer, "ALIAS_MODEL", review["batch"]["load_id"],
        {"raw_value": "CX743", "model_code": "P703 DBL RANGER"},
    )
    assert refused.status_code == 422, refused.text
    assert "leftover" in refused.json()["message"].lower()


def test_a_leftover_model_is_teachable_onto_its_own_catalogue(
    engineer, cleanup, admin_conn
):
    """CX743 → CX743 is identity. 0013 must have the catalogue."""
    # T76 CHANGE (cleanup): snapshot the CX743 aliases that already exist so
    # the teardown removes only the one this test approved (T64 incident class).
    alias_where = "raw_value = 'CX743' AND model_code = 'CX743'"
    aliases_before = row_keys(admin_conn, "ref_model_alias", "alias_id", alias_where)
    rows = unique_rows(1)
    rows[0]["Model"] = "CX743"
    review = ingest(engineer, cleanup, "held-leftover-own.xlsx", make_workbook(rows))
    created = propose(
        engineer, "ALIAS_MODEL", review["batch"]["load_id"],
        {"raw_value": "CX743", "model_code": "CX743",
         "note": "pytest leftover own catalogue"},
    )
    assert created.status_code in (201, 409), created.text
    try:
        replayed = wait_for(engineer, review["batch"]["load_id"])
        assert replayed["reject_reasons"].get("UNKNOWN_MODEL", 0) == 0
        # T76 CHANGE (D2 / T55): CX743 is offered only at FVL
        # (`ref_plant_model`), so at AAT the plant model gate holds the row
        # before any zone check. The identity resolved -- the point of this test.
        reasons = replayed["reject_reasons"]
        assert (
            "MODEL_NOT_OFFERED" in reasons
            or "ZONE_NOT_VALID_FOR_MODEL" in reasons
            or reasons.get("UNKNOWN_CHECKZONE", 0) >= 1
        ), reasons
    finally:
        # T76 CHANGE: only the alias this test created (the T55 FVL seed and
        # any owner row stay).
        delete_rows_created_since(
            admin_conn, "ref_model_alias", "alias_id", aliases_before, alias_where
        )


def test_a_second_file_does_not_double_an_active_identity(
    engineer, admin, cleanup, admin_conn
):
    """R3: existing cross-file dedup, not a new overlap rule."""
    first = unique_rows(1)
    review = ingest(engineer, cleanup, "held-dup-a.xlsx", make_workbook(first))
    load_a = review["batch"]["load_id"]
    acknowledge_required(admin, review)
    assert engineer.post(f"/api/v1/batches/{load_a}/commit").status_code == 200
    facts = count(admin_conn, "wavescan", load_a)
    assert facts == 1

    second = unique_rows(2)
    second[0]["Serial No"] = first[0]["Serial No"]
    second[0]["Checkzone"] = first[0]["Checkzone"]
    second[0]["CF"] = first[0]["CF"]
    review_b = ingest(engineer, cleanup, "held-dup-b.xlsx", make_workbook(second))
    assert review_b["batch"]["counts"]["rows_duplicate"] >= 1
    acknowledge_required(admin, review_b)
    committed_b = engineer.post(
        f"/api/v1/batches/{review_b['batch']['load_id']}/commit"
    )
    assert committed_b.status_code == 200, committed_b.text
    assert count(admin_conn, "wavescan", review_b["batch"]["load_id"]) == (
        review_b["batch"]["counts"]["rows_loaded"]
    )
    assert count(admin_conn, "wavescan", load_a) == facts


def _ensure_column_alias(engineer, admin, load_id: int, header: str, field: str) -> None:
    created = propose(
        engineer, "COLUMN", load_id,
        {"raw_header": header, "logical_field": field},
    )
    if created.status_code != 201:
        return
    approved = approve(admin, created.json()["id"])
    assert approved.status_code in (200, 409), approved.text
    if approved.status_code == 200:
        wait_for(engineer, load_id)


def _ensure_rostered_model(engineer, load_id: int, raw: str, model_code: str) -> None:
    created = propose(
        engineer, "ALIAS_MODEL", load_id,
        {"raw_value": raw, "model_code": model_code,
         "note": "pytest FVL 18-col rostered identity"},
    )
    assert created.status_code in (201, 409), created.text
    wait_for(engineer, load_id)


def wait_until_status(client, load_id: int, statuses: set[str], timeout: float = 30.0) -> dict:
    """Poll past a stale REJECTED_TEMPLATE until replay finishes."""
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/batches/{load_id}").json()
        if body["batch"]["status"] in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(
        f"batch {load_id} stayed {body.get('batch', {}).get('status')} "
        f"not {sorted(statuses)}: {body.get('batch', {}).get('notes')}"
    )


def test_fvl_eighteen_column_publish_loads_p703_and_holds_leftover(
    engineer, admin, admin_conn, cleanup, published_profiles
):
    """F1–F5 on a signature that cannot collide with standing 1063."""
    extra = f"TxxExtra {uuid.uuid4().hex[:8]}"
    # Header names must match sheet_bytes merge keys (ROW uses "DOI", not "Doi").
    # Year/Month stay recognised calendar fields: ignoring them would move the
    # semantic signature off standing 1063. Isolation is the unique extra.
    headers = [
        "Date", "Year", "Month", "Style", "Color", "Orientation", "Panel",
        "LW", "SW", "du", "Wa", "Wb", "Wc", "Wd", "We", "CF", "DOI", "Panel2",
        extra,
    ]
    p703 = {
        "Date": "2026-08-15", "Year": 2026, "Month": "August",
        "Style": "P703", "Color": "Ignite Orange",
        # T58 CHANGE (D-58-11): FVL Ranger gold is FVL's own compact 32, so the
        # P703 row writes FVL's `11ROOF`. The CX743 row inherits it; slot 11
        # on CX743 is `11LFRTDOOR`, so that row holds on the panel.
        "Orientation": "Horizontal", "Panel": "11ROOF", extra: "iso",
        "CF": 41.0, "DOI": 87.5, "LW": 3.7, "SW": 15.7,
    }
    leftover = {
        **p703, "Style": "CX743", "CF": 42.0, extra: "iso2",
    }
    data = sheet_bytes(headers, [p703, leftover], sheet="8")
    forget_bytes(admin_conn, data)

    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        was_active = cur.fetchone()[0]
        cur.execute(
            "UPDATE ref_plant SET is_active = true WHERE plant_code = 'FVL'"
        )
    try:
        accepted = upload(engineer, "held-fvl-18.xlsx", data, "FVL")
        assert accepted.status_code == 202, accepted.text
        load_id = accepted.json()["batches"][0]["load_id"]
        cleanup.append(load_id)
        before = wait_for(engineer, load_id)
        unknown = (
            before["batch"]["counts"]["rows_in_file"] == 0
            or "UNKNOWN_TEMPLATE" in (before.get("commit_blockers") or [])
            or before["batch"]["status"] == "REJECTED_TEMPLATE"
        )
        if unknown:
            _ensure_column_alias(engineer, admin, load_id, "Style", "model")
            _ensure_column_alias(engineer, admin, load_id, "Panel", "checkzone")
            published = admin.post(
                "/api/v1/plants/FVL/template-profiles/publish",
                json={
                    "file_hash": before["batch"]["file_hash"],
                    "source_sheet": "8",
                    "named_owner": "Efe Ularika",
                    "notes": (
                        "pytest FVL 18-col fixture; unique extra header so this "
                        "signature is not standing August 1063"
                    ),
                    "fill_missing_plant": True,
                    "ignored_headers": [
                        {"header": "Orientation", "reason": "not a WaveScan identity field"},
                        {"header": "Panel2", "reason": "cached group keyword"},
                        {"header": extra, "reason": "pytest extra, not identity"},
                    ],
                },
            )
            assert published.status_code == 200, published.text
            body = published.json()
            published_profiles.append((body["profile_id"], body.get("previous_profile_id")))
            assert load_id in body["replayed_load_ids"]
            assert 1063 not in body["replayed_load_ids"]
            after = wait_until_status(engineer, load_id, {"PENDING_REVIEW"})
        else:
            after = before
        _ensure_rostered_model(engineer, load_id, "P703", "P703 DBL RANGER")
        after = wait_until_status(engineer, load_id, {"PENDING_REVIEW"})
        assert after["batch"]["counts"]["rows_loaded"] >= 1, (
            after["batch"]["counts"], after.get("reject_reasons"),
            after.get("commit_blockers"), after.get("held_labels"),
        )
        assert "PAINTLINE_MISSING" not in (after.get("commit_blockers") or [])
        # T55 CHANGE (D-55-01/02): CX743 is offered at FVL, so the Style cell
        # resolves to CX743 itself -- never UNKNOWN_MODEL and never Ranger.
        # Its `01 RRHOOD` panel is a Ranger panel, so the row still holds on
        # the panel, not on the model.
        assert after["reject_reasons"].get("UNKNOWN_MODEL", 0) == 0
        assert not [h for h in after["held_labels"] if h["raw_value"] == "CX743"]
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT canonical ->> 'offending_column' FROM stg_review_row "
                "WHERE load_id = %s AND disposition = 'REJECT'",
                (load_id,),
            )
            columns = [r[0] for r in cur.fetchall()]
        assert columns == ["checkzone"], columns

        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT canonical ->> 'serial_no', canonical ->> 'paintline' "
                "FROM stg_review_row "
                "WHERE load_id = %s AND disposition = 'LOAD' LIMIT 1",
                (load_id,),
            )
            loaded = cur.fetchone()
        assert loaded is not None
        serial, paintline = loaded
        assert serial in (None, "")
        assert paintline in (None, "")

        acknowledge_required(admin, after)
        if after.get("committable"):
            committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
            assert committed.status_code == 200, committed.text
            assert count(admin_conn, "wavescan", load_id) == after["batch"]["counts"]["rows_loaded"]
        else:
            assert "UNREVIEWED_HEADER" in (after.get("commit_blockers") or [])
    finally:
        with admin_conn.cursor() as cur:
            cur.execute(
                "UPDATE ref_plant SET is_active = %s WHERE plant_code = 'FVL'",
                (was_active,),
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
    forget_proposals(admin_conn, before, ["3HC Traction "], 'held labels')
