"""AR05 Task 13: data complete, standard for, no standard, pairing."""

from __future__ import annotations

from datetime import date

from app.domain.assistant.answer import Box
from app.domain.assistant.data_checks import data_complete, no_standard, pairing, standard_for
from app.domain.assistant.readings import Reading
from tests.test_ar03_analysis_report import NOW, data, get  # noqa: F401
from tests.test_ar04_assistant import assert_clean


def _r(domain, day, out=False):
    return Reading(domain, "CLEAR" if domain == "film" else None, "M", "Blue", None, "Vertical", "p", None,
                   date(2026, 2, day), "cf", 1.0, out, "k")


def _b(layer="CLEAR", color="Blue", status="PASS", scope="COLOR", lsl=40.0, usl=None, n=12, orient="Vertical"):
    d = (date(2026, 2, 3),) * n
    return Box("film" if layer else "wavescan", layer, "M", color, orient, status, scope, lsl, usl,
               "µm" if layer else "", (50.0,) * n, d)


def test_data_complete_missing_weeks_and_small_boxes():
    film = [_r("film", d) for d in (2, 9, 23)]  # weeks 1, 2, 4
    ws = [_r("wavescan", d) for d in (2, 9, 16, 23)]
    a = data_complete(film + ws, [_b(n=3), _b(n=2, color="Red"), _b(), _b(color="Grey", n=1), _b(color="Pink", n=4)],
                      date(2026, 2, 20), [1, 2, 3, 4])
    assert_clean(a)
    assert a.headline == "Film week 3 missing; 4 boxes have under 10 readings"
    assert a.proof.endswith("Last upload 2026-02-20")
    ev = a.evidence
    assert ev["kind"] == "weekly_strip" and ev["columns"] == ["Week", "Readings", "Out", "Flag"]
    assert ["Week 3 · Film", 0, 0, "missing"] in ev["rows"] and ["Week 3 · Wave Scan", 1, 0, ""] in ev["rows"]


def test_data_complete_wording_and_clear():
    one = data_complete([_r("film", 2)], [_b(n=3)], None, [1, 2, 3])
    assert one.headline == "Film weeks 2 and 3 missing; 1 box has under 10 readings" and "Last upload" not in one.proof
    ok = data_complete([_r("film", 2), _r("film", 9)], [_b()], None, [1, 2])
    assert ok.status == "all_clear" and ok.headline == "This month's data looks complete."
    assert data_complete([], [], None, [1]).status == "not_enough"


def test_standard_for_failing_layer_and_cf():
    boxes = [_b("CLEAR", status="PASS", lsl=40), _b("BASE", status="FAIL", lsl=15, usl=30.04, scope="PLANT"),
             _b(None, status="PASS", lsl=55.0, scope=None), _b("BASE", orient="Horizontal", lsl=15, usl=30.04)]
    a = standard_for("Blue", boxes, {boxes[1].key: 22.5}, "2026-02")
    assert_clean(a)
    assert a.headline == ("Blue: Base Lo 15 µm (plant rule), Hi 30 µm (Vertical shown; other orientations "
                          "or models differ); CF minimum 55")
    ev = a.evidence
    assert ev["kind"] == "limit_card"
    assert {"label": "Base V", "value": "Lo 15 µm · Hi 30 µm · Target 22.5 µm · plant rule"} in ev["card"]
    assert {"label": "CF V", "value": "Minimum 55"} in ev["card"]
    clear = standard_for("Blue", [_b("CLEAR")], {}, "2026-02")
    assert clear.headline == "Blue: Clear Lo 40 µm (colour rule), no Hi"
    miss = standard_for("Red", boxes, {}, "2026-02")
    assert miss.status == "not_enough" and miss.headline == "No readings for Red in February 2026 with these filters."


def test_no_standard_and_pairing():
    bare = [_b(status=None, scope=None), _b(status=None, scope="COLOR", color="Red"), _b()]
    a = no_standard(bare)
    assert_clean(a)
    assert a.headline == "2 boxes not graded — M Blue · Clear · V has no rule"
    assert a.evidence["rows"] == [["M Blue · Clear · V", "No standard"], ["M Red · Clear · V", "Not graded"]]
    assert no_standard(bare[:1]).headline.startswith("1 box not graded")
    assert no_standard([_b()]).headline == "Every box has a standard this month."
    p = pairing({"paired_cars": 6})
    assert_clean(p)
    assert p.headline == "6 paired cars; layer checks stay exploratory until about 100"
    assert p.evidence["kind"] == "stat" and p.evidence["card"][1]["value"] == "about 100"
    assert pairing({"paired_cars": 120}).headline == "120 paired cars; layer checks can be trusted"


def test_standard_for_differ_hi_only_and_cf_orientations():
    same = standard_for("Blue", [_b("CLEAR"), _b("CLEAR", orient="Horizontal")], {}, "2026-02")
    assert same.headline == "Blue: Clear Lo 40 µm (colour rule), no Hi"
    hi_only = standard_for("Blue", [_b("BASE", lsl=None, usl=30.0)], {}, "2026-02")
    assert hi_only.headline == "Blue: Base no Lo (colour rule), Hi 30 µm"
    none = standard_for("Blue", [_b("BASE", lsl=None, usl=None, status=None)], {}, "2026-02")
    assert none.headline == "Blue: Base has no standard"
    cf = standard_for("Blue", [_b(None, lsl=55.0), _b(None, lsl=56.0, orient="Horizontal")], {}, "2026-02")
    assert cf.headline == "Blue: CF minimum V 55, H 56"
    bx = _b("CLEAR", scope="COLOR")
    t = standard_for("Blue", [bx], {bx.key: 45.0}, "2026-02")
    assert t.evidence["card"] == [{"label": "Clear V", "value": "Lo 40 µm · no Hi · Target 45 µm · colour rule"}]


def test_pairing_proof_and_caveat():
    p = pairing({"paired_cars": 6})
    assert p.proof == "All months, whole plant; the month, model and colour filters don't apply."
    assert p.method["caveats"] == ["Layer checks stay exploratory until about 100 paired cars."]


def test_runners_answer_on_fixture(data):
    ask = "analysis/ask"
    heads = {t: get(data, ask, topic=t, month=NOW)["decision"]["headline"]
             for t in ("data_complete", "no_standard", "pairing")}
    assert heads["pairing"].endswith("paired cars; layer checks stay exploratory until about 100")
    assert heads["no_standard"] == "Every box has a standard this month." or "not graded" in heads["no_standard"]
    assert heads["data_complete"] == "This month's data looks complete." or "missing" in heads["data_complete"] \
        or "under 10 readings" in heads["data_complete"]
    pick = get(data, ask, topic="standard_for", month=NOW)
    colour = pick["slot"]["choices"][0]["value"]
    body = get(data, ask, topic="standard_for", month=NOW, colour=colour)
    assert body["status"] == "answer" and body["decision"]["headline"].startswith(f"{colour}: ")
    assert body["evidence"]["kind"] == "limit_card"


def test_out_of_scope_plant_is_not_read(monkeypatch):
    from app.services import assistant as svc
    from app.services.assistant import AskContext
    called = []
    monkeypatch.setattr(svc.pairing_service, "read", lambda *a: called.append("pairing") or {"paired_cars": 1})
    monkeypatch.setattr(svc.landing_repo, "latest_files", lambda *a: called.append("files") or [])

    class Month:
        readings = [_r("film", 2)]
        boxes: list = []

    def ctx(scope):
        return AskContext(None, "FTM", scope, "2026-02", "2026-01", [], "both", [], [], lambda m: Month())

    out = svc.RUNNERS["pairing"](ctx(["SAP"]), {})
    assert out.status == "not_enough" and out.headline == "You can't see FTM."
    svc.RUNNERS["data_complete"](ctx(["SAP"]), {})
    assert called == []
    assert svc.RUNNERS["pairing"](ctx(["FTM"]), {}).status == "answer"
    svc.RUNNERS["data_complete"](ctx(None), {})
    assert called == ["pairing", "files"]
