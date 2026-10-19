"""T115-FIX -- a Film-only model on a Wave Scan sheet has its own reason.

Claims (task section 3):

1. **D-115F-1.** A Wave Scan row naming a Film-only model (RAPCAP, Single
   CAP) is held `FILM_ONLY_MODEL`, never `MODEL_NOT_OFFERED`; a Removed Wave
   Scan model still is `MODEL_NOT_OFFERED`. `reject_log` accepts the code
   (revision 0040).
2. **D-115F-2.** Its sentence is its own; the Removed-model and colour
   sentences are byte-for-byte what they were. No control: not teachable,
   no candidates.
3. **D-115F-3.** An Attach never replays a sheet held only for it, while the
   Removed-model sheet beside it is still reloaded.

**How the cell reaches the code.** Measured 2026-10-12: no `ref_model_alias`
row names RAPCAP or Single CAP, and `offered_model_code` never returns a
Film-only model (T112-FIX D-112F-5), so on the live data a `P703 RAPCAP` cell
is `UNKNOWN_MODEL`. `cleaner.py`'s Film-only branch is reached only through
an alias. The tests below add one, scoped to FVL, inside the rolled-back
transaction.

**What this file writes, and how.** As `test_t115_act_closeout.py`: every
write is inside one owner transaction that is always rolled back -- the
Remove, the Attach, the uploads and everything they produce. The plant x
model is FVL x P703 DBL RANGER, never FTM's.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.domain.cleaner import RejectReason
from app.domain.held_label_copy import (
    FILM_ONLY_MODEL_MESSAGE,
    display_group_for,
    operator_message_for,
)
from app.repositories import batches as batch_repo
from app.repositories import standards as repo
from app.schemas.ingest import TEACHABLE_HELD_REASONS
from app.services import model_offer
from app.services.held_labels import held_label_items
from tests.test_t04_ingest import ingest_apps, make_workbook, unique_rows  # noqa: F401
from tests.test_t115_act_closeout import (  # noqa: F401
    COLOUR_SENTENCE,
    MODEL,
    PLANT,
    engine,
    held,
    remove,
    service,
    tx,
    upload,
)

pytestmark = pytest.mark.ingest

FILM_ONLY = "P703 RAPCAP"

FILM_ONLY_SENTENCE = (
    "P703 RAPCAP is measured for Film Thickness only, so a Wave Scan sheet "
    "cannot load it. Check the sheet's Model column; nothing here can attach "
    "it to Wave Scan."
)
REMOVED_SENTENCE = (
    "P703 DBL RANGER is not on FVL's list (it was removed, or never "
    "attached), so these rows will not load. An Admin attaches it on "
    "Standard → Model; this file then loads by itself."
)


# =====================================================================
# 1. the code and the constraint
# =====================================================================
def test_reject_log_accepts_the_new_code(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone()[0] >= "0040"
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_reject_reason'"
        )
        said = cur.fetchone()[0]
    for code in ("FILM_ONLY_MODEL", "MODEL_NOT_OFFERED", "COLOR_NOT_OFFERED"):
        assert f"'{code}'" in said, code


def test_the_code_is_its_own():
    assert RejectReason.FILM_ONLY_MODEL == "FILM_ONLY_MODEL"
    assert RejectReason.FILM_ONLY_MODEL != RejectReason.MODEL_NOT_OFFERED


# =====================================================================
# 2. the sentence, the group, no control
# =====================================================================
def test_the_film_only_sentence():
    assert display_group_for("FILM_ONLY_MODEL", FILM_ONLY) == "plant_offer"
    said = operator_message_for(
        "plant_offer", FILM_ONLY, plant="FTM", reason="FILM_ONLY_MODEL")
    assert said == FILM_ONLY_SENTENCE
    assert "attaches" not in FILM_ONLY_MODEL_MESSAGE
    assert "loads by itself" not in FILM_ONLY_MODEL_MESSAGE
    assert len(said) <= 500


def test_the_other_two_sentences_are_byte_for_byte_unchanged():
    assert operator_message_for(
        "plant_offer", MODEL, plant=PLANT, reason="MODEL_NOT_OFFERED"
    ) == REMOVED_SENTENCE
    for reason in ("COLOR_NOT_OFFERED", None):
        assert operator_message_for(
            "plant_offer", "Pace Red", plant="FTM", reason=reason
        ) == COLOUR_SENTENCE


def test_it_is_not_teachable():
    assert "FILM_ONLY_MODEL" not in TEACHABLE_HELD_REASONS
    assert "MODEL_NOT_OFFERED" not in TEACHABLE_HELD_REASONS


# =====================================================================
# 3. on a real upload: held, said, no control, never reloaded
# =====================================================================
def film_only_sheet(conn, service, actor) -> int:
    conn.execute(text(
        "INSERT INTO ref_model_alias (raw_value, model_code, plant_code, note) "
        "VALUES (:m, :m, :p, 'T115-FIX test, rolled back') "
        "ON CONFLICT DO NOTHING"
    ), {"m": FILM_ONLY, "p": PLANT})
    [load_id] = upload(
        conn, service, actor, f"t115fix-rapcap-{uuid.uuid4().hex[:6]}.xlsx",
        make_workbook(unique_rows(3, Plant=PLANT, Model=FILM_ONLY)),
    )
    return load_id


def test_a_film_only_model_is_held_with_its_sentence_and_no_control(
    engine, service, actor_user_id
):
    with tx(engine) as conn:
        load_id = film_only_sheet(conn, service, actor_user_id)
        assert held(conn, load_id) == {"FILM_ONLY_MODEL": 3}
        items = [i for i in held_label_items(conn, load_id, plant_code=PLANT)
                 if i["reason"] == "FILM_ONLY_MODEL"]
        assert len(items) == 1, items
        [item] = items
        assert item["display_group"] == "plant_offer"
        assert item["teachable_kind"] is None and item["candidates"] == []
        assert item["operator_message"] == FILM_ONLY_SENTENCE


def test_attach_reloads_the_removed_sheet_and_never_the_film_only_one(
    engine, service, actor_user_id
):
    with tx(engine) as conn:
        remove(conn, actor_user_id)
        film_only = film_only_sheet(conn, service, actor_user_id)
        [removed] = upload(
            conn, service, actor_user_id,
            f"t115fix-removed-{uuid.uuid4().hex[:6]}.xlsx",
            make_workbook(unique_rows(3, Plant=PLANT)),
        )
        assert held(conn, removed) == {"MODEL_NOT_OFFERED": 3}
        items = [i for i in held_label_items(conn, removed, plant_code=PLANT)
                 if i["reason"] == "MODEL_NOT_OFFERED"]
        assert [i["operator_message"] for i in items] == [REMOVED_SENTENCE]

        candidates = batch_repo.held_for_model_offer(conn, PLANT)
        assert removed in candidates
        assert film_only not in candidates

        out = repo.attach_models(
            conn, model_code=MODEL, plants=[PLANT], actor_user_id=actor_user_id,
            correlation_id="t115fix-attach",
            reload=lambda plants: model_offer.reload_held(
                conn, service, plants=plants, model_code=MODEL,
                actor_user_id=actor_user_id, correlation_id="t115fix-attach"),
        )
        assert removed in out["reloaded_load_ids"]
        assert film_only not in out["reloaded_load_ids"]
        assert film_only not in [r["load_id"] for r in out["reload_refused"]]
        # Untouched: still held, still its own code, no replay audited.
        assert held(conn, film_only) == {"FILM_ONLY_MODEL": 3}
        assert batch_repo.get_batch(conn, film_only)["status"] in batch_repo.REPLAYABLE_STATUSES
