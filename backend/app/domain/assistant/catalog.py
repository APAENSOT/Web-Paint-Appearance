"""AR05 question registry: the single source of truth for the assistant's menu,
keywords, slots and graph kinds (spec §3, §5). Pure data; no SQL.

The 32 ids are spec §5's 31 plus AR04's ``changes`` (kept under its AR04 id).
AR04 ids keep their AR04 keywords.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotSpec:
    name: str  # the /analysis/ask query param that carries it
    kind: str  # month model colour colour_family layer metric band box point car side orient plant
    prompt: str
    prompt_th: str
    required: bool = True  # optional slots fall back to the filter bar or the topic's own default


@dataclass(frozen=True)
class Question:
    id: str
    group: str  # month compare problem trend appearance data
    label: str
    label_th: str
    keywords: tuple[str, ...]
    keywords_th: tuple[str, ...]
    slots: tuple[SlotSpec, ...]
    graph: str
    example: str


MONTH = SlotSpec("month", "month", "Which month?", "เดือนไหน?", required=False)
MONTH2 = SlotSpec("month2", "month", "Compare with which month?", "เทียบกับเดือนไหน?")
METRIC = SlotSpec("metric", "metric", "Which layer or Wave Scan metric?", "ชั้นหรือค่า Wave Scan ไหน?")
MODEL = SlotSpec("model", "model", "Which model?", "รุ่นไหน?")
COLOUR = SlotSpec("colour", "colour", "Which colour?", "สีไหน?")
LAYER = SlotSpec("layer", "layer", "Which layer?", "ชั้นไหน?")
BAND = SlotSpec("metric", "band", "Which Wave Scan band?", "แบนด์ Wave Scan ไหน?")  # du..we and CF only
BOX = SlotSpec("target", "box", "Which box?", "กล่องไหน?")
BOX_OPTIONAL = SlotSpec("target", "box", "Which box?", "กล่องไหน?", required=False)
PLANT2 = SlotSpec("plant2", "plant", "Compare with which plant?", "เทียบกับโรงงานไหน?")


def _pair(kind: str, what: str, what_th: str, one: str) -> tuple[SlotSpec, SlotSpec]:
    return (SlotSpec("a", kind, f"Which two {what}?", f"เทียบ{what_th}ไหนกับ{what_th}ไหน?"),
            SlotSpec("b", kind, f"Which {one} to compare with?", f"เทียบกับ{what_th}ไหน?"))


def _q(id, group, label, label_th, keywords, keywords_th, slots, graph, example) -> Question:
    return Question(id, group, label, label_th, tuple(keywords), tuple(keywords_th), tuple(slots), graph, example)


CATALOG: tuple[Question, ...] = (
    # ---- This month
    _q("summary", "month", "Summarize this month", "สรุปเดือนนี้",
       ("summary", "overview", "month"), ("สรุป", "ภาพรวม"), (), "bar",
       "Fix first: Ranger Desert Island Blue · Primer · V"),
    _q("colour_report", "month", "Colour report", "รายงานสี",
       ("colour report", "color report"), ("รายงานสี",), (MONTH,), "heatmap",
       "3 of 11 colours need action; start with Desert Island Blue (Primer)"),
    _q("model_report", "month", "Model report", "รายงานรุ่น",
       ("model report", "by model"), ("รายงานรุ่น",), (MODEL,), "heatmap",
       "Raptor: Clear is the only failing layer (12 of 14 boxes)"),
    _q("went_well", "month", "What went well?", "อะไรดีขึ้น",
       ("went well", "improved", "better"), ("ดีขึ้น",), (), "bar",
       "Command Grey CF improved for real (+2.1); now Pass"),
    _q("weekly", "month", "Week by week", "รายสัปดาห์",
       ("week by week", "weekly", "which week"), ("สัปดาห์",), (), "weekly_strip",
       "31 of 44 out readings were in week 3"),
    # ---- Compare
    _q("changes", "compare", "What changed since last month?", "อะไรเปลี่ยนจากเดือนก่อน",
       ("change", "last month", "compare", "vs"), ("เปลี่ยน", "เดือนก่อน", "เทียบ"), (), "shift",
       "6 boxes got worse (2 real shifts)"),
    _q("compare_months", "compare", "Compare two months", "เทียบสองเดือน",
       ("compare months", "month vs month"), ("เทียบเดือน",), (MONTH, MONTH2), "shift",
       "6 boxes worse (2 real shifts)"),
    _q("compare_models", "compare", "Compare models", "เทียบรุ่น",
       ("compare models", "model vs model"), ("เทียบรุ่น",), (*_pair("model", "models", "รุ่น", "model"), METRIC),
       "boxplot_pair", "Raptor is 4.1 µm thinner on Clear than Ranger — real difference"),
    _q("compare_colours", "compare", "Compare colours", "เทียบสี",
       ("compare colours", "compare colors"), ("เทียบสี",),
       (*_pair("colour", "colours", "สี", "colour"), METRIC), "boxplot_pair",
       "No real difference on Base (Δ 0.3 µm)"),
    _q("compare_orient", "compare", "Horizontal vs vertical", "แนวนอนเทียบแนวตั้ง",
       ("horizontal", "vertical"), ("แนวนอน", "แนวตั้ง"), (COLOUR, METRIC), "boxplot_pair",
       "Vertical is 3.2 µm thinner on Base — real difference"),
    _q("compare_sides", "compare", "Left vs right side", "ซ้ายเทียบขวา",
       ("left", "right"), ("ซ้าย", "ขวา"), (METRIC,), "mirrored_bar",
       "Left doors run 2.8 µm thinner on Clear — real difference"),
    _q("compare_families", "compare", "Compare colour families", "เทียบกลุ่มสี",
       ("family", "families"), ("กลุ่มสี",), (METRIC,), "boxplot_group",
       "Dark metallics drive 8 of 11 Clear fails"),
    _q("compare_cars", "compare", "Compare two cars", "เทียบรถสองคัน",
       ("compare cars", "car vs car"), ("เทียบรถ",), _pair("car", "cars", "รถคัน", "car"), "point_bars",
       "Car B is under Lo at 6 of 40 points, all on the roof"),
    _q("compare_plants", "compare", "Compare plants", "เทียบโรงงาน",
       ("compare plants", "other plant"), ("โรงงาน",), (PLANT2, METRIC), "boxplot_pair",
       "AAT Primer runs 5.0 µm higher on U704 — real difference"),
    # ---- Find the problem
    _q("colours", "problem", "Which colours to improve?", "สีไหนต้องปรับปรุง",
       ("colour", "color", "improve"), ("สี",), (), "bar",
       "Ranger Desert Island Blue · Primer · V is the weakest"),
    _q("points", "problem", "Which points to improve?", "จุดไหนต้องปรับปรุง",
       ("point", "panel", "zone", "where"), ("จุด", "ตำแหน่ง", "แผง"), (), "bar",
       "R-12 is a repeat problem: out on 7 of 8 cars"),
    _q("why_failing", "problem", "Why is it failing?", "ทำไมถึงไม่ผ่าน",
       ("why", "failing", "cause"), ("ทำไม", "สาเหตุ"), (BOX,), "breakdown",
       "Concentrated at R-12 and R-14 left, in week 3, on 4 cars"),
    _q("cars_or_process", "problem", "Few cars or whole process?", "รถบางคันหรือทั้งกระบวนการ",
       ("few cars", "whole process", "process"), ("กระบวนการ",), (BOX_OPTIONAL,), "car_bars",
       "Whole process: 14 of 15 cars have readings out"),
    _q("worst_cars", "problem", "Which cars were worst?", "รถคันไหนแย่ที่สุด",
       ("worst car", "which car"), ("แย่ที่สุด",), (), "car_bars",
       "Car 2005924: 31 points out — open its history"),
    _q("centre_or_spread", "problem", "Centring or spread?", "ค่ากลางหรือการกระจาย",
       ("centring", "centering", "spread"), ("ค่ากลาง", "การกระจาย"), (BOX,), "distribution",
       "Spread: mean centred, σ 4.2 µm vs 2.1 µm last month"),
    # ---- Trend and risk
    _q("trend", "trend", "Is it trending?", "มีแนวโน้มไหม",
       ("trend", "drift", "worse", "getting"), ("แนวโน้ม", "แย่ลง"), (BOX_OPTIONAL,), "trend",
       "Ranger Blue Primer V: drifting down 0.30 µm/day; reaches Lo in about 4 days"),
    _q("next_month_risk", "trend", "Next month's risk", "ความเสี่ยงเดือนหน้า",
       ("next month", "risk", "if nothing changes"), ("เดือนหน้า", "ความเสี่ยง"), (), "bar",
       "If nothing changes, Race Red Clear is next: about 6 of the next 30 cars out"),
    _q("history", "trend", "Last 6 months", "ย้อนหลัง 6 เดือน",
       ("history", "last 6 months", "six months"), ("ย้อนหลัง",), (BOX,), "trend_monthly",
       "Failed 3 months running — not a one-off"),
    _q("recurring", "trend", "Recurring problems", "ปัญหาที่เกิดซ้ำ",
       ("recurring", "keeps failing", "repeat"), ("ซ้ำ",), (), "grid",
       "4 boxes failed in 3 of the last 4 months"),
    # ---- Appearance and layers
    _q("bands", "appearance", "Which layer to check?", "ควรตรวจชั้นไหน",
       ("band", "layer"), ("ชั้น", "เลเยอร์"), (), "bar",
       "Wc up on Ranger White (+2.0) → check Base"),
    _q("appearance_profile", "appearance", "Appearance profile", "โปรไฟล์ลักษณะผิว",
       ("appearance", "profile", "wave"), ("ลักษณะผิว",), (COLOUR,), "spectrum",
       "Long waves high (Wd/We) → check Primer, then substrate"),
    _q("cf_drivers", "appearance", "What drives CF down?", "อะไรทำให้ CF ต่ำ",
       ("cf", "driving", "drives"), ("ปัจจัย", "cf ต่ำ"), (BOX,), "bar",
       "CF loss tracks Wb and Wc (ρ −0.7, −0.6)"),
    _q("layer_vs_band", "appearance", "Thickness vs appearance", "ความหนากับลักษณะผิว",
       ("thickness", "affect"), ("ความหนา",), (LAYER, BAND), "scatter",
       "Thicker Clear → lower Wa (ρ −0.6, n 6, exploratory)"),
    # ---- Data and standards
    _q("data_complete", "data", "Is the data complete?", "ข้อมูลครบไหม",
       ("complete", "missing data", "data"), ("ข้อมูลครบ", "ขาดข้อมูล"), (), "weekly_strip",
       "Film week 3 missing; 4 boxes have under 10 readings"),
    _q("standard_for", "data", "Which standard applies?", "ใช้มาตรฐานอะไร",
       ("standard", "limit", "spec"), ("มาตรฐาน",), (COLOUR,), "limit_card",
       "Clear: Lo 40 µm (colour rule), no Hi; CF minimum 55"),
    _q("no_standard", "data", "Boxes with no standard", "กล่องที่ไม่มีมาตรฐาน",
       ("no standard", "not graded"), ("ไม่มีมาตรฐาน",), (), "table",
       "3 boxes not graded — Arctic White Base V has no rule"),
    _q("pairing", "data", "Cars on both instruments", "รถที่วัดทั้งสองเครื่อง",
       ("both instruments", "paired", "pairing"), ("ทั้งสองเครื่อง", "จับคู่"), (), "stat",
       "6 paired cars; layer checks stay exploratory until about 100"),
)

_BY_ID = {q.id: q for q in CATALOG}
IDS = tuple(_BY_ID)


def by_id(id: str) -> Question:
    return _BY_ID[id]
