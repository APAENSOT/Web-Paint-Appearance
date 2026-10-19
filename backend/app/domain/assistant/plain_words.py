"""AR06 plain-language wording shared by the answer paragraphs (`explanation`). Pure."""

from __future__ import annotations

from app.domain.assistant.answer import Box, capability_word
from app.domain.report_summary import LAYER_WORD

# Statistics stay in `method`; a paragraph says them in words.
BANNED: tuple[str, ...] = ("Cpk", "σ", "ρ", "p <", "p=", "Mann", "Spearman", "OLS", "EWMA", "binomial")

_CAPABILITY = {"Capable": "the process holds the standard comfortably",
               "Marginal": "the process only just holds the standard",
               "Poor": "the process can't keep it inside the standard"}


def capability_sentence(c: float) -> str:
    return _CAPABILITY[capability_word(c)]


def difference_sentence(v) -> str:
    """v: a compare Verdict (anything with `.real`)."""
    return "a real difference, not day-to-day noise" if v.real else "within day-to-day noise"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "es" if word.endswith(("x", "s")) else "s")


def gap_words(delta: float, unit: str) -> str:
    """'4.0 µm thinner' / '0.3 higher'; '' when the gap rounds to nothing."""
    if round(abs(delta), 1) == 0:
        return ""
    word = ("thinner" if delta < 0 else "thicker") if unit else ("lower" if delta < 0 else "higher")
    return f"{abs(delta):.1f}{' ' + unit if unit else ''} {word}"


def model_word(model: str) -> str:
    """'P703 DBL RANGER' -> 'Ranger': the one casing paragraphs use for a model."""
    return model.split()[-1].title() if model.split() else model


def panels_words(box: Box) -> str:
    """'on the Ranger, vertical panels'."""
    return f"on the {model_word(box.model)}, {box.orient.lower()} panels"


def box_words(box: Box) -> str:
    """'Desert Island Blue Primer on the Ranger, vertical panels'."""
    return f"{box.color} {LAYER_WORD[box.layer] if box.layer else 'Wave Scan CF'} {panels_words(box)}"
