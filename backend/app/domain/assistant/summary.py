"""AR04 topic `summary`: the one box to fix first this month."""

from __future__ import annotations

from app.domain.assistant.answer import Answer, Box, all_clear, not_enough, severity
from app.domain.assistant.changes import shifts
from app.domain.assistant.colours import direction, position_clause
from app.domain.assistant.plain_words import box_words, plural
from app.domain.report_summary import month_words, status_word

RULE = "Non-Pass boxes ranked by status weight x readings out x distance past the limit"


def summary(now: list[Box], before: list[Box], before_month: str | None) -> Answer:
    if not now:
        return not_enough("No boxes for this month and filter.", 0, RULE)
    bad = sorted((b for b in now if b.status not in ("PASS", None)), key=lambda b: -severity(b))
    if not bad:
        a = all_clear(f"All {len(now)} boxes Pass this month.", RULE, len(now))
        a.explanation = f"{'All' if len(now) > 1 else 'The'} {plural(len(now), 'box')} measured this month passed, so nothing needs action."
        return a
    top = bad[0]
    proof = f"{top.out} of {len(top.values)} readings out"
    if before and before_month:
        moves = [s.move for s in shifts(now, before)]
        proof += f"; {moves.count('worse')} got worse, {moves.count('better')} recovered vs {month_words(before_month)}"
    text = (f"{box_words(top)}, is the box to fix first this month; it's at {status_word(top.status, top.scope)}. "
            f"{top.out} of {len(top.values)} readings were outside the standard{position_clause(top)}.")
    if len(bad) > 1:
        text += f" Next on the list is {box_words(bad[1])}."
    return Answer(
        status="answer",
        headline=f"Fix first: {top.label}",
        status_code=top.status,
        proof=proof,
        explanation=text,
        next_step=direction(top),
        confidence="solid",
        evidence={
            "kind": "bar",
            "columns": ["Box", "Status", "Out", "n"],
            "rows": [[b.label, status_word(b.status, b.scope), b.out, len(b.values)] for b in bad[:3]],
            "series": [],
        },
        followups=[
            {"label": "Which colours?", "topic": "colours", "target": None},
            {"label": "Which points?", "topic": "points", "target": None},
            {"label": "What changed?", "topic": "changes", "target": None},
        ],
        method={"rule": RULE, "n": len(now), "caveats": []},
    )
