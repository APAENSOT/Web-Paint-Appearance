"""T112-FIX -- "Remove from <plant>" refuses new Wave Scan AND Film files.

Claims (task section 3):

1. Migration 0036 seeded exactly two rows -- FTM x ``P703 RAPCAP`` and FTM x
   ``P703 SGL``, offered -- with one system audit row, and now every plant x
   model with Film readings or a live Film list is offered (D-112F-3).
2. Film ingest checks the model offer once the model has resolved (D-112F-2):
   a not-offered model is refused with WaveScan's ``MODEL_NOT_OFFERED`` and
   sentence; an offered one loads as before. Shown at the cleaner and on a
   real committed FTM SGL batch re-planned through ``IngestService._plan``.
3. Wave Scan is unchanged for Film-only models (D-112F-5): every spelling of
   them gets the same outcome with or without the 0036 rows, and an offered
   Film-only model is still refused as "not this domain".
4. Attach / Remove accept ``P703 RAPCAP`` and audit it (D-112F-4); the
   model-points read follows D-112F-6 and lists Film-only models to attach.

**What this file writes.** Nothing that commits. Claims 2 (real batch) and 4
run inside one owner transaction that is always rolled back -- the Remove,
the Attach and their audit rows never commit. The API calls are GETs, or an
Attach of an already-offered model, which answers 409 before any write.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.domain.cleaner import Cleaner, CleanRow, Reject, RejectReason
from app.domain.film import FilmCleaner, resolve_film_model
from app.domain.reader import RawRow, describe_film_sheet, read_film_sheet
from app.repositories import reference as reference_repo
from app.repositories import standards as repo
from tests.test_t04_ingest import admin, ingest_apps, viewer  # noqa: F401
from tests.test_t60_named_ingest_aliases import (  # noqa: F401
    MEASURES,
    T60_FILM_ALIAS,
    qs,
    refs,
)

PLANT = "FTM"
SEEDED = (("FTM", "P703 RAPCAP"), ("FTM", "P703 SGL"))
FILM_ONLY = ("P703 RAPCAP", "P703 SGL")


def sentence(model: str, plant: str) -> str:
    """WaveScan's sentence, `domain/cleaner.py` (D-112F-2: the same words)."""
    return f"model {model!r} is not on {plant}'s list. It will not load here."


@pytest.fixture()
def owner_tx(admin_dsn):
    """An owner SQLAlchemy connection inside a transaction that always rolls back."""
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                yield conn
            finally:
                tx.rollback()
    finally:
        engine.dispose()


# =====================================================================
# 1. migration 0036
# =====================================================================
def test_0036_seeded_exactly_the_two_ftm_offer_rows(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] >= "0036"
        cur.execute(
            "SELECT plant_code, model_code, is_offered FROM ref_plant_model "
            "WHERE model_code = ANY(%s) ORDER BY 1, 2", (list(FILM_ONLY),),
        )
        assert cur.fetchall() == [(*pair, True) for pair in SEEDED]
        cur.execute(
            "SELECT entity_id, after ->> 'revision' FROM audit_event "
            "WHERE action = 'catalogue.plant_model.seed'"
        )
        assert cur.fetchall() == [("FTM:P703 RAPCAP,P703 SGL", "0036")]
        # Nothing loaded today is refused by the new check.
        cur.execute(
            """
            WITH film AS (
                SELECT plant_code, model_code FROM ref_plant_film_point
                 WHERE retired_at IS NULL
                UNION SELECT DISTINCT plant, model FROM filmthickness
            )
            SELECT f.* FROM film f LEFT JOIN ref_plant_model pm
              USING (plant_code, model_code)
             WHERE NOT COALESCE(pm.is_offered, false)
            """
        )
        assert cur.fetchall() == []


# =====================================================================
# 2. Film checks the model offer (D-112F-2)
# =====================================================================
def _film(refs, offered_models, *, plant="FVL", filename="P703-T112F-AB.xlsx"):  # noqa: F811
    data = qs(["Clearcoat", "Primer", "E-Coat"], ["001HOOD", "002HOOD"],
              colour="Pace Red", job="T112F1")
    template = describe_film_sheet(data, "Quick Summary", T60_FILM_ALIAS)
    rows = list(read_film_sheet(data, "Quick Summary", template, filename))
    model = resolve_film_model(plant, filename, "Quick Summary", refs[1].model_alias)
    return FilmCleaner(
        refs[1], plant=plant, model=model, meta=template.meta_map,
        color_by_plant=refs[0].color_by_plant, color=refs[0].color,
        known_color_names=sorted(refs[0].known_color_names),
        offered_colors=refs[0].offered_colors,
        offered_models=offered_models,
    ).clean_all(rows)


def test_film_model_not_offered_is_refused_with_the_wavescan_sentence(refs):  # noqa: F811
    offered = dict(refs[0].offered_models)
    assert offered[("FVL", "P703 DBL RANGER")] is True
    loads = _film(refs, offered)
    assert loads.rejects == [] and len(loads.clean) == 2

    offered[("FVL", "P703 DBL RANGER")] = False   # in memory only: "Removed"
    result = _film(refs, offered)
    assert result.clean == [] and result.held == []
    assert {r.reason for r in result.rejects} == {RejectReason.MODEL_NOT_OFFERED}
    assert len(result.rejects) == 2
    for r in result.rejects:
        assert r.detail == sentence("P703 DBL RANGER", "FVL")
        assert (r.column, r.value) == ("model", "P703 DBL RANGER")


def test_film_model_with_no_offer_row_is_refused(refs):  # noqa: F811
    offered = {k: v for k, v in refs[0].offered_models.items() if k != ("FVL", "P703 DBL RANGER")}
    result = _film(refs, offered)
    assert result.clean == []
    assert {r.reason for r in result.rejects} == {RejectReason.MODEL_NOT_OFFERED}


def _service():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from app.core.config import Settings
    from app.services.ingest import IngestService
    from app.services.raw_store import RawStore
    from run_standing_8012 import app_url

    settings = Settings(env="development", app_database_url=app_url())
    return IngestService(settings, RawStore(settings.raw_store_path))


def test_a_real_sgl_file_is_refused_after_remove_and_loads_after_attach(
    owner_tx, actor_user_id
):
    """Rolled back: Remove SGL at FTM, re-plan a committed SGL file, Attach."""
    from app.repositories import batches as batch_repo
    from app.services.ingest import _projection_of

    conn = owner_tx
    load_id = conn.execute(text(
        "SELECT min(load_id) FROM load_batch WHERE plant_code = 'FTM' "
        "AND domain = 'FILMTHICKNESS' AND status = 'COMMITTED' "
        "AND source_file LIKE '%\\_SGL\\_%'"
    )).scalar_one()
    if load_id is None:
        pytest.skip("no committed FTM SGL Film batch on this database")
    service = _service()
    batch = batch_repo.get_batch(conn, load_id)
    if not service.store.exists(batch["raw_store_key"]):
        # Uploaded workbooks are plant data: they stay in the original raw store.
        pytest.skip("the batch's original workbook is not in this machine's raw store")
    data = service.store.get(batch["raw_store_key"])

    def outcomes() -> dict[str, int]:
        ref = reference_repo.load_reference_data(conn)
        plan, raw_rows, context = service._plan(conn, batch, data, ref)
        seen: dict[str, int] = {}
        for e in _projection_of(plan, raw_rows, context):
            key = f"{e['disposition']}:{e['reason']}"
            seen[key] = seen.get(key, 0) + 1
            if e["reason"] == "MODEL_NOT_OFFERED":
                assert e["detail"] == sentence("P703 SGL", PLANT)
        return seen

    before = outcomes()
    assert "REJECT:MODEL_NOT_OFFERED" not in before
    assert before.get("DUPLICATE:DUPLICATE_ROW", 0) > 0     # loaded before

    removed = repo.set_plant_model_offered(
        conn, plant_code=PLANT, model_code="P703 SGL", is_offered=False,
        actor_user_id=actor_user_id, correlation_id=None,
    )
    assert removed["is_offered"] is False
    after_remove = outcomes()
    assert after_remove.get("REJECT:MODEL_NOT_OFFERED") == before["DUPLICATE:DUPLICATE_ROW"]
    assert "DUPLICATE:DUPLICATE_ROW" not in after_remove
    # the known tail is still never a reason anything stops (D-99-6)
    assert after_remove.get("AGGREGATE_ROW:FILM_TAIL_LABEL") == before.get(
        "AGGREGATE_ROW:FILM_TAIL_LABEL")

    repo.attach_models(conn, model_code="P703 SGL", plants=[PLANT],
                       actor_user_id=actor_user_id, correlation_id=None)
    assert outcomes() == before


# =====================================================================
# 3. Wave Scan is unchanged for Film-only models (D-112F-5)
# =====================================================================
SPELLINGS = ("P703 RAPCAP", "p703 rapcap", "P703 SGL", "RAPCAP", "Single CAP",
             "SGL", "P703 RAP", "P703 DBL RANGER")


def _ws(ref, model_cell):
    return Cleaner(ref, (PLANT,), expected_plant=PLANT).clean_row(
        RawRow("t112f.xlsx", "s", 2, dict(
            date="2026-09-08", plant=PLANT, model=model_cell,
            checkzone="01 RRHOOD", color="Frozen White", **MEASURES))
    )


def _key(out):
    if isinstance(out, Reject):
        return ("REJECT", out.reason, out.detail, out.column, out.value)
    return (type(out).__name__, getattr(out, "model", None))


def test_wavescan_outcomes_for_film_only_spellings_are_what_they_were(refs):  # noqa: F811
    ref = refs[0]
    assert all(ref.offered_models.get(pair) is True for pair in SEEDED)
    before_0036 = replace(
        ref, offered_models={k: v for k, v in ref.offered_models.items() if k not in SEEDED},
    )
    for cell in SPELLINGS:
        assert _key(_ws(ref, cell)) == _key(_ws(before_0036, cell)), cell
    cleaner = Cleaner(ref, (PLANT,), expected_plant=PLANT)
    for code in FILM_ONLY:
        assert cleaner.offered_model_code(PLANT, code) is None


def test_an_offered_film_only_model_is_still_not_this_domain_for_wavescan(refs):  # noqa: F811
    ref = refs[0]
    for code in FILM_ONLY:
        alias_hit = Cleaner(ref, (PLANT,), expected_plant=PLANT).plant_first(
            ref.model_by_plant, ref.model, PLANT, code)
        out = _ws(ref, code)
        assert isinstance(out, Reject), out
        assert not isinstance(out, CleanRow)
        if alias_hit in FILM_ONLY:
            # T115-FIX (D-115F-1): its own code, never reloaded by an Attach.
            assert out.reason == RejectReason.FILM_ONLY_MODEL
            assert "not this domain" in out.detail
        else:
            assert out.reason == RejectReason.UNKNOWN_MODEL


# =====================================================================
# 4. Attach / Remove of a Film-only model; the model-points read
# =====================================================================
def test_attach_and_remove_accept_rapcap_with_audit(owner_tx, actor_user_id):
    conn = owner_tx
    actor = actor_user_id

    def audits(action: str, entity: str) -> int:
        return conn.execute(text(
            "SELECT count(*) FROM audit_event WHERE action = :a AND entity_id = :e"
        ), {"a": action, "e": entity}).scalar_one()

    removed_before = audits("catalogue.plant_model.offered", "FTM:P703 RAPCAP")
    out = repo.set_plant_model_offered(
        conn, plant_code=PLANT, model_code="P703 RAPCAP", is_offered=False,
        actor_user_id=actor, correlation_id=None,
    )
    assert out["is_offered"] is False and out["audit_id"]
    assert audits("catalogue.plant_model.offered", "FTM:P703 RAPCAP") == removed_before + 1
    cards = {m["model_code"] for m in repo.model_points(conn, PLANT)}
    assert "P703 RAPCAP" not in cards                      # the card leaves
    assert "P703 RAPCAP" in repo.attachable_models(conn, PLANT)

    attached_before = audits("catalogue.plant_model.attach", "P703 RAPCAP")
    out = repo.attach_models(conn, model_code="P703 RAPCAP", plants=[PLANT],
                             actor_user_id=actor, correlation_id=None)
    assert out["plants"] == [PLANT] and out["audit_id"]
    assert audits("catalogue.plant_model.attach", "P703 RAPCAP") == attached_before + 1
    by_code = {m["model_code"]: m for m in repo.model_points(conn, PLANT)}
    assert by_code["P703 RAPCAP"]["film_points"] == 93      # Attach brings it back

    # A Film-only model attached where it has no Film list: no Film points yet.
    repo.attach_models(conn, model_code="P703 SGL", plants=["AAT"],
                       actor_user_id=actor, correlation_id=None)
    aat = {m["model_code"]: m for m in repo.model_points(conn, "AAT")}
    assert (aat["P703 SGL"]["wavescan_points"], aat["P703 SGL"]["film_points"]) == (None, None)
    assert aat["P703 SGL"]["wavescan_ok"] is False


def test_attach_api_no_longer_refuses_a_film_only_model_as_not_this_domain(admin):  # noqa: F811
    # Already offered at FTM (0036): 409 "already attached", not 422, no write.
    for code in FILM_ONLY:
        response = admin.post(
            "/api/v1/standards/plant-models", json={"model_code": code, "plants": [PLANT]},
        )
        assert response.status_code == 409, response.text
        assert "not this domain" not in response.text


def test_model_points_is_offered_models_and_the_attach_list(admin):  # noqa: F811
    body = admin.get("/api/v1/plants/FTM/model-points").json()
    got = {m["model_code"]: (m["wavescan_points"], m["film_points"]) for m in body["models"]}
    assert got == {
        "P703 DBL RANGER": (32, 98), "P703 DBL RAPTOR": (32, 98),
        "P703 RAPCAP": (None, 93), "P703 SGL": (None, 58),
    }
    assert body["attachable_models"] == [
        "CX743", "J73 DBL", "P703 DBL SUPER DUTY", "U704", "V363",
    ]
    aat = admin.get("/api/v1/plants/AAT/model-points").json()
    assert set(FILM_ONLY) <= set(aat["attachable_models"])   # Film-only listed
    assert not set(FILM_ONLY) & {m["model_code"] for m in aat["models"]}
