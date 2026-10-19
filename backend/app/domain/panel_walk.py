"""T90: the walk is the identity, the name is only a label.

The owner asked the operator who physically walks the panels why
September's file has five panels all called ``HOOD`` with no position.
**They are the same five hood positions, walked in the same order, every
month.** The label changed; the walk did not.

Measured on three months of real FTM files, that is exactly right. The
spellings move around and the *structure* stays:

    group      canonical  September  August (as written)
    HOOD           5          5          5
    FENDER         6          6          6
    DOOR           6          6          8   <- differs
    ROOF           2          2          2
    PILLAR         2          2          0   <- differs
    BOX            6          6          6
    TAILGATE       5          5          5

September's group multiset equals the canonical multiset, so the Nth
occurrence of a group in the file's own walk order is that group's Nth
canonical point -- **rule (a)**. August's does not, because two of its
pillars are spelled as doors; what August has instead is a numbering that
*is* the canonical walk, so the label numbered k is canonical point k --
**rule (b)**. Anything else falls through to T88's name, orientation and
exhaustion candidates -- **rule (c)**.

This module is the rules and nothing else. It decides nothing: every pair
it produces is **yellow** ("looks right, still confirm") or **red** ("needs
attention"), there is no green, and a person confirms every one of them
(D-90-5, D-90-6). Pure: no FastAPI, no psycopg.

What each locked decision is, in code
-------------------------------------

* **D-90-1** -- two rules and a test for which applies, computed per
  ``(plant, model)``. :func:`rule_group_ordinal` and
  :func:`rule_walk_number` each state their own precondition and refuse
  themselves when it does not hold; :func:`match_walk` never picks between
  them by preference.
* **D-90-2** -- where both are available and they disagree, **nothing** is
  proposed as correct. Both answers are carried on the row, the row is red,
  and so is every other row of the set: a disagreement is information about
  the whole alignment, not noise on one line.
* **D-90-3** -- :func:`classify_specificity`. A label is **rough** when its
  name-core is shared with another label of the same ``(plant, model)``
  sheet, because then the number is doing the identifying. Only the
  **specific** ones may ever become permanent aliases; the caller enforces
  that at the write boundary.
* **D-90-4** -- :func:`fingerprint` is the ordered sequence of **groups**,
  never the spellings, so a respelling does not invalidate a confirmed walk
  while a reshuffle does.
* **D-90-7 / D-90-13** -- :func:`verify_walk_order` is *checked*, per
  vehicle, from the leading numbers. Where it cannot be verified rule (a)
  is withheld entirely and every row is red. The sheet is never refused.
* **D-90-8** -- :func:`side_hint`. Where the file's label and the proposed
  canonical name both carry a side, they must agree.
* **D-90-12** -- a group no label of which carries a side has nothing to
  cross-check. It is red the first time a fingerprint is seen and yellow
  afterwards while that fingerprint holds, pre-filled with the earlier
  answer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Collection, Mapping, Sequence

from app.domain.panel_match import name_core, read_position
from app.domain.references import normalise_alias
from app.domain.ws_plant_gold import gold_key, ws_panel_match

#: The two attention levels the owner named, and the only two there are
#: (D-90-6). There is no green: a clean rule still earns a confirmation.
ATTENTION_YELLOW = "yellow"
ATTENTION_RED = "red"

#: Which rule produced a proposal (D-90-1). ``none`` is rule (c): no
#: structural rule applies and T88's candidates are all there is.
RULE_GROUP_ORDINAL = "group_ordinal"
RULE_WALK_NUMBER = "walk_number"
RULE_NONE = "none"

#: D-90-3. ``rough`` means the name alone does not name a position.
SPECIFICITY_ROUGH = "rough"
SPECIFICITY_SPECIFIC = "specific"

#: T91 (D-91-3). How far a confirmed pair is allowed to travel, said in
#: the data rather than in a comment. ``alias`` is a permanent
#: `ref_plant_zone_map` row -- the name identifies the panel at this plant
#: for good. ``batch`` is confirmed for the upload being reviewed and
#: recorded on it (D-90-11); nothing on the resolution path can read it.
#: Two things make a pair ``batch``: the sheet's own specificity test
#: (D-90-3, a rough name), and the plant's history (D-91-2, a name another
#: sheet of this plant confirmed as a different panel). The second one
#: outranks the first in both directions: a *specific* name that
#: contradicts a prior confirmation is still ``batch``.
BINDING_ALIAS = "alias"
BINDING_BATCH = "batch"

#: Letters that claim a side. Everything else -- ``C`` for a centre hood,
#: ``F`` for ``FTFDOOR`` -- claims none, and a side that is not claimed is
#: never cross-checked against one that is (D-90-8).
_SIDES = {"L": "L", "R": "R"}


@dataclass(frozen=True)
class WalkRow:
    """One projection row of the sheet, in the order the file wrote it."""

    source_row: int
    raw_zone_text: str
    #: What tells one walk from the next: the vehicle the reading is of.
    #: Serial number and measured date together, because the same serial
    #: walks more than once in a month.
    vehicle: str = ""


@dataclass(frozen=True)
class CanonicalPoint:
    """One point of the model's canonical list, with its walk number."""

    zone_code: str
    point_no: int
    #: RO19: measuring rank; None keeps legacy in-memory fixtures ordered.
    walk_rank: int | None = None


@dataclass(frozen=True)
class WalkLabel:
    """One distinct label the file wrote, with what can be read off it."""

    raw_zone_text: str
    #: The panel family (``ws_panel_group``), or None when the name has none.
    group: str | None
    #: The label's own leading number, or None.
    position: int | None
    #: ``L``, ``R`` or None -- read from the letters in front of the family
    #: word, never from the first letter of the whole name.
    side: str | None
    #: Where it first appears, which is this label's place in the walk.
    first_row: int
    #: How many rows carry it.
    rows: int = 0


@dataclass(frozen=True)
class RuleOutcome:
    """One rule's answer, or its refusal to answer, in plain words."""

    rule: str
    available: bool
    #: Why it does or does not apply, for a person to read.
    reason: str
    #: ``{raw_zone_text: zone_code}``. Empty when `available` is false.
    pairs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WalkVerdict:
    """What the screen shows for one label: a colour and a reason."""

    raw_zone_text: str
    specificity: str
    group: str | None
    side: str | None
    #: What the rules agree this label is, or None.
    proposed_zone_code: str | None
    rule: str
    attention: str
    reason: str
    #: Each rule's own answer, carried so a disagreement can be shown whole.
    rule_a_zone_code: str | None = None
    rule_b_zone_code: str | None = None
    #: True when both sides carried a side and they were compared (D-90-8).
    side_hint_checked: bool = False
    #: The answer confirmed last under this same fingerprint, pre-filled.
    prefilled_zone_code: str | None = None


@dataclass(frozen=True)
class WalkMatch:
    """The whole structural reading of one ``(plant, model)``."""

    fingerprint: tuple[str, ...]
    canonical_fingerprint: tuple[str, ...]
    labels: tuple[WalkLabel, ...]
    verdicts: tuple[WalkVerdict, ...]
    rule_a: RuleOutcome
    rule_b: RuleOutcome
    multiset_matches: bool
    walk_order_verified: bool
    walk_order_reason: str
    #: Labels the two rules answer differently (D-90-2).
    disagreements: tuple[str, ...] = ()
    #: The fingerprint the remembered set was confirmed under, or None.
    remembered_fingerprint: tuple[str, ...] | None = None
    #: True when a set was remembered and this walk is not it (D-90-6).
    fingerprint_moved: bool = False

    @property
    def yellow(self) -> tuple[WalkVerdict, ...]:
        return tuple(v for v in self.verdicts if v.attention == ATTENTION_YELLOW)

    @property
    def red(self) -> tuple[WalkVerdict, ...]:
        return tuple(v for v in self.verdicts if v.attention == ATTENTION_RED)

    def by_spelling(self) -> dict[str, WalkVerdict]:
        return {v.raw_zone_text: v for v in self.verdicts}


# --------------------------------------------------------------------------
# Reading a label
# --------------------------------------------------------------------------


def label_group(label: str) -> str | None:
    """The panel family of this name, or None when the name has none."""
    try:
        return ws_panel_match(label)[1]
    except ValueError:
        return None


def side_hint(label: str) -> str | None:
    """``L``, ``R`` or None, from the letters in front of the family word.

    This is the one place a side may be read, and the reason it is not the
    first letter of the name is ``ROOF``: a bare roof claims no side, and
    reading its ``R`` would silently make every roof a right-hand panel and
    then "catch" a left-hand one as a contradiction. ``LCROOF`` claims a
    side; ``ROOF``, ``HOOD`` and ``TGATE`` claim none.

    A letter that is not ``L`` or ``R`` -- ``CFHOOD``, ``FTFDOOR`` -- claims
    nothing either. An unclaimed side is never compared against a claimed
    one (D-90-8).
    """
    try:
        keyword, _ = ws_panel_match(label)
    except ValueError:
        return None
    compact = "".join(ch for ch in str(label).upper() if ch.isalpha())
    at = compact.find(keyword)
    if at <= 0:
        # The name *is* the family word, or the keyword was matched as a
        # standalone word we cannot locate in the compacted name. Either
        # way there is no prefix to read, and inventing one is the bug.
        return None
    return _SIDES.get(compact[0])


def read_walk(rows: Sequence[WalkRow]) -> tuple[WalkLabel, ...]:
    """The distinct labels of one ``(plant, model)``, in walk order.

    Walk order is **first appearance** in the file, which is what rule (a)
    reads. The count is every row carrying the label, across every vehicle,
    so a vehicle with a missing reading does not change the set (the
    multiset is over distinct labels, never per vehicle).
    """
    first: dict[str, WalkRow] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        text = (row.raw_zone_text or "").strip()
        if not text:
            continue
        key = normalise_alias(text)
        counts[key] += 1
        if key not in first:
            first[key] = WalkRow(row.source_row, text, row.vehicle)
    return tuple(
        WalkLabel(
            raw_zone_text=row.raw_zone_text,
            group=label_group(row.raw_zone_text),
            position=read_position(row.raw_zone_text),
            side=side_hint(row.raw_zone_text),
            first_row=row.source_row,
            rows=counts[key],
        )
        for key, row in sorted(first.items(), key=lambda kv: kv[1].source_row)
    )


def fingerprint(labels: Sequence[WalkLabel]) -> tuple[str, ...]:
    """D-90-4: the ordered sequence of **groups**, not the spellings.

    A label whose name has no family contributes ``?``: it is part of the
    walk and the fingerprint must move if it appears or goes away, but it
    cannot claim a group it does not have.
    """
    return tuple(label.group or "?" for label in labels)


def in_walk_order(points: Sequence[CanonicalPoint]) -> list[CanonicalPoint]:
    """The list in measuring order. One rule, so every walk rule agrees."""
    return sorted(points, key=lambda p: p.walk_rank if p.walk_rank is not None else p.point_no)


def canonical_fingerprint(points: Sequence[CanonicalPoint]) -> tuple[str, ...]:
    """The canonical list's own group sequence, in walk-number order."""
    return tuple(label_group(point.zone_code) or "?" for point in in_walk_order(points))


def fingerprint_text(groups: Sequence[str]) -> str:
    """The stored form: unambiguous, and stable across a respelling."""
    return "|".join(groups)


def fingerprint_initials(groups: Sequence[str]) -> str:
    """The short form the owner reads: ``H H H H H F F F D D R P ...``."""
    return " ".join((group or "?")[0] for group in groups)


def group_counts(groups: Sequence[str]) -> dict[str, int]:
    return dict(Counter(groups))


def classify_specificity(labels: Sequence[WalkLabel]) -> dict[str, str]:
    """D-90-3: rough when the name-core is shared, specific when it is not.

    ``01HOOD`` .. ``05HOOD`` all have the core ``hood``, so the **number**
    is doing the identifying and none of the five names a position. Those
    are rough, and a rough label must never become a permanent alias: the
    month the plant reshuffles its walk, a learned ``01HOOD -> RRHOOD``
    would file a hood as the wrong hood with no error anywhere.

    ``12LCPILLAR`` shares its core with nothing in the sheet, so the name
    alone names the position. That one is safe to learn forever.
    """
    cores = Counter(name_core(label.raw_zone_text) for label in labels)
    return {
        label.raw_zone_text: (
            SPECIFICITY_ROUGH
            if cores[name_core(label.raw_zone_text)] > 1
            else SPECIFICITY_SPECIFIC
        )
        for label in labels
    }


def leads_with_number(label: str) -> bool:
    """T96 (D-96-1): does the file write a walk position in front of the name?

    ``06LFFFEND``, ``01 RRHOOD``, ``17TGATE`` -- yes. ``LCPILLAR`` -- no.
    Read off the text and nothing else, so a number outside
    :func:`panel_match.read_position`'s 1..40 provenance range still counts:
    the question here is only whether the plant is numbering its walk.
    """
    return str(label).strip()[:1].isdigit()


def is_canonical_panel(label: str, zone_codes: Collection[str]) -> str | None:
    """The canonical panel this label **is the name of**, or None.

    Compared with `gold_key` -- trim, case-fold, and the leading-zero pad
    the gold list already treats as one point (``01HOOD`` == ``1HOOD``,
    D-58-03) -- and with nothing else. So this is the plant's own catalogue
    identity for the panel, numbers and all.

    It is the first thing D-94-1 asks, and it has to be, because **at some
    plants the number IS the name**. FVL's ``CX743`` catalogue is
    ``1HOOD``..``5HOOD``, ``11LFRTDOOR``, ``12LFRTDOOR``: those are the
    model's own 32 positions, so ``11LFRTDOOR`` names exactly one panel and
    is as specific as ``LCPILLAR`` is at FTM. Reading the number off it and
    then calling it vague because ``12LFRTDOOR`` shares the remaining
    letters would hold a whole FVL file for a question that has no answer --
    there is nothing to disambiguate it to.

    This is also the line D-94-2 draws. FTM has a **live** panel spelled
    ``01HOOD`` and that one does not count, because it is not on the model's
    own catalogue (`ref_model_zone`) and so is not canonical: it is the T58
    numbered block, the accident that made ``01HOOD`` read "Ready to add".
    A panel spelled like the label saves the label only when the label is
    one of the model's positions.
    """
    key = gold_key(label)
    for zone in zone_codes:
        if gold_key(zone) == key:
            return zone
    return None


def names_canonical_panel(label: str, zone_code: str) -> bool:
    """T94 (D-94-1): does this label's **name** name this canonical panel?

    True when the label **is** the panel's name (`gold_key`, above), and
    true when the label's name with its leading number dropped is the
    **tail** of the panel's name and the panel family agrees -- ``hood`` is
    the tail of ``rrhood``, ``rfhood``, ``cfhood``, ``lfhood`` and
    ``lrhood``, so ``01HOOD`` names five panels and therefore names none of
    them.

    The second clause is the whole of the owner's complaint, said once: a
    generic word with a number in front of it is a *family* plus a position,
    and the position is not in the name. ``LFFENDER`` is not the tail of
    ``RFFENDER`` (the ``L`` is part of the name), so ``06LFFENDER`` still
    names exactly one panel.

    The family gate is `ws_panel_match`'s, the same one T86 uses, so a tail
    match across families cannot happen: nothing here can make ``ROOF`` a
    near-miss of ``LFBOXSD``.

    Deliberately one-directional. A label *longer* than the canonical name
    (``16RTRDOOR`` against ``RCRDOOR``) is not matched here: that is a
    spelling question for the match screen, not the rough/specific question,
    and answering it with a tail test would make every long name rough.
    """
    if gold_key(label) == gold_key(zone_code):
        return True
    core = name_core(label)
    target = name_core(zone_code)
    if not core or not target or not target.endswith(core):
        return False
    family = label_group(label)
    return family is not None and family == label_group(zone_code)


def canonical_named_by(
    label: str, zone_codes: Collection[str]
) -> tuple[str, ...]:
    """Every canonical panel this label's name names, in name order."""
    return tuple(
        sorted(zone for zone in zone_codes if names_canonical_panel(label, zone))
    )


def classify_against_canonical(
    labels: Sequence[str], zone_codes: Collection[str]
) -> dict[str, str]:
    """T94 (D-94-1): rough / specific for every label of one (plant, model).

    **First, and before either condition: a label that IS one of the
    model's own canonical names is specific** (:func:`is_canonical_panel`).
    D-94-1 asks whether the name identifies exactly one *canonical panel*,
    and a name that is on the list identifies the panel it is. At FVL the
    catalogue is ``1HOOD``..``5HOOD``, so the number is the name there; at
    FTM the canonical names are ``RRHOOD``..``LRHOOD`` and the live
    ``01HOOD`` is the T58 numbered block, which is not a position on the
    model and therefore saves nothing (D-94-2).

    Then three conditions, **any** of them sufficient, and this is the
    locked rule:

    (0) **T96, D-96-1: the label leads with a number and its name does not
        name exactly one canonical panel.** A plant that numbers its walk
        is writing the position in front of a loose word for the panel, so
        the word is not the identity: on the owner's August file
        ``25RTRDOOR`` is ``RCPILLAR`` and ``13LFRDOOR`` is ``LCPILLAR``,
        both confirmed by the owner, and the number was the only truthful
        part of each. This is the hole T94 left open -- ``06LFFFEND``,
        ``16LFBOXS``, ``25RTRDOOR`` and ``26RTRDOO`` are FTM's own
        truncated spellings: they name **no** canonical panel and their
        siblings are truncated differently, so neither (a) nor (b) fired
        and each one matched the live T58 panel spelled exactly like it.
        No sibling test is needed and "the list cannot name it so it must
        be unknown" does not apply.

        A numbered label whose name still names exactly one panel --
        ``01 RRHOOD``, ``12LCPILLAR`` -- is **specific**: the name says the
        position and the number in front of it is provenance. Measured with
        the owner 2026-10-10 against the alternative, which held every
        numbered label at all four plants including the 534 rows of the
        August spaced block that load correctly today.

    (a) the name, number dropped, names **more than one** canonical panel of
        this ``(plant, model)``. ``01HOOD`` names five hoods, so it names no
        hood, and it is rough **even when it is the only label on the
        sheet**. That is what :func:`classify_specificity` could not see:
        T90's test is per sheet, so a sheet carrying only ``01HOOD`` came
        out "specific" and loaded as ``01HOOD`` -- the bug T94 exists to
        stop.

    (b) **another label of the same sheet reduces to the same name.**
        ``06``/``07``/``08LFFENDER`` all reduce to ``lffender``, only one
        panel is ``LFFENDER``, and the number is doing the identifying. This
        is T90's D-90-3 rule, reused unchanged.

    Anything else is **specific**: the name on its own names one panel here,
    or it names none and is a spelling question for the match screen. Note
    that "names none" is specific on purpose -- a label the canonical list
    has no name for is not vague, it is unknown, and the honest answer to it
    is the existing hold rather than a confirmation with nothing to propose.
    Since T96 that exception survives only for a label with **no leading
    number** (D-96-1), and a pair with no canonical list still claims
    nothing at all (T89 Part 1).

    Keyed by the label text as given. Computed per ``(plant, model)``, never
    per sheet alone (D-94-1).
    """
    shared = Counter(name_core(label) for label in labels)
    out: dict[str, str] = {}
    for label in labels:
        if is_canonical_panel(label, zone_codes) is not None:
            # The label IS one of this model's positions, so it identifies
            # exactly one panel and neither condition can apply: there is
            # nothing to disambiguate it to. This is what keeps FVL's
            # numbered catalogue specific while FTM's `01HOOD` -- live, but
            # not a position on the model -- stays rough.
            out[label] = SPECIFICITY_SPECIFIC
            continue
        rough = (
            # D-96-1: once the file writes a position in front of the
            # name, the name is the plant's loose word for the panel and
            # not its identity -- unless the name still names exactly one
            # canonical panel on its own, in which case it is that panel
            # and the number in front of it is provenance (owner, 2026-10-10,
            # on the measurement below). `06LFFFEND`, `16LFBOXS`,
            # `25RTRDOOR` and `26RTRDOO` name NONE: FTM's numbered block is
            # stored truncated, their siblings are truncated differently,
            # and so neither (a) nor (b) fired and each matched the live
            # T58 panel spelled exactly like it. On the same file the
            # number is the only truthful part -- `25RTRDOOR` is
            # `RCPILLAR` and `13LFRDOOR` is `LCPILLAR`, both confirmed by
            # the owner. Guarded by `zone_codes` because a pair with no
            # canonical list makes no claim either way (T89 Part 1).
            bool(
                zone_codes
                and leads_with_number(label)
                and len(canonical_named_by(label, zone_codes)) != 1
            )
            or len(canonical_named_by(label, zone_codes)) > 1
            or shared[name_core(label)] > 1
        )
        out[label] = SPECIFICITY_ROUGH if rough else SPECIFICITY_SPECIFIC
    return out


def verify_walk_order(rows: Sequence[WalkRow]) -> tuple[bool, str]:
    """D-90-7: are this sheet's rows in walk order? Checked, never assumed.

    The operator's "we always walk the same order" is a claim to be tested
    per file, not trusted. The test is the one D-90-7 names: **within every
    vehicle the rows never go backwards**, except at a clean restart of the
    walk. Every row must carry a leading number, or there is nothing to
    check the order against.

    The restart allowance is not a loophole; it is the real September file.
    It walks one vehicle identity twice -- the same date, colour, serial
    and booth, 32 points and then 24 more -- which the platform's own
    `identity_of` cannot tell apart either. A second pass is allowed when
    it begins at the lowest number that vehicle writes. Anything else going
    backwards inside a vehicle is not a pass; it is a sort, and the real
    July sheet is one: it lists its panels by family, so ``06 LFFender``
    arrives after ``27 RCRoof``.

    Where this fails, rule (a) is withheld entirely and every row keeps
    T88's candidates and stays red (D-90-13). The sheet is never refused.

    **What this does not promise.** Rule (a) reads *first-appearance* order,
    and when a vehicle is partial a lower-numbered panel can first appear
    later than a higher-numbered one even though every vehicle ascends. The
    answer to that is not to withhold rule (a) -- it is D-90-2: rule (b) is
    then available too, the two disagree, and the row goes red showing both.
    A disagreement is information.
    """
    if not rows:
        return False, "the sheet has no rows for this model, so nothing can be checked"
    per_vehicle: dict[str, list[tuple[int, int | None, str]]] = {}
    for row in rows:
        text = (row.raw_zone_text or "").strip()
        if not text:
            continue
        per_vehicle.setdefault(row.vehicle, []).append(
            (row.source_row, read_position(text), text)
        )
    if not per_vehicle:
        return False, "no row of this model carries a panel name"

    passes = 0
    for vehicle, entries in sorted(per_vehicle.items()):
        entries.sort(key=lambda item: item[0])
        unnumbered = [text for _, position, text in entries if position is None]
        if unnumbered:
            return False, (
                f"{unnumbered[0]!r} carries no walk number, so the order of "
                f"this sheet cannot be checked against one"
            )
        lowest = min(position for _, position, _ in entries if position is not None)
        previous: int | None = None
        passes += 1
        for _, position, text in entries:
            assert position is not None
            if previous is not None and position <= previous:
                if position != lowest:
                    return False, (
                        f"the rows are not in walk order: {text!r} comes "
                        f"after number {previous}"
                        + (f" for vehicle {vehicle}" if vehicle else "")
                        + ", and it does not begin a new pass of the walk"
                    )
                passes += 1
            previous = position

    vehicles = len(per_vehicle)
    return True, (
        f"the leading numbers ascend within every vehicle ({vehicles} "
        f"vehicle{'' if vehicles == 1 else 's'}, {passes} pass"
        f"{'' if passes == 1 else 'es'} checked)"
    )


# --------------------------------------------------------------------------
# The two rules
# --------------------------------------------------------------------------


def rule_group_ordinal(
    labels: Sequence[WalkLabel],
    points: Sequence[CanonicalPoint],
    *,
    walk_order_ok: bool,
    walk_order_reason: str = "",
) -> RuleOutcome:
    """Rule (a): the Nth occurrence of a group is that group's Nth point.

    Available only when the file's group multiset **equals** the canonical
    multiset -- every group present the same number of times -- and only
    when the sheet's walk order has been verified (D-90-7). Equality of the
    multiset is what makes the ordinals mean anything: with six doors
    against six doors the third door of the walk is the third canonical
    door, and with eight against six it is not the third of anything.
    """
    if not walk_order_ok:
        return RuleOutcome(
            RULE_GROUP_ORDINAL,
            False,
            "withheld: this rule is about walk order and "
            + (walk_order_reason or "the sheet's walk order could not be verified")
            + " (D-90-7, D-90-13)",
        )
    file_counts = group_counts(fingerprint(labels))
    canon_counts = group_counts(canonical_fingerprint(points))
    if file_counts != canon_counts:
        differs = sorted(
            set(file_counts) | set(canon_counts),
            key=lambda group: group,
        )
        detail = ", ".join(
            f"{group} {file_counts.get(group, 0)} in the file against "
            f"{canon_counts.get(group, 0)} canonical"
            for group in differs
            if file_counts.get(group, 0) != canon_counts.get(group, 0)
        )
        return RuleOutcome(
            RULE_GROUP_ORDINAL,
            False,
            f"does not apply: the file's groups are not the canonical groups "
            f"({detail})",
        )

    by_group: dict[str, list[str]] = {}
    for label in labels:
        by_group.setdefault(label.group or "?", []).append(label.raw_zone_text)
    canon_by_group: dict[str, list[str]] = {}
    for point in in_walk_order(points):
        canon_by_group.setdefault(
            label_group(point.zone_code) or "?", []
        ).append(point.zone_code)

    pairs: dict[str, str] = {}
    for group, spellings in by_group.items():
        for spelling, zone_code in zip(spellings, canon_by_group[group]):
            pairs[spelling] = zone_code
    return RuleOutcome(
        RULE_GROUP_ORDINAL,
        True,
        "the file walks the canonical groups in the canonical numbers "
        f"({len(labels)} names, {len(points)} canonical points), and "
        + (walk_order_reason or "the rows are in walk order"),
        pairs,
    )


def rule_walk_number(
    labels: Sequence[WalkLabel], points: Sequence[CanonicalPoint]
) -> RuleOutcome:
    """Rule (b): the label numbered k is canonical point k.

    This is August, "where the names are lossy but the numbering **is** the
    canonical walk" (D-90-1). Both halves of that sentence are checked:

    * the numbering spans exactly ``1..N`` against ``N`` canonical points;
    * the numbering really is the canonical walk -- every label lands on a
      point of its own group, **except** where the file's own group counts
      explain it. August spells two of its pillars as doors, so it carries
      two doors too many and two pillars too few; the only mismatches rule
      (b) may produce there are doors landing on pillar points, and there
      must be exactly as many of them as that discrepancy.

    The second check is what keeps September off this rule. September's
    multiset matches the canonical multiset exactly, so no mismatch is
    excused -- and September's numbering is a *different* walk order from
    the canonical one, which would put ``14ROOF`` on ``LFBOX``. It is
    refused here rather than offered and argued with later.
    """
    n = len(points)
    if not labels or not n:
        return RuleOutcome(
            RULE_WALK_NUMBER, False, "does not apply: there is nothing to align"
        )
    if len(labels) != n:
        return RuleOutcome(
            RULE_WALK_NUMBER,
            False,
            f"does not apply: the file writes {len(labels)} names against "
            f"{n} canonical points",
        )
    numbers = [label.position for label in labels]
    if any(number is None for number in numbers):
        missing = next(
            label.raw_zone_text for label in labels if label.position is None
        )
        return RuleOutcome(
            RULE_WALK_NUMBER,
            False,
            f"does not apply: {missing!r} carries no walk number",
        )
    if sorted(n for n in numbers if n is not None) != list(range(1, n + 1)):
        return RuleOutcome(
            RULE_WALK_NUMBER,
            False,
            f"does not apply: the file's numbers do not span 1..{n} exactly",
        )

    # The file's number k is the k-th point of the measuring order, not the
    # point numbered k: after an order edit those differ, and the group rules
    # below already read the list in walk order.
    by_number = {
        rank: point.zone_code for rank, point in enumerate(in_walk_order(points), 1)
    }
    file_counts = group_counts(fingerprint(labels))
    canon_counts = group_counts(canonical_fingerprint(points))
    excess = {
        group: file_counts[group] - canon_counts.get(group, 0)
        for group in file_counts
        if file_counts[group] > canon_counts.get(group, 0)
    }
    deficit = {
        group: canon_counts[group] - file_counts.get(group, 0)
        for group in canon_counts
        if canon_counts[group] > file_counts.get(group, 0)
    }
    allowance = sum(excess.values())

    pairs: dict[str, str] = {}
    mismatched: list[str] = []
    for label in labels:
        assert label.position is not None
        zone_code = by_number[label.position]
        pairs[label.raw_zone_text] = zone_code
        point_group = label_group(zone_code) or "?"
        if (label.group or "?") == point_group:
            continue
        if (label.group or "?") not in excess or point_group not in deficit:
            return RuleOutcome(
                RULE_WALK_NUMBER,
                False,
                f"does not apply: by number {label.raw_zone_text!r} would be "
                f"{zone_code}, which is a {point_group} and not a "
                f"{label.group or 'panel of no family'}; the file's own group "
                f"counts do not explain that, so this numbering is not the "
                f"canonical walk",
            )
        mismatched.append(label.raw_zone_text)
    if len(mismatched) != allowance:
        return RuleOutcome(
            RULE_WALK_NUMBER,
            False,
            f"does not apply: {len(mismatched)} name(s) land on a point of "
            f"another group but the file's group counts differ by "
            f"{allowance}; the two do not account for each other",
        )
    detail = (
        ""
        if not mismatched
        else (
            ". The file's names and the canonical groups disagree on "
            + ", ".join(sorted(mismatched))
            + ", which is exactly how many its own group counts are out by"
        )
    )
    return RuleOutcome(
        RULE_WALK_NUMBER,
        True,
        f"the file's numbers span 1..{n} and the name numbered k lands on "
        f"canonical point k of its own group{detail}",
        pairs,
    )


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

_REASON_DISAGREE = (
    "the two rules disagree: group+ordinal says {a} and the walk number "
    "says {b}. Neither is proposed -- a disagreement is information, so you "
    "choose (D-90-2)"
)
_REASON_SET_DISAGREE = (
    "the two rules disagree about {count} name(s) in this set, so no row of "
    "it is taken on trust (D-90-2)"
)
_REASON_SIDE = (
    "the file calls this a {file_side}-hand panel and {zone} is a "
    "{zone_side}-hand one. A rule applied cleanly and the sides still "
    "disagree, which is what a group walked right-before-left looks like "
    "(D-90-8)"
)
_REASON_NO_RULE = (
    "no structural rule applies to this sheet, so there is nothing but the "
    "name candidates to go on"
)
_REASON_FIRST_TIME = (
    "this is the first time this walk has been seen for this plant and "
    "model, so nothing has been confirmed under it yet"
)
_REASON_NO_SIDE_FIRST = (
    "nothing in this group carries a side, so there is no left-against-right "
    "check to make -- and this is the first time this walk has been seen. "
    "Your answer is the evidence the data cannot supply (D-90-12)"
)
_REASON_MOVED = (
    "the walk has changed since the last confirmed set, so every name is "
    "open again (D-90-6)"
)
_REASON_NEW = (
    "this name was not in the set confirmed last under this walk, so the "
    "pair is new"
)
_REASON_CHANGED = (
    "the rule says {proposed} and the set confirmed last under this walk "
    "says {remembered}. The two do not agree"
)
#: T114 (D-114-4): the memory points at a panel that has left the live list.
_REASON_OFF_LIST = (
    "the set confirmed last under this walk says {remembered}, which is no "
    "longer a live point of this list (it was retired), so nothing is "
    "pre-filled -- say which point this is"
)
_REASON_YELLOW = (
    "{rule_words}, the side hint {side_words}, and it is what was confirmed "
    "last under this same walk. Looks right -- still confirm it"
)
_RULE_WORDS = {
    RULE_GROUP_ORDINAL: "the groups line up with the canonical groups",
    RULE_WALK_NUMBER: "the file's own number is this canonical point",
}


def match_walk(
    rows: Sequence[WalkRow],
    points: Sequence[CanonicalPoint],
    *,
    remembered: Mapping[str, str] | None = None,
    remembered_fingerprint: Sequence[str] | None = None,
) -> WalkMatch:
    """The whole structural reading of one ``(plant, model)``.

    ``remembered`` is the set confirmed last for this ``(plant, model,
    fingerprint)`` and ``remembered_fingerprint`` the walk it was confirmed
    under. They are a **pre-fill and a yellow licence**, never an answer:
    with nothing remembered every row is red, because yellow means "it is
    also what was confirmed last" and on a first sight there is no last
    (D-90-6, D-90-12).
    """
    labels = read_walk(rows)
    file_fingerprint = fingerprint(labels)
    canon_fingerprint = canonical_fingerprint(points)
    order_ok, order_reason = verify_walk_order(rows)
    rule_a = rule_group_ordinal(
        labels, points, walk_order_ok=order_ok, walk_order_reason=order_reason
    )
    rule_b = rule_walk_number(labels, points)
    specificity = classify_specificity(labels)

    # The stored keys are normalised (trim + case-fold), the same way
    # `ref_plant_zone_map.raw_zone_text` is, so the lookup normalises too:
    # a file that respells `01HOOD` as `01hood` is the same question.
    remembered = {
        normalise_alias(spelling): zone
        for spelling, zone in (remembered or {}).items()
    }
    confirmed_fingerprint = (
        tuple(remembered_fingerprint) if remembered_fingerprint is not None else None
    )
    moved = bool(remembered) and confirmed_fingerprint != file_fingerprint
    # T114 (D-114-4): a remembered answer is only ever a pre-fill onto a
    # point that is live now. `points` is the live canonical list, so an
    # answer onto a point retired since is dropped here and its row arrives
    # red and asked, never pre-filled onto the retired point.
    live_codes = {point.zone_code for point in points}
    off_list = {
        key: zone for key, zone in remembered.items() if zone not in live_codes
    }
    usable_memory = (
        {key: zone for key, zone in remembered.items() if key not in off_list}
        if (remembered and not moved)
        else {}
    )

    # Which groups have nothing to cross-check left against right (D-90-12).
    sided_groups = {
        label.group or "?" for label in labels if label.side is not None
    }

    disagreements = tuple(
        spelling
        for spelling in (
            set(rule_a.pairs) & set(rule_b.pairs) if rule_a.available and rule_b.available else ()
        )
        if rule_a.pairs[spelling] != rule_b.pairs[spelling]
    )

    verdicts: list[WalkVerdict] = []
    for label in labels:
        spelling = label.raw_zone_text
        key = normalise_alias(spelling)
        from_a = rule_a.pairs.get(spelling) if rule_a.available else None
        from_b = rule_b.pairs.get(spelling) if rule_b.available else None

        if from_a is not None and from_b is not None and from_a != from_b:
            verdicts.append(
                WalkVerdict(
                    raw_zone_text=spelling,
                    specificity=specificity[spelling],
                    group=label.group,
                    side=label.side,
                    proposed_zone_code=None,
                    rule=RULE_NONE,
                    attention=ATTENTION_RED,
                    reason=_REASON_DISAGREE.format(a=from_a, b=from_b),
                    rule_a_zone_code=from_a,
                    rule_b_zone_code=from_b,
                    prefilled_zone_code=usable_memory.get(key),
                )
            )
            continue

        proposed = from_a if from_a is not None else from_b
        rule = (
            RULE_GROUP_ORDINAL
            if from_a is not None
            else (RULE_WALK_NUMBER if from_b is not None else RULE_NONE)
        )
        zone_side = side_hint(proposed) if proposed else None
        side_checked = label.side is not None and zone_side is not None
        prefilled = usable_memory.get(key)

        reason, attention = _colour(
            label=label,
            proposed=proposed,
            rule=rule,
            zone_side=zone_side,
            side_checked=side_checked,
            sided_groups=sided_groups,
            remembered=usable_memory,
            remembered_any=bool(remembered),
            moved=moved,
            set_disagreements=disagreements,
            off_list=off_list,
        )
        verdicts.append(
            WalkVerdict(
                raw_zone_text=spelling,
                specificity=specificity[spelling],
                group=label.group,
                side=label.side,
                proposed_zone_code=proposed,
                rule=rule,
                attention=attention,
                reason=reason,
                rule_a_zone_code=from_a,
                rule_b_zone_code=from_b,
                side_hint_checked=side_checked,
                prefilled_zone_code=prefilled,
            )
        )

    return WalkMatch(
        fingerprint=file_fingerprint,
        canonical_fingerprint=canon_fingerprint,
        labels=labels,
        verdicts=tuple(verdicts),
        rule_a=rule_a,
        rule_b=rule_b,
        multiset_matches=group_counts(file_fingerprint)
        == group_counts(canon_fingerprint),
        walk_order_verified=order_ok,
        walk_order_reason=order_reason,
        disagreements=tuple(sorted(disagreements)),
        remembered_fingerprint=confirmed_fingerprint,
        fingerprint_moved=moved,
    )


def _colour(
    *,
    label: WalkLabel,
    proposed: str | None,
    rule: str,
    zone_side: str | None,
    side_checked: bool,
    sided_groups: set[str],
    remembered: Mapping[str, str],
    remembered_any: bool,
    moved: bool,
    set_disagreements: Sequence[str],
    off_list: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """The reason and the colour for one row, in the order they are tested.

    Red wins over yellow at every step, and yellow is reached only by
    passing all of them. Returned as words because the owner reads the
    reason, not the colour: "red" on its own is a demand without a case.
    """
    if set_disagreements:
        return (
            _REASON_SET_DISAGREE.format(count=len(set_disagreements)),
            ATTENTION_RED,
        )
    # T114 (D-114-4): said before "no rule", because it is the reason a
    # person can act on -- the answer they gave last time is gone.
    gone = (
        None if moved else (off_list or {}).get(normalise_alias(label.raw_zone_text))
    )
    if gone is not None:
        return _REASON_OFF_LIST.format(remembered=gone), ATTENTION_RED
    if proposed is None:
        return _REASON_NO_RULE, ATTENTION_RED
    if side_checked and label.side != zone_side:
        return (
            _REASON_SIDE.format(
                file_side=label.side, zone=proposed, zone_side=zone_side
            ),
            ATTENTION_RED,
        )
    if moved:
        return _REASON_MOVED, ATTENTION_RED
    if not remembered_any:
        if (label.group or "?") not in sided_groups:
            return _REASON_NO_SIDE_FIRST, ATTENTION_RED
        return _REASON_FIRST_TIME, ATTENTION_RED
    key = normalise_alias(label.raw_zone_text)
    if key not in remembered:
        return _REASON_NEW, ATTENTION_RED
    if remembered[key] != proposed:
        return (
            _REASON_CHANGED.format(
                proposed=proposed, remembered=remembered[key]
            ),
            ATTENTION_RED,
        )
    return (
        _REASON_YELLOW.format(
            rule_words=_RULE_WORDS.get(rule, "a rule applied"),
            side_words=(
                "agrees"
                if side_checked
                else "has nothing to compare here, and you confirmed it before"
            ),
        ),
        ATTENTION_YELLOW,
    )


__all__ = [
    "ATTENTION_RED",
    "ATTENTION_YELLOW",
    "CanonicalPoint",
    "RULE_GROUP_ORDINAL",
    "RULE_NONE",
    "RULE_WALK_NUMBER",
    "RuleOutcome",
    "SPECIFICITY_ROUGH",
    "SPECIFICITY_SPECIFIC",
    "WalkLabel",
    "WalkMatch",
    "WalkRow",
    "WalkVerdict",
    "canonical_fingerprint",
    "canonical_named_by",
    "classify_against_canonical",
    "classify_specificity",
    "fingerprint",
    "fingerprint_initials",
    "fingerprint_text",
    "group_counts",
    "is_canonical_panel",
    "label_group",
    "leads_with_number",
    "match_walk",
    "read_walk",
    "rule_group_ordinal",
    "rule_walk_number",
    "names_canonical_panel",
    "side_hint",
    "verify_walk_order",
]
