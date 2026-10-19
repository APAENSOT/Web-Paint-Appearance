"""T83 -- the T54-copied RAPCAP / SGL / Raptor Film lists are retired.

D-FT-08c, owner 2026-10-07. Migration 0030 retired the 735
``ref_plant_film_point`` rows T54 cross-joined onto AAT, FVL and SAP for
``P703 RAPCAP``, ``P703 SGL`` and ``P703 DBL RAPTOR``. Nothing was deleted
(ADR 0005): the rows carry ``retired_at`` / ``retired_reason``.

Claims (task section 2):

1. AAT, FVL and SAP have **no live** RAPCAP / SGL / Raptor Film point, every
   one of their 735 rows is retired with exactly the T83 reason, and FTM's
   four lists are all 94 **live**. Every other plant's list -- AAT Ranger
   and U704, FVL CX743 and V363, SAP J73 DBL, every plant's Ranger -- is
   unchanged, against the live count recorded before the migration.
2. The Film reads and the T66 overview for AAT, FVL and SAP list only their
   real models, checked live. (The before/after response snapshots taken
   either side of 0030 hold plant measurements, so they are not shipped in
   this repository; that one-off comparison passed when 0030 landed.)
3. T78 Choose model still refuses ``P703 RAPCAP`` at SAP, because the Film
   vocabulary a choice may come from is derived from
   ``ref_film_model_alias`` alone (D-78-32) -- a table 0030 does not touch.
   Asserted here through the same pure ``film_model_options`` the service
   calls; the live 422 over HTTP is
   ``test_t78_film_model_choose.py::test_a_model_outside_the_plant_vocabulary_is_422``,
   which runs in the same suite.
4. No fact, and no row of any table, was lost: the 735 rows are still there,
   and ``filmthickness`` never named one.

**Read-only.** Every test here only SELECTs and only GETs. Nothing is
inserted, updated, deleted or uploaded, so there is nothing to clean up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.film import film_model_options, plant_film_vocabulary
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
COUNTS_BEFORE = REPO / "backend" / "tests" / "fixtures" / "gold" / "T83-gold-counts-before-0030.txt"

PLANTS = ("AAT", "FVL", "SAP")
RETIRED_MODELS = ("P703 RAPCAP", "P703 SGL", "P703 DBL RAPTOR")
#: Exactly migration 0030's REASON. A different string is a different decision.
REASON = (
    "T83 (D-FT-08c, owner 2026-10-07): T54 copy; RAPCAP/SGL/Raptor Film lists "
    "exist only at FTM"
)
T54_NOTE = "T54 copy of the T46/T47 model catalogue"
EXPECTED_RETIRED = 735
#: Per (plant, model), the rows T54 copied. Their sum is EXPECTED_RETIRED.
EXPECTED_PER_MODEL = {
    (plant, model): size
    for plant in PLANTS
    for model, size in (("P703 RAPCAP", 93), ("P703 SGL", 58), ("P703 DBL RAPTOR", 94))
}
FTM_MODELS = ("P703 DBL RANGER", "P703 DBL RAPTOR", "P703 RAPCAP", "P703 SGL")
#: T99 CHANGE (D-99-5): FTM's four lists were four copies of one 94-name
#: catalogue when T83 ran; revision 0033 made each the walk its own real
#: files write. The sizes are asserted per model below.
FTM_LIVE = {
    "P703 DBL RANGER": 98, "P703 DBL RAPTOR": 98,
    "P703 RAPCAP": 93, "P703 SGL": 58,
}


def rows(admin_conn, sql: str, args: tuple = ()) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def live_counts(admin_conn) -> dict[tuple[str, str], int]:
    return {
        (p, m): n
        for p, m, n in rows(
            admin_conn,
            "SELECT plant_code, model_code, count(*) FROM ref_plant_film_point "
            " WHERE retired_at IS NULL GROUP BY 1, 2",
        )
    }


# =====================================================================
# 1. the gold lists
# =====================================================================
def test_no_live_rapcap_sgl_or_raptor_film_point_at_aat_fvl_sap(admin_conn):
    """D-FT-08c: those three Film lists exist only at FTM now."""
    assert (
        rows(
            admin_conn,
            "SELECT plant_code, model_code, count(*) FROM ref_plant_film_point "
            " WHERE retired_at IS NULL AND plant_code = ANY(%s) "
            "   AND model_code = ANY(%s) GROUP BY 1, 2",
            (list(PLANTS), list(RETIRED_MODELS)),
        )
        == []
    )


def test_the_735_rows_are_retired_and_not_deleted(admin_conn):
    """ADR 0005: a retired gold row stays, so a fact that named it keeps its FK."""
    kept = {
        (p, m): n
        for p, m, n in rows(
            admin_conn,
            "SELECT plant_code, model_code, count(*) FROM ref_plant_film_point "
            " WHERE plant_code = ANY(%s) AND model_code = ANY(%s) GROUP BY 1, 2",
            (list(PLANTS), list(RETIRED_MODELS)),
        )
    }
    assert kept == EXPECTED_PER_MODEL
    assert sum(kept.values()) == EXPECTED_RETIRED

    with_reason = rows(
        admin_conn,
        "SELECT count(*) FROM ref_plant_film_point "
        " WHERE plant_code = ANY(%s) AND model_code = ANY(%s) "
        "   AND retired_at IS NOT NULL AND retired_reason = %s "
        "   AND note = %s AND proof_hash IS NULL",
        (list(PLANTS), list(RETIRED_MODELS), REASON, T54_NOTE),
    )[0][0]
    assert with_reason == EXPECTED_RETIRED


def test_ftm_keeps_all_four_lists_live(admin_conn):
    counts = {
        m: n
        for m, n in rows(
            admin_conn,
            "SELECT model_code, count(*) FROM ref_plant_film_point "
            " WHERE plant_code = 'FTM' AND retired_at IS NULL GROUP BY 1",
        )
    }
    # T99 CHANGE (D-99-5): T83's claim is that FTM keeps **all four** lists
    # live while AAT, FVL and SAP lose their copies. It still does -- but the
    # four are their own measured walks now (98 / 98 / 93 / 58) rather than
    # four copies of one 94.
    assert set(counts) == set(FTM_MODELS)
    assert counts == FTM_LIVE


def test_every_other_plant_and_model_list_is_unchanged(admin_conn):
    """The live count recorded off the cluster before 0030, minus the target set."""
    expected: dict[tuple[str, str], int] = {}
    for line in COUNTS_BEFORE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        plant, model, live, _total = line.split("|")
        if (plant, model) in EXPECTED_PER_MODEL:
            continue
        expected[(plant, model)] = int(live)
    # the recorded snapshot is the real catalogue, not an empty fixture
    assert expected, f"{COUNTS_BEFORE} carries no non-target list"
    assert ("SAP", "J73 DBL") in expected and ("AAT", "U704") in expected

    live = live_counts(admin_conn)
    # T99 CHANGE (D-99-5): FTM's own four lists are the one thing T99 moved,
    # so they are compared to what T99 measured rather than to the pre-0030
    # snapshot. Every list of every **other** plant is still exactly what
    # that snapshot recorded -- which is the claim this test makes.
    t99 = {("FTM", model): n for model, n in FTM_LIVE.items()}
    expected = {**expected, **{k: v for k, v in t99.items() if k in expected}}
    # RO19 CHANGE (D-RO19-5, 2026-10-19): the owner added 061TGATE to SAP
    # J73 on Point Check (point 94), so that list is the snapshot plus one.
    expected[("SAP", "J73 DBL")] += 1
    assert {k: v for k, v in live.items() if k in expected} == expected
    assert {k: v for k, v in expected.items() if k[0] != "FTM"}, "other plants checked"
    assert not set(live) & set(EXPECTED_PER_MODEL)


def test_no_fact_and_no_film_alias_ever_used_those_lists(admin_conn):
    """0030's two guards, re-checked: this is why retiring was safe."""
    assert (
        rows(
            admin_conn,
            "SELECT plant, model, count(*) FROM filmthickness "
            " WHERE plant = ANY(%s) AND model = ANY(%s) GROUP BY 1, 2",
            (list(PLANTS), list(RETIRED_MODELS)),
        )
        == []
    )
    assert (
        rows(
            admin_conn,
            "SELECT plant_code, raw_token, model_code FROM ref_film_model_alias "
            " WHERE plant_code = ANY(%s) AND model_code = ANY(%s)",
            (list(PLANTS), list(RETIRED_MODELS)),
        )
        == []
    )


def test_the_migration_is_audited(admin_conn):  # T85
    found = rows(
        admin_conn,
        "SELECT after FROM audit_event "
        " WHERE action = 'catalogue.plant_film_point.retire_t54_copy'",
    )
    if not found:
        # T85 (D-87-6) truncated `audit_event` by owner decision
        # (docs/reports/T85-TRIAL-DATA-RESET.md), and 0030's audit row went
        # with it. It cannot be recreated: an invented row would not be the
        # record the migration wrote, and `audit_event` is append-only, so
        # nothing may write one now. The retirement **itself** is still
        # asserted, unskipped, by every other test in this module -- what is
        # gone is only the migration's own note that it did it. The
        # assertion below is unchanged and runs wherever the row survives.
        pytest.skip(
            "T85 cleared audit_event by owner decision; migration 0030's "
            "'catalogue.plant_film_point.retire_t54_copy' row is not in this "
            "database. The retired lists themselves are still asserted by the "
            "rest of this module."
        )
    assert len(found) >= 1
    after = found[-1][0]
    assert after["revision"] == "0030"
    assert after["retired_gold_rows"] == EXPECTED_RETIRED
    assert after["reason"] == REASON
    assert after["decision"] == "D-FT-08c"


def test_no_film_location_map_at_those_plants_named_those_models(admin_conn):
    """Expected 0, before and after: 0030 reports the count it retired."""
    assert (
        rows(
            admin_conn,
            "SELECT count(*) FROM ref_film_location_map "
            " WHERE plant_code = ANY(%s) AND model_code = ANY(%s)",
            (list(PLANTS), list(RETIRED_MODELS)),
        )[0][0]
        == 0
    )


# =====================================================================
# 2. the Film reads
# =====================================================================
@pytest.mark.parametrize("plant", PLANTS)
def test_the_live_film_reads_offer_no_retired_model(viewer, plant):  # noqa: F811
    """T48 facets and T66 overview, live, for each of the three plants."""
    base = f"/api/v1/plants/{plant}/filmthickness"
    facets = viewer.get(f"{base}/facets")
    assert facets.status_code == 200, facets.text
    assert not set(facets.json()["models"]) & set(RETIRED_MODELS)

    overview = viewer.get(f"{base}/overview")
    assert overview.status_code == 200, overview.text
    payload = overview.json()
    assert not set(payload["model_options"]) & set(RETIRED_MODELS)
    assert not {b["model_code"] for b in payload["boxes"]} & set(RETIRED_MODELS)


def test_ftm_film_reads_still_offer_its_models(viewer):  # noqa: F811
    """Retiring at three plants did not touch FTM's reads."""
    facets = viewer.get("/api/v1/plants/FTM/filmthickness/facets")
    assert facets.status_code == 200, facets.text
    assert facets.json()["plant_code"] == "FTM"
    overview = viewer.get("/api/v1/plants/FTM/filmthickness/overview")
    assert overview.status_code == 200, overview.text


# =====================================================================
# 3. T78 Choose model
# =====================================================================
def film_aliases(admin_conn) -> dict[tuple[str, str], str]:
    return {
        (p, t): m
        for p, t, m in rows(
            admin_conn,
            "SELECT plant_code, raw_token, model_code FROM ref_film_model_alias",
        )
    }


def test_rapcap_is_not_in_saps_film_vocabulary(admin_conn):
    """D-78-32: the vocabulary is ref_film_model_alias, which 0030 never touched."""
    aliases = film_aliases(admin_conn)
    vocabulary = plant_film_vocabulary("SAP", aliases)
    assert vocabulary, "SAP has no Film vocabulary at all; the seed changed"
    assert "P703 RAPCAP" not in vocabulary
    assert "P703 SGL" not in vocabulary
    assert "P703 DBL RANGER" in vocabulary


def test_a_sap_sheet_is_never_offered_rapcap(admin_conn):
    """The same pure options the 422 in ``_require_film_model_choice`` reads."""
    options = film_model_options(
        "SAP", "AW_ZZ_T83TEST.xlsx", "Quick Summary", film_aliases(admin_conn)
    )
    assert "P703 RAPCAP" not in options.choices
    assert "P703 SGL" not in options.choices
    assert "P703 DBL RANGER" in options.choices


def test_ftm_is_still_offered_rapcap(admin_conn):
    """The FTM side of D-FT-08c: RAPCAP did not stop existing, it is FTM's."""
    assert "P703 RAPCAP" in plant_film_vocabulary("FTM", film_aliases(admin_conn))
