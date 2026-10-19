"""RO18 -- the generic gaps SAP and FVL need (every plant).

Claims:

* **B1** The Wave Scan panel question offers the plant x model's own live
  list: SAP J73, SAP Ranger and FVL Ranger (own words, off the shared
  catalogue) now offer 32; every other plant x model offers exactly what it
  did. A map onto a plant's own panel stores (``fk_pzm_plant_point``) and
  resolves; a panel that is not on that plant's list is refused by the key.
* **B2** ``19-Sept-26`` and ``19-09-2026`` read; every older format reads
  exactly as before.
* **B3** A Film sheet more than 3 days from the one date in its file name is
  held with one question; 3 days is not; no date or two dates in the name is
  no check; "the file name" and "the sheet" both replay.
* **B4** A sheet with no date anywhere, either domain, asks which month; the
  answer files every row on the 1st with ``date_is_month_only``; two
  same-colour cars stay two; History puts them in week 0 ("day not
  recorded"); they never pair.
* **B5** "Not a point of this list" is remembered per plant x model, frees the
  sheet, never loads, is listed on Aliases and retirable by an Admin.

Synthetic rows only. Pure tests and rolled-back transactions write nothing;
uploads are removed by ``film_cleanup`` (facts first) and the one tail-label
row B5 writes is removed by its test.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime

import psycopg
import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.domain.cleaner import Cleaner, parse_month_answer, suggest_month
from app.domain.film import (
    FilmCleaner, FilmReference, ModelResolution, REASON_FILM_NOT_A_POINT,
    file_name_date, parse_film_date,
)
from app.domain.history import MONTH_ONLY_WEEK, week_of
from app.domain.reader import RawRow
from app.repositories import mappings as maps
from app.repositories import pairing as pairing_repo
from app.repositories.reference import load_reference_data
from app.services.panel_pool import panel_pool
from tests.test_t04_ingest import admin, engineer, ingest_apps, wait_for  # noqa: F401
from tests.test_t46_filmthickness import commit, film_cleanup, sent  # noqa: F401

OWN_WORD_LISTS = (("SAP", "J73 DBL"), ("SAP", "P703 DBL RANGER"), ("FVL", "P703 DBL RANGER"))


# =====================================================================
# pure
# =====================================================================
def test_b2_the_new_spellings_read_and_the_old_ones_are_unchanged():
    assert parse_film_date("19-Sept-26") == (date(2026, 9, 19), None)
    assert parse_film_date("19-SEPTEMBER-2026") == (date(2026, 9, 19), None)
    assert parse_film_date("19-sept-2026") == (date(2026, 9, 19), None)
    assert parse_film_date("19-09-2026") == (date(2026, 9, 19), None)
    # The formats that read before read the same.
    for text_value, expected in (
        ("03-Jul-26", date(2026, 7, 3)), ("03-Jul-2026", date(2026, 7, 3)),
        ("03/07/2026", date(2026, 7, 3)), ("03.07.2026", date(2026, 7, 3)),
        ("2026-07-03", date(2026, 7, 3)), (datetime(2026, 7, 3, 9), date(2026, 7, 3)),
    ):
        assert parse_film_date(text_value) == (expected, None)
    # Still refused: two letters, a day the month has not got, no date.
    for bad in ("19-Ju-26", "31-Sept-26", "Sept 19"):
        assert parse_film_date(bad)[0] is None


def test_b3_the_file_name_date_is_one_full_date_or_none():
    assert file_name_date("IG P703 CC C1 PELT TB26249 18.09.2026.ods") == date(2026, 9, 18)
    assert file_name_date("160720267VP703CCC2TM06350PELT.ods") == date(2026, 7, 16)
    assert file_name_date("12082026 7V P703 CC C1 TP20484 PELT.ods") == date(2026, 8, 12)
    assert file_name_date("x 18-09-2026.xlsx") == date(2026, 9, 18)
    assert file_name_date("P703-MR60334-MG.xlsx") is None, "no date: no check"
    assert file_name_date("a 18.09.2026 b 19.09.2026.ods") is None, "two dates: no check"
    assert file_name_date("a 31.02.2026.ods") is None, "not a date"


def test_b4_the_month_is_suggested_by_the_name_and_answered_as_yyyy_mm():
    assert suggest_month("AAT Thickness Jul2026.xlsx") == "2026-07"
    assert suggest_month("Input Data 09.2026.xlsx") == "2026-09"
    assert suggest_month("Input Data Jul 2026 and Aug 2026.xlsx") is None
    assert suggest_month("P703-MR60334-MG.xlsx") is None
    assert parse_month_answer("2026-07") == date(2026, 7, 1)
    assert parse_month_answer("2026-13") is None and parse_month_answer("July") is None
    assert week_of(date(2026, 7, 1), True) == MONTH_ONLY_WEEK == 0
    assert week_of(date(2026, 7, 1)) == 1


def _film_row(row: int, location: str) -> RawRow:
    return RawRow(
        values={"location": location, "clear": 40.0, "ecoat": 20.0, "color": "Command Grey",
                "date": "2026-07-03"},
        extra={}, source_file="t.xlsx", source_sheet="S", source_row=row,
    )


def test_b5_an_answered_label_is_kept_never_loaded_with_or_without_rules():
    key = ("ZRO18", "M")
    for settings in ({}, {key: {"001A": (True, "H")}}):
        ref = FilmReference(
            plant_catalogue={key: {"001A": "001A"}},
            tail_labels={key: frozenset({"028LTFTDOOR", "BOOTH_1"})},
            not_a_point={key: frozenset({"028LTFTDOOR"})},
            point_setting=settings,
        )
        cleaner = FilmCleaner(
            ref, plant="ZRO18", model=ModelResolution("M", "M", "t", "t"), meta={},
            color_by_plant={}, color={"command grey": "Command Grey"},
            known_color_names=["Command Grey"],
            offered_colors={("ZRO18", "Command Grey"): True},
            offered_models={("ZRO18", "M"): True},
        )
        out = cleaner.clean_all([_film_row(2, "001A"), _film_row(3, "028LTFTDOOR"),
                                 _film_row(4, "BOOTH_1")])
        assert [r.point_code for r in out.clean] == ["001A"]
        assert [a.reason for a in out.aggregates] == [REASON_FILM_NOT_A_POINT, "FILM_TAIL_LABEL"]
        assert not out.held and not out.rejects


# =====================================================================
# B1: the panel question, on the standing database (read / rolled back)
# =====================================================================
@pytest.fixture()
def owner(admin_dsn):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    try:
        with engine.connect() as c:
            tx = c.begin()
            try:
                yield c
            finally:
                tx.rollback()
    finally:
        engine.dispose()


def _pairs(c) -> list[tuple[str, str]]:
    return [tuple(r) for r in c.execute(text(
        "SELECT DISTINCT plant_code, model_code FROM ref_plant_ws_point "
        "WHERE retired_at IS NULL ORDER BY 1, 2")).all()]


def test_b1_every_plant_offers_its_own_live_list_and_old_offers_are_unchanged(owner):
    for plant, model in _pairs(owner):
        live = {r["zone_code"] for r in maps.live_plant_panels(owner, plant, model)}
        catalogue = maps.expected_zone_codes(owner, model)
        offered = set(panel_pool(owner, load_id=None, plant_code=plant, model_code=model)
                      .offer("RO18 HELD PANEL").offerable)
        assert offered == live, (plant, model)
        if (plant, model) in OWN_WORD_LISTS:
            assert len(offered) == 32 and not offered & catalogue, (plant, model)
        else:
            # Before RO18 the offer was the live panels on the catalogue: the same set.
            assert offered == live & catalogue, (plant, model)


def test_b1_a_map_onto_the_plants_own_panel_stores_and_resolves(owner):
    plant, model = "SAP", "J73 DBL"
    panel = sorted(r["zone_code"] for r in maps.live_plant_panels(owner, plant, model))[0]
    raw = f"RO18 TEST {uuid.uuid4().hex[:6]}"
    maps.insert_engineer_zone_alias(
        owner, plant_code=plant, model_code=model, raw_zone_text=raw, raw_position=None,
        zone_code=panel, approved_by="ro18-test", note="RO18 test, rolled back",
    )
    cleaner = Cleaner(load_reference_data(owner), (plant,), expected_plant=plant)
    assert cleaner.resolve_checkzone(plant, model, raw) == panel
    # A panel SAP J73's own list never held (live or retired) is refused by the key.
    off_list = owner.execute(text(
        "SELECT min(z.zone_code) FROM ref_checkzone z WHERE NOT EXISTS ("
        " SELECT 1 FROM ref_plant_ws_point p WHERE (p.plant_code, p.model_code, p.zone_code)"
        " = (:p, :m, z.zone_code))"), {"m": model, "p": plant}).scalar_one()
    assert off_list is not None
    with pytest.raises(IntegrityError, match="fk_pzm_plant_point"):
        with owner.begin_nested():
            maps.insert_engineer_zone_alias(
                owner, plant_code=plant, model_code=model, raw_zone_text=raw + "X",
                raw_position=None, zone_code=off_list, approved_by="ro18-test",
                note="RO18 test, rolled back",
            )


# =====================================================================
# uploads (AAT Film, FVL CX743 Wave Scan): synthetic, cleaned up
# =====================================================================
WALK = ["001HOOD", "002HOOD", "003HOOD"]
FILM_HEADERS = ["Checkzone", "Clearcoat", "Basecoat2", "Basecoat1", "E-coat", "Orientation", "Color"]


def a_day() -> date:
    n = uuid.uuid4().int
    return date(2001 + n % 15, 1 + (n // 15) % 12, 1 + (n // 180) % 20)


def film_sheet(cars, *, dated: bool = True) -> bytes:
    """AAT's layout; ``cars`` is ``[(labels, colour, day)]``. ``dated=False``
    leaves the Date column out: a sheet with no date anywhere (B4)."""
    wb = Workbook()
    wb.properties.title = uuid.uuid4().hex
    ws = wb.active
    ws.title = "P703"
    ws.append(FILM_HEADERS + (["Date"] if dated else []))
    base = uuid.uuid4().int % 500 / 100
    for k, (labels, colour, day) in enumerate(cars):
        for i, label in enumerate(labels):
            ws.append([label, 40.0 + base + i, 10.0 + k, 8.0, 20.0, "H", colour]
                      + ([day.isoformat()] if dated else []))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def rows_of(admin_conn, load_id: int) -> list[tuple]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT source_row, disposition, reason, canonical->>'measured_date', "
            "       canonical->>'logical_vehicle_id', canonical->>'date_is_month_only' "
            "  FROM stg_review_row WHERE load_id = %s ORDER BY source_row", (load_id,))
        return cur.fetchall()


def upload(engineer, film_cleanup, admin_conn, name, data, plant):  # noqa: F811
    [review] = sent(engineer, film_cleanup, admin_conn, name, data, plant).values()
    return review


def tab_of(engineer, plant, review) -> dict:  # noqa: F811
    body = engineer.get(
        f"/api/v1/plants/{plant}/workbooks/{review['batch']['file_hash']}/worksheet").json()
    [tab] = [s for s in body["sheets"] if s["load_id"] == review["batch"]["load_id"]]
    return tab


def answer(engineer, plant, review, path, **body):  # noqa: F811
    response = engineer.post(
        f"/api/v1/plants/{plant}/workbooks/{review['batch']['file_hash']}/{path}",
        json={"load_id": review["batch"]["load_id"], **body},
    )
    assert response.status_code == 200, response.text
    # The tab is re-read from the stored bytes by the worker.
    wait_for(engineer, review["batch"]["load_id"])
    return response.json()


@pytest.mark.ingest
@pytest.mark.parametrize("apart, asked", [(3, False), (-3, False), (4, True), (-4, True)])
def test_b3_more_than_three_days_from_the_file_name_is_one_question(
    engineer, admin_conn, film_cleanup, apart, asked  # noqa: F811
):
    day = a_day()
    named = date.fromordinal(day.toordinal() + apart)
    review = upload(engineer, film_cleanup, admin_conn,
                    f"RO18 B3 {uuid.uuid4().hex[:6]} {named:%d.%m.%Y}.xlsx",
                    film_sheet([(WALK, "Command Grey", day)]), "AAT")
    rows = rows_of(admin_conn, review["batch"]["load_id"])
    tab = tab_of(engineer, "AAT", review)
    if not asked:
        assert [(r[1], r[3]) for r in rows] == [("LOAD", day.isoformat())] * 3
        assert tab["date_question"] is None
        return
    assert {(r[1], r[2]) for r in rows} == {("QUARANTINE", "FILM_DATE_DISAGREES")}
    question = tab["date_question"]
    assert question["kind"] == "date" and tab["state"] == "needs_answer"
    assert (question["sheet_date"], question["file_name_date"]) == (day.isoformat(), named.isoformat())
    assert question["operator_message"].startswith("Which date is right?")


@pytest.mark.ingest
@pytest.mark.parametrize("choice", ["file_name", "sheet"])
def test_b3_both_answers_replay(engineer, admin_conn, film_cleanup, choice):  # noqa: F811
    day = a_day()
    named = date.fromordinal(day.toordinal() + 10)
    review = upload(engineer, film_cleanup, admin_conn,
                    f"RO18 B3 answer {uuid.uuid4().hex[:6]} {named:%d.%m.%Y}.xlsx",
                    film_sheet([(WALK, "Command Grey", day)]), "AAT")
    out = answer(engineer, "AAT", review, "film-date-answer", choice=choice)
    assert out["replayed_load_ids"] == [review["batch"]["load_id"]]
    want = (named if choice == "file_name" else day).isoformat()
    assert [(r[1], r[3]) for r in rows_of(admin_conn, review["batch"]["load_id"])] == [("LOAD", want)] * 3
    assert tab_of(engineer, "AAT", review)["date_question"] is None
    with admin_conn.cursor() as cur:
        cur.execute("SELECT kind, subject FROM worksheet_decision WHERE load_id = %s",
                    (review["batch"]["load_id"],))
        assert cur.fetchall() == [("FILM_DATE_CHOICE", choice)]


@pytest.mark.ingest
def test_b4_a_film_sheet_with_no_date_asks_the_month_and_files_it_month_only(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    cars = [(WALK, "Command Grey", None), (WALK, "Command Grey", None)]
    review = upload(engineer, film_cleanup, admin_conn,
                    f"RO18 B4 Jul2026 {uuid.uuid4().hex[:6]}.xlsx",
                    film_sheet(cars, dated=False), "AAT")
    load_id = review["batch"]["load_id"]
    assert {(r[1], r[2]) for r in rows_of(admin_conn, load_id)} == {("QUARANTINE", "MONTH_UNKNOWN")}
    question = tab_of(engineer, "AAT", review)["date_question"]
    assert (question["kind"], question["suggested_month"]) == ("month", "2026-07")
    assert "Which month" in question["operator_message"]

    month = f"{2001 + uuid.uuid4().int % 15}-0{1 + uuid.uuid4().int % 9}"  # no real car's month
    answer(engineer, "AAT", review, "month-answer", month=month)
    rows = rows_of(admin_conn, load_id)
    assert {(r[1], r[3], r[5]) for r in rows} == {("LOAD", f"{month}-01", "true")}
    assert len({r[4] for r in rows}) == 2, "two same-colour cars of the month stay two"

    commit(engineer, admin, wait_for(engineer, load_id))
    with admin_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT measured_date, date_is_month_only FROM filmthickness "
                    "WHERE load_id = %s", (load_id,))
        assert cur.fetchall() == [(date.fromisoformat(f"{month}-01"), True)]
    weeks = engineer.get("/api/v1/plants/AAT/filmthickness/summaries",
                         params={"month": month}).json()["weeks"]
    assert [w["week"] for w in weeks] == [0], "day not recorded, never week 1"
    cars_page = engineer.get("/api/v1/plants/AAT/filmthickness/vehicles",
                             params={"month": month, "week": 0}).json()
    assert cars_page["page"]["total"] == 2
    assert all(v["date_is_month_only"] for v in cars_page["items"])


FVL_HEADERS = ["Style", "Color", "Panel", "LW", "SW", "du", "Wa", "Wb",
               "Wc", "Wd", "We", "CF", "Doi", "Serial No"]


@pytest.fixture()
def cx743(admin_conn) -> tuple[list[str], str]:
    with admin_conn.cursor() as cur:
        cur.execute("SELECT zone_code FROM ref_plant_ws_point WHERE plant_code = 'FVL' "
                    "AND model_code = 'CX743' AND retired_at IS NULL AND NOT is_extra "
                    "ORDER BY point_no")
        walk = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT color_name FROM ref_plant_color WHERE plant_code = 'FVL' "
                    "AND is_offered ORDER BY color_name LIMIT 1")
        colour = cur.fetchone()[0]
    return walk, colour


@pytest.mark.ingest
def test_b4_a_wave_scan_sheet_with_no_date_asks_the_month_and_never_pairs(
    engineer, admin, admin_conn, film_cleanup, cx743, owner  # noqa: F811
):
    walk, colour = cx743
    serial = f"RO18-{uuid.uuid4().hex[:8]}"
    wb = Workbook()
    ws = wb.active
    ws.title = "CF data template"
    ws.append(FVL_HEADERS)
    base = uuid.uuid4().int % 500 / 100
    for i, label in enumerate(walk):
        ws.append(["CX743", colour, label, 10.0 + base, 20.0, 1.0, 9.0, 17.0, 14.0,
                   18.0, 9.0, 60.0 + i / 10, 80.0, serial])
    data = io.BytesIO()
    wb.save(data)
    review = upload(engineer, film_cleanup, admin_conn,
                    f"RO18 B4 WS 09.2026 {uuid.uuid4().hex[:6]}.xlsx", data.getvalue(), "FVL")
    load_id = review["batch"]["load_id"]
    assert {(r[1], r[2]) for r in rows_of(admin_conn, load_id)} == {("REJECT", "MONTH_UNKNOWN")}
    question = tab_of(engineer, "FVL", review)["date_question"]
    assert (question["kind"], question["suggested_month"]) == ("month", "2026-09")

    month = f"{2001 + uuid.uuid4().int % 15}-0{1 + uuid.uuid4().int % 9}"
    answer(engineer, "FVL", review, "month-answer", month=month)
    rows = rows_of(admin_conn, load_id)
    assert {(r[1], r[3]) for r in rows} == {("LOAD", f"{month}-01")}
    commit(engineer, admin, wait_for(engineer, load_id))
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*), bool_and(date_is_month_only) FROM wavescan "
                    "WHERE load_id = %s", (load_id,))
        assert cur.fetchone() == (len(walk), True)
    assert not [car for car in pairing_repo.wavescan_cars(owner, "FVL") if car["car_no"] == serial]
    found = engineer.get("/api/v1/plants/FVL/history/vehicles", params={
        "month": month, "week": 0, "model": "CX743", "color": colour}).json()["items"]
    assert [(v["serial_no"], v["week"], v["date_is_month_only"]) for v in found] == [(serial, 0, True)]


@pytest.mark.ingest
def test_b5_not_a_point_frees_the_sheet_is_listed_and_retirable(
    engineer, admin, admin_conn, film_cleanup  # noqa: F811
):
    label = f"RO18NAP{uuid.uuid4().hex[:6].upper()}"
    day = a_day()
    data = film_sheet([(["001HOOD", label, "002HOOD", "003HOOD"], "Command Grey", day)])
    review = upload(engineer, film_cleanup, admin_conn, f"RO18 B5 {uuid.uuid4().hex[:6]}.xlsx",
                    data, "AAT")
    load_id = review["batch"]["load_id"]
    try:
        rows = rows_of(admin_conn, load_id)
        assert not [r for r in rows if r[1] == "LOAD"], "an unanswered label holds the sheet (rules on)"
        assert any(u["raw_location"] == label
                   for u in tab_of(engineer, "AAT", review)["film_unknown_labels"])

        answer(engineer, "AAT", review, "film-not-a-point", raw_location=label)
        rows = rows_of(admin_conn, load_id)
        assert [(r[1], r[2]) for r in rows] == [
            ("LOAD", None), ("AGGREGATE_ROW", REASON_FILM_NOT_A_POINT), ("LOAD", None), ("LOAD", None)]
        tab = tab_of(engineer, "AAT", review)
        assert tab["state"] == "ready" and tab["rows"][1]["film_tail"] is True

        url = "/api/v1/plants/AAT/point-aliases/film/P703 DBL RANGER"
        [item] = [i for i in engineer.get(url).json()["items"] if i["kind"] == "not_a_point"
                  and i["spelling"] == label]
        assert item["not_a_point"] and item["retirable"] and item["code"] == ""
        # Asked again, a second answer is refused: it is remembered.
        again = engineer.post(
            f"/api/v1/plants/AAT/workbooks/{review['batch']['file_hash']}/film-not-a-point",
            json={"load_id": load_id, "raw_location": label})
        assert again.status_code == 409
        # An Admin retires it; the label is a question again on the next upload.
        assert engineer.post(f"{url}/retire", json={"kind": "not_a_point", "alias_id": label,
                                                    "reason": "RO18 test"}).status_code == 403
        retired = admin.post(f"{url}/retire", json={"kind": "not_a_point", "alias_id": label,
                                                    "reason": "RO18 test"})
        assert retired.status_code == 200, retired.text
        second = upload(engineer, film_cleanup, admin_conn, f"RO18 B5 again {uuid.uuid4().hex[:6]}.xlsx",
                        film_sheet([(["001HOOD", label, "002HOOD", "003HOOD"], "Command Grey",
                                     a_day())]), "AAT")
        assert any(u["raw_location"] == label
                   for u in tab_of(engineer, "AAT", second)["film_unknown_labels"])
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM ref_plant_film_tail_label WHERE plant_code = 'AAT' "
                        "AND label_norm = %s AND not_a_point", (label,))


def test_the_panel_question_stays_under_the_500_character_limit():
    """RO18: B1 made SAP's panel question reachable; a file with swapped columns
    writes a panel name where the Tolerance Group goes, and a long name and
    model ran the sentence past ``HeldLabelGroup.operator_message`` (500)."""
    from app.domain.held_label_copy import operator_message_for
    many = [f"{n:02d}RHS Box Middle Long Panel Name" for n in range(32)]
    # The longest held checkzone values of SAP's September file (27 characters).
    for shown in ("Vertical", "IGNITE ORANGE 3C", "Cyclone terra green 4GREWHA"):
        text_out = operator_message_for(
            "zone", shown, column="checkzone", plant="SAP", teachable=True,
            model="P703 DBL RANGER", orientations=many,
        )
        assert len(text_out) <= 500, len(text_out)
        assert "32 different values" in text_out


def test_a_column_proposal_may_teach_a_film_header_in_the_film_vocabulary():
    """RO18 (owner, in chat 2026-10-14): FVL's Vapor Blue files spell Clearcoat
    'Cleatcoat'. A COLUMN proposal now names its domain; each domain takes
    only its own fields, and the default is still Wave Scan."""
    from pydantic import ValidationError
    from app.schemas.mappings import ColumnPayload
    film = ColumnPayload(raw_header="Cleatcoat", logical_field="clear", domain="FILMTHICKNESS")
    assert (film.raw_header, film.logical_field, film.domain) == ("cleatcoat", "clear", "FILMTHICKNESS")
    assert ColumnPayload(raw_header="CF Value", logical_field="cf").domain == "WAVESCAN"
    for bad in ({"logical_field": "clear"}, {"logical_field": "cf", "domain": "FILMTHICKNESS"}):
        with pytest.raises(ValidationError, match="is not a"):
            ColumnPayload(raw_header="x", **bad)


def test_an_existing_column_alias_is_read_per_domain(owner):
    """RO18: a COLUMN approval that repeats an existing alias is a confirmation
    (nothing inserted, the batch replayed); the lookup is per domain."""
    assert maps.column_alias(owner, "FILMTHICKNESS", "clearcoat") == "clear"
    assert maps.column_alias(owner, "WAVESCAN", "clearcoat") is None
    assert maps.column_alias(owner, "FILMTHICKNESS", "ro18 no such header") is None
