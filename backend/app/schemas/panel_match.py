"""T86 guided panel match: the read model the match screen is drawn from.

One GET answers the whole screen: what the file calls each panel, what this
plant x model's live panels are, and which live panels each file name
*looks* like by name. Every number in here is server-derived from the
persisted review projection and the reference tables; the client computes no
score and invents no panel.

What this shape deliberately does **not** carry is an answer. `candidates`
is a list a person reads, ordered by a name score, and `raw_position` is
shown beside the name as provenance. Neither is a decision, and an empty
`candidates` is a real answer (`AGENTS.md` rule 6, D-86-3).
"""

from __future__ import annotations

from datetime import datetime

from app.domain.panel_match import MIN_SCORE
from app.schemas.common import StrictModel
from pydantic import Field


class PanelCandidateOut(StrictModel):
    """One live panel this file name could be, by **name** similarity."""

    zone_code: str = Field(description="The live panel's own name at this plant x model.")
    point_no: int = Field(
        ge=1,
        description=(
            "The live panel's walk number. Shown so a person can read it. It "
            "took no part in this candidate being offered (D-86-3)."
        ),
    )
    tolerance_group: str = Field(
        description="Horizontal or Vertical, derived from the panel name (D-58-04)."
    )
    score: float = Field(
        ge=0,
        le=1,
        description=(
            f"Name similarity, {MIN_SCORE} or more or it is not listed. "
            "Advisory: nothing in the backend branches on it."
        ),
    )
    basis: str = Field(
        description=(
            "Words for why it scored that: 'same panel name', 'same name, "
            "different number', or 'similar name'. For a person, never read "
            "by code."
        )
    )


class HeldPanelOut(StrictModel):
    """One distinct panel spelling the file wrote and this plant held."""

    raw_zone_text: str = Field(description="The Checkzone cell as the file spells it.")
    raw_position: int | None = Field(
        default=None,
        description=(
            "The label's own leading number, 1-40, or null. Provenance only "
            "(S14): it is shown beside the name and never drives a proposal."
        ),
    )
    count: int = Field(ge=1, description="Held rows carrying this spelling.")
    reasons: list[str] = Field(
        description=(
            "Why it is held: UNKNOWN_CHECKZONE (on no list here) and/or "
            "ZONE_NOT_VALID_FOR_MODEL (a real panel another model owns). "
            "Both ask the same question on this screen."
        )
    )
    candidates: list[PanelCandidateOut] = Field(
        default_factory=list,
        description=(
            "Live panels this spelling could be, best first. **T88:** the "
            "list is filtered by orientation first (a hard constraint, never "
            "a score) and then ranked by T86/T87's family, name and number. "
            "Empty is an answer, not a gap to fill with the nearest number."
        ),
    )
    orientations: list[str] = Field(
        default_factory=list,
        description=(
            "T88. The Tolerance Group values the file wrote for this "
            "spelling on this model. One is normal; more than one is a file "
            "problem and switches the orientation filter and exhaustion off "
            "for this spelling (G-88-5)."
        ),
    )
    proposed_zone_code: str | None = Field(
        default=None,
        description=(
            "T88. The panel the solver would pair this spelling with, or "
            "null. **Never an answer** -- a person confirms every pair "
            "(D-88-3)."
        ),
    )
    signal: str = Field(
        default="none",
        description=(
            "T88 (D-88-3). Which signal argued for `proposed_zone_code`: "
            "`name`, `number`, `exhaustion`, or `none` (no proposal, or a "
            "pair the owner already confirmed). Shown in the screen so the "
            "owner sees what argued for a pair; nothing branches on it."
        ),
    )
    signal_reason: str = Field(
        default="",
        description=(
            "T88. The same thing in plain words, including -- for an "
            "exhaustion claim -- the counts it rests on (G-88-3)."
        ),
    )
    orientation_conflict: bool = Field(
        default=False,
        description=(
            "T88 (G-88-5). True when this spelling's own rows disagree about "
            "Tolerance Group. The orientation filter and exhaustion are both "
            "switched off for it, and the screen says so."
        ),
    )
    filtered_out: list[str] = Field(
        default_factory=list,
        description=(
            "T88 (G-88-5). Panels the orientation filter removed from the "
            "**proposals**. They stay choosable: a constraint narrows what "
            "is suggested and never what the owner may pick."
        ),
    )
    choosable: list[str] = Field(
        default_factory=list,
        description=(
            "T89 (D-89-6). **The** list this spelling may be answered with, "
            "suggestions first and then the rest in walk order: mappable "
            "panels only, orientation-filtered, with the panels this batch "
            "has already used taken out. The per-row picker in the "
            "held-label list is built from the same call, so the two "
            "pickers are the same list in the same order and no panel the "
            "approval path would refuse is ever offered."
        ),
    )
    blocked: list[BlockedPanelOut] = Field(
        default_factory=list,
        description=(
            "T89 (D-89-6). Panels of the right orientation this file has "
            "already used: shown last, disabled, each labelled with the "
            "spelling that took it."
        ),
    )
    carried_over: CarriedOverOut | None = Field(
        default=None,
        description=(
            "T89 (D-89-9). An earlier decision about this spelling, to "
            "arrive pre-selected and marked as carried over. Null when "
            "there is none. Never auto-applied."
        ),
    )
    walk: WalkRowOut | None = Field(
        default=None,
        description=(
            "T90. This spelling's place in the structural reading of the "
            "whole walk: its colour, its reason, and what each rule says it "
            "is. Null when the walk has nothing to say about it. The same "
            "row appears in `walk.rows`, which covers every name the file "
            "writes rather than only the held ones."
        ),
    )


class BlockedPanelOut(StrictModel):
    """A panel that is shown but cannot be chosen, and what took it.

    **T89 (D-89-6).** A panel this very file has already loaded rows onto is
    spoken for: offering it again would put two spellings on one panel,
    which is the defect this whole round of work exists to undo. The owner
    chose to keep them visible rather than silently absent -- "already
    matched to 06LFFENDER" is an explanation a reviewer can act on, a gap in
    a list is a puzzle -- so they come back here, to be rendered last and
    disabled.
    """

    zone_code: str
    point_no: int = Field(ge=1)
    tolerance_group: str
    taken_by: str = Field(
        description="The file spelling that already loaded rows onto this panel."
    )
    label: str = Field(
        description='Why it cannot be chosen, in words: "already matched to 06LFFENDER".'
    )


class CarriedOverOut(StrictModel):
    """A panel decision somebody already made, offered again (D-89-9).

    Present only when this exact question has an earlier answer that does
    not already resolve it: the pair is still `PROPOSED`, or it was taught
    on another model of this plant, or this spelling is one or two
    characters off one that was taught. The row arrives with `zone_code`
    pre-selected and marked as carried over.

    **It is never an answer.** A person still confirms it, and can change
    it; nothing is auto-applied. A carried pair whose panel is not on offer
    for this question is dropped rather than shown, because pre-selecting
    something the approval path would refuse is the defect Part 1 removes.
    """

    zone_code: str = Field(description="The panel that spelling was mapped to before.")
    kind: str = Field(
        description=(
            "`pending` (the same spelling and model, still waiting for an "
            "Admin), `other_model` (taught on another model of this plant), "
            "or `near_miss` (one or two characters off a taught spelling). "
            "Shown; nothing branches on it."
        )
    )
    reason: str = Field(
        description=(
            "The whole thing in plain words, naming when it was decided and "
            "which batch it came from."
        )
    )
    source_raw_zone_text: str = Field(
        description="The spelling that was taught, which may differ from this one."
    )
    source_model_code: str = Field(description="The model it was taught on.")
    decided_at: datetime | None = Field(
        default=None, description="When that decision was recorded."
    )
    load_id: int | None = Field(
        default=None,
        description=(
            "The batch the decision was made on, when it is still a pending "
            "proposal. Null for an approved pair -- the learning table does "
            "not keep a batch."
        ),
    )


class WalkGroupCountOut(StrictModel):
    """One panel family, counted in the file and in the canonical list."""

    panel_group: str
    file: int = Field(ge=0, description="Distinct names of this family the file writes.")
    canonical: int = Field(
        ge=0, description="Points of this family on the canonical list."
    )


class WalkRowOut(StrictModel):
    """T90: the structural verdict for one name the file writes.

    **Two colours and no green** (D-90-6). `attention` is `yellow` ("looks
    right, still confirm") only when a rule applied cleanly, any side hint
    agreed, and the answer is what was confirmed last under this same walk.
    Everything else is `red`, and `reason` says which of those it was in
    plain words -- the colour on its own is a demand without a case.
    """

    raw_zone_text: str = Field(description="The panel name as the file spells it.")
    panel_group: str | None = Field(
        default=None,
        description="HOOD / FENDER / DOOR / ROOF / PILLAR / BOX / TAILGATE, or null.",
    )
    side: str | None = Field(
        default=None,
        description=(
            "`L`, `R` or null, read from the letters in front of the family "
            "word. `LCROOF` carries a side; `ROOF`, `HOOD` and `TGATE` carry "
            "none, and an absent side is never cross-checked against a "
            "present one (D-90-8)."
        ),
    )
    specificity: str = Field(
        description=(
            "T90 (D-90-3). `rough` when this name's core is shared with "
            "another name of the same sheet -- then the **number** is doing "
            "the identifying and the name alone names no position. `specific` "
            "when it is not. A rough confirmation is recorded on the batch "
            "and is **never** written to `ref_plant_zone_map`."
        )
    )
    binding: str = Field(
        default="alias",
        description=(
            "T91 (D-91-3). How far confirming this pair may travel, said in "
            "the data: `alias` becomes a permanent `ref_plant_zone_map` row, "
            "`batch` is confirmed for this upload only and recorded on it "
            "(D-90-11). Two things make it `batch` -- a rough name "
            "(D-90-3), and a name another sheet of this plant confirmed as a "
            "**different** panel (D-91-2). The second holds even for a "
            "`specific` name: `13LFRDOOR` is a pillar in August and a door "
            "in September, so at FTM that spelling identifies no panel on "
            "its own and can never be learned forever again. Offering a "
            "`batch` row as a permanent alias is refused at the write "
            "boundary; this field is so the screen says it first."
        ),
    )
    binding_reason: str | None = Field(
        default=None,
        description=(
            "Why it is `batch`, in plain words, naming the file that "
            "confirmed it differently. Null when it is `alias`."
        ),
    )
    attention: str = Field(
        description=(
            "`yellow` (looks right, still confirm) or `red`. There is no green."
        )
    )
    reason: str = Field(description="Why it is that colour, in plain words.")
    rule: str = Field(
        description=(
            "`group_ordinal` (rule a), `walk_number` (rule b) or `none` "
            "(rule c: no structural rule applies, or the two disagree)."
        )
    )
    proposed_zone_code: str | None = Field(
        default=None,
        description=(
            "What the rules agree this name is, or null. Null when no rule "
            "applies **and** when the two rules disagree -- a disagreement "
            "proposes neither answer (D-90-2). Never applied without a click."
        ),
    )
    rule_group_ordinal_zone_code: str | None = Field(
        default=None, description="Rule (a)'s own answer, or null."
    )
    rule_walk_number_zone_code: str | None = Field(
        default=None,
        description=(
            "Rule (b)'s own answer, or null. Both are carried so a "
            "disagreement can be shown whole rather than summarised."
        ),
    )
    side_hint_checked: bool = Field(
        default=False,
        description=(
            "True when the file's name and the proposed panel both carried a "
            "side and they were compared. False means there was nothing to "
            "compare -- `25TGATE`..`29TGATE` -- which is why that group is "
            "red the first time a walk is seen (D-90-12)."
        ),
    )
    prefilled_zone_code: str | None = Field(
        default=None,
        description=(
            "The answer confirmed last under this same walk, to arrive "
            "pre-filled. Null when the walk has changed or nothing was "
            "confirmed before. Never an answer."
        ),
    )


class WalkMatchOut(StrictModel):
    """T90: the whole structural reading of one `(plant, model)`'s walk.

    **The walk is the identity; the label is only a label.** Three months of
    real FTM files describe the same 32-point walk under three naming
    schemes, so this block is about the *structure* the file writes and not
    about its spellings: `fingerprint` is the ordered sequence of panel
    **groups** (D-90-4), deliberately not the names, so a respelling does
    not invalidate a confirmed walk while a reshuffle does.

    Null on the parent when the sheet writes no panel name for this model,
    or when the model has no canonical list to align against at all.
    """

    model_code: str
    fingerprint: str = Field(
        description=(
            "The ordered group sequence, `|`-joined. The stored form: this "
            "is what a confirmed set is remembered under (D-90-4, D-90-11)."
        )
    )
    fingerprint_display: str = Field(
        description='The same thing to read: "H H H H H F F F D D R P D ...".'
    )
    canonical_fingerprint: str
    canonical_fingerprint_display: str
    group_counts: list[WalkGroupCountOut] = Field(
        description="File against canonical, per family. This is the multiset test."
    )
    multiset_matches: bool = Field(
        description="True when every family appears as often as it does canonically."
    )
    walk_order_verified: bool = Field(
        description=(
            "D-90-7. True when the leading numbers ascend within every "
            "vehicle and the panels first appear in walk order. **Checked, "
            "not assumed**: where it is false rule (a) is withheld entirely "
            "and every row is red, and the sheet is still never refused "
            "(D-90-13)."
        )
    )
    walk_order_reason: str
    rule_group_ordinal_available: bool
    rule_group_ordinal_reason: str = Field(
        description="Why rule (a) does or does not apply, in plain words."
    )
    rule_walk_number_available: bool
    rule_walk_number_reason: str
    disagreements: list[str] = Field(
        default_factory=list,
        description=(
            "D-90-2. Names the two rules answer differently. When this is "
            "not empty **no** row of the set is yellow: a disagreement is "
            "information about the whole alignment, not noise on one line."
        ),
    )
    fingerprint_moved: bool = Field(
        description=(
            "True when a set was confirmed before and this file does not "
            "walk it."
        )
    )
    confirmed_before: bool = Field(
        description="True when any walk has been confirmed for this plant x model."
    )
    confirmed_source_file: str | None = Field(default=None)
    confirmed_at: datetime | None = Field(default=None)
    confirmed_load_id: int | None = Field(
        default=None,
        description=(
            "The batch the remembered set was confirmed on. D-90-11: a "
            "confirmed **rough** mapping lives on the batch and nowhere "
            "else, because nothing on the resolution path can read a batch."
        ),
    )
    yellow_count: int = Field(ge=0)
    red_count: int = Field(
        ge=0,
        description=(
            "D-90-14. Bulk accept confirms the yellow rows only and reports "
            "both numbers -- '28 accepted, 4 still need you'. A red is never "
            "swept along."
        ),
    )
    operator_message: str = Field(
        min_length=1,
        max_length=800,
        description=(
            "D-90-5. What one click would do, in the owner's words -- *same "
            "walk as September, confirmed 9 Oct, accept all 32* -- or why "
            "there is no such click yet. Never silence: even an unchanged "
            "walk is confirmed, once, by a person."
        ),
    )
    rows: list[WalkRowOut] = Field(
        description="One per distinct name the file writes, in walk order."
    )


class LivePanelOut(StrictModel):
    """One live panel of this plant x model (`ref_plant_ws_point`)."""

    zone_code: str
    point_no: int = Field(ge=1)
    tolerance_group: str
    note: str | None = Field(
        default=None,
        description=(
            "The panel row's own note, which is the only provenance a person "
            "has for telling one block of panels from another. Shown so the "
            "owner can see what they are retiring; never parsed."
        ),
    )
    already_used: bool = Field(
        default=False,
        description=(
            "T88. True when this batch has already loaded rows onto this "
            "panel, so it is spoken for by this very file. It is still "
            "shown -- the owner can see where each panel went -- but it is "
            "out of the pool the solver proposes from."
        ),
    )
    mappable: bool = Field(
        description=(
            "True when a confirmed pair may point at this panel. False when "
            "`ref_plant_zone_map` cannot reference it -- see "
            "`not_mappable_reason`."
        )
    )
    not_mappable_reason: str | None = Field(
        default=None,
        description=(
            "Why this live panel cannot be a match target, in plain words. "
            "Null when `mappable` is true."
        ),
    )


class PanelMatchOut(StrictModel):
    """Everything the guided match screen needs for one batch and model."""

    plant_code: str
    model_code: str
    load_id: int = Field(ge=1)
    source_sheet: str = Field(description="The tab the held rows are on.")
    batch_status: str = Field(description="The batch's status, for the UI's own gating.")
    held_panels: list[HeldPanelOut] = Field(
        description="One per distinct held panel spelling, busiest first."
    )
    live_panels: list[LivePanelOut] = Field(
        description="This plant x model's live panels, in walk order."
    )
    min_score: float = Field(
        default=MIN_SCORE,
        description="The score floor a candidate had to clear, so the UI can say so.",
    )
    catalogue_warning: str | None = Field(
        default=None,
        description=(
            "T88 (G-88-2). Set when this plant x model's live panel count "
            "does not equal the number of panels the file walks -- FTM today "
            "is 64 against 32 -- naming both numbers. The screen shows it "
            "**before** any exhaustion claim, because exhaustion is only "
            "sound over a closed pool. Null when the two agree."
        ),
    )
    walk: WalkMatchOut | None = Field(
        default=None,
        description=(
            "T90. The structural reading of this `(plant, model)`'s walk: "
            "the fingerprint, which rules apply and why, and a colour and a "
            "reason for every name the file writes. Null when the sheet "
            "writes no panel name for this model, or when the model has no "
            "canonical list to align against."
        ),
    )
    orientation_conflicts: list[str] = Field(
        default_factory=list,
        description=(
            "T88 (G-88-5). Spellings whose own rows disagree about Tolerance "
            "Group. A file problem, flagged rather than guessed around."
        ),
    )
    operator_message: str = Field(
        min_length=1,
        max_length=800,
        description="What this screen is for, in the uploader's own words.",
    )


__all__ = [
    "BlockedPanelOut",
    "WalkGroupCountOut",
    "WalkMatchOut",
    "WalkRowOut",
    "CarriedOverOut",
    "HeldPanelOut",
    "LivePanelOut",
    "PanelCandidateOut",
    "PanelMatchOut",
]
