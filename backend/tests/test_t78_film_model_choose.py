"""T78 part D / T61 -- the Engineer picks which model a held Film sheet is.

D-78-30..34. A Film sheet whose file and tab name do not settle one model is
held ``FILM_MODEL_UNRESOLVED``. Until now the Engineer had no action. Now:

* the held-label read publishes **server-derived** options -- the hold
  detail, the models the names pointed at, the plant's whole Film
  vocabulary (candidates first) and the teachable tokens;
* the Engineer proposes ``kind = "FILM_MODEL"``, an **Admin** approves, both
  audited, and the sheet is replayed through the **same** ingest service;
* a choice carrying a teachable token also teaches
  ``ref_film_model_alias``, so the next file with that token resolves by
  itself; the same model again is a no-op and a different model is 409;
* an ambiguous hold resolves the sheet only and teaches nothing.

Claims proved here, against the live seed, the running application, the
worker and the database:

1. FTM ``_XX_`` is held; teaching ``XX`` -> ``P703 SGL`` and approving
   replays the sheet and loads it; a second ``_XX_`` file resolves alone.
2. An ambiguous file/tab is a sheet-only choice and writes no alias.
3. A SAP file proposing ``P703 RAPCAP`` is 422 (not SAP's vocabulary).
4. An FVL ``J73`` leftover is 422 (no Film list for it at FVL).
5. A token already taught as a different model is 409, and is not overwritten.
6. An Engineer cannot approve; a Viewer cannot propose.
7. ``mapping.propose`` and ``mapping.approve`` audit rows are written.
8. WaveScan ``ALIAS_MODEL`` is unchanged.
9. Film ``_RAP_`` is still RAPCAP at FTM (D-FT-08).

Every workbook is synthetic. The fixtures delete **only** the rows these
tests created: the batches and their facts (``film_cleanup``), the
``ref_film_model_alias`` rows they taught and the ``proposed_mapping`` rows
they raised. ``audit_event`` is append-only and is never touched.
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer, wait_for  # noqa: F401
from tests.test_t46_filmthickness import (  # noqa: F401  (fixtures + helpers)
    film_cleanup,
    film_facts,
    pelt,
    sent,
)

pytestmark = pytest.mark.ingest

PROPOSALS = "/api/v1/mappings/proposals"


# =====================================================================
# fixtures -- read the live seed, and clean up only what we made
# =====================================================================
@pytest.fixture
def taught(admin_conn):
    """Forget the ref_film_model_alias rows a test taught."""
    tokens: list[tuple[str, str]] = []
    yield tokens
    if not tokens:
        return
    with admin_conn.cursor() as cur:
        for plant, token in tokens:
            cur.execute(
                "DELETE FROM ref_film_model_alias "
                " WHERE plant_code = %s AND raw_token = %s",
                (plant, token),
            )


@pytest.fixture
def proposals(admin_conn):
    """Forget the proposed_mapping rows a test raised (never audit_event)."""
    ids: list[str] = []
    yield ids
    if not ids:
        return
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM proposed_mapping WHERE id = ANY(%s::uuid[])", (ids,))


@pytest.fixture(scope="module")
def seed(admin_conn):
    """The plant Film vocabulary, SGL gold names and an FTM-offered colour."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code FROM ref_film_model_alias "
            " GROUP BY plant_code, model_code"
        )
        vocab: dict[str, set[str]] = {}
        for plant, model in cur.fetchall():
            vocab.setdefault(plant, set()).add(model)
        cur.execute(
            "SELECT point_code FROM ref_plant_film_point "
            " WHERE plant_code = 'FTM' AND model_code = 'P703 SGL' "
            " ORDER BY point_no LIMIT 12"
        )
        sgl = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT color_name FROM ref_plant_color "
            " WHERE plant_code = 'FTM' AND is_offered ORDER BY color_name LIMIT 1"
        )
        colour = cur.fetchone()[0]
    assert sgl, "the FTM P703 SGL gold list is empty; the seed changed"
    return {"vocab": vocab, "sgl": sgl, "colour": colour}


def propose(client, plant, load_id, sheet, model, token=None, note=None):
    payload = {
        "plant": plant,
        "load_id": load_id,
        "source_sheet": sheet,
        "model_code": model,
    }
    if token is not None:
        payload["raw_token"] = token
    if note is not None:
        payload["note"] = note
    return client.post(
        PROPOSALS, json={"kind": "FILM_MODEL", "load_id": load_id, "payload": payload}
    )


def film_model_hold(review) -> dict | None:
    for item in review["held_labels"]:
        if item["reason"] == "FILM_MODEL_UNRESOLVED":
            return item
    return None


def upload_ftm_xx(engineer, film_cleanup, admin_conn, seed, token="XX"):
    """An FTM PELT whose filename token no alias covers -> the sheet holds.

    T99 CHANGE (D-99-10): the Job Number is FTM's shape now
    (``{COLOUR}_{TOKEN}_{7 digits}``) and names the **filename's** token, so
    that once the model question is answered the sheet is not held again for
    its Job Number or for naming two models. Neither is this file's subject;
    both have their own tests in `test_t99_film_point_lists`.
    """
    job = f"AW_{token}_{uuid.uuid4().int % 10**7:07d}"
    data = pelt(seed["sgl"], colour=seed["colour"], job=job)
    reviews = sent(engineer, film_cleanup, admin_conn, f"{job}.xlsx", data, "FTM")
    return reviews["Quick Summary"]


def upload_ftm_held_naming(engineer, film_cleanup, admin_conn, seed, carried):
    """A held FTM sheet whose name also carries ``carried`` as a word.

    ``AW_YY_XX.xlsx`` is `{COLOR}_{TOKEN}_{job}`: the filename token is the
    unknown ``YY``, and ``XX`` is a word of the name, so while neither is
    taught the sheet is held and **both** are teachable tokens of it.

    Order matters for the conflict tests. Once ``XX`` is taught, step 2 of
    `resolve_film_model` finds it as a word and this sheet resolves by
    itself -- so a clashing proposal has to be *raised* before the token
    exists. It is still answerable afterwards because "is this sheet held?"
    is read from the stored review projection, and only the sheet that was
    replayed stopped asking.
    """
    # T99 CHANGE (D-99-10/11): the Job Number is FTM's shape and names the
    # filename's own token `YY`, so the sheet is held for the model question
    # this test is about and for nothing else.
    job = f"AW_YY_{uuid.uuid4().int % 10**7:07d}"
    data = pelt(seed["sgl"], colour=seed["colour"], job=job)
    reviews = sent(
        engineer, film_cleanup, admin_conn, f"AW_YY_{carried}.xlsx", data, "FTM"
    )
    return reviews["Quick Summary"]


def staged_models(admin_conn, load_id) -> set:
    """The model the review projection staged for the rows it will load."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT canonical ->> 'model' FROM stg_review_row "
            " WHERE load_id = %s AND disposition = 'LOAD'",
            (load_id,),
        )
        return {r[0] for r in cur.fetchall()}


# =====================================================================
# 1. the whole T61 round trip
# =====================================================================
def test_an_unknown_ftm_token_is_held_with_server_derived_options(
    engineer, admin_conn, film_cleanup, seed  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    assert review["batch"]["counts"]["rows_loaded"] == 0

    held = film_model_hold(review)
    assert held is not None, review["held_labels"]
    assert held["teachable_kind"] == "FILM_MODEL"
    assert held["display_group"] == "film_model"

    options = held["film_model"]
    assert options is not None
    assert options["load_id"] == review["batch"]["load_id"]
    assert options["source_sheet"] == "Quick Summary"
    assert options["plant_code"] == "FTM"
    assert options["resolution_source"] == "none"
    assert options["candidates"] == []           # neither name named a model
    # choices are exactly FTM's Film vocabulary -- never ref_plant_model
    assert set(options["choices"]) == seed["vocab"]["FTM"]
    assert "P703 SGL" in options["choices"]
    # the server derived the token from the filename; the client never types it
    assert "XX" in options["teachable_tokens"]
    assert options["detail"]


def test_teaching_the_token_replays_the_sheet_and_the_next_file_resolves_alone(
    engineer, admin, admin_conn, film_cleanup, seed, taught, proposals  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    load_id = review["batch"]["load_id"]

    # -- the Engineer proposes ------------------------------------------
    response = propose(
        engineer, "FTM", load_id, "Quick Summary", "P703 SGL",
        token="XX", note="T78 part D test",
    )
    assert response.status_code == 201, response.text
    proposal = response.json()
    proposals.append(proposal["id"])
    assert proposal["kind"] == "FILM_MODEL"
    # NOT applied in the Engineer's request: an Admin decides (D-78-31)
    assert proposal["status"] == "PROPOSED"
    assert proposal["decided_by"] is None

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_film_model_alias "
            " WHERE plant_code = 'FTM' AND raw_token = 'XX'"
        )
        assert cur.fetchone()[0] == 0, "proposing must not write the alias"

    # -- the Admin approves: alias + replay -----------------------------
    taught.append(("FTM", "XX"))
    approved = admin.post(f"{PROPOSALS}/{proposal['id']}/approve")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["proposal"]["status"] == "APPROVED"
    assert body["applied_to"] == "ref_film_model_alias"
    assert body["replay"] is not None, "the sheet must be replayed"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, note FROM ref_film_model_alias "
            " WHERE plant_code = 'FTM' AND raw_token = 'XX'"
        )
        row = cur.fetchone()
    assert row[0] == "P703 SGL"
    assert proposal["id"] in row[1] and "T78 part D test" in row[1]

    # -- the replayed sheet now resolves, and is ready as P703 SGL ------
    # Replay re-stages the sheet through the same ingest service; facts are
    # written at commit (ADR 0005), so what replay must show is that the
    # model question is gone and every row is staged to LOAD as P703 SGL.
    after = wait_for(engineer, load_id)
    assert film_model_hold(after) is None, "the model question is answered"
    assert after["batch"]["counts"]["rows_loaded"] == len(seed["sgl"])
    assert staged_models(admin_conn, load_id) == {"P703 SGL"}

    # -- a SECOND _XX_ file now resolves by itself ----------------------
    second = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    assert film_model_hold(second) is None, "the taught token must resolve alone"
    assert second["batch"]["counts"]["rows_loaded"] == len(seed["sgl"])


def test_both_steps_are_audited(
    engineer, admin, admin_conn, film_cleanup, seed, taught, proposals  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    load_id = review["batch"]["load_id"]
    response = propose(
        engineer, "FTM", load_id, "Quick Summary", "P703 SGL", token="XX"
    )
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    proposals.append(pid)
    taught.append(("FTM", "XX"))
    assert admin.post(f"{PROPOSALS}/{pid}/approve").status_code == 200

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT action, actor_type FROM audit_event "
            " WHERE entity_type = 'proposed_mapping' AND entity_id = %s "
            " ORDER BY id",
            (pid,),
        )
        rows = cur.fetchall()
    actions = [a for a, _t in rows]
    assert "mapping.propose" in actions
    assert "mapping.approve" in actions
    assert {t for _a, t in rows} == {"user"}


# =====================================================================
# 2. ambiguous: the sheet only, no alias
# =====================================================================
def test_an_ambiguous_sheet_is_a_sheet_only_choice_and_teaches_nothing(
    engineer, admin, admin_conn, film_cleanup, seed, proposals  # noqa: F811
):
    # SAP knows both J73 and P703, so a name carrying both settles nothing.
    job = f"T78{uuid.uuid4().hex[:6].upper()}"
    data = pelt(seed["sgl"], colour=seed["colour"], job=job)
    name = f"{job} J73 P703 PELT.xlsx"
    reviews = sent(engineer, film_cleanup, admin_conn, name, data, "SAP")
    review = reviews["Quick Summary"]
    load_id = review["batch"]["load_id"]

    held = film_model_hold(review)
    assert held is not None, review["held_labels"]
    options = held["film_model"]
    assert options["resolution_source"] == "ambiguous"
    assert set(options["candidates"]) == {"J73 DBL", "P703 DBL RANGER"}
    # ambiguous => nothing is teachable, so raw_token must be absent
    assert options["teachable_tokens"] == []

    # a token is refused ...
    refused = propose(
        engineer, "SAP", load_id, "Quick Summary", "J73 DBL", token="J73"
    )
    assert refused.status_code == 422, refused.text
    assert "raw_token must be absent" in refused.json()["message"]
    assert refused.json()["correlationId"]

    # ... and the sheet-only choice is accepted
    ok = propose(engineer, "SAP", load_id, "Quick Summary", "J73 DBL")
    assert ok.status_code == 201, ok.text
    pid = ok.json()["id"]
    proposals.append(pid)
    approved = admin.post(f"{PROPOSALS}/{pid}/approve")
    assert approved.status_code == 200, approved.text
    assert "sheet-only" in approved.json()["applied_to"]

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_film_model_alias WHERE plant_code='SAP'")
        # SAP's four seeded rows and not one more
        assert cur.fetchone()[0] == 4


# =====================================================================
# 3-5. the refusals
# =====================================================================
def test_a_model_outside_the_plant_vocabulary_is_422(
    engineer, admin_conn, film_cleanup, seed  # noqa: F811
):
    """A SAP file may not be RAPCAP: RAPCAP exists only at FTM (D-FT-08c)."""
    job = f"T78{uuid.uuid4().hex[:6].upper()}"
    data = pelt(seed["sgl"], colour=seed["colour"], job=job)
    reviews = sent(
        engineer, film_cleanup, admin_conn, f"AW_ZZ_{job}.xlsx", data, "SAP"
    )
    review = reviews["Quick Summary"]
    assert film_model_hold(review) is not None
    assert "P703 RAPCAP" not in seed["vocab"]["SAP"]

    response = propose(
        engineer, "SAP", review["batch"]["load_id"], "Quick Summary", "P703 RAPCAP"
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "vocabulary" in body["message"]
    assert body["correlationId"]


def test_a_leftover_program_with_no_film_list_at_the_plant_is_422(
    engineer, admin_conn, film_cleanup, seed  # noqa: F811
):
    """FVL has CX743 and V363 of its own, but no J73 Film list (F8/D-55-09)."""
    job = f"T78{uuid.uuid4().hex[:6].upper()}"
    data = pelt(seed["sgl"], colour=seed["colour"], job=job)
    reviews = sent(
        engineer, film_cleanup, admin_conn, f"AW_ZZ_{job}.xlsx", data, "FVL"
    )
    review = reviews["Quick Summary"]
    assert film_model_hold(review) is not None
    assert "J73 DBL" not in seed["vocab"]["FVL"]

    response = propose(
        engineer, "FVL", review["batch"]["load_id"], "Quick Summary", "J73 DBL"
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "leftover program" in body["message"]
    assert body["correlationId"]


def test_a_token_already_taught_as_another_model_is_409_and_not_overwritten(
    engineer, admin, admin_conn, film_cleanup, seed, taught, proposals  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    load_id = review["batch"]["load_id"]

    taught.append(("FTM", "XX"))

    # A second held sheet whose name also carries XX, raised BEFORE XX exists.
    other = upload_ftm_held_naming(engineer, film_cleanup, admin_conn, seed, "XX")
    other_id = other["batch"]["load_id"]
    assert film_model_hold(other) is not None
    assert "XX" in film_model_hold(other)["film_model"]["teachable_tokens"]
    clash = propose(
        engineer, "FTM", other_id, "Quick Summary", "P703 RAPCAP", token="XX"
    )
    assert clash.status_code == 201, clash.text
    proposals.append(clash.json()["id"])

    # Now XX is taught as P703 SGL by the first sheet.
    first = propose(engineer, "FTM", load_id, "Quick Summary", "P703 SGL", token="XX")
    assert first.status_code == 201, first.text
    proposals.append(first.json()["id"])
    assert admin.post(f"{PROPOSALS}/{first.json()['id']}/approve").status_code == 200

    # Approving the older, clashing proposal must be refused outright.
    answered = admin.post(f"{PROPOSALS}/{clash.json()['id']}/approve")
    assert answered.status_code == 409, answered.text
    body = answered.json()
    assert "never overwritten" in body["message"]
    assert body["correlationId"]

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code FROM ref_film_model_alias "
            " WHERE plant_code = 'FTM' AND raw_token = 'XX'"
        )
        assert cur.fetchone()[0] == "P703 SGL", "the live alias must be untouched"
        cur.execute("SELECT status FROM proposed_mapping WHERE id = %s",
                    (clash.json()["id"],))
        assert cur.fetchone()[0] == "PROPOSED", "a refused approval decides nothing"
    # and the sheet it was refused on is still held, not half-resolved
    assert film_model_hold(wait_for(engineer, other_id)) is not None


def test_the_same_token_and_the_same_model_again_is_a_no_op(
    engineer, admin, admin_conn, film_cleanup, seed, taught, proposals  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    load_id = review["batch"]["load_id"]
    taught.append(("FTM", "XX"))

    # Both proposals are raised while XX is still unknown, so both sheets are
    # held and XX is teachable on both.
    other = upload_ftm_held_naming(engineer, film_cleanup, admin_conn, seed, "XX")
    again = propose(
        engineer, "FTM", other["batch"]["load_id"], "Quick Summary",
        "P703 SGL", token="XX",
    )
    assert again.status_code == 201, again.text
    proposals.append(again.json()["id"])

    first = propose(engineer, "FTM", load_id, "Quick Summary", "P703 SGL", token="XX")
    proposals.append(first.json()["id"])
    assert admin.post(f"{PROPOSALS}/{first.json()['id']}/approve").status_code == 200

    # The SAME token already meaning the SAME model is the Engineer
    # confirming it, not a conflict: accepted, and it writes no second row
    # (T39's reasoning, applied to Film tokens).
    approved = admin.post(f"{PROPOSALS}/{again.json()['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["applied_to"] == "ref_film_model_alias"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_film_model_alias "
            " WHERE plant_code = 'FTM' AND raw_token = 'XX'"
        )
        assert cur.fetchone()[0] == 1, "no second row for the same token"


def test_a_non_film_batch_is_422(engineer, admin_conn):  # noqa: F811
    """FILM_MODEL answers a FilmThickness sheet only."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT load_id, plant_code, source_sheet FROM load_batch "
            " WHERE domain = 'WAVESCAN' ORDER BY load_id LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip("no WaveScan batch in this database to exercise the gate")
    load_id, plant, sheet = row
    response = propose(engineer, plant, load_id, sheet, "P703 DBL RANGER")
    assert response.status_code == 422, response.text
    assert "FilmThickness" in response.json()["message"]
    assert response.json()["correlationId"]


def test_a_sheet_not_held_for_its_model_is_422(
    engineer, admin_conn, film_cleanup, seed  # noqa: F811
):
    """A file whose name DOES settle the model has no question to answer."""
    job = f"T78{uuid.uuid4().hex[:6].upper()}"
    data = pelt(seed["sgl"], colour=seed["colour"], job=job)
    reviews = sent(
        engineer, film_cleanup, admin_conn, f"AW_SGL_{job}.xlsx", data, "FTM"
    )
    review = reviews["Quick Summary"]
    assert film_model_hold(review) is None, "_SGL_ settles the model by itself"

    response = propose(
        engineer, "FTM", review["batch"]["load_id"], "Quick Summary", "P703 SGL"
    )
    assert response.status_code == 422, response.text
    assert "not held" in response.json()["message"]
    assert response.json()["correlationId"]


def test_a_raw_token_the_server_did_not_derive_is_422(
    engineer, admin_conn, film_cleanup, seed  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    response = propose(
        engineer, "FTM", review["batch"]["load_id"], "Quick Summary", "P703 SGL",
        token="NOTINTHENAME",
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "teachable" in body["message"]
    assert body["correlationId"]


# =====================================================================
# 6. who may do what
# =====================================================================
def test_an_engineer_cannot_approve_and_a_viewer_cannot_propose(
    engineer, viewer, admin_conn, film_cleanup, seed, proposals  # noqa: F811
):
    review = upload_ftm_xx(engineer, film_cleanup, admin_conn, seed)
    load_id = review["batch"]["load_id"]

    assert propose(viewer, "FTM", load_id, "Quick Summary", "P703 SGL").status_code == 403

    response = propose(engineer, "FTM", load_id, "Quick Summary", "P703 SGL", token="XX")
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    proposals.append(pid)

    assert engineer.post(f"{PROPOSALS}/{pid}/approve").status_code == 403
    assert viewer.post(f"{PROPOSALS}/{pid}/approve").status_code == 403

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM proposed_mapping WHERE id = %s", (pid,))
        assert cur.fetchone()[0] == "PROPOSED"
        cur.execute(
            "SELECT count(*) FROM ref_film_model_alias "
            " WHERE plant_code = 'FTM' AND raw_token = 'XX'"
        )
        assert cur.fetchone()[0] == 0


# =====================================================================
# 8-9. nothing else moved
# =====================================================================
def test_wavescan_alias_model_is_unchanged(admin_conn):
    """T78 adds a kind; it does not touch WaveScan's model aliases."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ref_model_alias")
        assert cur.fetchone()[0] == 18, "T77 left exactly 18 WaveScan model aliases"
        cur.execute(
            "SELECT model_code FROM ref_model_alias "
            " WHERE upper(raw_value) LIKE '%%RAP%%' AND plant_code = 'SAP'"
        )
        wavescan = {r[0] for r in cur.fetchall()}
    # WaveScan RAP is Raptor; it is never RAPCAP (D-FT-08)
    assert "P703 RAPCAP" not in wavescan


def test_film_rap_is_still_rapcap_at_ftm(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code FROM ref_film_model_alias "
            " WHERE plant_code = 'FTM' AND raw_token = 'RAP'"
        )
        assert cur.fetchone()[0] == "P703 RAPCAP"
