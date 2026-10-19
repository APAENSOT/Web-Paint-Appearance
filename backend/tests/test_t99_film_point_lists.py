"""T99 -- FTM Film: own point lists, a remembered setting, and a walk guard.

Claims (task section 4), against revision 0033, the real uploader, the running
application and the live database:

1. The migration: FTM's four lists are 98 / 98 / 93 / 58, there are 347
   `film_point_setting` rows, every seeded H/V equals the one D-99-5 rule, the
   109 retired rows carry a reason, `ref_film_point` has the four new names,
   and no AAT / FVL / SAP row moved.
2. A full DBL walk loads 98 and keeps its six FTWISH rows as not stored, with
   nothing held. The same for RB, which is `P703 DBL RAPTOR`.
3. A full RAPCAP walk loads 93; a full SGL walk loads 58.
4. `BOOTH_1` after the FTWISH tail is not stored and does not stop the file.
5. A no-box RAPCAP (to `059RTFEND`) and a no-box DBL (to `064RAPILLAR`) are
   **complete**; a walk stopping at `063LBOXSIDE` loads and is incomplete.
6. The walk guard: a label inserted mid-walk is asked about in its own row
   while the rest of the sheet loads (**T109, D-109-6** -- it used to hold
   the whole sheet); an appended name holds the sheet until the uploader
   confirms it, and then it loads with a `worksheet_decision` row and an
   `audit_event` naming who; a mid-walk insertion still cannot be confirmed,
   and a live name out of the list's order still holds everything.
7. A sheet whose Locations are `Point NNN` is refused, with no fact.
8. An unusual Job Number holds the sheet and loads on "load as written"; a
   model conflict holds it and loads on the uploader's choice; a colour-code
   disagreement loads with a warning and the Layer 2 colour.
9. The setting: a POST of `counted = false` writes a new row and an
   `audit_event`, leaves the older row alone, drops the point from the
   dashboard's Hor / Ver, and keeps it in History marked `counted: false`.
   A Viewer gets 403.
10. Other plants: AAT now has settings (RO04), so an AAT walk with `095...`
    past its list holds the sheet as at FTM; an FVL walk (no settings) still
    holds `EXTRA_POINT`.
12. No UPDATE or DELETE of `filmthickness`, `load_batch` or
    `film_point_setting` anywhere in `app/` (source level).

**What this file writes, and how it cleans up.** Uploads go through
`film_cleanup`, which deletes the batches and their facts by `load_id`. The
one test that appends a point to a list (claim 6) adds a marker point name
and removes exactly the rows it created, by id. No seeded FTM row is written,
retired or deleted anywhere here, and the reference counts are flat across the
run -- `test_reference_counts_are_flat` asserts that on the way out.
"""

from __future__ import annotations

from tests.ro19_synthetic import ro19_plants  # noqa: F401

import ast
import json
import re
import uuid
from pathlib import Path

import pytest

from app.domain.film_catalog import FTM_RAPCAP_93, FTM_SGL_58
from tests.test_t04_ingest import admin, engineer, ingest_apps, viewer  # noqa: F401
from tests.test_t46_filmthickness import (
    film_cleanup,  # noqa: F401
    film_facts,
    pelt,
    review_rows,
    sent,
    wait_for,
)

pytestmark = pytest.mark.ingest

APP_DIR = Path(__file__).resolve().parents[1] / "app"

PLANT = "FTM"
RANGER = "P703 DBL RANGER"
RAPTOR = "P703 DBL RAPTOR"
RAPCAP = "P703 RAPCAP"
SGL = "P703 SGL"
MODELS = (RANGER, RAPTOR, RAPCAP, SGL)
LIVE = {RANGER: 98, RAPTOR: 98, RAPCAP: 93, SGL: 58}
COLOUR = "Arctic White"
TAIL = tuple(f"{n:03d}FTWISH" for n in range(1, 7))
#: The marker name claim 6 appends and then removes, by id.
MARKER_POINT = "099T99MARK"

#: The four names revision 0033 added to `ref_film_point` (D-99-5).
NEW_CODES = ("095RBXFLOOR", "096TGATEIN", "097TGATEIN", "098TGATEIN")

#: The tables the reference-count guard watches (task section 6).
WATCHED = (
    "ref_plant_film_point", "film_point_setting", "ref_film_point",
    "ref_plant_zone_map", "proposed_mapping", "film_standard", "cf_standard",
)


def hv(point_code: str) -> str:
    """The one D-99-5 rule, written once here as the tests' own statement."""
    return "H" if re.sub(r"^[0-9]+", "", point_code) in (
        "HOOD", "ROOF", "LBXFLOOR", "RBXFLOOR"
    ) else "V"


def job_name(token: str) -> tuple[str, str]:
    """``(filename, Job Number)`` of FTM's shape: ``AW_<token>_<7 digits>``."""
    job = f"AW_{token}_{uuid.uuid4().int % 10**7:07d}"
    return f"{job}.xlsx", job


def walk_of(admin_conn, model: str) -> list[str]:
    """A plant's live list in walk order, read rather than typed."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT point_code FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND retired_at IS NULL "
            " ORDER BY point_no",
            (PLANT, model),
        )
        return [r[0] for r in cur.fetchall()]


def counts(admin_conn) -> dict[str, int]:
    out: dict[str, int] = {}
    with admin_conn.cursor() as cur:
        for table in WATCHED:
            cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed list
            out[table] = cur.fetchone()[0]
    return out


@pytest.fixture(scope="module")
def reference_before(admin_conn) -> dict[str, int]:
    return counts(admin_conn)


@pytest.fixture()
def setting_cleanup(admin_conn):
    """Remove the `film_point_setting` rows a test added, by id.

    The application never deletes one (D-99-4, ADR 0005); a test does, so the
    reference counts this module measures stay flat and the owner's seeded
    rows are the only ones left behind. Scoped to ids, which is the tightest
    form there is (T95 / D-95-5).
    """
    seen: list[int] = []
    yield seen
    if not seen:
        return
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM film_point_setting WHERE setting_id = ANY(%s)",
                    (seen,))


@pytest.fixture()
def marker_cleanup(admin_conn):
    """Remove the marker point and its settings, by id, whatever happened."""
    # RO19 F2: every model this module confirms a marker on, not just SGL.
    # `test_skipped_points_plus_an_appended_name_is_still_confirmable` writes on
    # RAPCAP, and a model-scoped snapshot left that version in the live list.
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_id FROM point_walk_version WHERE plant_code = %s "
                    "AND domain = 'FILMTHICKNESS'", (PLANT,))
        versions_before = [row[0] for row in cur.fetchall()]
    yield MARKER_POINT
    with admin_conn.cursor() as cur:
        # Appended confirmation records a whole new version. Its members
        # include this fixture's exact marker, and it did not exist before:
        # the marker point lives only between this fixture's setup and here.
        cur.execute(
            "SELECT v.version_id FROM point_walk_version v WHERE v.plant_code = %s "
            "AND v.domain = 'FILMTHICKNESS' "
            "AND NOT (v.version_id = ANY(%s)) AND EXISTS "
            "(SELECT 1 FROM point_walk_member m WHERE m.version_id = v.version_id "
            "AND m.point_code = %s)",
            (PLANT, versions_before, MARKER_POINT),
        )
        own_versions = [row[0] for row in cur.fetchall()]
        if own_versions:
            cur.execute("DELETE FROM audit_event WHERE entity_type = 'point_walk_version' "
                        "AND entity_id = ANY(%s)", ([str(v) for v in own_versions],))
            cur.execute("DELETE FROM point_walk_member WHERE version_id = ANY(%s)", (own_versions,))
            cur.execute("DELETE FROM point_walk_version WHERE version_id = ANY(%s)", (own_versions,))
        cur.execute(
            "DELETE FROM film_point_setting WHERE plant_code = %s "
            "  AND point_code = %s",
            (PLANT, MARKER_POINT),
        )
        # RO17-FIX (D-RO17F-1): a confirmed point now has its first label row.
        cur.execute(
            "DELETE FROM ref_plant_film_point_label WHERE plant_code = %s "
            "  AND point_code = %s",
            (PLANT, MARKER_POINT),
        )
        cur.execute(
            "DELETE FROM ref_plant_film_point WHERE plant_code = %s "
            "  AND point_code = %s",
            (PLANT, MARKER_POINT),
        )
        cur.execute(
            "DELETE FROM ref_film_point WHERE point_code = %s", (MARKER_POINT,)
        )


def ws(plant: str, file_hash: str, tail: str) -> str:
    return f"/api/v1/plants/{plant}/workbooks/{file_hash}/{tail}"


def rows_by_label(admin_conn, load_id: int) -> dict[str, tuple[str, str | None]]:
    """``{Location as written: (disposition, reason)}`` of one parse."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT r.raw -> 'values' ->> 'location', r.disposition, r.reason "
            "  FROM stg_review_row r WHERE r.load_id = %s ORDER BY r.source_row",
            (load_id,),
        )
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def details(admin_conn, load_id: int, reason: str) -> set[str]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT detail FROM stg_review_row "
            " WHERE load_id = %s AND reason = %s",
            (load_id, reason),
        )
        return {r[0] for r in cur.fetchall()}


# =====================================================================
# 1. the migration (revision 0033)
# =====================================================================
def test_the_seed_is_the_measured_walk_with_one_hv_rule(admin_conn, reference_before):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT model_code, count(*) FROM ref_plant_film_point "
            " WHERE plant_code = %s AND retired_at IS NULL GROUP BY 1",
            (PLANT,),
        )
        live = dict(cur.fetchall())
        cur.execute(
            "SELECT model_code, point_code, btrim(orientation) "
            "  FROM ref_plant_film_point "
            " WHERE plant_code = %s AND retired_at IS NULL",
            (PLANT,),
        )
        orientation = {(r[0], r[1]): r[2] for r in cur.fetchall()}
        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE retired_reason IS NOT NULL) "
            "  FROM ref_plant_film_point "
            " WHERE plant_code = %s AND retired_reason LIKE 'T99 %%'",
            (PLANT,),
        )
        retired, with_reason = cur.fetchone()
        # T103-FIX (D-103F-2): `film_point_setting` is append-only and a
        # person may correct themselves (D-99-4), so the number of rows in it
        # is not a claim about the seed -- D-101-4 added two rows on
        # `095RBXFLOOR` and this test used to fail on the live database for
        # it. What the seed means is that **the earliest row of every live
        # point** is the one revision 0033 wrote. That is what is read here;
        # every later row is somebody's decision and none of this test's
        # business.
        cur.execute(
            "SELECT DISTINCT ON (model_code, point_code) "
            "       model_code, point_code, counted, btrim(orientation), reason "
            "  FROM film_point_setting WHERE plant_code = %s "
            " ORDER BY model_code, point_code, setting_id",
            (PLANT,),
        )
        seed = cur.fetchall()
        cur.execute(
            "SELECT count(*) FROM film_point_setting WHERE plant_code = %s",
            (PLANT,),
        )
        setting_rows = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM ref_film_point WHERE point_code = ANY(%s)",
            (list(NEW_CODES),),
        )
        new_codes = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM ref_plant_film_tail_label WHERE plant_code = %s",
            (PLANT,),
        )
        tails = cur.fetchone()[0]
        cur.execute(
            "SELECT model_code, point_code FROM ref_plant_film_point "
            " WHERE plant_code = %s AND is_complete_stop ORDER BY 1, point_no",
            (PLANT,),
        )
        stops = cur.fetchall()
        cur.execute("SELECT film_job_no_pattern FROM ref_plant WHERE plant_code = %s",
                    (PLANT,))
        pattern = cur.fetchone()[0]

    assert live == LIVE
    assert walk_of(admin_conn, RAPCAP) == list(FTM_RAPCAP_93)
    assert walk_of(admin_conn, SGL) == list(FTM_SGL_58)
    assert walk_of(admin_conn, RANGER)[94:] == list(NEW_CODES)
    assert walk_of(admin_conn, RAPTOR) == walk_of(admin_conn, RANGER)
    # Every live FTM point, and every seeded setting, carries the one rule.
    assert {k: v for k, v in orientation.items() if v != hv(k[1])} == {}
    assert (retired, with_reason) == (109, 109)
    # The seed: one per live point, 347 of them, each the row 0033 wrote.
    assert len(seed) == sum(LIVE.values()) == 347
    assert {(m, p) for m, p, _, _, _ in seed} == set(orientation), (
        "every live FTM point has a setting row, and no row names a point "
        "that is not live"
    )
    assert {c for _, _, c, _, _ in seed} == {True}
    assert {(p, o) for _, p, _, o, _ in seed if o != hv(p)} == set()
    assert {r.startswith("T99 seed") for _, _, _, _, r in seed} == {True}, (
        "the earliest row of every point is the seed, not a later decision"
    )
    assert setting_rows >= len(seed), (
        "an append-only table only grows; a later row is not a broken seed"
    )
    assert new_codes == 4
    assert tails == 7 * len(MODELS) == 28
    assert stops == [
        (RANGER, "064RAPILLAR"), (RANGER, "098TGATEIN"),
        (RAPTOR, "064RAPILLAR"), (RAPTOR, "098TGATEIN"),
        (RAPCAP, "059RTFEND"), (RAPCAP, "093TGATEIN"),
        (SGL, "058RTFEND"),
    ]
    assert pattern == "^([A-Z]{2})_([A-Z]+)_([0-9]{7})$"


def test_no_other_plant_moved(admin_conn, engineer, ro19_plants):
    """A change on one list leaves every field of another plant untouched."""
    target = ro19_plants(ruled=True)
    other = ro19_plants(ruled=True)
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO ref_plant_film_tail_label "
                    "(plant_code, model_code, label_norm, note) "
                    "VALUES (%s, %s, 'BOOTH_1', 'RO19 synthetic')", (other, RANGER))
        cur.execute("UPDATE ref_plant SET film_job_no_pattern = '^TEST$' WHERE plant_code = %s", (other,))

    def snapshot():
        with admin_conn.cursor() as cur:
            result = []
            for table, order in (("ref_plant_film_point", "model_code, point_no"),
                                 ("film_point_setting", "setting_id"),
                                 ("ref_plant_film_tail_label", "model_code, label_norm"),
                                 ("ref_plant", "plant_code")):
                cur.execute(f"SELECT * FROM {table} WHERE plant_code = %s ORDER BY {order}", (other,))
                result.append(cur.fetchall())
            return result

    before = snapshot()
    assert len(before[0]) == len(before[1]) == 3
    assert len(before[2]) == len(before[3]) == 1
    changed = engineer.post(f"/api/v1/plants/{target}/film-points/{RANGER}", json={
        "points": [{"point_code": "002HOOD", "counted": False, "orientation": "V"}],
        "reason": "RO19 synthetic isolation proof",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["rows_written"] == 1
    assert snapshot() == before, "points, H/V, stops, settings, tails and job pattern stay unchanged"


# =====================================================================
# 2 + 3 + 4. a whole walk loads; the tail is kept and not stored
# =====================================================================
@pytest.mark.parametrize("token, model", [
    ("DBL", RANGER), ("RB", RAPTOR), ("RAP", RAPCAP), ("SGL", SGL),
])
def test_a_whole_walk_loads_and_the_tail_is_not_stored(
    engineer, admin_conn, film_cleanup, token, model  # noqa: F811
):
    walk = walk_of(admin_conn, model)
    assert len(walk) == LIVE[model]
    name, job = job_name(token)
    data = pelt([*walk, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    counts_ = review["batch"]["counts"]
    assert (counts_["rows_loaded"], counts_["rows_quarantine"],
            counts_["rows_rejected"]) == (LIVE[model], 0, 0)
    labels = rows_by_label(admin_conn, review["batch"]["load_id"])
    assert {labels[p] for p in walk} == {("LOAD", None)}
    assert {labels[t] for t in TAIL} == {("AGGREGATE_ROW", "FILM_TAIL_LABEL")}
    projection = review_rows(admin_conn, review["batch"]["load_id"])
    assert {r[2]["model"] for r in projection.values() if r[0] == "LOAD"} == {model}


def test_booth_1_after_the_tail_is_not_stored_and_the_file_still_loads(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    data = pelt([*walk, *TAIL, "BOOTH_1"], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    assert review["batch"]["counts"]["rows_loaded"] == 58
    labels = rows_by_label(admin_conn, review["batch"]["load_id"])
    assert labels["BOOTH_1"] == ("AGGREGATE_ROW", "FILM_TAIL_LABEL")
    assert review["batch"]["status"] == "PENDING_REVIEW"


# =====================================================================
# 5. a no-box truck is complete (D-99-8)
# =====================================================================
@pytest.mark.parametrize("token, model, stop, complete", [
    ("RAP", RAPCAP, "059RTFEND", True),
    ("DBL", RANGER, "064RAPILLAR", True),
    ("DBL", RANGER, "063RAPILLAR", False),
])
def test_a_walk_that_stops_at_a_stop_is_complete(
    engineer, admin, viewer, admin_conn, film_cleanup, token, model, stop, complete  # noqa: F811
):
    from tests.test_t46_filmthickness import commit

    walk = walk_of(admin_conn, model)
    cut = walk[: walk.index(stop) + 1]
    name, job = job_name(token)
    data = pelt([*cut, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    assert review["batch"]["counts"]["rows_loaded"] == len(cut)
    commit(engineer, admin, review)
    [vid] = {f[6] for f in film_facts(admin_conn, review["batch"]["load_id"])}
    grid = viewer.get(
        f"/api/v1/plants/{PLANT}/filmthickness/vehicles/{vid}/points"
    ).json()
    assert grid["vehicle"]["mapped_point_count"] == len(cut)
    assert grid["vehicle"]["incomplete"] is not complete
    assert grid["vehicle"]["expected_point_count"] == (
        len(cut) if complete else LIVE[model]
    )


# =====================================================================
# 6. the walk guard (D-99-7, D-99-14)
# =====================================================================
def test_a_label_inserted_mid_walk_is_asked_in_its_row(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    """T109 CHANGE (D-109-6). The question moved into the label's own row.

    It used to hold the whole sheet because there was no way to say what the
    label is. Now there is -- which live point is this? remembered for every
    later upload, or add it as a new point on Point Check -- so the label's
    own row is the question. What has not changed: nothing is guessed, the
    reading on that row is not stored until somebody answers, and a live name
    out of the list's order still holds everything (D-99-7,
    `test_a_renumbered_or_reordered_walk...` below).

    T109-FIX CHANGE (D-109F-1): **and nothing else on the sheet loads
    either**, until every label is answered. T109 loaded "the rest", which on
    a walk renumbered down is 76 readings filed one point out. The row
    questions are unchanged; what changed is that the rows that resolved wait
    with them, under `FILM_POINT_WAITING`.
    """
    walk = walk_of(admin_conn, SGL)
    body = [*walk[:5], "035LBPILLAR", *walk[5:]]
    name, job = job_name("SGL")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    counts_ = review["batch"]["counts"]
    # T109-FIX CHANGE (D-109F-1): was `== len(walk)`.
    assert counts_["rows_loaded"] == 0, "nothing loads while a label is unanswered"
    held = {
        label: reason for label, (disposition, reason)
        in rows_by_label(admin_conn, load_id).items()
        if disposition == "QUARANTINE" and reason != "FILM_TAIL_LABEL"
    }
    # T109-FIX CHANGE (D-109F-1): the unknown label is still asked in its own
    # row; every other row of the walk waits, and says what for.
    assert held["035LBPILLAR"] == "FILM_POINT_UNKNOWN", "asked in its row"
    assert set(held) == {*body}, "every body row of the sheet is held"
    assert set(held.values()) == {"FILM_POINT_UNKNOWN", "FILM_POINT_WAITING"}
    [waiting] = details(admin_conn, load_id, "FILM_POINT_WAITING")
    assert "Nothing on this sheet loads until every label is answered" in waiting
    assert "renumbered" in waiting and "fix the file" in waiting, (
        "D-109F-3: a renumbered walk is told not to map its labels"
    )
    [detail] = details(admin_conn, load_id, "FILM_POINT_UNKNOWN")
    # The sentence names the name, and says the two things a person can do.
    assert '"035LBPILLAR"' in detail, detail
    assert "is not a point of" in detail and "FTM's P703 SGL list" in detail
    assert "Point Check" in detail and "remember it" in detail
    assert "point 6" not in detail, "no row positions in the sentence"
    assert "renumbered" in detail and "nothing" in detail.lower()
    # The tail is still not a hold (D-99-6).
    labels = rows_by_label(admin_conn, load_id)
    assert {labels[t] for t in TAIL} == {("AGGREGATE_ROW", "FILM_TAIL_LABEL")}


def test_a_mid_walk_insertion_cannot_be_confirmed(
    engineer, admin_conn, film_cleanup  # noqa: F811
):
    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    data = pelt([*walk[:5], "035LBPILLAR", *walk[5:], *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    refused = engineer.post(
        ws(PLANT, review["batch"]["file_hash"], "film-walk-confirm"),
        json={
            "load_id": review["batch"]["load_id"],
            "points": [{"point_code": "035LBPILLAR", "orientation": "V"}],
        },
    )
    assert refused.status_code == 409, refused.text
    # T109 CHANGE (D-109-6): the tab is no longer held sheet-wide for a label
    # the list does not hold, so the walk confirm refuses it as "this tab is
    # not held for that" rather than with the owner-decision sentence. The
    # claim is the one that matters and is unchanged: a mid-walk insertion
    # cannot be confirmed into the list, and nothing is written.
    assert "not held for FILM_WALK_UNKNOWN" in refused.json()["message"]
    assert "Nothing was changed" in refused.json()["message"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM worksheet_decision WHERE load_id = %s",
            (review["batch"]["load_id"],),
        )
        assert cur.fetchone()[0] == 0, "nothing was written"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, "035LBPILLAR"),
        )
        assert cur.fetchone()[0] == 0, "it never joined the list"


def test_an_appended_name_is_held_until_the_uploader_confirms_it(
    # `marker_cleanup` is created first on purpose, so it is finalised **last**:
    # the facts this test commits name the marker point, and the batch has to
    # go before the point it references can (`fk_ft_plant_model_point`).
    engineer, admin, admin_conn, marker_cleanup, film_cleanup  # noqa: F811
):
    from tests.test_t46_filmthickness import commit

    walk = walk_of(admin_conn, SGL)
    name, job = job_name("SGL")
    data = pelt([*walk, MARKER_POINT, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    [detail] = details(admin_conn, load_id, "FILM_WALK_UNKNOWN")
    # T99-FIX CHANGE (D-99-15): "past the end of the list" became "past the
    # last point of the walk it names", because a sheet may now skip points
    # and still have names appended after the last one it wrote.
    assert MARKER_POINT in detail and "past the last point" in detail

    # A name the sheet did not append cannot be answered.
    wrong = engineer.post(
        ws(PLANT, file_hash, "film-walk-confirm"),
        json={"load_id": load_id,
              "points": [{"point_code": "035LBPILLAR", "orientation": "V"}]},
    )
    assert wrong.status_code == 422, wrong.text

    confirmed = engineer.post(
        ws(PLANT, file_hash, "film-walk-confirm"),
        json={"load_id": load_id,
              "points": [{"point_code": MARKER_POINT, "counted": True,
                          "orientation": "V"}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["decisions_written"] == 1
    assert MARKER_POINT in confirmed.json()["operator_message"]

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT point_no, note, orientation FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, MARKER_POINT),
        )
        point_no, note, catalogue_orientation = cur.fetchone()
        assert point_no == 59, "appended after the last known point, never inside"
        assert note.startswith("T99 (D-99-14)")
        assert catalogue_orientation is None, (
            "the H/V of a confirmed point lives in its setting, not the catalogue"
        )
        cur.execute(
            "SELECT counted, btrim(orientation), created_by IS NOT NULL "
            "  FROM film_point_setting WHERE plant_code = %s AND point_code = %s",
            (PLANT, MARKER_POINT),
        )
        assert cur.fetchall() == [(True, "V", True)]
        cur.execute(
            "SELECT kind, subject, actor_user_id IS NOT NULL FROM worksheet_decision "
            " WHERE load_id = %s", (load_id,),
        )
        assert cur.fetchall() == [("FILM_WALK_CONFIRM", f"{MARKER_POINT}|true|V", True)]
        cur.execute(
            "SELECT count(*) FROM audit_event "
            " WHERE action = 'catalogue.plant_film_point.confirm_appended' "
            "   AND after ->> 'load_id' = %s", (str(load_id),),
        )
        assert cur.fetchone()[0] == 1, "an audit_event names who confirmed"
        cur.execute(
            "SELECT label, reason FROM ref_plant_film_point_label "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, MARKER_POINT),
        )
        assert cur.fetchall() == [(MARKER_POINT, "walk confirm: the code")], (
            "RO17-FIX (D-RO17F-1): the confirmed point gets its first label"
        )

    after = wait_for(engineer, load_id)
    assert after["batch"]["counts"]["rows_loaded"] == 59, after["batch"]["counts"]
    commit(engineer, admin, after)
    assert {f[1] for f in film_facts(admin_conn, load_id)} == {*walk, MARKER_POINT}


# =====================================================================
# T99-FIX (D-99-15): a walk that skips points loads and is incomplete
# =====================================================================
#: What `7.Jul/6-10/AW_RAP_1954807Pum.xlsx` does: every name on RAPCAP's list,
#: in RAPCAP's order, with two of them simply not measured.
SKIPPED = ("061LBOXSIDE", "062LBOXSIDE")


def test_a_walk_that_skips_points_loads_and_is_incomplete(
    engineer, admin, viewer, admin_conn, film_cleanup  # noqa: F811
):
    from tests.test_t46_filmthickness import commit

    walk = walk_of(admin_conn, RAPCAP)
    body = [p for p in walk[:63] if p not in SKIPPED]
    assert len(body) == 61 and set(SKIPPED) <= set(walk)
    name, job = job_name("RAP")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    counts_ = review["batch"]["counts"]
    assert (counts_["rows_loaded"], counts_["rows_quarantine"]) == (len(body), 0), (
        "a skipped point is a point nobody measured, not another walk"
    )
    labels = rows_by_label(admin_conn, load_id)
    assert {labels[p] for p in body} == {("LOAD", None)}

    commit(engineer, admin, review)
    assert {f[1] for f in film_facts(admin_conn, load_id)} == set(body)
    [vid] = {f[6] for f in film_facts(admin_conn, load_id)}
    grid = viewer.get(
        f"/api/v1/plants/{PLANT}/filmthickness/vehicles/{vid}/points"
    ).json()
    assert grid["vehicle"]["mapped_point_count"] == len(body)
    assert grid["vehicle"]["incomplete"] is True, (
        "63 points up to a non-stop, two of them missing: not a whole vehicle"
    )
    assert grid["vehicle"]["expected_point_count"] == LIVE[RAPCAP]
    # The skipped points are still slots of the grid, with nothing in them.
    empty = {
        p["point_code"] for p in grid["items"] if p["src_location_text"] is None
    }
    assert set(SKIPPED) <= empty, "a skipped point is an empty slot, not absent"


def _renumbered(walk: list[str]) -> list[str]:
    """``walk`` with its 5th point deleted and the rest renumbered down."""
    rest = walk[:4] + walk[5:]
    return [
        f"{i + 1:03d}{re.sub(r'^[0-9]+', '', point)}"
        for i, point in enumerate(rest)
    ]


def _swapped(walk: list[str]) -> list[str]:
    """``walk`` with two of its own names exchanged."""
    out = list(walk)
    out[10], out[20] = out[20], out[10]
    return out


@pytest.mark.parametrize("shape, says", [
    ("swapped", "in its own order"),
])
def test_a_renumbered_or_reordered_walk_still_holds_the_whole_sheet(
    engineer, admin_conn, film_cleanup, shape, says  # noqa: F811
):
    """D-99-15 widens the guard for skipped points and for nothing else.

    A reorder writes the list's own names out of its order: the file is
    describing a different walk, it holds the whole sheet, and it cannot be
    confirmed -- a point is its number *and* its name (D-99-1).

    T109 CHANGE (D-109-6): the `renumbered` case left this test. A renumber
    writes names the list does not hold (`015LTFEND` where the list has
    `015HOOD`), and since T109 a name the list does not hold is a question in
    its own row. T109-FIX CHANGE (D-109F-1): it holds the whole sheet again,
    but under the row questions rather than as one sheet-wide refusal -- 0
    rows load, every unknown label is asked, and the rest wait -- so it is
    covered by `test_a_renumbered_walk_down_loads_nothing_and_asks_every_label`
    in `test_t109_point_check_film.py` and by T100's
    `test_a_label_the_list_does_not_hold_is_a_row_question[renumbered]`
    instead of here. Nothing is filed onto a different spot either way.
    """
    walk = walk_of(admin_conn, SGL)
    body = _renumbered(walk) if shape == "renumbered" else _swapped(walk)
    assert body != walk
    name, job = job_name("SGL")
    data = pelt([*body, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    held = {
        reason for _, (disposition, reason)
        in rows_by_label(admin_conn, load_id).items() if disposition == "QUARANTINE"
    }
    assert held == {"FILM_WALK_UNKNOWN"}
    [detail] = details(admin_conn, load_id, "FILM_WALK_UNKNOWN")
    assert says in detail, detail
    assert "owner decision" in detail
    # The sentence names names. No row position is quoted as a point number.
    assert not re.search(r"\bas point [0-9]+\b", detail), detail
    assert re.search(r'"[0-9]{3}[A-Z]+"', detail), "it quotes a point name"
    refused = engineer.post(
        ws(PLANT, file_hash, "film-walk-confirm"),
        json={"load_id": load_id,
              "points": [{"point_code": body[-1], "orientation": "V"}]},
    )
    assert refused.status_code == 409, refused.text


def test_skipped_points_plus_an_appended_name_is_still_confirmable(
    # `marker_cleanup` first, so it is finalised last: the facts name the
    # marker point and the batch has to go before the point it references.
    engineer, admin, viewer, admin_conn, marker_cleanup, film_cleanup  # noqa: F811
):
    """D-99-15: skipped points before an appended name do not change D-99-14.

    An appended name still lands after the end of the list, so nothing
    already on the list moves, and the uploader may still confirm it.
    """
    from tests.test_t46_filmthickness import commit

    walk = walk_of(admin_conn, RAPCAP)
    body = [p for p in walk[:63] if p not in SKIPPED]
    name, job = job_name("RAP")
    data = pelt([*body, MARKER_POINT, *TAIL], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    [detail] = details(admin_conn, load_id, "FILM_WALK_UNKNOWN")
    assert MARKER_POINT in detail and "past the last point" in detail

    confirmed = engineer.post(
        ws(PLANT, file_hash, "film-walk-confirm"),
        json={"load_id": load_id,
              "points": [{"point_code": MARKER_POINT, "counted": True,
                          "orientation": "V"}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT point_no FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, RAPCAP, MARKER_POINT),
        )
        assert cur.fetchone() == (LIVE[RAPCAP] + 1,), "appended, never inserted"

    after = wait_for(engineer, load_id)
    assert after["batch"]["counts"]["rows_loaded"] == len(body) + 1
    commit(engineer, admin, after)
    [vid] = {f[6] for f in film_facts(admin_conn, load_id)}
    grid = viewer.get(
        f"/api/v1/plants/{PLANT}/filmthickness/vehicles/{vid}/points"
    ).json()
    assert grid["vehicle"]["mapped_point_count"] == len(body) + 1
    assert grid["vehicle"]["incomplete"] is True, "two points are still missing"


# =====================================================================
# 7. a sheet that names no points (D-99-9)
# =====================================================================
# T99-FIX (D-99-9): the nine real no-name FTM files write the second form,
# ``Point NNN / NNN`` -- point number out of total. `normalise_location` folds
# it to ``POINT001/017``, which T99's pattern did not match, so D-99-9 never
# fired on a real file. Both forms are refused now, and both are asserted.
@pytest.mark.parametrize("label", ["Point {n:03d}", "Point {n:03d} / 017"])
def test_a_sheet_of_point_nnn_labels_is_refused(
    engineer, admin_conn, film_cleanup, label  # noqa: F811
):
    name, job = job_name("SGL")
    data = pelt([label.format(n=n) for n in range(1, 18)], colour=COLOUR, job=job)
    review = sent(engineer, film_cleanup, admin_conn, name, data, PLANT)["Quick Summary"]
    load_id = review["batch"]["load_id"]
    assert review["batch"]["status"] == "REJECTED_TEMPLATE"
    with admin_conn.cursor() as cur:
        cur.execute("SELECT notes FROM load_batch WHERE load_id = %s", (load_id,))
        notes = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM filmthickness WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM stg_review_row WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0, "no data row was read"
        cur.execute(
            "SELECT count(*) FROM proposed_mapping WHERE load_id = %s", (load_id,)
        )
        assert cur.fetchone()[0] == 0, "nobody is asked to map a header we understand"
    assert "names no points" in notes and "Point 001" in notes


# =====================================================================
# 8. the Job Number (D-99-10, D-99-11)
# =====================================================================
def test_an_unusual_job_number_holds_the_sheet_and_loads_as_written(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    from tests.test_t46_filmthickness import commit

    walk = walk_of(admin_conn, RAPCAP)[:4]
    job = f"BL_RAP_{uuid.uuid4().int % 10**4:04d}"
    data = pelt([*walk, *TAIL], colour=COLOUR, job=job)
    review = sent(
        engineer, film_cleanup, admin_conn, f"{job}.xlsx", data, PLANT
    )["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    held = {
        reason for _, (disposition, reason)
        in rows_by_label(admin_conn, load_id).items() if disposition == "QUARANTINE"
    }
    assert held == {"FILM_JOB_UNUSUAL"}
    [detail] = details(admin_conn, load_id, "FILM_JOB_UNUSUAL")
    assert job in detail and "load as written" in detail

    answered = engineer.post(
        ws(PLANT, file_hash, "film-job-answer"), json={"load_id": load_id}
    )
    assert answered.status_code == 200, answered.text
    after = wait_for(engineer, load_id)
    assert after["batch"]["counts"]["rows_loaded"] == len(walk)
    commit(engineer, admin, after)
    assert {f[7] for f in film_facts(admin_conn, load_id)} == {job}, (
        "it loads as its own vehicle under exactly that number"
    )


def test_a_model_conflict_holds_the_sheet_until_the_uploader_chooses(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    from tests.test_t46_filmthickness import commit

    serial = f"{uuid.uuid4().int % 10**7:07d}"
    walk = walk_of(admin_conn, RAPTOR)[:4]
    data = pelt([*walk, *TAIL], colour=COLOUR, job=f"AW_RB_{serial}")
    review = sent(
        engineer, film_cleanup, admin_conn, f"AW_DBL_{serial}.xlsx", data, PLANT
    )["Quick Summary"]
    load_id = review["batch"]["load_id"]
    file_hash = review["batch"]["file_hash"]
    assert review["batch"]["counts"]["rows_loaded"] == 0
    [detail] = details(admin_conn, load_id, "FILM_MODEL_CONFLICT")
    assert RAPTOR in detail and RANGER in detail

    refused = engineer.post(
        ws(PLANT, file_hash, "film-model-answer"),
        json={"load_id": load_id, "model_code": "U704"},
    )
    assert refused.status_code == 422, refused.text

    chosen = engineer.post(
        ws(PLANT, file_hash, "film-model-answer"),
        json={"load_id": load_id, "model_code": RAPTOR},
    )
    assert chosen.status_code == 200, chosen.text
    after = wait_for(engineer, load_id)
    assert after["batch"]["counts"]["rows_loaded"] == len(walk)
    commit(engineer, admin, after)
    assert {f[4] for f in film_facts(admin_conn, load_id)} == {RAPTOR}


def test_a_colour_code_disagreement_loads_with_a_warning(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    from tests.test_t46_filmthickness import commit

    serial = f"{uuid.uuid4().int % 10**7:07d}"
    walk = walk_of(admin_conn, SGL)[:3]
    data = pelt([*walk, *TAIL], colour=COLOUR, job=f"AM_SGL_{serial}")
    review = sent(
        engineer, film_cleanup, admin_conn, f"AW_SGL_{serial}.xlsx", data, PLANT
    )["Quick Summary"]
    load_id = review["batch"]["load_id"]
    assert review["batch"]["counts"]["rows_loaded"] == len(walk), "it does not hold"
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT detail FROM stg_review_row "
            " WHERE load_id = %s AND disposition = 'LOAD'", (load_id,),
        )
        [warning] = [r[0] for r in cur.fetchall()]
    assert '"AM"' in warning and '"AW"' in warning and COLOUR in warning
    commit(engineer, admin, review)
    assert {f[5] for f in film_facts(admin_conn, load_id)} == {COLOUR}, (
        "Layer 2 decides the colour (D-99-11)"
    )


# =====================================================================
# 9. the setting (D-99-2, D-99-4)
# =====================================================================
def test_the_setting_is_read_changed_append_only_and_read_back(
    engineer, viewer, admin_conn, setting_cleanup  # noqa: F811
):
    url = f"/api/v1/plants/{PLANT}/film-points/{SGL}"
    before = engineer.get(url)
    assert before.status_code == 200, before.text
    body = before.json()
    assert (body["plant_code"], body["model_code"], body["has_setting"]) == (
        PLANT, SGL, True
    )
    assert [p["point_code"] for p in body["items"]] == list(FTM_SGL_58)
    assert all(p["counted"] for p in body["items"])
    assert {p["point_code"] for p in body["items"] if p["is_complete_stop"]} == {
        "058RTFEND"
    }
    assert {p["reason"] for p in body["items"]} == {
        "T99 seed (owner D-99-5, 2026-10-10)"
    }

    point = body["items"][1]["point_code"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT setting_id FROM film_point_setting "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s",
            (PLANT, SGL, point),
        )
        seeded = [r[0] for r in cur.fetchall()]
    assert len(seeded) == 1

    assert viewer.post(url, json={
        "points": [{"point_code": point, "counted": False, "orientation": "V"}],
        "reason": "T99 test: a Viewer may not change the setting",
    }).status_code == 403

    changed = engineer.post(url, json={
        "points": [{"point_code": point, "counted": False, "orientation": "V"}],
        "reason": "T99 test: this point is not walked any more",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["rows_written"] == 1
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT setting_id, counted FROM film_point_setting "
            " WHERE plant_code = %s AND model_code = %s AND point_code = %s "
            " ORDER BY setting_id",
            (PLANT, SGL, point),
        )
        rows = cur.fetchall()
        setting_cleanup.extend(r[0] for r in rows if r[0] not in seeded)
        cur.execute(
            "SELECT count(*) FROM audit_event "
            " WHERE action = 'catalogue.film_point_setting.change' "
            "   AND entity_id = %s", (f"{PLANT}:{SGL}",),
        )
        audited = cur.fetchone()[0]
    assert [r[0] for r in rows][:1] == seeded
    assert [r[1] for r in rows] == [True, False], (
        "a new row, and the older one untouched (ADR 0005, D-99-4)"
    )
    assert audited >= 1

    # The read says so, and still lists the point (D-99-2).
    after = engineer.get(url).json()
    shown = {p["point_code"]: p for p in after["items"]}
    assert shown[point]["counted"] is False
    assert shown[point]["reason"] == "T99 test: this point is not walked any more"
    assert shown[point]["changed_by"] is not None
    assert len(after["items"]) == 58, "a point that does not count is still listed"


def test_a_model_this_plant_does_not_walk_is_a_404(engineer):  # noqa: F811
    assert engineer.get(
        f"/api/v1/plants/{PLANT}/film-points/U704"
    ).status_code == 404


# =====================================================================
# 10. other plants: AAT now walks like FTM (RO04); FVL behaves as before
# =====================================================================
def test_an_aat_walk_with_095_past_its_list_holds_the_sheet_and_fvl_still_holds_extra_point(
    engineer, admin_conn, film_cleanup, ro19_plants  # noqa: F811
):
    ruled = ro19_plants({RANGER: ("059LBOXSIDE", "060LBOXSIDE")}, ruled=True)
    unruled = ro19_plants()
    # RO05 CHANGE (owner, RO04): AAT has `film_point_setting` rows, so T99
    # reaches it. Names written past the end of its list hold the whole
    # sheet, exactly as `test_an_appended_name_is_held_until_the_uploader_
    # confirms_it` does at FTM; nothing loads until the uploader confirms.
    data = pelt(["059LBOXSIDE", "095TGATEIN", "001FTWISH"],
                colour="Command Grey", job="",
                title="Ford Thailand Motors - PELT Filmbuild Report")
    review = sent(
        engineer, film_cleanup, admin_conn,
        f"Data Pelt P703 Box {uuid.uuid4().hex[:6]}.xlsx", data, ruled,
    )["Quick Summary"]
    load_id = review["batch"]["load_id"]
    held = {
        label: reason for label, (disposition, reason)
        in rows_by_label(admin_conn, load_id).items()
        if disposition == "QUARANTINE"
    }
    assert held == {"059LBOXSIDE": "FILM_WALK_UNKNOWN",
                    "095TGATEIN": "FILM_WALK_UNKNOWN",
                    "001FTWISH": "FILM_WALK_UNKNOWN"}, (
        "AAT has film_point_setting rows, so T99's sheet-level hold reaches it"
    )
    assert review["batch"]["counts"]["rows_loaded"] == 0
    [detail] = details(admin_conn, load_id, "FILM_WALK_UNKNOWN")
    assert "095TGATEIN" in detail and "past the last point" in detail

    # The old claim, on a plant that still has no setting: FVL.
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM film_point_setting WHERE plant_code = %s", (unruled,))
        assert cur.fetchone()[0] == 0, "synthetic plant has no film_point_setting row"
        cur.execute(
            "SELECT point_code FROM ref_plant_film_point "
            " WHERE plant_code = %s AND model_code = %s AND retired_at IS NULL "
            " ORDER BY point_no LIMIT 1",
            (unruled, RANGER),
        )
        [first] = cur.fetchone()
    job = f"UR{uuid.uuid4().hex[:8].upper()}"
    data = pelt([first, "095TGATEIN", "001FTWISH"], job=job, vin=0)
    review = sent(engineer, film_cleanup, admin_conn,
                  f"P703-{job}-AB.xlsx", data, unruled)["Quick Summary"]
    held = {
        label: reason for label, (disposition, reason)
        in rows_by_label(admin_conn, review["batch"]["load_id"]).items()
        if disposition == "QUARANTINE"
    }
    assert held == {"095TGATEIN": "EXTRA_POINT", "001FTWISH": "EXTRA_POINT"}, (
        "FVL has no film_point_setting row, so T99 does not reach it"
    )
    assert review["batch"]["counts"]["rows_loaded"] == 1


# =====================================================================
# 12. source level: no UPDATE / DELETE of a fact, an upload or a setting
# =====================================================================
#: ADR 0005: a measurement fact, an upload and a setting are never rewritten.
#: `load_batch` is the one of the three with a legitimate UPDATE -- its status
#: and row counts, under the column-scoped grant of revision 0001 -- so the
#: two files that hold that one statement are named here and nothing else may
#: carry it. A DELETE is never allowed anywhere, on any of the three.
UPDATE_ALLOWED = {
    "load_batch": (
        "app/repositories/batches.py",      # set_batch_outcome, the parse path
        "app/repositories/corrections.py",  # supersede / restore, T09 / T25
    ),
}


@pytest.mark.parametrize("table", ["filmthickness", "load_batch", "film_point_setting"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_no_update_or_delete_of_a_fact_an_upload_or_a_setting(table, verb):
    pattern = re.compile(
        rf"\bUPDATE\s+{table}\b" if verb == "UPDATE"
        else rf"\bDELETE\s+FROM\s+{table}\b",
        re.IGNORECASE,
    )
    allowed = UPDATE_ALLOWED.get(table, ()) if verb == "UPDATE" else ()
    found: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR.parent).as_posix()
        if rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                flat = " ".join(node.value.split())
                if pattern.search(flat):
                    found.append(f"{rel}:{node.lineno} {flat[:120]}")
    assert found == [], found


# =====================================================================
# the bound: the reference tables are flat across this module
# =====================================================================
def test_reference_counts_are_flat(admin_conn, reference_before):
    assert counts(admin_conn) == reference_before
