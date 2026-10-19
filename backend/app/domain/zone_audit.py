"""T28 -- safe P703 zone/model evidence pack (advisory only, no SQL).

This module produces **candidates for an owner to look at**, never a
mapping. Every ambiguity it can detect, it flags rather than resolves --
S15 forbids keyword/count/sequence activation, and a walk that "looks like"
32 unique checkpoints is not the same thing as a proved zone map.

Nothing here writes to a database, reads an Excel file, or imports
FastAPI/psycopg (`00-ARCHITECTURE.md` §5 rule 1; `AGENTS.md` §4). The one
piece of cleaning-rule logic this module needs -- how a raw spelling is
normalised before comparison -- is **imported**, not retyped, from
``app.domain.references`` (`AGENTS.md` rule 4).

Two frozen, code-sourced lookup tables live here, and both are transcribed
directly from files already in this repo, never from Excel and never
invented:

``FROZEN_ZONE_ALIASES``
    Copied from ``backend/migrations/sql/baseline/01_reference.sql``:
    every ``ref_checkzone_alias`` row (raw AAT/FTM spelling incl. leading
    zone number) and every ``ref_checkzone.zone_name`` display name, both
    normalised the same way the cleaner would. One entry is added that is
    not a literal row in that file but *is* the documented correction on
    it: the ``LTTAILGATE`` alias row's own note reads "source typo:
    Tailagte -> Tailgate", so the corrected display spelling ("LT
    Tailgate") and the undone typo ("LT Tailagte", without the leading
    zone number the source alias carries) both resolve to ``LTTAILGATE``.
    That is precisely the trap `T28-p703-evidence.md` §4.2 requires this
    pack to be able to flag: two raw spellings, one canonical target.

``FROZEN_MODEL_ALIASES``
    Copied from ``backend/migrations/versions/0009_...py``
    (``OWNER_LOCKED_RANGER_PLANTS``, ``ASSUMED_RANGER_SPELLINGS``): the one
    plant-scoped model lock the owner actually made, in code, already --
    bare ``P703`` / ``P703 DBL`` at **FVL** is ``P703 DBL RANGER``. SAP has
    no such row (S11: SAP writes ``P703 RAP``, which nothing here may call
    a Ranger), so a SAP walk's ``proposed_model_code`` is always ``None``.

Both tables are advisory exact-match lookups. A miss returns ``None``, not
a guess -- "If unsure, leave `proposed_zone_code` null" (task brief §3).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable

from app.domain.references import normalise_alias

# ---------------------------------------------------------------------
# Required flags (spec 2026-09-21 §4.2 / task brief §3)
# ---------------------------------------------------------------------

#: SAP writes tailgate checkpoints as "17LHS TG Top12" / "18LHS TG Bot13".
#: Sequence-matching already swapped Top/Bottom once (design doc §"Why this
#: exists"); this flag exists so nobody repeats that by pattern-matching a
#: position number instead of reading the word.
FLAG_SAP_TAILGATE = "SAP_TAILGATE_TOP_BOTTOM"

#: FVL's real Jan-Jul P703 export carries both "11ROOF" and "14ROOF" as
#: distinct raw Panel spellings on the same 32-walk. They are not the same
#: physical position (`01_reference.sql`: RCROOF is #27 on P703, #26 on
#: U704 -- FVL's own numbering is a third scheme again). Never resolved by
#: this module; only flagged.
FLAG_FVL_ROOF = "FVL_ROOF_11_VS_14"

#: FVL's real export also carries "25TGATE" among five consecutive
#: "*TGATE" rows (25-29). Which canonical tailgate/box zone each one is
#: cannot be decided by counting -- that is exactly the mis-pairing this
#: evidence pack exists to stop (design doc: "20 of 25 FVL verticals
#: wrong").
FLAG_FVL_TGATE = "FVL_25TGATE"

#: Two raw labels normalise to the same text. A walk that looks like 32
#: unique checkpoints but is actually 31 distinct ones plus a repeat is not
#: complete -- it is missing a checkpoint wearing a disguise.
FLAG_DUP_RAW = "DUPLICATE_NORMALISED_LABEL"

#: Two *different* raw spellings both look like a conservative match for
#: the same canonical zone (via ``FROZEN_ZONE_ALIASES``). Picking either
#: one is a guess about which spelling is the "real" one -- G1's job, not
#: this script's.
FLAG_TWO_CANDIDATES = "CANONICAL_HAS_TWO_RAW_CANDIDATES"

#: Every P703 variant has exactly 32 zones (`ref_model.expected_zone_count`
#: / `01_reference.sql`). A walk that is not exactly 32 unique normalised
#: labels is not a complete vehicle and must not be treated as one.
FLAG_NOT_32 = "WALK_NOT_32_UNIQUE"

#: Every P703 model variant this milestone is scoped to (spec P1). Fixed
#: by `ref_model` / `01_reference.sql`; this list is never derived from a
#: workbook.
P703_MODEL_CODES: tuple[str, ...] = (
    "P703 DBL RANGER",
    "P703 DBL RAPTOR",
    "P703 DBL SUPER DUTY",
)

#: Keys a nested structure must never carry into a committed artifact
#: (task brief §3 / spec §4.3): identity, measurement values, and any
#: named-person attribution before G1.
FORBIDDEN_KEYS = frozenset(
    {"serial", "serial_no", "cf", "lw", "sw", "doi", "named_owner", "verified_by"}
)


def _frozen_zone_aliases() -> dict[str, str]:
    """`ref_checkzone_alias` + `ref_checkzone.zone_name`, transcribed from
    `backend/migrations/sql/baseline/01_reference.sql`, normalised.

    This is the *only* source. Nothing here is read from a workbook, and
    nothing here is a new canonical target -- every zone_code below is one
    `01_reference.sql` already names.
    """
    # (raw_value, zone_code) -- backend/migrations/sql/baseline/01_reference.sql
    # lines ~187-227, `INSERT INTO ref_checkzone_alias`.
    alias_rows: tuple[tuple[str, str], ...] = (
        ("01 RRHOOD", "RRHOOD"), ("02 RFHOOD", "RFHOOD"),
        ("03 CFHOOD", "CFHOOD"), ("04 LFHOOD", "LFHOOD"),
        ("05 LRHOOD", "LRHOOD"),
        ("06 LFFender", "LFFENDER"), ("06LFFENDER", "LFFENDER"),
        ("07 LCFender", "LCFENDER"), ("08 LRFender", "LRFENDER"),
        ("09 LTFDoor", "LTFDOOR"), ("10 LCFDoor", "LCFDOOR"),
        ("11 LCRoof", "LCROOF"), ("12 LCRDoor", "LCRDOOR"),
        ("13 LCPillar", "LCPILLAR"),
        ("14 LFBoox", "LFBOX"),
        ("15 LCBox", "LCBOX"), ("16 LRBox", "LRBOX"),
        ("17 LTTailagte", "LTTAILGATE"),
        ("18 LBTailagte", "LBTAILGATE"),
        ("19 LCTailagate", "LCTAILGATE"),
        ("20 RBTailgate", "RBTAILGATE"), ("21RTTailgate", "RTTAILGATE"),
        ("22 RRBox", "RRBOX"), ("23 RCBox", "RCBOX"),
        ("24 RFBox", "RFBOX"), ("25 RCPillar", "RCPILLAR"),
        ("26 RCRDoor", "RCRDOOR"), ("27 RCRoof", "RCROOF"),
        ("28 RCFDoor", "RCFDOOR"), ("29 FTFDoor", "FTFDOOR"),
        ("30 RRFender", "RRFENDER"), ("31 RCFender", "RCFENDER"),
        ("32 RFFender", "RFFENDER"),
        ("14 RFENDER HI LH", "RFENDERHILH"),
        ("15 RFENDER MID LH", "RFENDERMIDLH"),
        ("16 RFENDER LOW LH", "RFENDERLOWLH"),
        ("17 Liftgate Hi LH", "LIFTGATEHILH"),
        ("18 Liftgate Low LH", "LIFTGATELOWLH"),
        ("19 Liftgate Low RH", "LIFTGATELOWRH"),
        ("20 Liftgate Hi RH", "LIFTGATEHIRH"),
        ("21 Rr Fen Low RH", "RRFENLOWRH"),
        ("22 Rr Fen Mid RH", "RRFENMIDRH"),
        ("23 Rr Fen Hi RH", "RRFENHIRH"),
        ("24 Rr Pillar RH", "RRPILLARRH"),
        ("25 Rr Door Mid RH", "RRDOORMIDRH"),
        ("26 RCROOF", "RCROOF"),
        ("27 Fr Door Mid RH", "FRDOORMIDRH"),
        ("28 Fr Door Hi RH", "FRDOORHIRH"),
        ("29 Fr Fen RH3", "FRFENRH3"),
        ("30 Fr Fen RH2", "FRFENRH2"),
        ("31 Fr Fen RH1", "FRFENRH1"),
    )
    # (zone_name, zone_code) -- same file, `INSERT INTO ref_checkzone`,
    # lines ~121-176 (columns are `zone_code, zone_name, ...`; reversed
    # here so this tuple unpacks the same way as `alias_rows` above:
    # `(raw spelling, zone_code)`).
    display_rows: tuple[tuple[str, str], ...] = (
        ("RR Hood", "RRHOOD"), ("RF Hood", "RFHOOD"), ("CF Hood", "CFHOOD"),
        ("LF Hood", "LFHOOD"), ("LR Hood", "LRHOOD"),
        ("LC Roof", "LCROOF"), ("RC Roof", "RCROOF"),
        ("LF Fender", "LFFENDER"), ("LC Fender", "LCFENDER"),
        ("LR Fender", "LRFENDER"),
        ("LT Front Door", "LTFDOOR"), ("LC Front Door", "LCFDOOR"),
        ("LC Rear Door", "LCRDOOR"), ("LC Pillar", "LCPILLAR"),
        ("LF Box", "LFBOX"), ("LC Box", "LCBOX"), ("LR Box", "LRBOX"),
        ("LT Tailgate", "LTTAILGATE"), ("LB Tailgate", "LBTAILGATE"),
        ("LC Tailgate", "LCTAILGATE"), ("RB Tailgate", "RBTAILGATE"),
        ("RT Tailgate", "RTTAILGATE"),
        ("RR Box", "RRBOX"), ("RC Box", "RCBOX"), ("RF Box", "RFBOX"),
        ("RC Pillar", "RCPILLAR"), ("RC Rear Door", "RCRDOOR"),
        ("RC Front Door", "RCFDOOR"), ("FT Front Door", "FTFDOOR"),
        ("RR Fender", "RRFENDER"), ("RC Fender", "RCFENDER"),
        ("RF Fender", "RFFENDER"),
        ("R Fender Hi LH", "RFENDERHILH"),
        ("R Fender Mid LH", "RFENDERMIDLH"),
        ("R Fender Low LH", "RFENDERLOWLH"),
        ("Liftgate Hi LH", "LIFTGATEHILH"),
        ("Liftgate Low LH", "LIFTGATELOWLH"),
        ("Liftgate Low RH", "LIFTGATELOWRH"),
        ("Liftgate Hi RH", "LIFTGATEHIRH"),
        ("Rr Fender Low RH", "RRFENLOWRH"),
        ("Rr Fender Mid RH", "RRFENMIDRH"),
        ("Rr Fender Hi RH", "RRFENHIRH"),
        ("Rr Pillar RH", "RRPILLARRH"),
        ("Rr Door Mid RH", "RRDOORMIDRH"),
        ("Fr Door Mid RH", "FRDOORMIDRH"),
        ("Fr Door Hi RH", "FRDOORHIRH"),
        ("Fr Fender RH1", "FRFENRH1"),
        ("Fr Fender RH2", "FRFENRH2"),
        ("Fr Fender RH3", "FRFENRH3"),
    )
    # One derived entry, not a literal row: `01_reference.sql`'s own
    # comment on the LTTAILGATE alias row reads
    #   -- src typo 'LTTailagte' ... note: 'source typo: Tailagte -> Tailgate'
    # i.e. the file already documents "Tailagte" as the typo of "Tailgate"
    # for *this* zone specifically. Registering the corrected wording
    # without the source row's leading zone number ("17 ") lets a plant
    # that writes either spelling bare (no leading number) resolve to the
    # same zone this file already names -- which is exactly the
    # `FLAG_TWO_CANDIDATES` trap task brief §3 asks this pack to prove it
    # can catch, using nothing invented.
    documented_typo_rows: tuple[tuple[str, str], ...] = (
        ("LT Tailagte", "LTTAILGATE"),
    )

    table: dict[str, str] = {}
    for raw, zone_code in (*alias_rows, *display_rows, *documented_typo_rows):
        table[normalise_alias(raw)] = zone_code
    return table


FROZEN_ZONE_ALIASES: dict[str, str] = _frozen_zone_aliases()


def _frozen_model_aliases() -> dict[tuple[str, str], str]:
    """Plant-scoped model locks already in migration code, transcribed
    from `backend/migrations/versions/0009_t26_wavescan_semantic_clean_layer.py`
    (`OWNER_LOCKED_RANGER_PLANTS`, `ASSUMED_RANGER_SPELLINGS`, `RANGER`).

    That revision inserts exactly these `(plant_code, raw_value) ->
    model_code` rows and then **deletes** the old plant-agnostic default,
    "because SAP -- whose `P703 RAP` is not a Ranger -- silently inherited
    an assumption nobody made about it." SAP therefore has no row here, on
    purpose, and this table must never grow a SAP entry from this module.
    """
    owner_locked_ranger_plants = ("FVL",)
    assumed_ranger_spellings = ("P703", "P703 DBL")
    ranger = "P703 DBL RANGER"
    table: dict[tuple[str, str], str] = {}
    for plant in owner_locked_ranger_plants:
        for spelling in assumed_ranger_spellings:
            table[(plant, normalise_alias(spelling))] = ranger
    return table


FROZEN_MODEL_ALIASES: dict[tuple[str, str], str] = _frozen_model_aliases()


def candidate_zone_code(normalised: str) -> str | None:
    """Conservative exact-match advisory lookup. ``None`` on any miss.

    Never a guess: the argument must already equal (post
    ``normalise_alias`` -- ``strip().casefold()``, exactly, no further
    transformation) one of the frozen spellings above, or nothing is
    returned.
    """
    return FROZEN_ZONE_ALIASES.get(normalised)


def candidate_model_code(plant_code: str, raw_model_spelling: str) -> str | None:
    """Conservative exact-match advisory lookup against the one
    plant-scoped model lock already in migration code (FVL only).

    SAP never resolves here -- there is no SAP row in
    ``FROZEN_MODEL_ALIASES``, and this function must not invent one.
    """
    return FROZEN_MODEL_ALIASES.get((plant_code, normalise_alias(raw_model_spelling)))


def _leading_position(raw_label: str) -> int | None:
    """Leading integer in a raw label, or ``None``. Not identity (task
    brief §3): two zones can share a leading number under different
    numbering schemes (`01_reference.sql`: RCROOF is #27 on P703, #26 on
    U704; FVL numbers again differently), so this is carried as
    provenance only, never compared or deduplicated on.
    """
    match = re.match(r"^(\d+)", raw_label.strip())
    return int(match.group(1)) if match else None


def _is_sap_tailgate(normalised: str) -> bool:
    """"TG"/"tailgate" plus a vertical-position word.

    Task brief §3 names the pair as "top"/"bottom" literally. SAP's real
    July/August exports abbreviate to "Bot" ("18LHS TG Bot13"), which
    ``"bot" in normalised`` still catches because it is a substring of
    "bottom" -- so this stays a strict superset of the brief's wording
    instead of a narrower, real-data-blind version of it.
    """
    has_vertical_word = "top" in normalised or "bot" in normalised
    has_tailgate_word = "tg" in normalised or "tailgate" in normalised
    return has_vertical_word and has_tailgate_word


def _is_fvl_roof(normalised: str) -> bool:
    return "11roof" in normalised or "14roof" in normalised


def _is_fvl_tgate(normalised: str) -> bool:
    return "25tgate" in normalised


def build_walk(raw_labels: list[str]) -> dict:
    """One P703 checkpoint walk: per-label detail + walk-level flags.

    Never sets anything resembling ``APPROVED``. ``proposed_zone_code`` on
    a label is always the advisory, frozen, exact-match lookup above --
    never a fuzzy or count-based guess (spec S15).
    """
    from collections import Counter

    normalised_counts: Counter[str] = Counter()
    zone_to_normalised_raws: dict[str, set[str]] = {}
    all_row_flags: set[str] = set()
    label_rows: list[dict] = []

    for raw_label in raw_labels:
        normalised = normalise_alias(raw_label)
        normalised_counts[normalised] += 1

        row_flags: list[str] = []
        if _is_sap_tailgate(normalised):
            row_flags.append(FLAG_SAP_TAILGATE)
        if _is_fvl_roof(normalised):
            row_flags.append(FLAG_FVL_ROOF)
        if _is_fvl_tgate(normalised):
            row_flags.append(FLAG_FVL_TGATE)
        all_row_flags.update(row_flags)

        proposed = candidate_zone_code(normalised)
        if proposed is not None:
            zone_to_normalised_raws.setdefault(proposed, set()).add(normalised)

        label_rows.append(
            {
                "raw_zone_text": raw_label,
                "normalised": normalised,
                "raw_position": _leading_position(raw_label),
                "proposed_zone_code": proposed,
                "flags": row_flags,
            }
        )

    walk_flags = set(all_row_flags)
    unique_normalised_count = len(normalised_counts)
    if any(count > 1 for count in normalised_counts.values()):
        walk_flags.add(FLAG_DUP_RAW)
    if unique_normalised_count != 32:
        walk_flags.add(FLAG_NOT_32)
    if any(len(raws) > 1 for raws in zone_to_normalised_raws.values()):
        walk_flags.add(FLAG_TWO_CANDIDATES)

    return {
        "labels": label_rows,
        "unique_normalised_count": unique_normalised_count,
        "flags": sorted(walk_flags),
    }


def flag_walk(labels: list[str]) -> list[str]:
    """Just the walk-level flags for ``labels`` (task brief §2 interface)."""
    return build_walk(labels)["flags"]


def sha256_bytes(data: bytes) -> str:
    """Content identity for a workbook, never its bytes (spec §4.3)."""
    return hashlib.sha256(data).hexdigest()


def forbidden_keys_present(obj: object) -> bool:
    """True if any nested mapping key casefold-matches a forbidden key.

    Recurses through dict/list/tuple/set so a forbidden key nested inside
    a ``labels`` array or a ``source_files`` entry is still caught, not
    just a top-level one. Used as a hard gate before any artifact this
    module's caller writes to disk (task brief §3 step 5.6).
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).strip().casefold() in FORBIDDEN_KEYS:
                return True
            if forbidden_keys_present(value):
                return True
        return False
    if isinstance(obj, (list, tuple, set, frozenset)):
        return any(forbidden_keys_present(item) for item in obj)
    return False
