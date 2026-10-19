"""RO17 -- point labels, Wave Scan point editing and the aliases screen (C1a).

Spec section 4, the backend items this part owns:

* the label resolves **last** and only at its own plant x model (pure);
* rename keeps one series under one code; an earlier label still resolves;
* each D-RO17-4 clash is refused;
* Wave Scan restore works, and is refused on a clash or a taken number;
* a first list on an offered model; refused on one not offered;
* add with ``counted_in_completeness`` reports the incomplete cars, false
  keeps today's ``is_extra``; the impact read persists nothing;
* alias retire refused when it would orphan stored spellings; the global
  alias is read-only;
* ``app_rw`` holds no UPDATE / DELETE beyond the granted columns.

**Zero residue.** Every DB test runs as ``app_rw`` inside one transaction
that is always rolled back (`tx`), calling the services the routes call.
Nothing commits. SAP P703 DBL RAPTOR (not offered) is only read.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from sqlalchemy import create_engine, text

from app.domain.cleaner import Cleaner
from app.domain.references import ReferenceData
from app.domain.ws_plant_gold import gold_key
from app.services import point_labels as labels
from app.services import ws_points as ws
from app.services.workbooks import WorkbookError

PLANT, MODEL = "FTM", "P703 DBL RAPTOR"
REASON = "RO17 test, rolled back"


# =====================================================================
# helpers
# =====================================================================
@pytest.fixture(scope="module")
def engine(app_dsn):
    found = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(app_dsn))
    yield found
    found.dispose()


@contextmanager
def tx(engine):
    """One transaction, always rolled back."""
    with engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()


def live(conn, plant=PLANT, model=MODEL) -> list[dict]:
    return ws.ws_point_list(conn, plant, model)["items"]


def resolves(conn, plant, model, raw):
    return labels.resolver(conn, "wavescan", plant)(model, raw)


def rename(conn, code, label, *, plant=PLANT, model=MODEL, domain="wavescan"):
    return labels.rename(
        conn, domain, plant, model, code=code, label=label, reason=REASON,
        actor=None, correlation_id=None,
    )


def refused(status, fn, *args, **kwargs) -> str:
    with pytest.raises(WorkbookError) as exc:
        fn(*args, **kwargs)
    assert exc.value.status_code == status, exc.value.detail
    assert exc.value.detail.endswith("Nothing was changed."), exc.value.detail
    return exc.value.detail


def fact(conn, zone_code, tolerance, raw_label):
    """One COMMITTED synthetic reading at FTM / Raptor whose raw label is ``raw_label``."""
    digest = hashlib.sha256(f"RO17:{uuid.uuid4().hex}".encode()).hexdigest()
    load_id = conn.execute(text(
        """
        INSERT INTO load_batch (source_file, source_sheet, plant_code, file_hash,
            status, rows_in_file, rows_loaded, rows_duplicate, rows_rejected,
            rows_quarantine, raw_store_key, finished_at, notes)
        VALUES ('RO17 test.xlsx', 'Sheet1', :p, :h, 'COMMITTED', 1, 1, 0, 0, 0,
                :k, now(), 'RO17 fixture, rolled back')
        RETURNING load_id
        """
    ), {"p": PLANT, "h": digest, "k": f"wavescan/raw/{digest}"}).scalar_one()
    colour = conn.execute(text(
        "SELECT color_name FROM ref_plant_color WHERE plant_code = :p AND is_offered "
        "ORDER BY color_name LIMIT 1"
    ), {"p": PLANT}).scalar_one()
    conn.execute(text(
        """
        INSERT INTO wavescan (measured_date, plant, model, checkzone, color,
            tolerance_group, paintline, serial_no, lw, sw, cf, doi, du, wa, wb,
            wc, wd, we, b, load_id, source_sheet, source_row, src_zone_text)
        VALUES ('2099-01-10', :p, :m, :z, :c, :t, 'BOOTH1', :s, 1, 2, 60, 80, 3,
                4, 5, 6, 7, 8, 0, :l, 'Sheet1', 2, :raw)
        """
    ), {"p": PLANT, "m": MODEL, "z": zone_code, "c": colour, "t": tolerance,
        "s": f"RO17-{load_id}", "l": load_id, "raw": raw_label})


# =====================================================================
# pure: resolution order (D-RO17-3)
# =====================================================================
def _ref(**extra) -> ReferenceData:
    gold = {gold_key(z): z for z in ("RRHOOD", "RFHOOD", "LFDOOR")}
    return ReferenceData(
        plant_gold={("P1", "M1"): gold},
        model_zone=frozenset({("M1", "RRHOOD"), ("M1", "RFHOOD"), ("M1", "LFDOOR")}),
        plant_ws_label={
            ("P1", "M1", "bonnet rear"): "RRHOOD",
            ("P1", "M1", "rfhood"): "RRHOOD",       # never reached: gold answers first
            ("P1", "M1", "ghost"): "NOTGOLD",        # not on this list: never answers
            ("P2", "M2", "lid"): "LID",              # a pair with no gold list
        },
        **extra,
    )


def test_label_resolves_last_and_only_at_its_own_plant_and_model():
    cleaner = Cleaner(_ref(), ("P1", "P2"), expected_plant="P1")
    assert cleaner.resolve_checkzone("P1", "M1", "Bonnet Rear") == "RRHOOD"
    assert cleaner.resolve_checkzone("P1", "M1", "BONNET REAR ") == "RRHOOD"
    # Everything that resolves today still wins: the gold code itself.
    assert cleaner.resolve_checkzone("P1", "M1", "RFHOOD") == "RFHOOD"
    # Only onto this list's gold.
    assert cleaner.resolve_checkzone("P1", "M1", "ghost") is None
    # Never at another plant or on another model.
    assert cleaner.resolve_checkzone("P2", "M1", "Bonnet Rear") is None
    assert cleaner.resolve_checkzone("P1", "M2", "Bonnet Rear") is None
    # The no-gold branch reads it last too.
    assert cleaner.resolve_checkzone("P2", "M2", "Lid") == "LID"


def test_without_labels_every_result_is_unchanged():
    """Labels only answer what returned None before: compare with and without."""
    bare = Cleaner(ReferenceData(**{
        k: getattr(_ref(), k) for k in ("plant_gold", "model_zone")
    }), ("P1",), expected_plant="P1")
    full = Cleaner(_ref(), ("P1",), expected_plant="P1")
    for raw in ("RRHOOD", "rfhood", "01LFDOOR", "LFDOOR", "x", "ghost", "Bonnet Rear"):
        before = bare.resolve_checkzone("P1", "M1", raw)
        if before is not None:
            assert full.resolve_checkzone("P1", "M1", raw) == before


# =====================================================================
# rename (D-RO17-6), earlier labels (D-RO17-3)
# =====================================================================
def test_rename_keeps_one_code_and_every_earlier_label_resolves(engine):
    with tx(engine) as conn:
        # RO17 Part F labelled FTM's list: read the current label, not the code.
        a, was = live(conn)[0]["zone_code"], live(conn)[0]["label"]
        stored = conn.execute(text(
            "SELECT count(*), max(measurement_id) FROM wavescan "
            "WHERE plant = :p AND model = :m AND checkzone = :z"
        ), {"p": PLANT, "m": MODEL, "z": a}).one()

        first = rename(conn, a, "RO17 Bonnet")
        second = rename(conn, a, "RO17 Hood Front")
        assert (first["previous_label"], second["previous_label"]) == (was, "RO17 Bonnet")
        assert second["label"] == "RO17 Hood Front" and second["audit_id"] > 0
        assert labels.current_labels(conn, "wavescan", PLANT, MODEL)[a] == "RO17 Hood Front"
        assert next(p for p in live(conn) if p["zone_code"] == a)["label"] == "RO17 Hood Front"

        # One code, one series: no fact moved, nothing new under another code.
        assert conn.execute(text(
            "SELECT count(*), max(measurement_id) FROM wavescan "
            "WHERE plant = :p AND model = :m AND checkzone = :z"
        ), {"p": PLANT, "m": MODEL, "z": a}).one() == stored

        # Current and earlier labels both load onto the code, here only.
        assert resolves(conn, PLANT, MODEL, "ro17 hood front") == a
        assert resolves(conn, PLANT, MODEL, "RO17 BONNET") == a
        assert resolves(conn, PLANT, "P703 DBL RANGER", "RO17 Bonnet") is None
        assert resolves(conn, "SAP", MODEL, "RO17 Bonnet") is None  # read only

        # The aliases screen lists the earlier one, not the current one.
        earlier = [
            i for i in labels.aliases(conn, PLANT, "wavescan", MODEL)["items"]
            if i["kind"] == "earlier_label"
        ]
        assert {i["spelling"] for i in earlier} >= {a, was, "RO17 Bonnet"}
        assert "RO17 Hood Front" not in {i["spelling"] for i in earlier}


def test_rename_refusals(engine):
    with tx(engine) as conn:
        points = live(conn)
        a, b = points[0]["zone_code"], points[1]["zone_code"]
        refused(404, rename, conn, "NO SUCH POINT", "x")
        refused(409, rename, conn, a, points[0]["label"])     # same as now
        # (a) another live point's code, by the normaliser and by gold_key
        assert "code of point" in refused(409, rename, conn, a, f"  {b.lower()} ")
        # (b) another live point's label, current or earlier
        rename(conn, b, "RO17 Lid")
        assert "label" in refused(409, rename, conn, a, "ro17 lid")
        rename(conn, b, "RO17 Lid Two")
        assert "earlier label" in refused(409, rename, conn, a, "RO17 LID")
        # (c) a spelling that resolves today to another point
        spelling, target = next(
            (i["spelling"], i["code"])
            for i in labels.aliases(conn, PLANT, "wavescan", MODEL)["items"]
            if i["kind"] in ("zone_map", "global_alias") and i["live"]
            and resolves(conn, PLANT, MODEL, i["spelling"]) == i["code"]
        )
        other = next(p["zone_code"] for p in points if p["zone_code"] != target)
        assert "already loads onto" in refused(409, rename, conn, other, spelling)
        # Per plant: the same word at another plant is fine.
        aat = live(conn, "AAT", "P703 DBL RANGER")[0]["zone_code"]
        assert rename(conn, aat, "RO17 Lid", plant="AAT", model="P703 DBL RANGER")["label_id"]
        # A retired point: restore first.
        last = points[-1]["zone_code"]
        ws.retire_ws_point(conn, PLANT, MODEL, zone_code=last, reason=REASON,
                           actor=None, correlation_id=None)
        assert "restore it first" in refused(409, rename, conn, last, "RO17 Gone")


# =====================================================================
# restore (D-RO17-9)
# =====================================================================
def test_ws_restore_and_its_refusals(engine):
    with tx(engine) as conn:
        points = live(conn)
        a, b, last = points[0], points[1], points[-1]
        retire = lambda code: ws.retire_ws_point(  # noqa: E731
            conn, PLANT, MODEL, zone_code=code, reason=REASON, actor=None,
            correlation_id=None,
        )
        restore = lambda code: ws.restore_ws_point(  # noqa: E731
            conn, PLANT, MODEL, zone_code=code, reason=REASON, actor=None,
            correlation_id=None,
        )
        refused(409, restore, a["zone_code"])                  # live already
        refused(404, restore, "NO SUCH POINT")

        retire(a["zone_code"])
        done = restore(a["zone_code"])
        assert done["point_no"] == a["point_no"] and done["label"] == a["label"]
        assert a["zone_code"] in {p["zone_code"] for p in live(conn)}
        assert resolves(conn, PLANT, MODEL, a["zone_code"]) == a["zone_code"]

        # Its label is taken by another point meanwhile.
        rename(conn, a["zone_code"], "RO17 Lid")
        retire(a["zone_code"])
        rename(conn, b["zone_code"], "RO17 LID")
        assert "label" in refused(409, restore, a["zone_code"])

        # D-RO19-3: its number being held no longer refuses the restore. 0049
        # dropped the live-number unique index precisely so a restored identity
        # keeps its own number; only a code or label clash still refuses.
        retire(last["zone_code"])
        added = ws.add_ws_point(
            conn, PLANT, MODEL, zone_code="RO17 TEST DOOR", counted=True,
            reason=REASON, actor=None, actor_name="test", correlation_id=None,
        )
        assert added["point_no"] == last["point_no"]
        back = restore(last["zone_code"])
        assert back["point_no"] == last["point_no"], "it keeps its own number"
        assert {"RO17 TEST DOOR", last["zone_code"]} <= {p["zone_code"] for p in live(conn)}


# =====================================================================
# first list (D-RO17-10)
# =====================================================================
def test_first_list_only_on_an_offered_wave_scan_model(engine):
    with tx(engine) as conn:
        # SAP P703 DBL RAPTOR is not offered: read only, never written.
        assert "P703 DBL RAPTOR" not in ws.ws_models(conn, "SAP")["offered_without_list"]
        # FVL has no ref_plant_model row for Raptor: not offered, still a 404.
        for fn in (
            lambda: ws.ws_point_list(conn, "FVL", MODEL),
            lambda: ws.add_ws_point(conn, "FVL", MODEL, zone_code="RO17 TEST DOOR",
                                    counted=True, reason=REASON, actor=None,
                                    actor_name="t", correlation_id=None),
        ):
            with pytest.raises(WorkbookError) as exc:
                fn()
            assert exc.value.status_code == 404
        # Offered but no Wave Scan model (wavescan_ok false): 404 too.
        film_only = conn.execute(text(
            "SELECT pm.model_code FROM ref_plant_model pm JOIN ref_model m "
            "USING (model_code) WHERE pm.plant_code = 'FTM' AND pm.is_offered "
            "AND NOT m.wavescan_ok LIMIT 1"
        )).scalar()
        if film_only:
            with pytest.raises(WorkbookError) as exc:
                ws.ws_point_list(conn, "FTM", film_only)
            assert exc.value.status_code == 404

        conn.execute(text(
            "INSERT INTO ref_plant_model (plant_code, model_code, is_offered) "
            "VALUES ('FVL', :m, true)"
        ), {"m": MODEL})
        assert MODEL in ws.ws_models(conn, "FVL")["offered_without_list"]
        empty = ws.ws_point_list(conn, "FVL", MODEL)
        assert empty["items"] == [] and empty["retired_items"] == []
        first = ws.add_ws_point(
            conn, "FVL", MODEL, zone_code="RO17 TEST DOOR", counted=True,
            reason=REASON, actor=None, actor_name="t", correlation_id=None,
        )
        assert first["point_no"] == 1 and "first point" in first["operator_message"]
        assert [p["label"] for p in live(conn, "FVL", MODEL)] == ["RO17 TEST DOOR"]
        assert MODEL not in ws.ws_models(conn, "FVL")["offered_without_list"]


# =====================================================================
# counted_in_completeness (D-RO17-7)
# =====================================================================
def _is_extra(conn, code):
    return conn.execute(text(
        "SELECT is_extra FROM ref_plant_ws_point WHERE plant_code = :p "
        "AND model_code = :m AND zone_code = :z"
    ), {"p": PLANT, "m": MODEL, "z": code}).scalar()


def test_add_counted_in_completeness_reports_cars_and_false_keeps_extra(engine):
    add = lambda code, counted_in, admin=True: ws.add_ws_point(  # noqa: E731
        conn, PLANT, MODEL, zone_code=code, counted=True, reason=REASON,
        actor=None, actor_name="t", correlation_id=None,
        counted_in_completeness=counted_in, admin=admin,
    )
    with tx(engine) as conn:
        fact(conn, live(conn)[0]["zone_code"], live(conn)[0]["tolerance_group"], "x")
        now = conn.execute(text(
            "SELECT count(*) FROM v_car_completeness WHERE plant = :p AND model = :m "
            "AND completeness = 'INCOMPLETE'"
        ), {"p": PLANT, "m": MODEL}).scalar_one()

        refused(403, add, "RO17 TEST DOOR", True, admin=False)

        kept = add("RO17 TEST DOOR", False)
        assert kept["incomplete_cars"] is None and _is_extra(conn, "RO17 TEST DOOR") is True

        impact = ws.completeness_impact(conn, PLANT, MODEL, zone_code="RO17 TEST FENDER")
        assert ws.repo.point_row(conn, PLANT, MODEL, "RO17 TEST FENDER") is None
        assert ws.repo.checkzone(conn, "RO17 TEST FENDER") is None
        assert impact["cars_incomplete_now"] == now
        assert impact["cars_become_incomplete"] >= 1  # at least the synthetic car

        counted = add("RO17 TEST FENDER", True)
        assert _is_extra(conn, "RO17 TEST FENDER") is False
        assert counted["incomplete_cars"] == impact["cars_become_incomplete"]
        assert conn.execute(text(
            "SELECT count(*) FROM v_car_completeness WHERE plant = :p AND model = :m "
            "AND completeness = 'INCOMPLETE'"
        ), {"p": PLANT, "m": MODEL}).scalar_one() == now + counted["incomplete_cars"]


# =====================================================================
# aliases screen (D-RO17-13)
# =====================================================================
def retire_alias(conn, kind, alias_id):
    return labels.retire_alias(
        conn, PLANT, "wavescan", MODEL, kind=kind, alias_id=alias_id,
        reason=REASON, actor=None, correlation_id=None,
    )


def test_alias_retire_refusals_and_orphan_guard(engine):
    with tx(engine) as conn:
        items = labels.aliases(conn, PLANT, "wavescan", MODEL)["items"]
        glob = next((i for i in items if i["kind"] == "global_alias"), None)
        if glob is not None:
            assert glob["shared"] and not glob["retirable"]
            assert "shared by all plants" in refused(409, retire_alias, conn, "global_alias", glob["alias_id"])

        a = live(conn)[0]
        rename(conn, a["zone_code"], "RO17 Bonnet")
        rename(conn, a["zone_code"], "RO17 Hood Front")
        rows = {r["label"]: r for r in labels.repo.label_rows(conn, "wavescan", PLANT, MODEL)}
        assert "rename it instead" in refused(
            409, retire_alias, conn, "earlier_label", str(rows["RO17 Hood Front"]["label_id"])
        )

        # A stored reading wrote the earlier spelling: retiring it would orphan it.
        fact(conn, a["zone_code"], a["tolerance_group"], "RO17 Bonnet")
        bonnet = str(rows["RO17 Bonnet"]["label_id"])
        listed = next(i for i in labels.aliases(conn, PLANT, "wavescan", MODEL)["items"]
                      if i["alias_id"] == bonnet)
        assert listed["stored_facts"] == 1
        assert "1 stored reading(s)" in refused(409, retire_alias, conn, "earlier_label", bonnet)
        assert resolves(conn, PLANT, MODEL, "RO17 Bonnet") == a["zone_code"]

        # One no reading wrote: retired, and it stops resolving; the row stays.
        rename(conn, a["zone_code"], "RO17 Hood Three")
        front = str(rows["RO17 Hood Front"]["label_id"])
        done = retire_alias(conn, "earlier_label", front)
        assert done["audit_id"] > 0
        assert resolves(conn, PLANT, MODEL, "RO17 Hood Front") is None
        refused(409, retire_alias, conn, "earlier_label", front)    # already retired


def test_film_aliases_read(engine):
    with tx(engine) as conn:
        found = labels.aliases(conn, "SAP", "film", "P703 DBL RANGER")
        kinds = {i["kind"] for i in found["items"]}
        # RO18 (B5): plus the uploaders' "Not a point of this list" answers.
        assert kinds <= {"film_alias", "location_map", "earlier_label", "not_a_point"}
        assert all(not i["shared"] for i in found["items"])


# =====================================================================
# grants (app_rw: no UPDATE / DELETE beyond the granted columns)
# =====================================================================
@pytest.mark.parametrize(
    "table, allowed",
    [
        ("ref_plant_ws_point_label", "retired_at"),
        ("ref_plant_film_point_label", "retired_at"),
        ("ref_plant_zone_map", "retired_at"),
        ("ref_film_point_alias", "retired_at"),
        ("ref_film_location_map", "retired_at"),
    ],
)
def test_app_role_updates_only_the_retire_columns(app_conn, table, allowed):
    with app_conn.cursor() as cur:
        cur.execute("SAVEPOINT ok")
        cur.execute(f"UPDATE {table} SET {allowed} = now() WHERE false")
        cur.execute("RELEASE SAVEPOINT ok")
        for sql in (
            f"UPDATE {table} SET plant_code = plant_code WHERE false",
            f"DELETE FROM {table} WHERE false",
        ):
            cur.execute("SAVEPOINT s")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
            cur.execute("ROLLBACK TO SAVEPOINT s")
    assert os.environ.get("T01_APP_DSN")
