"""T114-FIX: the one rule for "is this Wave Scan car complete".

No FastAPI, no psycopg, no SQL (`AGENTS.md` rule 8). The list is injected.

* **D-114F-1.** A car is complete when it has a reading on every **live,
  non-extra** point of its plant x model list. Expected = how many such
  points the list has; mapped = how many of them the car has a reading on.
  A reading on a retired point, an extra point or a code that is not on the
  list counts neither way.
* **D-114F-2.** Counted (Point Check's switch) does not enter: it says what
  the dashboard sums, not whether the car was measured.
* **D-114F-4.** No live list for that plant x model -> the old rule:
  expected = `ref_model.expected_zone_count`, mapped = every distinct
  checkzone the car has.

History, review vehicles, the worksheet's short vehicles and Comparison all
call `wavescan_points`; `v_car_completeness` (revision 0038) is the same
rule in SQL. Nothing here grades anything. D1 is open.
"""

from __future__ import annotations

from typing import Iterable, Mapping


def wavescan_points(
    zones: Iterable[str | None],
    model: str | None,
    *,
    live_points: Mapping[str, frozenset[str]] | None,
    expected_zones: Mapping[str, int],
) -> tuple[int, int | None]:
    """`(mapped, expected)` for one car of one plant.

    `live_points` is that plant's live, non-extra codes per model
    (`repositories.ws_points.live_lists`); `expected_zones` is
    `ref_model.expected_zone_count`, used only when the model has no list.
    An unknown or missing model answers `expected = None`, as before.
    """
    found = {zone for zone in zones if zone is not None}
    listed = (live_points or {}).get(model) if model is not None else None
    if listed:
        return len(found & listed), len(listed)
    expected = expected_zones.get(model) if model is not None else None
    return len(found), int(expected) if expected is not None else None


__all__ = ["wavescan_points"]
