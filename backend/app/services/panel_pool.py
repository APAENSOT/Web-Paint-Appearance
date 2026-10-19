"""T89 (D-89-6): one panel list, built once, offered by both pickers.

Before T89 the same question had two answers. The guided match screen
(`services/panel_match.py`) offered 32 candidates -- mappable only,
orientation-filtered, with the panels this batch had already used taken out
-- while the per-row picker in the held-label list offered the raw
`plant_zone_codes`, which at FTM is **64**: the 32 the approval path
accepts plus the 32 T58 numbered panels that are not on the model's own
`ref_model_zone` catalogue and therefore cannot be the target of a
`ref_plant_zone_map` row at all. Measured live before the owner purged:

    '07LFFENDER' / P703 DBL RANGER -> candidates = 64, 32 of them refusable

The owner's screenshots were that picker. They were handed a list half of
which cannot work: `_require_checkzone_target` admits any panel that is
**live** here (T58 / D-58-10), so the refusal did not arrive until the row
was written -- against `fk_pzm_model_zone`.

So this module answers the question once, and both callers read it:

* **mappable only** -- on the model's `ref_model_zone` catalogue, which is
  what the learning table's foreign key can reference;
* **orientation-filtered** -- the Tolerance Group the file wrote for this
  spelling against the panel's own, a hard constraint and never a score
  (D-88-2);
* **taken panels last, greyed, named** -- a panel this batch has already
  loaded rows onto is still shown, disabled, labelled with the file
  spelling that took it. The owner chose that over hiding them: "already
  matched to 06LFFENDER" is an explanation, an absence is a puzzle;
* **suggestions first** -- the order is T86/T87's ranking (family, then
  name score, then the walk number) and then the rest of the list in walk
  order, so the two pickers are the same list in the same order and a test
  can say so.

**A panel the approval path would refuse is never offered.** That is the
whole claim; everything above is how it is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Connection

from app.domain.panel_match import LivePanel, rank_candidates
from app.domain.panel_walk import CanonicalPoint
from app.repositories import batches as batch_repo
from app.repositories import mappings as maps

#: Every reason that holds a row because of its **panel** name. T41 teaches
#: the first one row at a time; T86's guided set covers both, which is the
#: point -- two held rows that look identical to a reviewer must not get two
#: different answers. It lives here because both the held-label list and the
#: match screen read it, and neither owns it.
PANEL_HOLD_REASONS = ("UNKNOWN_CHECKZONE", "ZONE_NOT_VALID_FOR_MODEL")

#: Why a live panel cannot be a match target.
NOT_MAPPABLE_REASON = (
    "This panel is live at {plant} but is not a position on {model}'s own "
    "catalogue, so a panel map cannot point at it. An Admin would have to "
    "add it to the model catalogue first."
)

#: Said about a panel this very file has already loaded rows onto (D-89-6).
TAKEN_LABEL = "already matched to {spelling}"


@dataclass(frozen=True)
class PanelRow:
    """One live panel of this plant x model, with why it is or is not offered."""

    zone_code: str
    point_no: int
    tolerance_group: str
    note: str | None
    mappable: bool
    not_mappable_reason: str | None
    #: The file spelling that already loaded rows onto this panel, or None.
    taken_by: str | None
    #: RO19: measuring rank, independent from the immutable catalogue number.
    walk_rank: int | None = None

    @property
    def taken(self) -> bool:
        return self.taken_by is not None

    @property
    def taken_label(self) -> str | None:
        return TAKEN_LABEL.format(spelling=self.taken_by) if self.taken_by else None


@dataclass(frozen=True)
class Offering:
    """What one held spelling may be answered with, in the order shown."""

    #: Panels a person may choose, suggestions first. Every one of these is
    #: confirmable: mappable, live and not taken.
    offerable: tuple[str, ...]
    #: Taken panels of the same orientation: shown, disabled, labelled.
    blocked: tuple[PanelRow, ...]
    #: Panels the orientation filter removed from the suggestions (G-88-5).
    filtered_out: tuple[str, ...]


@dataclass(frozen=True)
class PanelPool:
    """Every live panel of one plant x model, and who has taken what."""

    plant_code: str
    model_code: str
    rows: tuple[PanelRow, ...]

    @property
    def open_mappable(self) -> list[LivePanel]:
        """The pool the set solver proposes from: mappable and not taken."""
        return [
            LivePanel(
                zone_code=row.zone_code,
                point_no=row.point_no,
                tolerance_group=row.tolerance_group,
                mappable=True,
            )
            for row in self.rows
            if row.mappable and not row.taken
        ]

    @property
    def canonical_points(self) -> list[CanonicalPoint]:
        """T90: the model's own canonical walk, in walk order.

        Every **mappable** panel, taken or not. The walk belongs to the
        model, not to this batch: a panel a spelling of this very file has
        already loaded onto is still one of the model's 32 positions, and
        leaving it out would shift every ordinal after it.
        """
        return [
            CanonicalPoint(zone_code=row.zone_code, point_no=row.point_no, walk_rank=row.walk_rank)
            for row in sorted(self.rows, key=lambda row: row.walk_rank if row.walk_rank is not None else row.point_no)
            if row.mappable
        ]

    def offer(
        self, raw_zone_text: str, orientations: Sequence[str] = ()
    ) -> Offering:
        """The one list, for one held spelling on this model (D-89-6).

        `orientations` is what the **file** wrote for this spelling. Exactly
        one is the normal case and filters; none, or more than one, filters
        nothing -- a file that disagrees with itself about Horizontal and
        Vertical is a file problem to be flagged, not a constraint to apply
        (G-88-5).
        """
        wanted = orientations[0] if len(set(orientations)) == 1 else None
        mappable = [row for row in self.rows if row.mappable]

        def right_way_round(row: PanelRow) -> bool:
            return wanted is None or (row.tolerance_group or "").strip() == wanted

        kept = [row for row in mappable if right_way_round(row)]
        filtered_out = tuple(
            sorted(row.zone_code for row in mappable if not right_way_round(row))
        )
        open_rows = [row for row in kept if not row.taken]
        ranked = [
            candidate.zone_code
            for candidate in rank_candidates(
                raw_zone_text,
                [
                    LivePanel(
                        zone_code=row.zone_code,
                        point_no=row.point_no,
                        tolerance_group=row.tolerance_group,
                        mappable=True,
                    )
                    for row in open_rows
                ],
            )
        ]
        rest = [row.zone_code for row in open_rows if row.zone_code not in ranked]
        return Offering(
            offerable=tuple(ranked + rest),
            blocked=tuple(row for row in kept if row.taken),
            filtered_out=filtered_out,
        )


def panel_pool(
    conn: Connection, *, load_id: int | None, plant_code: str, model_code: str
) -> PanelPool:
    """Read the pool for one plant x model, for one batch.

    `load_id` is what makes "taken" meaningful: a panel is taken when
    **this** file has already loaded rows onto it. Without a batch (a
    committed remainder being taught long after the fact, or a caller that
    has no sheet in hand) nothing is taken and the list is simply every
    mappable panel.
    """
    taken_by = (
        batch_repo.panels_already_used_by(conn, load_id, model_code)
        if load_id
        else {}
    )
    rows = []
    for row in maps.live_plant_panels(conn, plant_code, model_code):
        # RO18 (B1): a map may land on any panel of this plant x model's own
        # live list (`fk_pzm_plant_point`, revision 0048), not only on the
        # shared `ref_model_zone` catalogue.
        mappable = True
        rows.append(
            PanelRow(
                zone_code=row["zone_code"],
                point_no=int(row["point_no"]),
                walk_rank=int(row["walk_rank"]) if row.get("walk_rank") is not None else None,
                tolerance_group=row["tolerance_group"],
                note=row["note"],
                mappable=mappable,
                not_mappable_reason=(
                    None
                    if mappable
                    else NOT_MAPPABLE_REASON.format(
                        plant=plant_code, model=model_code
                    )
                ),
                taken_by=taken_by.get(row["zone_code"]),
            )
        )
    return PanelPool(
        plant_code=plant_code, model_code=model_code, rows=tuple(rows)
    )


__all__ = [
    "NOT_MAPPABLE_REASON",
    "PANEL_HOLD_REASONS",
    "Offering",
    "PanelPool",
    "PanelRow",
    "TAKEN_LABEL",
    "panel_pool",
]
