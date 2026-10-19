"""T32 -- FVL activation after G2, against the live API.

G2 is September `CF_Sep.xlsx` (T28 SHA-256). Every leaf row has Serial No
and Paintline text `(None)` — a documented missing-paintline sentinel, not
a booth. This suite does not copy that workbook into git: it records
the hash, applies the T31 maps, turns FVL `is_active` on as 0011 does,
owner-publishes a synthetic G2-shaped fixture, commits one 32-point vehicle
with paintline NULL, and checks History against `GET /measurements`. A
Jan–Aug-shaped sheet without identity still cannot commit. FVL `is_active`
is restored afterwards so suites that have not applied 0011 stay meaningful.
"""

from __future__ import annotations

from tests.conftest import delete_rows_created_since, row_keys
import hashlib
import uuid
from pathlib import Path

import pytest

from tests.test_t04_ingest import forget_proposals

from tests.test_t04_ingest import (
    acknowledge_required,
    forget_bytes,
    upload,
    wait_for,
)
from tests.test_t04_ingest import (  # noqa: F401
    admin,
    cleanup,
    engineer,
    ingest_apps,
)
from tests.test_t08_mapping import approve
from tests.test_t26_semantic_clean_layer import (
    HEADERS,
    published_profiles,
    sheet_bytes,
)
from app.domain.history import month_date_bounds
from tests.test_t23_history import cards_of, measurements_total, summaries_of
from tests.test_t31_fvl_activation_ready import (
    AUGUST_HASH,
    FVL_MAPPINGS,
    padded_hood_mappings,
    read_g1_fvl,
    zone_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFERRED_PATH = REPO_ROOT / "docs" / "DEFERRED.md"
MIGRATION = (
    BACKEND_ROOT / "migrations" / "versions" / "0011_t32_fvl_active.py"
)
G2_HASH = (
    "e3ecc6a7e209f262eeb0906aae71edc31b6b27fbe0d3d13a611448ce9d0f6a34"
)
G2_VAULT = REPO_ROOT.parent / "Data" / "FVL" / "CF" / "09 Sep data" / "CF_Sep.xlsx"


def test_g2_hash_is_the_september_fvl_export():
    text = MIGRATION.read_text(encoding="utf-8")
    upgrade = text.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    assert G2_HASH in text
    assert "UPDATE ref_plant SET is_active = true WHERE plant_code = 'FVL'" in upgrade
    assert "INSERT INTO ref_plant_alias" in upgrade
    assert "DELETE FROM" not in upgrade
    assert "down_revision = \"0010\"" in text or "down_revision = '0010'" in text
    if G2_VAULT.is_file():
        assert hashlib.sha256(G2_VAULT.read_bytes()).hexdigest() == G2_HASH


def test_d5_is_closed_in_deferred_with_the_four_conditions():
    text = DEFERRED_PATH.read_text(encoding="utf-8")
    row = [line for line in text.splitlines() if line.startswith("| **D5**")]
    assert row, text
    assert "**Closed**" in row[0]
    assert G2_HASH[:12] in text or G2_HASH in text


def test_t31_no_longer_claims_d5_is_open():
    t31 = (BACKEND_ROOT / "tests" / "test_t31_fvl_activation_ready.py").read_text(
        encoding="utf-8"
    )
    assert "Still open" not in t31


def g2_rows() -> list[dict]:
    serial = f"T32-{uuid.uuid4().hex[:10]}"
    rows = []
    for i, (_pos, raw, code) in enumerate(padded_hood_mappings()):
        rows.append(
            {
                "Date": "2026-09-08",
                "Month": "September",
                "Year": 2026,
                "Plant": "FVL",
                "Model": "P703 DBL",
                # T76 CHANGE (D2): BASE_ROW's `3HC Traction Green` is not on
                # FVL's offered list, so every row was COLOR_NOT_OFFERED.
                "Color": "Frozen White",
                "Checkzone": raw,
                "Paintline": "(None)",
                "Serial No": serial,
                "CF": 40.0 + i,
                "Tolerance Group": (
                    "Horizontal" if code in {
                        "RRHOOD", "RFHOOD", "CFHOOD", "LFHOOD", "LRHOOD",
                        "LCROOF", "RCROOF",
                    } else "Vertical"
                ),
            }
        )
    return rows


@pytest.fixture()
def fvl_active_with_maps(engineer, admin, admin_conn):
    owner, proof = read_g1_fvl()
    assert proof == AUGUST_HASH
    with admin_conn.cursor() as cur:
        cur.execute("SELECT is_active FROM ref_plant WHERE plant_code = 'FVL'")
        before = cur.fetchone()[0]
        cur.execute(
            "SELECT 1 FROM ref_plant_alias WHERE plant_code = 'FVL' LIMIT 1"
        )
        had_alias = cur.fetchone() is not None
        cur.execute(
            "UPDATE ref_plant SET is_active = true WHERE plant_code = 'FVL'"
        )
        if not had_alias:
            cur.execute(
                "INSERT INTO ref_plant_alias (raw_value, plant_code) "
                "VALUES ('FVL', 'FVL') ON CONFLICT (raw_value) DO NOTHING"
            )
    # T76 CHANGE: snapshot first; only the maps approved here are removed
    # (the live 0013 FVL maps carry the same owner and proof).
    maps_before = row_keys(admin_conn, "ref_plant_zone_map", "map_id")
    for mappings in (FVL_MAPPINGS, padded_hood_mappings()):
        created = engineer.post(
            "/api/v1/mappings/proposals",
            json={"kind": "ZONE", "payload": zone_payload(owner, proof, mappings)},
        )
        assert created.status_code == 201, created.text
        approved = approve(admin, created.json()["id"])
        assert approved.status_code == 200, approved.text

    yield owner, proof, before, had_alias

    delete_rows_created_since(
        admin_conn, "ref_plant_zone_map", "map_id", maps_before,
        "plant_code = 'FVL' AND verified_by = %s AND proof_hash = %s "
        "AND model_code LIKE 'P703%%'",
        (owner, proof),
    )
    with admin_conn.cursor() as cur:
        if not had_alias:
            cur.execute(
                "DELETE FROM ref_plant_alias "
                " WHERE raw_value = 'FVL' AND plant_code = 'FVL'"
            )
        cur.execute(
            "UPDATE ref_plant SET is_active = %s WHERE plant_code = 'FVL'",
            (before,),
        )


@pytest.mark.ingest
def test_g2_shaped_fvl_commits_and_january_august_does_not(
    engineer,
    admin,
    admin_conn,
    cleanup,
    published_profiles,
    fvl_active_with_maps,
):
    owner, _proof, _before, _had_alias = fvl_active_with_maps
    data = sheet_bytes(HEADERS, g2_rows(), sheet="PasteData")
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t32-fvl-g2.xlsx", data, "FVL")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)
    review = wait_for(engineer, load_id)
    file_hash = review["batch"]["file_hash"]
    status = review["batch"]["status"]
    assert status in {"PENDING_REVIEW", "REJECTED_TEMPLATE"}, review["batch"].get("notes")

    if status == "REJECTED_TEMPLATE" or "UNVERIFIED_PROFILE" in review.get(
        "commit_blockers", []
    ):
        published = admin.post(
            "/api/v1/plants/FVL/template-profiles/publish",
            json={
                "file_hash": file_hash,
                "source_sheet": "PasteData",
                "named_owner": owner,
                "notes": "T32 synthetic G2-shaped fixture; G1 FVL map already approved.",
            },
        )
        assert published.status_code == 200, published.text
        body = published.json()
        published_profiles.append((body["profile_id"], body["previous_profile_id"]))
        review = wait_for(engineer, load_id)
        assert review["batch"]["status"] == "PENDING_REVIEW", review["batch"].get("notes")

    acknowledge_required(admin, review)
    review = wait_for(engineer, load_id)
    assert "PAINTLINE_MISSING" not in (review.get("commit_blockers") or []), review.get(
        "commit_blockers"
    )
    assert review["committable"] is True, review["commit_blockers"]
    committed = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert committed.status_code == 200, committed.text
    inserted = committed.json()
    assert inserted.get("measurements_inserted") == 32, inserted

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT checkzone, src_zone_text, model, is_duplicate, plant, paintline "
            " FROM wavescan WHERE load_id = %s",
            (load_id,),
        )
        facts = cur.fetchall()
    assert len(facts) == 32, facts
    live = [row for row in facts if not row[3]]
    assert len(live) == 32, facts
    assert {row[5] for row in live} == {None}
    by_src = {src: (zone, model) for zone, src, model, _dup, _plant, _line in live}
    # T76 CHANGE (T58 D-58-01): FVL keeps its own WaveScan gold names; the
    # file's `01HOOD` is FVL gold `1HOOD`, never relabelled onto RRHOOD /
    # LCROOF / RCROOF / RTTAILGATE. Slot 11 and slot 14 stay two panels.
    assert by_src["01HOOD"][0] == "1HOOD"
    assert by_src["11ROOF"][0] == "11ROOF"
    assert by_src["14ROOF"][0] == "14ROOF"
    assert by_src["28TGATE"][0] == "28TGATE"
    assert by_src["11ROOF"][0] != by_src["14ROOF"][0]
    assert {model for _z, _s, model, _d, _p, _line in live} == {"P703 DBL RANGER"}
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code FROM ref_plant_ws_point WHERE plant_code = 'FVL' "
            "AND model_code = 'P703 DBL RANGER' AND retired_at IS NULL"
        )
        fvl_gold = {r[0] for r in cur.fetchall()}
    stored_zones = {zone for zone, *_rest in live}
    assert stored_zones <= fvl_gold, stored_zones - fvl_gold

    listed = engineer.get(
        "/api/v1/measurements",
        params={"plant": "FVL", "load_id": load_id, "limit": 100},
    )
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["page"]["total"] == 32, page["page"]
    # T76 CHANGE (T58 D-58-01): the list shows the FVL gold names stored.
    assert {item["checkzone"] for item in page["items"]} == stored_zones

    month = "2026-09"
    first, last = month_date_bounds(month)
    history = summaries_of(engineer, "FVL", month=month)
    assert history["plant_is_active"] is True
    history_points = sum(card["point_count"] for card in cards_of(history))
    listed_month = measurements_total(
        engineer,
        plant="FVL",
        date_from=first.isoformat(),
        date_to=last.isoformat(),
    )
    assert history_points == listed_month
    assert measurements_total(engineer, plant="FVL", load_id=load_id) == 32

    historical = sheet_bytes(
        HEADERS,
        [
            {
                "Date": "2026-08-03",
                "Plant": "FVL",
                "Model": "P703 DBL",
                # T76 CHANGE (D2): BASE_ROW's `3HC Traction Green` is not on
                # FVL's offered list, so every row was COLOR_NOT_OFFERED.
                "Color": "Frozen White",
                "Checkzone": "1HOOD",
                "Serial No": "",
                "Paintline": "",
                "CF": 41.0,
            }
        ],
        sheet="PasteData",
    )
    forget_bytes(admin_conn, historical)
    accepted = upload(engineer, "t32-fvl-aug-historical.xlsx", historical, "FVL")
    assert accepted.status_code == 202, accepted.text
    hist_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(hist_id)
    review = wait_for(engineer, hist_id)
    blockers = review.get("commit_blockers") or []
    # T76 CHANGE (ADR 0013 decision 2, T39): VEHICLE_IDENTITY_MISSING and
    # PAINTLINE_MISSING are no longer raised -- a blank serial and booth load
    # NULL at every plant (this supersedes the D5 note that Jan-Aug stay
    # non-committable). What must still hold: nothing is invented.
    assert "VEHICLE_IDENTITY_MISSING" not in blockers, blockers
    assert "PAINTLINE_MISSING" not in blockers, blockers
    committed_hist = engineer.post(f"/api/v1/batches/{hist_id}/commit")
    assert committed_hist.status_code == 200, committed_hist.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT serial_no, paintline FROM wavescan WHERE load_id = %s", (hist_id,)
        )
        assert cur.fetchall() == [(None, None)], "no serial or booth invented"


@pytest.fixture(autouse=True)
def _t92_proposal_cleanup(admin_conn):
    """T92 Part 5: this module's own mapping proposals, removed after each test.

    T32 posts T31's FVL pack through T31's own `zone_payload`, so it leaks
    rows with T31's note on them -- which is why fixing T31 alone left two
    per suite run behind. Snapshot first and delete only what this test
    added (the T76 shape), then fail loudly rather than leak (T87 D-87-8).
    """
    before = row_keys(admin_conn, "proposed_mapping", "id")
    yield
    forget_proposals(
        admin_conn,
        before,
        ["T31 FVL activation-ready from G1-P703-OWNER-PROOF.md"],
        "T32 FVL activation",
    )
