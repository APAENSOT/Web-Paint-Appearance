"""T95 D-95-5 -- a test deletes only its own reference rows, asserted on the source.

The incident: six cleanups ran `DELETE FROM ref_plant_zone_map` keyed on
`raw_zone_text` alone, so a suite run reached rows at plants and models the
test never exercised and removed the owner's approved `12lcpillar` alias
(FTM / P703 DBL RANGER) from the live trial database. Four more deleted
`proposed_mapping` by a note prefix or a `payload::text LIKE` that the
**product** writes too, which took a genuine approved proposal with it.

Both are now scoped, and T98 (D-98-3) adds the bound a scope is not: a
cleanup that names the owner's own plant and model still reached a row the
owner taught minutes earlier, so every `ref_plant_zone_map` delete must
also floor itself in time. This file is why none of it can come back. It is a
source-level assertion, the same kind T87 made about its column-scoped
GRANT and D-90-11 about the reference loader's imports: the rule is a
property of the code, so it is read off the code rather than inferred from
one run's behaviour.

Adjacent string literals are folded by the parser, so one `cur.execute`
statement is one `ast` constant however many lines it is written over --
which is what makes "in the same statement" checkable at all.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SELF = Path(__file__).resolve()

ZONE_MAP = "ref_plant_zone_map"
PROPOSALS = "proposed_mapping"


def _sql_literals(path: Path):
    """Every string literal in one test module, whitespace-flattened."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, " ".join(node.value.split())
        elif isinstance(node, ast.JoinedStr):
            parts = [
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ]
            yield node.lineno, " ".join(" ".join(parts).split())


def _by_primary_key(text: str, key: str) -> bool:
    """A delete keyed on the row's own id needs no scope and no bound.

    It is the tightest form there is (`test_every_mapping_proposal_delete_is
    _keyed_on_an_id` asks for exactly this on the other table), so the two
    assertions below pass over it rather than demanding plant, model and a
    `created_at` floor it cannot be wrong without.
    """
    return bool(re.search(rf"\b{key}\s*=", text))


def _deletes(table: str) -> list[tuple[str, int, str]]:
    """`(file, line, statement)` for every DELETE of `table` in the suite.

    This module is skipped: it quotes the forbidden statements in its own
    failure messages, and quoting them is the only thing it does with them.
    """
    pattern = re.compile(rf"\bDELETE\s+FROM\s+{table}\b", re.IGNORECASE)
    found: list[tuple[str, int, str]] = []
    paths = [*TESTS_DIR.rglob("test_*.py"), *TESTS_DIR.rglob("conftest.py")]
    for path in sorted(paths):
        if path.resolve() == SELF:
            continue
        for lineno, text in _sql_literals(path):
            if pattern.search(text):
                found.append((path.name, lineno, text))
    return found


def test_every_zone_map_delete_in_a_test_names_its_plant_and_its_model():
    """D-95-1: all three of plant, model and spelling, in one statement."""
    statements = _deletes(ZONE_MAP)
    assert statements, (
        f"no {ZONE_MAP} delete found at all; this guard has stopped "
        f"reading the suite and would pass whatever the cleanups do"
    )
    unscoped = [
        (name, lineno, text)
        for name, lineno, text in statements
        if not _by_primary_key(text, "map_id")
        and ("plant_code" not in text or "model_code" not in text)
    ]
    assert not unscoped, (
        "these test cleanups can delete another plant's or another model's "
        "approved reference rows (T95 D-95-1 -- it is how the owner's "
        f"`12lcpillar` was lost):\n"
        + "\n".join(f"  {name}:{lineno}  {text}" for name, lineno, text in unscoped)
    )


def test_every_zone_map_delete_in_a_test_is_bounded_to_rows_the_test_created():
    """T98 D-98-3: plant and model are a scope, not a bound.

    The assertion above passes a cleanup that names the owner's **own**
    plant and model -- which is what every FTM fixture does, and how T97
    still lost a `ref_plant_zone_map` row the owner had taught minutes
    earlier. So the statement must also carry a floor in time
    (``created_at >=``, from `conftest.SUITE_STARTED`), which no row written
    before the run can clear.
    """
    unbounded = [
        (name, lineno, text)
        for name, lineno, text in _deletes(ZONE_MAP)
        if "created_at" not in text and not _by_primary_key(text, "map_id")
    ]
    assert not unbounded, (
        "these test cleanups are scoped but not bounded: each can still "
        "delete a reference row the owner created before the run, at the "
        "same plant and model (T98 D-98-3 -- add `AND created_at >= %s` "
        "with `since=SUITE_STARTED`, as every other cleanup does):"
        + "".join(
            f"\n  {name}:{lineno}  {text}"
            for name, lineno, text in unbounded
        )
    )


def test_no_test_deletes_a_mapping_proposal_by_note_or_payload():
    """D-95-2: by the ids the test created, never by content the product writes."""
    statements = _deletes(PROPOSALS)
    assert statements, (
        f"no {PROPOSALS} delete found at all; this guard has stopped "
        f"reading the suite"
    )
    by_content = [
        (name, lineno, text)
        for name, lineno, text in statements
        if "note" in text.lower() or "payload" in text.lower()
    ]
    assert not by_content, (
        "these test cleanups delete mapping proposals by content the "
        "product writes too, so they remove the owner's approved proposals "
        "(T95 D-95-2 -- delete by id, as `forget_proposals` does):\n"
        + "\n".join(f"  {name}:{lineno}  {text}" for name, lineno, text in by_content)
    )


def test_every_mapping_proposal_delete_is_keyed_on_an_id():
    """The other half of D-95-2: there is an `id` in the WHERE clause."""
    for name, lineno, text in _deletes(PROPOSALS):
        assert re.search(r"\bid\b", text), (
            f"{name}:{lineno} deletes mapping proposals without naming an "
            f"id: {text}"
        )
