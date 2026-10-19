"""Analysis assistant DTOs (AR04). One guided answer: decision, proof, next step.

``status_code`` carries the overview code unchanged (PASS, WARNING, FAIL, OVER,
null). Counts as "x of y" only; no key names a rate, percentage, score or grade.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.assistant.catalog import IDS
from app.schemas.common import StrictModel
from app.schemas.history import MONTH_PATTERN
from app.schemas.report import Domain

Topic = Literal[IDS]  # every catalog id (AR05 §5 plus AR04 changes)
EvidenceKind = Literal["bar", "table", "shift", "trend", "heatmap", "weekly_strip", "boxplot_pair",
                       "boxplot_group", "mirrored_bar", "point_bars", "car_bars", "breakdown", "distribution",
                       "trend_monthly", "grid", "spectrum", "scatter", "limit_card", "stat"]
Cell = str | int | float | None


class AssistantDecision(StrictModel):
    status_code: str | None = Field(description="The deciding box's overview status code, unchanged; null when none.")
    headline: str = Field(description="The decision in one short sentence.")


class AssistantRisk(StrictModel):
    expected_out: int = Field(description="Cars expected out of limits among the next of_next cars.")
    of_next: int = Field(description="How many upcoming cars the count is about.")
    basis: str = Field(description="What the projection uses, e.g. the current mean and spread.")


class AssistantSeriesPoint(StrictModel):
    x: str = Field(description="Measuring day, YYYY-MM-DD.")
    y: float = Field(description="Mean of that day's readings.")


class AssistantLimits(StrictModel):
    lo: float | None = Field(description="Lower limit (Lo or Wave Scan minimum); null when none.")
    hi: float | None = Field(description="Upper limit (Hi); null when none.")


class AssistantCell(StrictModel):
    status_code: str | None = Field(description="Overview status code of the cell, unchanged; null when none.")
    word: str = Field(description="Site word for the status, e.g. Pass, Fail, No standard; empty for an empty cell.")
    note: str = Field(default="", description="What sets the cell, e.g. the model and orientation of the worst box.")
    arrow: str = Field(default="", description="Status move vs the previous month: up (better), down (worse) or empty.")


class AssistantGroupStats(StrictModel):
    label: str = Field(description="Group name, e.g. a model, colour, side or plant.")
    n: int = Field(description="Readings in the group.")
    q1: float | None = Field(description="First quartile.")
    median: float | None = Field(description="Median.")
    q3: float | None = Field(description="Third quartile.")
    low: float | None = Field(description="Lower whisker end.")
    high: float | None = Field(description="Upper whisker end.")
    mean: float | None = Field(description="Mean.")


class AssistantXY(StrictModel):
    x: float = Field(description="Horizontal value.")
    y: float = Field(description="Vertical value.")
    label: str | None = Field(default=None, description="What the dot is, e.g. a car; null when unnamed.")


class AssistantCardRow(StrictModel):
    label: str = Field(description="Row name, e.g. a layer and orientation.")
    value: str = Field(description="Row value in words, e.g. Lo 40 µm (colour rule).")


class AssistantChoice(StrictModel):
    value: str = Field(description="Value to send back in the slot's query param.")
    label: str = Field(description="Chip text.")


class AssistantSlot(StrictModel):
    name: str = Field(description="Query param that fills the slot, e.g. a, b, metric, target.")
    prompt: str = Field(description="Short question for the missing detail; starts with the no-readings line when the value sent matched nothing.")
    choices: list[AssistantChoice] = Field(description="Valid values from this month's live data.")


class AssistantEvidence(StrictModel):
    kind: EvidenceKind | None = Field(
        default=None, description="How to draw the evidence; null when the answer has none.")
    columns: list[str] = Field(default=[], description="Column headings for rows.")
    rows: list[list[Cell]] = Field(default=[], description="Evidence rows, ranked; the UI shows the top 5.")
    series: list[AssistantSeriesPoint] = Field(default=[], description="Daily means for a trend; empty otherwise.")
    limits: AssistantLimits | None = Field(default=None, description="Box limits for a trend line; null for other topics.")
    cells: list[list[AssistantCell]] = Field(default=[], description="Heatmap or grid cells, row by row, aligned with rows and columns.")
    groups: list[AssistantGroupStats] = Field(default=[], description="Box-plot statistics per compared group.")
    points: list[AssistantXY] = Field(default=[], description="Scatter dots.")
    card: list[AssistantCardRow] = Field(default=[], description="Label and value rows for a limit card or stat.")


class AssistantFollowup(StrictModel):
    label: str = Field(description="Button text for the next question.")
    topic: Topic = Field(description="Topic the button asks.")
    target: str | None = Field(description="Box key domain|layer|model|color|orient, or null for the default.")


class AssistantMethod(StrictModel):
    rule: str = Field(description="The rule used to reach the answer, in words.")
    n: int = Field(description="How many boxes, readings or comparisons the rule looked at.")
    caveats: list[str] = Field(description="Limits on the answer, e.g. boxes skipped and why.")


class AssistantAnswerOut(StrictModel):
    topic: Topic = Field(description="The topic asked, echoed.")
    month: str | None = Field(pattern=MONTH_PATTERN, description="Month answered; null when the plant has no readings.")
    previous_month: str | None = Field(pattern=MONTH_PATTERN, description="The month before, used for comparisons.")
    domain: Domain = Field(description="Instrument filter, echoed.")
    models: list[str] = Field(description="Model filter, echoed; empty means all.")
    colors: list[str] = Field(description="Colour filter, echoed; empty means all.")
    status: Literal["answer", "all_clear", "not_enough_data", "needs_slot"] = Field(
        description="answer: a finding; all_clear: nothing to fix; not_enough_data: the headline says what is missing; "
        "needs_slot: a detail is missing, see slot (the headline repeats its prompt).")
    decision: AssistantDecision = Field(description="The one decision.")
    proof: str = Field(description="The one proving number, as counts; empty when not an answer.")
    explanation: str = Field(
        description="Two or three plain-language sentences for an engineer: what, how big in real units, why it "
        "matters; one sentence for all_clear; empty for not_enough_data and needs_slot.")
    next_step: str | None = Field(description="What to check next; null when none.")
    risk: AssistantRisk | None = Field(description="Cars expected out if nothing changes; null when not projected.")
    confidence: str = Field(description="solid or exploratory; empty when not an answer.")
    evidence: AssistantEvidence = Field(description="Table or chart data behind the answer.")
    followups: list[AssistantFollowup] = Field(description="Suggested next questions.")
    method: AssistantMethod = Field(description="How this was worked out.")
    slot: AssistantSlot | None = Field(default=None, description="The missing detail when status is needs_slot; null otherwise.")


class AssistantSlotSpec(StrictModel):
    name: str = Field(description="Query param that fills the slot.")
    kind: str = Field(description="month, model, colour, colour_family, layer, metric, band, box, point, car, side, orient or plant.")
    prompt: str = Field(description="Question asked when the slot is missing.")
    prompt_th: str = Field(description="The prompt in Thai.")
    required: bool = Field(description="False when the filter bar or the topic supplies a default.")


class AssistantQuestion(StrictModel):
    id: Topic = Field(description="Catalog id; send it as topic.")
    group: Literal["month", "compare", "problem", "trend", "appearance", "data"] = Field(description="Menu group.")
    label: str = Field(description="Menu label.")
    label_th: str = Field(description="Menu label in Thai.")
    slots: list[AssistantSlotSpec] = Field(description="Details the question uses, in order.")
    graph: EvidenceKind = Field(description="The graph kind the answer draws.")
    example: str = Field(description="An example headline.")


class AssistantQuestionsOut(StrictModel):
    questions: list[AssistantQuestion] = Field(description="Every question, in menu order.")
    keywords: dict[str, list[str]] = Field(description="Typed-text keywords per question id, English then Thai.")
