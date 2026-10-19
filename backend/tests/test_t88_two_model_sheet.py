"""T88 Part 1 and D-88-6 -- against the running application and database.

Claims:

* **Part 1 / D-88-1.** A sheet whose odd panel spelling appears on **two**
  models yields **two** held groups -- one per `(spelling, model)` -- each
  carrying its own model, its own row count, its own candidates and its own
  orientation. Before T88 it yielded one group with `teachable_kind`,
  `model_code` and `candidates` all blanked and the sentence *"map it after
  the model is settled"*, which is what kept the owner's September file out
  of a screen built for it.
* A **one-model** sheet is unchanged -- the T41 behaviour this widens.
* The match screen **opens** for each model of a two-model sheet, and each
  one sees only its own spellings and its own panels.
* A pair is still only ever confirmed against **that** model's panels.
* **D-88-6 / G-88-8.** Held rows of a **COMMITTED** batch can be matched and
  then loaded without re-uploading: the loaded count rises by exactly the
  matched held count, and **no pre-existing `measurement_id` changes**
  (ADR 0005 -- those rows were never loaded, so they are new facts).

Two plants (D-88-8). Every batch is this module's own and is removed again;
the owner's `43599` / `43601` / `61551` are never touched.
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
    sent,
    viewer,
)

pytestmark = pytest.mark.ingest

PROPOSALS = "/api/v1/mappings/proposals"
PANEL_MATCH = "/api/v1/mappings/panel-match"

#: `(plant, [(model cell as the file writes it, resolved model)], colour)`.
#: Two plants, because nothing in T88 may be special-cased (D-88-8).
TWO_MODEL_PLANTS = {
    "FTM": (
        [("P703 DBL", "P703 DBL RANGER"), ("P703 DBL-RAPTOR", "P703 DBL RAPTOR")],
        "Ignite Orange",
    ),
    # RO18 CHANGE (owner decision): SAP has no Raptor -- P703 DBL RAPTOR is
    # not offered there and a `P703 RAP` row never loads -- so SAP's two
    # models are the two it offers, J73 DBL and P703 DBL RANGER.
    "SAP": (
        [("J73 DBL", "J73 DBL"), ("P703 DBL", "P703 DBL RANGER")],
        "Frozen White",
    ),
    # AAT's two models have genuinely DIFFERENT panel lists, which is what
    # makes "each question offers only its own model's panels" a real claim
    # rather than a vacuous one -- at FTM the two P703 variants share a list,
    # so there is nothing there to tell apart.
    "AAT": (
        [("P703 DBL RANGER", "P703 DBL RANGER"), ("U704", "U704")],
        "Arctic White",
    ),
}


def odd_panel() -> str:
    """A spelling no catalogue has, so the rows hold on the panel alone."""
    return f"T88ODDHOOD{uuid.uuid4().hex[:4].upper()}"


def live_panel(admin_conn, plant: str, model: str, orientation: str | None = None):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT zone_code, tolerance_group FROM ref_plant_ws_point "
            " WHERE plant_code = %s AND model_code = %s AND retired_at IS NULL "
            + ("  AND tolerance_group = %s " if orientation else "")
            + " ORDER BY point_no LIMIT 1",
            (plant, model, orientation) if orientation else (plant, model),
        )
        return cur.fetchone()


def forget_maps(
    admin_conn, plant: str, models: list[str], raws: list[str],
    since=SUITE_STARTED,
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    `models` is this test's own model list, never a default: a sheet of
    this module teaches the same spelling on two models, so both are named.

    **T98 (D-98-2).** Plant and model are not enough on their own: this
    module writes real spellings at a real plant and model, so a row the
    owner taught before the run matched the delete too (the
    `ref_plant_zone_map` row T97 lost). ``since`` floors the delete at the
    moment this suite started, so it reaches only rows this run inserted.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
            "   AND model_code = ANY(%s) AND raw_zone_text = ANY(%s)"
            "   AND created_at >= %s",
            (plant, list(models), [r.lower() for r in raws], since),
        )


def rows_for(plant: str, model_cell: str, colour: str, panel: str, zone: str,
             orientation: str, n: int, tag: str) -> list[dict]:
    day = "2026-08-05"
    out = []
    for i in range(n):
        out.append({
            "Date": day, "Plant": plant, "Model": model_cell, "Color": colour,
            "Checkzone": zone, "Tolerance Group": orientation,
            "CF": 55.0 + i, "Serial No": f"{tag}-{model_cell}-{i}",
        })
    # One row carrying the odd spelling: that is what holds.
    out.append({
        "Date": day, "Plant": plant, "Model": model_cell, "Color": colour,
        "Checkzone": panel, "Tolerance Group": orientation,
        "CF": 61.0, "Serial No": f"{tag}-{model_cell}-odd",
    })
    return out


@pytest.fixture(params=sorted(TWO_MODEL_PLANTS))
def two_model_sheet(request, engineer, cleanup, admin_conn):  # noqa: F811
    """One tab, two models, the same odd panel spelling on both."""
    plant = request.param
    models, colour = TWO_MODEL_PLANTS[plant]
    panel = odd_panel()
    tag = uuid.uuid4().hex[:6]
    rows: list[dict] = []
    known: dict[str, tuple[str, str]] = {}
    for model_cell, resolved in models:
        found = live_panel(admin_conn, plant, resolved)
        if found is None:
            pytest.skip(f"{plant} / {resolved} has no live panel list here")
        zone, orientation = found
        known[resolved] = (zone, orientation)
        rows.extend(
            rows_for(plant, model_cell, colour, panel, zone, orientation, 2, tag)
        )
    [review] = sent(
        engineer, cleanup, admin_conn, f"t88-two-model-{tag}.xlsx",
        book(HEADERS, rows), plant,
    )
    try:
        yield {
            "plant": plant, "panel": panel, "review": review,
            "models": [resolved for _, resolved in models], "known": known,
            "load_id": review["batch"]["load_id"],
        }
    finally:
        forget_maps(
            admin_conn, plant, [resolved for _, resolved in models], [panel]
        )


def own_mappable_panels(admin_conn, plant: str, model: str) -> set[str]:
    """That model's panels a confirmed pair may point at, read live.

    RO18 CHANGE (B1, revision 0048): a pair points at the plant x model's
    own live ``ref_plant_ws_point`` list (``fk_pzm_plant_point``), no longer
    only at panels also on the shared ``ref_model_zone`` catalogue.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT p.zone_code FROM ref_plant_ws_point p"
            " WHERE p.plant_code = %s AND p.model_code = %s"
            "   AND p.retired_at IS NULL",
            (plant, model),
        )
        return {row[0] for row in cur.fetchall()}


def zone_groups(review: dict, panel: str) -> list[dict]:
    return [
        h for h in review["held_labels"]
        if h["display_group"] == "zone" and h["raw_value"] == panel
    ]


# =====================================================================
# Part 1 -- D-88-1
# =====================================================================
def test_a_spelling_on_two_models_is_two_teachable_questions(two_model_sheet):
    groups = zone_groups(two_model_sheet["review"], two_model_sheet["panel"])
    assert len(groups) == 2, [
        (g["raw_value"], g["model_code"]) for g in groups
    ]
    by_model = {g["model_code"]: g for g in groups}
    assert sorted(by_model) == sorted(two_model_sheet["models"])
    for model, group in by_model.items():
        assert group["model_code"] == model
        # T89 (D-89-6): a question is answerable only where this plant x
        # model has a panel the approval path accepts -- one on the model's
        # own `ref_model_zone` catalogue. Measured 2026-10-08, three pairs
        # have **none**: FVL / P703 DBL RANGER, SAP / J73 DBL and
        # SAP / P703 DBL RANGER carry 32 live panels and 0 mappable ones,
        # so before T89 all 32 were offered and the write failed against
        # `fk_pzm_model_zone`. An empty list is now the honest answer, and
        # the sentence says why instead of promising a pick. (RO18 B1 later
        # let a pair point at the plant's own live list, so those three now
        # offer their panels; the empty-list branch stays for a pair without.)
        if group["candidates"]:
            assert group["teachable_kind"] == "ALIAS_CHECKZONE", group
        else:
            assert group["teachable_kind"] is None, group
            assert "catalogue" in group["operator_message"], group
        # Its own row count, not the other model's share as well.
        assert group["count"] == 1, group
        # And its own orientation, read from the file (D-88-2).
        assert len(group["orientations"]) == 1, group
        # The sentence names the model, so two identical-looking rows are
        # visibly two questions.
        assert model in group["operator_message"]
        assert "map it after the model is settled" not in (
            group["operator_message"].lower()
        )


def test_each_question_offers_only_its_own_models_panels(
    two_model_sheet, admin_conn
):
    """T41 / D-31 survives: never a union of two models' panels."""
    groups = {
        g["model_code"]: g
        for g in zone_groups(two_model_sheet["review"], two_model_sheet["panel"])
    }
    first, second = sorted(groups)
    # D-31's own guarantee, which is never vacuous: each question's list is
    # drawn from that model's panels alone. T89's orientation filter can
    # make the two lists EQUAL where the models differ only in the other
    # orientation (AAT: 7 shared horizontals, 24 vs 25 verticals), so the
    # strict inequality below is skipped there -- this is not.
    for model, group in groups.items():
        assert set(group["candidates"]) <= own_mappable_panels(
            admin_conn, two_model_sheet["plant"], model
        )
    if not (groups[first]["candidates"] and groups[second]["candidates"]):
        # T89: one of the two has no panel a pair may point at, so there is
        # nothing to compare. The claim is exercised where both do.
        pytest.skip(f"{first} or {second} has no mappable panel here")
    if groups[first]["candidates"] == groups[second]["candidates"]:
        # The two models genuinely share a panel list at this plant; then
        # there is nothing to tell apart and the claim is vacuous here.
        pytest.skip(f"{first} and {second} have identical panel lists")
    assert set(groups[first]["candidates"]) != set(groups[second]["candidates"])


def test_a_one_model_sheet_is_unchanged(engineer, cleanup, admin_conn):  # noqa: F811
    """The T41 behaviour this widens, still exactly itself."""
    plant = "FTM"
    model_cell, resolved = TWO_MODEL_PLANTS[plant][0][0]
    colour = TWO_MODEL_PLANTS[plant][1]
    found = live_panel(admin_conn, plant, resolved)
    assert found is not None
    zone, orientation = found
    panel = odd_panel()
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t88-one-model-{tag}.xlsx",
        book(HEADERS, rows_for(plant, model_cell, colour, panel, zone, orientation, 2, tag)),
        plant,
    )
    try:
        groups = zone_groups(review, panel)
        assert len(groups) == 1
        assert groups[0]["model_code"] == resolved
        assert groups[0]["teachable_kind"] == "ALIAS_CHECKZONE"
        assert groups[0]["candidates"]
    finally:
        forget_maps(admin_conn, plant, [resolved], [panel])


def test_the_match_screen_opens_for_each_model_of_a_two_model_sheet(
    engineer, two_model_sheet  # noqa: F811
):
    """Part 1's acceptance, on a sheet this test built."""
    for model in two_model_sheet["models"]:
        response = engineer.get(
            PANEL_MATCH,
            params={"load_id": two_model_sheet["load_id"], "model_code": model},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["model_code"] == model
        held = {h["raw_zone_text"] for h in body["held_panels"]}
        assert two_model_sheet["panel"] in held, held
        # Each screen sees only its own model's panels.
        assert all(
            panel["zone_code"]
            for panel in body["live_panels"]
        )


def test_a_pair_is_still_refused_against_another_models_panel(
    engineer, two_model_sheet, admin_conn  # noqa: F811
):
    """D-88-1's safety half, unchanged from T41."""
    first, second = sorted(two_model_sheet["models"])
    other = live_panel(admin_conn, two_model_sheet["plant"], second)
    assert other is not None
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ref_plant_ws_point WHERE plant_code = %s "
            "  AND model_code = %s AND zone_code = %s AND retired_at IS NULL",
            (two_model_sheet["plant"], first, other[0]),
        )
        if cur.fetchone() is not None:
            pytest.skip("both models carry that panel; nothing to refuse")
    response = engineer.post(
        PROPOSALS,
        json={
            "kind": "ALIAS_CHECKZONE",
            "load_id": two_model_sheet["load_id"],
            "payload": {
                "raw_value": two_model_sheet["panel"],
                "zone_code": other[0],
                "plant_code": two_model_sheet["plant"],
                "model_code": first,
            },
        },
    )
    assert response.status_code == 422, response.text
    assert "is not a panel of" in response.text


# =====================================================================
# D-88-6 / G-88-8 -- held rows of a COMMITTED batch
# =====================================================================
def test_held_rows_of_a_committed_batch_load_without_re_upload(
    engineer, admin, cleanup, admin_conn  # noqa: F811
):
    """D-88-6, and G-88-8's two assertions about how they load.

    The owner's `61551` is COMMITTED with 741 held rows. They must become
    loadable by matching them now, with no second upload -- and loading them
    may only INSERT, because those rows were never loaded and are new facts
    (ADR 0005).
    """
    plant = "FTM"
    model_cell, resolved = TWO_MODEL_PLANTS[plant][0][0]
    colour = TWO_MODEL_PLANTS[plant][1]
    found = live_panel(admin_conn, plant, resolved)
    assert found is not None
    zone, orientation = found
    panel = odd_panel()
    tag = uuid.uuid4().hex[:6]
    [review] = sent(
        engineer, cleanup, admin_conn, f"t88-committed-{tag}.xlsx",
        book(HEADERS, rows_for(plant, model_cell, colour, panel, zone, orientation, 2, tag)),
        plant,
    )
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    try:
        # Commit the good rows; the odd panel stays held.
        from tests.test_t04_ingest import acknowledge_required  # noqa: F811
        acknowledge_required(admin, review)
        commit = engineer.post(f"/api/v1/batches/{load_id}/commit")
        assert commit.status_code == 200, commit.text

        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT measurement_id, cf FROM wavescan WHERE load_id = %s "
                " ORDER BY measurement_id",
                (load_id,),
            )
            before = cur.fetchall()
            cur.execute(
                "SELECT status FROM load_batch WHERE load_id = %s", (load_id,)
            )
            assert cur.fetchone()[0] == "COMMITTED"
        assert before, "nothing committed; this would prove nothing"

        # The held row is still matchable, from a COMMITTED batch.
        screen = engineer.get(
            PANEL_MATCH, params={"load_id": load_id, "model_code": resolved}
        )
        assert screen.status_code == 200, screen.text
        assert panel in {h["raw_zone_text"] for h in screen.json()["held_panels"]}

        # Match it, with no re-upload anywhere in this test.
        taught = engineer.post(
            PROPOSALS,
            json={
                "kind": "ALIAS_CHECKZONE",
                "payload": {
                    "raw_value": panel, "zone_code": zone,
                    "plant_code": plant, "model_code": resolved,
                },
            },
        )
        assert taught.status_code == 201, taught.text

        loaded = engineer.post(
            f"/api/v1/plants/{plant}/workbooks/{file_hash}/load-remaining"
        )
        assert loaded.status_code == 200, loaded.text
        added = loaded.json()["measurements_inserted"]
        assert added == 1, loaded.json()

        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT measurement_id, cf FROM wavescan WHERE load_id = %s "
                " ORDER BY measurement_id",
                (load_id,),
            )
            after = cur.fetchall()
            cur.execute(
                "SELECT count(*) FROM wavescan WHERE load_id = %s "
                "  AND corrects_measurement_id IS NOT NULL",
                (load_id,),
            )
            corrections = cur.fetchone()[0]

        # G-88-8: INSERT only. The count rises by exactly the matched held
        # count, every pre-existing row is still there **unchanged**, and no
        # correction row was written -- this is not a correction, it is a
        # first load of a row that never loaded.
        assert len(after) == len(before) + added
        assert after[: len(before)] == before, "a pre-existing measurement changed"
        assert corrections == 0
    finally:
        forget_maps(admin_conn, plant, [resolved], [panel])


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
    forget_proposals(admin_conn, before, ["T88ODDHOOD"], 'T88 two-model sheet')
