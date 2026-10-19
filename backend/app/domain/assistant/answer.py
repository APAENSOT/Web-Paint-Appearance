"""AR04 answer model: the shape every topic answer shares, plus severity.

Pure: no SQL, no network, no AI. Status is copied from the overview, never re-graded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from app.domain.report_stats import mean_sd
from app.domain.report_summary import LAYER_WORD

MIN_BOX_N = 10
MIN_TREND_DATES = 5
MIN_POINT_OUT = 3
POINT_P = 0.01
SHIFT_P = 0.05
SHIFT_SIGMA = 0.5
RISK_CARS = 30
RISK_DAYS_AHEAD = 7
LIMIT_HORIZON_DAYS = 30
PAIRED_MIN_REGRESSION = 10
WEIGHT = {"FAIL": 3, "OVER": 2, "WARNING": 1, "PASS": 0, None: 0}


@dataclass(frozen=True)
class Box:
    domain: str
    layer: str | None
    model: str
    color: str
    orient: str
    status: str | None
    scope: str | None
    lsl: float | None
    usl: float | None
    unit: str
    values: tuple[float, ...]
    dates: tuple[date, ...]

    @property
    def key(self) -> str:
        return f"{self.domain}|{self.layer or ''}|{self.model}|{self.color}|{self.orient}"

    @property
    def label(self) -> str:
        word = LAYER_WORD[self.layer] if self.layer else "CF"
        return f"{self.model} {self.color} · {word} · {self.orient[0]}"

    @property
    def out(self) -> int:
        return sum(
            (self.lsl is not None and v < self.lsl) or (self.usl is not None and v > self.usl)
            for v in self.values
        )

    @property
    def mean(self) -> float | None:
        return mean_sd(self.values)[0]

    @property
    def sd(self) -> float | None:
        return mean_sd(self.values)[1]


@dataclass(frozen=True)
class PointReading:
    domain: str
    point: str
    car: str | None
    out: bool


@dataclass(frozen=True)
class BandRow:
    model: str | None
    color: str | None
    values: dict[str, float | None]  # keys du wa wb wc wd we cf


@dataclass(frozen=True)
class MonthPoint:
    month: str
    mean: float | None
    status: str | None


@dataclass
class Answer:
    status: str
    headline: str
    status_code: str | None = None
    proof: str = ""
    explanation: str = ""  # AR06 plain-language paragraph; "" for not_enough / needs_slot
    next_step: str | None = None
    risk: dict | None = None
    confidence: str = ""
    evidence: dict = field(default_factory=dict)
    followups: list[dict] = field(default_factory=list)
    method: dict = field(default_factory=dict)
    slot: dict | None = None  # AR05 needs_slot: {name, prompt, choices: [{value, label}]}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision"] = {"status_code": d.pop("status_code"), "headline": d.pop("headline")}
        return d


def not_enough(reason: str, n: int, rule: str) -> Answer:
    return Answer(status="not_enough", headline=reason, method={"rule": rule, "n": n, "caveats": []})


def all_clear(headline: str, rule: str, n: int) -> Answer:
    return Answer(status="all_clear", headline=headline, method={"rule": rule, "n": n, "caveats": []})


def severity(box: Box) -> float:
    mean, sd = box.mean, box.sd
    past = 0.0
    if mean is not None and sd is not None and sd >= 1e-9:
        if box.lsl is not None:
            past = max(past, (box.lsl - mean) / sd)
        if box.usl is not None:
            past = max(past, (mean - box.usl) / sd)
    return WEIGHT[box.status] * box.out * (1 + past)


def capability_word(c: float) -> str:
    return "Capable" if c >= 1.33 else "Marginal" if c >= 1.0 else "Poor"
