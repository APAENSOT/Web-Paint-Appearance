"""Duplicate detection.

Ported from the vault's ``dedup.py``. Two rows are the same measurement if
they share a vehicle-zone key **and** their ten instrument measurements
agree, at one decimal place, on at least ``threshold`` percent. The key is
``cleaner.dedup_key``: ``(plant, serial_no, checkzone)`` when there is a
serial, ``(plant, measured_date, model, colour, checkzone)`` when there is
not (T39-FIX, ADR 0013 decision 8a).

Validated against the June/July 2026 AAT+FTM files: 255 true duplicate groups
all scored 100%, every other comparison scored 30% or less. Nothing sits near
the 80% line, so the threshold is not fragile.

Two kinds of duplicate exist and both must be caught:

* **within-file** -- FTM June contains the same seven cars pasted twice (224
  rows), one copy carrying B and one not;
* **cross-file** -- AAT June car 2478750 reappears in the July file (31
  rows) with identical measurements.

The cross-file case is why this compares against rows already in
``wavescan``. Those rows are **passed in**, not queried: the query lives in
``app/repositories/measurements.py`` and this module stays framework-free
(`00-ARCHITECTURE.md` §5 rule 1).

**The one behavioural change from the vault version.** There, the cleaner
rounded every value to one decimal on the way in, so ``==`` was safe here.
T04 stores measurements unrounded (`AGENTS.md` §4, L12), so the rounding
moved *into this module*, where it is a comparison tolerance rather than a
change to the stored fact. Same 80% threshold, same outcomes, and the file's
own digits survive.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from app.domain.cleaner import CleanRow
from app.domain.reader import MEASURES_CORE

#: Decimal places at which two gauge readings are "the same number".
#: One decimal is what the plants' own files carry and what the demo loader
#: compared at; the float4 noise in a workbook (2.70000004768372 for 2.7) is
#: exactly what this absorbs.
COMPARISON_DECIMALS = 1


def _quantise(value: object, decimals: int = COMPARISON_DECIMALS) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-decimals))


@dataclass
class ExistingMeasurement:
    """One measurement already stored, as far as dedup is concerned."""

    measures: Mapping[str, object]
    source: str


@dataclass
class DuplicateInfo:
    """A row that was dropped, and what it duplicated."""

    dropped: CleanRow
    kept_description: str
    similarity: float


@dataclass
class DedupResult:
    keep: list[CleanRow]
    duplicates: list[DuplicateInfo]

    def counts(self) -> tuple[int, int]:
        return len(self.keep), len(self.duplicates)


def similarity(a: CleanRow, b: CleanRow) -> float:
    """Percent of the ten instrument measurements that agree at one decimal."""
    matches = 0
    for m in MEASURES_CORE:
        left = _quantise(a.measures.get(m))
        right = _quantise(b.measures.get(m))
        if left is not None and left == right:
            matches += 1
    return matches / len(MEASURES_CORE) * 100.0


def _better(candidate: CleanRow, current: CleanRow) -> bool:
    """True if ``candidate`` should replace ``current`` as the kept row.

    More complete wins; ties go to the earlier source row. This matters: in
    FTM June only the first copy carries B, so a naive "keep the last" rule
    would destroy 224 B values.
    """
    return (candidate.completeness(), -candidate.source_row) > (
        current.completeness(), -current.source_row
    )


class Deduplicator:
    def __init__(self, threshold: float = 80.0):
        self.threshold = threshold

    def _matches_existing(
        self,
        row: CleanRow,
        existing: Mapping[tuple, Sequence[ExistingMeasurement]],
    ) -> tuple[bool, float, str]:
        for prior in existing.get(row.key(), ()):  # type: ignore[arg-type]
            matches = 0
            for m in MEASURES_CORE:
                mine = _quantise(row.measures.get(m))
                theirs = _quantise(prior.measures.get(m))
                if mine is not None and mine == theirs:
                    matches += 1
            score = matches / len(MEASURES_CORE) * 100.0
            if score >= self.threshold:
                return True, score, prior.source
        return False, 0.0, ""

    def run(
        self,
        rows: Iterable[CleanRow],
        existing: Mapping[tuple, Sequence[ExistingMeasurement]] | None = None,
    ) -> DedupResult:
        rows = list(rows)
        existing = existing or {}

        kept: dict[tuple, CleanRow] = {}
        duplicates: list[DuplicateInfo] = []

        for row in rows:
            # 1. already in the database? (cross-file / re-upload)
            is_dup, score, where = self._matches_existing(row, existing)
            if is_dup:
                duplicates.append(DuplicateInfo(
                    dropped=row,
                    kept_description=f"already loaded from {where}",
                    similarity=score,
                ))
                continue

            # 2. already seen in this file?
            key = row.key()
            incumbent = kept.get(key)
            if incumbent is None:
                kept[key] = row
                continue

            score = similarity(row, incumbent)
            if score < self.threshold:
                # Same vehicle and zone but genuinely different numbers:
                # a real re-measurement. Keep both.
                kept[(*key, f"#{row.source_row}")] = row
                continue

            if _better(row, incumbent):
                duplicates.append(DuplicateInfo(
                    dropped=incumbent,
                    kept_description=(
                        f"{row.source_file} [{row.source_sheet}] "
                        f"row {row.source_row} (more complete)"
                    ),
                    similarity=score,
                ))
                kept[key] = row
            else:
                duplicates.append(DuplicateInfo(
                    dropped=row,
                    kept_description=(
                        f"{incumbent.source_file} [{incumbent.source_sheet}] "
                        f"row {incumbent.source_row}"
                    ),
                    similarity=score,
                ))

        keep = sorted(kept.values(), key=lambda r: (r.source_file, r.source_row))
        return DedupResult(keep=keep, duplicates=duplicates)
