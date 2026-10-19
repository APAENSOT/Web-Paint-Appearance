"""RO17 Part C1b -- Film point editing without the T99 switch.

Claims (spec section 4, D-RO17-3/-8/-9/-10/-11/-12):

* add / retire work on a Film list **without** `film_point_setting`, and add
  writes no setting row there (the T99 rules stay off); with settings the
  add is exactly T109's (one setting row) -- the rules apply only there;
* never the last live point;
* restore puts a retired point back with its own number (RO19), and is
  refused on a clashing code / label;
* a first list on an offered plant x model; one not offered stays 404 (SAP
  P703 DBL RAPTOR is read, never written);
* tail labels: add, refuse, retire, put back; the loader skips retired ones;
* an earlier label resolves, last, and never at another plant.

**Zero residue.** Pure tests build `FilmReference` in memory. DB tests run on
one owner connection inside a transaction that is always rolled back: the
synthetic plant ``ZRO17`` and its models exist only inside it, and the
service calls run under ``SET LOCAL ROLE app_rw`` so the application's own
grants are what is exercised.
"""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.domain.film import FilmReference
from app.repositories import filmthickness as film_repo
from app.services import worksheet as svc
from app.services.workbooks import WorkbookError

PLANT = "ZRO17"
OTHER = "ZRO17X"
LISTED = "ZRO17 FILM A"   # offered, live list, no setting
RULED = "ZRO17 FILM S"    # offered, live list, with setting
FRESH = "ZRO17 FILM B"    # offered, in the Film vocabulary, no list
UNOFFERED = "ZRO17 FILM C"  # in the Film vocabulary, not offered
POINTS = (("001ZHOOD", "H"), ("002ZROOF", "H"), ("003ZDOOR", "V"))


# =====================================================================
# pure: resolution order (D-RO17-3)
# =====================================================================
def test_a_label_resolves_last_and_only_at_its_own_plant():
    ref = FilmReference(
        plant_catalogue={(PLANT, LISTED): {"001ZHOOD": "001ZHOOD", "002ZROOF": "002ZROOF"}},
        point_label={
            (PLANT, LISTED, "ROOFLH"): "002ZROOF",
            # A label can never beat an exact name: gold answers first.
            (PLANT, LISTED, "001ZHOOD"): "002ZROOF",
        },
    )
    assert ref.resolve_point(PLANT, LISTED, "Roof LH") == "002ZROOF"
    assert ref.resolve_point(PLANT, LISTED, "001zhood") == "001ZHOOD"
    assert ref.resolve_point(OTHER, LISTED, "Roof LH") is None, "another plant"
    assert ref.resolve_point(PLANT, FRESH, "Roof LH") is None, "another model"


# =====================================================================
# DB: one rolled-back transaction per test
# =====================================================================
@pytest.fixture()
def conn(admin_dsn):
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(admin_dsn))
    try:
        with engine.connect() as c:
            tx = c.begin()
            try:
                _seed(c)
                c.execute(text("SET LOCAL ROLE app_rw"))
                yield c
            finally:
                tx.rollback()
    finally:
        engine.dispose()


@pytest.fixture()
def actor(conn) -> str:
    return str(conn.execute(text("SELECT id FROM app_user ORDER BY id LIMIT 1")).scalar_one())


def _seed(c) -> None:
    run = lambda sql, **p: c.execute(text(sql), p)  # noqa: E731
    for plant in (PLANT, OTHER):
        run("INSERT INTO ref_plant (plant_code, plant_name) VALUES (:p, 'RO17 test, rolled back')", p=plant)
    for i, model in enumerate((LISTED, RULED, FRESH, UNOFFERED)):
        run(
            "INSERT INTO ref_model (model_code, model_family, body_style, expected_zone_count, wavescan_ok) "
            "VALUES (:m, 'ZRO17', 'PICKUP', 0, false)", m=model,
        )
        run("INSERT INTO ref_film_model_alias (plant_code, raw_token, model_code) "
            "VALUES (:p, :t, :m)", p=PLANT, t=f"ZRO17T{i}", m=model)
        run("INSERT INTO ref_plant_model (plant_code, model_code, is_offered) VALUES (:p, :m, :o)",
            p=PLANT, m=model, o=model != UNOFFERED)
    for model in (LISTED, RULED):
        for no, (code, orient) in enumerate(POINTS, start=1):
            run("INSERT INTO ref_film_point (point_code) VALUES (:c) ON CONFLICT DO NOTHING", c=code)
            run("INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, point_no, orientation) "
                "VALUES (:p, :m, :c, :n, :o)", p=PLANT, m=model, c=code, n=no, o=orient)
            run("INSERT INTO ref_plant_film_point_label (plant_code, model_code, point_code, label, "
                "label_norm, reason) VALUES (:p, :m, :c, :c, :c, 'initial: the code')",
                p=PLANT, m=model, c=code)
            if model == RULED:
                run("INSERT INTO film_point_setting (plant_code, model_code, point_code, counted, "
                    "orientation, reason) VALUES (:p, :m, :c, true, :o, 'RO17 test, rolled back')",
                    p=PLANT, m=model, c=code, o=orient)


def _settings(conn, model: str) -> int:
    return conn.execute(text(
        "SELECT count(*) FROM film_point_setting WHERE plant_code = :p AND model_code = :m"
    ), {"p": PLANT, "m": model}).scalar_one()


def _refused(status: int, fn, *args, **kwargs) -> str:
    with pytest.raises(WorkbookError) as caught:
        fn(*args, **kwargs)
    assert caught.value.status_code == status, caught.value
    return str(caught.value)


def _add(conn, actor, model, code, **kw):
    return svc.add_film_point(
        conn, PLANT, model, point_code=code, counted=kw.pop("counted", True),
        orientation=kw.pop("orientation", None), reason="RO17 test, rolled back",
        actor=actor, correlation_id=None,
    )


def _retire(conn, actor, model, code):
    return svc.retire_film_point(conn, PLANT, model, point_code=code,
                                 reason="RO17 test", actor=actor, correlation_id=None)


def _restore(conn, actor, model, code):
    return svc.restore_film_point(conn, PLANT, model, point_code=code,
                                  reason="RO17 test", actor=actor, correlation_id=None)


# ---------------------------------------------------------------------
# D-RO17-11: editing without the switch; the rules only with it
# ---------------------------------------------------------------------
def test_add_without_settings_writes_no_setting_and_keeps_the_rules_off(conn, actor):
    out = _add(conn, actor, LISTED, " 004zdoor ")
    assert (out["point_code"], out["point_no"], out["label"]) == ("004ZDOOR", 4, "004zdoor")
    assert "point rules are not on" in out["operator_message"]
    assert _settings(conn, LISTED) == 0, "a setting row would switch T99 on"
    assert conn.execute(text(
        "SELECT orientation FROM ref_plant_film_point WHERE plant_code = :p "
        "AND model_code = :m AND point_code = '004ZDOOR'"), {"p": PLANT, "m": LISTED}
    ).scalar_one() == "V", "proposed from the list's own DOOR point, on the list row"
    assert conn.execute(text(
        "SELECT label, reason FROM ref_plant_film_point_label WHERE plant_code = :p "
        "AND model_code = :m AND point_code = '004ZDOOR'"), {"p": PLANT, "m": LISTED}
    ).one() == ("004zdoor", "added on Point Check -- RO17 test, rolled back")
    film = film_repo.load_film_reference(conn)
    assert not film.has_setting(PLANT, LISTED)
    assert film.resolve_point(PLANT, LISTED, "004ZDOOR") == "004ZDOOR"
    read = svc.film_point_setting(conn, PLANT, LISTED)
    assert read["has_setting"] is False
    assert [p["label"] for p in read["items"]][-1] == "004zdoor"


def test_add_with_settings_is_exactly_t109(conn, actor):
    before = _settings(conn, RULED)
    out = _add(conn, actor, RULED, "004ZDOOR", counted=False)
    assert "point rules are not on" not in out["operator_message"]
    assert _settings(conn, RULED) == before + 1
    assert conn.execute(text(
        "SELECT orientation FROM ref_plant_film_point WHERE plant_code = :p "
        "AND model_code = :m AND point_code = '004ZDOOR'"), {"p": PLANT, "m": RULED}
    ).scalar_one() is None, "with settings the H / V lives on the setting row, as today"
    film = film_repo.load_film_reference(conn)
    assert film.has_setting(PLANT, RULED) and not film.has_setting(PLANT, LISTED)
    assert film.point_setting[(PLANT, RULED)]["004ZDOOR"] == (False, "V")


def test_add_refuses_a_label_that_already_names_another_point(conn, actor):
    conn.execute(text(
        "INSERT INTO ref_plant_film_point_label (plant_code, model_code, point_code, label, "
        "label_norm, reason) VALUES (:p, :m, '002ZROOF', '004ZROOF', '004ZROOF', 'test')"
    ), {"p": PLANT, "m": LISTED})
    message = _refused(409, _add, conn, actor, LISTED, "004ZROOF")
    assert "002ZROOF" in message and "Nothing was changed" in message


# ---------------------------------------------------------------------
# D-RO17-8: never the last live point
# ---------------------------------------------------------------------
def test_retire_without_settings_and_the_last_point_guard(conn, actor):
    out = _retire(conn, actor, LISTED, "001ZHOOD")
    assert out["label"] == "001ZHOOD"
    _retire(conn, actor, LISTED, "002ZROOF")
    message = _refused(409, _retire, conn, actor, LISTED, "003ZDOOR")
    assert "last live point" in message
    assert [p["point_code"] for p in film_repo.point_setting(conn, PLANT, LISTED)] == ["003ZDOOR"]


# ---------------------------------------------------------------------
# D-RO17-9: restore
# ---------------------------------------------------------------------
def test_restore_puts_the_point_back_with_its_label(conn, actor):
    _retire(conn, actor, LISTED, "002ZROOF")
    out = _restore(conn, actor, LISTED, "002ZROOF")
    assert (out["point_no"], out["label"]) == (2, "002ZROOF")
    assert [p["point_code"] for p in film_repo.point_setting(conn, PLANT, LISTED)] == [
        c for c, _ in POINTS
    ]
    assert conn.execute(text(
        "SELECT count(*) FROM ref_plant_film_point_label WHERE plant_code = :p "
        "AND model_code = :m AND point_code = '002ZROOF'"), {"p": PLANT, "m": LISTED}
    ).scalar_one() == 1, "it had a label row, so none is added"
    assert conn.execute(text(
        "SELECT count(*) FROM audit_event WHERE action = 'catalogue.plant_film_point.restore' "
        "AND entity_id = :e"), {"e": f"{PLANT}:{LISTED}:002ZROOF"}
    ).scalar_one() == 1
    _refused(409, _restore, conn, actor, LISTED, "002ZROOF")  # live already
    _refused(404, _restore, conn, actor, LISTED, "009NOPE")


def test_restore_of_a_point_with_no_label_row_writes_the_code(conn, actor):
    conn.execute(text("RESET ROLE"))
    conn.execute(text(
        "INSERT INTO ref_film_point (point_code) VALUES ('009ZOLD') ON CONFLICT DO NOTHING"))
    conn.execute(text(
        "INSERT INTO ref_plant_film_point (plant_code, model_code, point_code, point_no, "
        "retired_at, retired_reason) VALUES (:p, :m, '009ZOLD', 9, now(), 'old code')"
    ), {"p": PLANT, "m": LISTED})
    conn.execute(text("SET LOCAL ROLE app_rw"))
    assert _restore(conn, actor, LISTED, "009ZOLD")["label"] == "009ZOLD"
    assert conn.execute(text(
        "SELECT label, reason FROM ref_plant_film_point_label WHERE plant_code = :p "
        "AND model_code = :m AND point_code = '009ZOLD'"), {"p": PLANT, "m": LISTED}
    ).one() == ("009ZOLD", "restore: the code")


def test_restore_keeps_its_held_number_but_refuses_a_label_clash(conn, actor):
    _retire(conn, actor, LISTED, "003ZDOOR")
    _add(conn, actor, LISTED, "003ZDOORNEW", orientation="V")
    restored = _restore(conn, actor, LISTED, "003ZDOOR")
    assert (restored["point_code"], restored["label"], restored["point_no"]) == (
        "003ZDOOR", "003ZDOOR", 3,
    )
    # RO19 F6: 3 stays the retired point's until it is restored, so the added
    # point took the next free number rather than sharing 3. Both are live now.
    assert conn.execute(text(
        "SELECT point_no FROM ref_plant_film_point WHERE plant_code = :p "
        "AND model_code = :m AND point_code = '003ZDOORNEW'"
    ), {"p": PLANT, "m": LISTED}).scalar_one() != 3, "a retired number is never handed out"
    live = conn.execute(text(
        "SELECT point_no FROM ref_plant_film_point WHERE plant_code = :p "
        "AND model_code = :m AND retired_at IS NULL"
    ), {"p": PLANT, "m": LISTED}).scalars().all()
    assert len(live) == len(set(live)), f"two live points share a number: {sorted(live)}"
    _retire(conn, actor, LISTED, "002ZROOF")
    # Somebody's label for another point is now the retired point's code.
    conn.execute(text(
        "INSERT INTO ref_plant_film_point_label (plant_code, model_code, point_code, label, "
        "label_norm, reason) VALUES (:p, :m, '001ZHOOD', '002ZROOF', '002ZROOF', 'test')"
    ), {"p": PLANT, "m": LISTED})
    message = _refused(409, _restore, conn, actor, LISTED, "002ZROOF")
    assert "001ZHOOD" in message and "Nothing was changed" in message


# ---------------------------------------------------------------------
# D-RO17-10: a first list on an offered model only
# ---------------------------------------------------------------------
def test_a_first_list_on_an_offered_model_and_not_on_one_not_offered(conn, actor):
    models = svc.film_models(conn, PLANT)
    assert models["offered_without_list"] == [FRESH]
    assert {m["model_code"] for m in models["items"]} == {LISTED, RULED}
    empty = svc.film_point_setting(conn, PLANT, FRESH)
    assert (empty["items"], empty["has_setting"]) == ([], False)
    _refused(404, _retire, conn, actor, FRESH, "001ZHOOD")

    out = _add(conn, actor, FRESH, "001ZHOOD", orientation="H")
    assert "first point of the list" in out["operator_message"]
    assert _settings(conn, FRESH) == 0
    assert svc.film_models(conn, PLANT)["offered_without_list"] == []

    _refused(404, svc.film_point_setting, conn, PLANT, UNOFFERED)
    _refused(404, _add, conn, actor, UNOFFERED, "001ZHOOD", orientation="H")


def test_sap_raptor_is_not_offered_so_no_first_list(conn, actor):
    """Read only: every call here is refused before any write."""
    _refused(404, svc.film_point_setting, conn, "SAP", "P703 DBL RAPTOR")
    _refused(404, svc.add_film_point, conn, "SAP", "P703 DBL RAPTOR",
             point_code="001HOOD", counted=True, orientation="H", reason="RO17 test",
             actor=actor, correlation_id=None)
    assert "P703 DBL RAPTOR" not in svc.film_models(conn, "SAP")["offered_without_list"]


# ---------------------------------------------------------------------
# D-RO17-12: tail labels
# ---------------------------------------------------------------------
def _tail(conn, actor, label, retire=False):
    fn = svc.retire_film_tail_label if retire else svc.add_film_tail_label
    return fn(conn, PLANT, LISTED, label=label, reason="RO17 test",
              actor=actor, correlation_id=None)


def test_tail_labels_add_refuse_retire_and_put_back(conn, actor):
    out = _tail(conn, actor, "booth 1")
    assert out["label_norm"] == "BOOTH1" and out["audit_id"] > 0
    assert film_repo.load_film_reference(conn).is_tail_label(PLANT, LISTED, "BOOTH1")
    _refused(409, _tail, conn, actor, "BOOTH1")
    message = _refused(409, _tail, conn, actor, "002zroof")
    assert "002ZROOF" in message and "vanish" in message
    _refused(422, _tail, conn, actor, "   ")

    _tail(conn, actor, "BOOTH1", retire=True)
    assert not film_repo.load_film_reference(conn).is_tail_label(PLANT, LISTED, "BOOTH1"), (
        "the loader skips a retired tail label"
    )
    listed = svc.film_point_setting(conn, PLANT, LISTED)["tail_labels"]
    assert [(t["label_norm"], t["retired_at"] is not None) for t in listed] == [("BOOTH1", True)]
    _refused(409, _tail, conn, actor, "BOOTH1", retire=True)
    _refused(404, _tail, conn, actor, "NOPE", retire=True)

    _tail(conn, actor, "BOOTH1")  # put back: clears the two columns
    assert film_repo.load_film_reference(conn).is_tail_label(PLANT, LISTED, "BOOTH1")


# ---------------------------------------------------------------------
# D-RO17-3 against the loader
# ---------------------------------------------------------------------
def test_an_earlier_label_resolves_and_never_at_another_plant(conn, actor):
    for label in ("Roof LH", "Roof"):  # a rename: the first becomes earlier
        conn.execute(text(
            "INSERT INTO ref_plant_film_point_label (plant_code, model_code, point_code, label, "
            "label_norm, reason) VALUES (:p, :m, '002ZROOF', :l, upper(replace(:l, ' ', '')), 'test')"
        ), {"p": PLANT, "m": LISTED, "l": label})
    film = film_repo.load_film_reference(conn)
    assert film.resolve_point(PLANT, LISTED, "roof lh") == "002ZROOF"
    assert film.resolve_point(PLANT, LISTED, "ROOF") == "002ZROOF"
    assert film.resolve_point(OTHER, LISTED, "Roof LH") is None
    assert film.resolve_point(PLANT, RULED, "Roof LH") is None
    assert svc.film_point_setting(conn, PLANT, LISTED)["items"][1]["label"] == "Roof"
    _retire(conn, actor, LISTED, "002ZROOF")
    assert film_repo.load_film_reference(conn).resolve_point(PLANT, LISTED, "Roof LH") is None, (
        "a retired point's labels do not resolve"
    )
