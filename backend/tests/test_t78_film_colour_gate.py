"""T78 part C -- Film ingest holds a colour the batch plant does not offer.

D-78-20. The gate sits at the end of colour resolution in
``domain/film.FilmCleaner``: the spelling resolves through the plant-scoped
alias, folds to its canonical name (T64 / ADR 0014), and only then is asked
whether the batch plant actually paints that colour (``ref_plant_color``).
Reason code, message and therefore the held-label copy are WaveScan's
(``domain/cleaner.py``), because it is the same question to the same person.

Claims:

* a synthetic Film upload whose colour the plant does not offer is **held**,
  not loaded -- no fact rows, and ``COLOR_NOT_OFFERED`` on the review;
* an offered colour on the same sheet still loads its facts;
* an alias that *resolves* to a non-offered colour is held -- resolution and
  offer are two separate questions, and the file's own spelling is what the
  Engineer is asked about;
* a merged name that folds onto an **offered** canonical name still loads;
* WaveScan is unchanged;
* the colour gate asks about colour only. (D-78-21 -- "no Film model offer
  gate" -- was reversed by T112-FIX D-112F-1/2; the model offer is now
  tested in ``test_t112fix_remove_both_domains.py``.)

Fixtures delete only the batches and facts these tests create
(``film_cleanup``).
"""

from __future__ import annotations

import pytest

from app.domain.cleaner import Cleaner, Reject, RejectReason
from app.domain.reader import RawRow
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (  # noqa: F401  (fixtures + helpers)
    film_cleanup,
    film_facts,
    sent,
)
from tests.test_t60_named_ingest_aliases import MEASURES, film_rows, qs, refs  # noqa: F401

pytestmark = pytest.mark.ingest

#: FVL is the plant with the clearest split in the seeded catalogue.
PLANT = "FVL"
OFFERED = "Pace Red"                       # on FVL's list
NOT_OFFERED = "Command Grey"               # active catalogue colour FVL does not paint
ALIAS_TO_NOT_OFFERED = "Aluminum Met_4"    # FVL's own alias -> Aluminum Metallic
MERGED_TO_OFFERED = "AB - Absolute Black"  # folds to Absolute / Shadow Black (offered)

HEADERS = ["Clearcoat", "Primer", "E-Coat"]
GOLD_POINT = "001HOOD"
FILENAME = "P703-T78-AB.xlsx"
NOT_ON_THE_LIST = "is not on " + PLANT + "'s list"


# =====================================================================
# A. the premise these tests rest on
# =====================================================================
def test_the_catalogue_really_does_split_these_colours(refs):  # noqa: F811
    offered = refs[0].offered_colors
    assert offered.get((PLANT, OFFERED)) is True
    assert not offered.get((PLANT, NOT_OFFERED), False)
    # the alias exists and points at a colour FVL does not offer
    assert refs[0].color_by_plant[(PLANT, ALIAS_TO_NOT_OFFERED.lower())] == "Aluminum Metallic"
    assert not offered.get((PLANT, "Aluminum Metallic"), False)


# =====================================================================
# B. the gate, at the cleaner
# =====================================================================
def test_a_non_offered_colour_is_held_and_becomes_no_fact(refs):  # noqa: F811
    data = qs(HEADERS, [GOLD_POINT], colour=NOT_OFFERED)
    _template, result = film_rows(refs, data, plant=PLANT, filename=FILENAME)

    assert result.clean == []
    [held] = result.rejects
    assert held.reason == RejectReason.COLOR_NOT_OFFERED
    assert held.column == "color"
    assert held.value == NOT_OFFERED
    assert NOT_ON_THE_LIST in held.detail


def test_an_offered_colour_on_the_same_sheet_still_loads(refs):  # noqa: F811
    data = qs(HEADERS, [GOLD_POINT], colour=OFFERED)
    _template, result = film_rows(refs, data, plant=PLANT, filename=FILENAME)

    assert result.rejects == []
    assert {r.color for r in result.clean} == {OFFERED}
    assert {r.point_code for r in result.clean} == {GOLD_POINT}


def test_an_alias_that_resolves_to_a_non_offered_colour_is_held(refs):  # noqa: F811
    """Resolution succeeds; the offer question is what refuses it."""
    data = qs(HEADERS, [GOLD_POINT], colour=ALIAS_TO_NOT_OFFERED)
    _template, result = film_rows(refs, data, plant=PLANT, filename=FILENAME)

    assert result.clean == []
    [held] = result.rejects
    assert held.reason == RejectReason.COLOR_NOT_OFFERED
    # the Engineer is asked about the spelling the FILE used ...
    assert held.value == ALIAS_TO_NOT_OFFERED
    # ... and told the catalogue name it resolved to.
    assert "Aluminum Metallic" in held.detail


def test_a_merged_name_folding_onto_an_offered_colour_still_loads(refs):  # noqa: F811
    """T64 folds first, so the gate asks about the canonical name (ADR 0014)."""
    data = qs(HEADERS, [GOLD_POINT], colour=MERGED_TO_OFFERED)
    _template, result = film_rows(refs, data, plant=PLANT, filename=FILENAME)

    assert result.rejects == []
    assert {r.color for r in result.clean} == {"Absolute / Shadow Black"}


# =====================================================================
# C. the colour gate asks about colour only
# =====================================================================
# T112-FIX (D-112F-1 / D-112F-3): D-78-21 is reversed. Film now checks the
# model offer, and migration 0036 seeded FTM x P703 RAPCAP / P703 SGL, so the
# old claim "no Film model in ref_plant_model" is replaced by its opposite.
def test_ftm_film_only_models_are_offered_after_0036(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT plant_code, model_code, is_offered FROM ref_plant_model "
            " WHERE model_code IN ('P703 RAPCAP', 'P703 SGL') ORDER BY 1, 2"
        )
        assert cur.fetchall() == [
            ("FTM", "P703 RAPCAP", True), ("FTM", "P703 SGL", True),
        ]


def test_the_gate_asks_about_colour_only_not_the_model(refs):  # noqa: F811
    """An offered colour on an offered Film model loads; no model refusal."""
    data = qs(HEADERS, [GOLD_POINT], colour=OFFERED)
    _template, result = film_rows(refs, data, plant=PLANT, filename=FILENAME)
    assert result.clean and {r.model for r in result.clean} == {"P703 DBL RANGER"}
    assert all(r.reason != "MODEL_NOT_OFFERED" for r in result.rejects)


# =====================================================================
# D. WaveScan is unchanged
# =====================================================================
def test_wavescan_still_refuses_a_non_offered_colour_the_same_way(refs):  # noqa: F811
    out = Cleaner(refs[0], (PLANT,), expected_plant=PLANT).clean_row(
        RawRow("t78.xlsx", "s", 2, dict(
            date="2026-09-08", plant=PLANT, model="P703", checkzone="1HOOD",
            color=NOT_OFFERED, **MEASURES))
    )
    assert isinstance(out, Reject)
    assert out.reason == RejectReason.COLOR_NOT_OFFERED
    assert out.value == NOT_OFFERED
    assert NOT_ON_THE_LIST in out.detail


def test_wavescan_still_loads_an_offered_colour(refs):  # noqa: F811
    out = Cleaner(refs[0], (PLANT,), expected_plant=PLANT).clean_row(
        RawRow("t78.xlsx", "s", 2, dict(
            date="2026-09-08", plant=PLANT, model="P703", checkzone="1HOOD",
            color=OFFERED, **MEASURES))
    )
    assert not isinstance(out, Reject), getattr(out, "detail", out)
    assert out.color == OFFERED


# =====================================================================
# E. the running application: a real upload is held, not loaded
# =====================================================================
def test_a_film_upload_with_a_non_offered_colour_loads_nothing(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    data = qs(HEADERS, [GOLD_POINT], colour=NOT_OFFERED, job="T78GATE1")
    reviews = sent(engineer, film_cleanup, admin_conn, FILENAME, data, PLANT)
    review = reviews["Quick Summary"]

    assert review["reject_reasons"].get("COLOR_NOT_OFFERED") == 1, review["reject_reasons"]
    assert film_facts(admin_conn, review["batch"]["load_id"]) == []
    counts = review["batch"]["counts"]
    assert (counts["rows_loaded"], counts["rows_rejected"]) == (0, 1), counts
    assert not review["committable"]

    # the held label asks the plant-offer question, WaveScan's copy
    held = [h for h in review["held_labels"] if h["reason"] == "COLOR_NOT_OFFERED"]
    assert held and held[0]["raw_value"] == NOT_OFFERED
