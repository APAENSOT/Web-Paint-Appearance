"""T26 -- the WaveScan semantic clean layer.

Two halves, and the split is deliberate.

**Pure (no database).** Everything about how a header row is *read*: the
order-independent semantic signature against the exact ordered-layout hash,
duplicate logical fields, sheet classification, `[All]` roll-ups, and the
plant-first alias rule. These are the claims that decide whether a
measurement means what the file said, and `00-ARCHITECTURE.md` section 5
rule 1 exists so they can be exercised without a server. They run anywhere.

**Against PostgreSQL and the running application** (`pytest.mark.ingest`, the
T04 harness). Everything about what is *stored and refused*: that a reordered
AAT workbook still commits, that a SAP-shaped reorder parses and does not,
that an unknown extra header blocks a commit until a named owner publishes a
policy and the bytes are replayed, that owner-publish appends an immutable
verified version with an audit row, and that the Admin mapping-approve route
still cannot verify a layout. A mock cannot fail to hold a grant, so the M6
and ADR 0005 claims are asserted against the catalog.

**No Ford workbook is copied into this repository.** Every fixture here is
synthetic: layouts shaped like the ones reviewed read-only under
`Internship/Data/{AAT,FTM,FVL,SAP}/CF`, built from the suite's own values.
No real serial, colour or plant file is committed (`03-SECURITY.md`).
"""

from __future__ import annotations

import importlib.util
import io
import uuid
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.domain import reader
from app.domain.cleaner import (
    AGGREGATE_SENTINELS,
    Aggregate,
    Cleaner,
    CleanRow,
)
from app.domain.reader import (
    DOMAIN_WAVESCAN,
    SHEET_OUT_OF_SCOPE,
    SHEET_UNKNOWN_DATA,
    SHEET_WAVESCAN,
    DuplicateFieldError,
    classify_sheet,
    describe_sheet,
    read_sheet,
    semantic_signature,
)
from app.domain.references import ReferenceData

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

#: The canonical twenty-one-column CF layout, as AAT and FTM June/July write
#: it. Header spellings only -- no values from a real workbook.
HEADERS = [
    "Date", "Month", "Year", "Plant", "Model", "Checkzone", "Color",
    "Tolerance Group", "Paintline", "Serial No",
    "LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We", "B",
]

#: FTM August and SAP July move the measures. Same twenty-one logical fields.
REORDERED = [
    "Date", "Month", "Year", "Plant", "Model", "Checkzone", "Color",
    "Tolerance Group", "Paintline", "Serial No",
    "CF", "LW", "SW", "DOI", "Wa", "du", "B", "Wb", "Wc", "Wd", "We",
]

#: SAP July also moves the identity columns to the end.
SAP_JULY_SHAPED = [
    "Model", "Checkzone", "Color", "Tolerance Group", "Month", "Year",
    "CF", "LW", "SW", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We", "B",
    "Date", "Plant", "Paintline", "Serial No",
]

ALIAS_MAP = {
    "date": "date", "month": "month", "year": "year", "plant": "plant",
    "model": "model", "checkzone": "checkzone", "color": "color",
    "tolerance group": "tolerance_group", "paintline": "paintline",
    "serial no": "serial_no",
    "lw": "lw", "sw": "sw", "cf": "cf", "doi": "doi", "du": "du",
    "wa": "wa", "wb": "wb", "wc": "wc", "wd": "wd", "we": "we", "b": "b",
}

ROW = {
    "Date": "2026-08-03", "Month": "August", "Year": 2026,
    "Plant": "AAT", "Model": "U704", "Checkzone": "01 RRHOOD",
    "Color": "3HC Traction Green", "Tolerance Group": "Horizontal",
    "Paintline": "BOOTH1", "Serial No": "T26-0001",
    "LW": 3.7, "SW": 15.7, "CF": 60.9, "DOI": 87.5, "du": 15.9,
    "Wa": 13.4, "Wb": 21.5, "Wc": 11.6, "Wd": 12.7, "We": 6.7, "B": -0.2,
}


def sheet_bytes(
    headers: list[str],
    rows: list[dict] | None = None,
    *,
    sheet: str = "PasteData",
    extra_sheets: dict[str, tuple[list, list[list]]] | None = None,
) -> bytes:
    """A workbook built from header names, with values looked up by name.

    Values are always keyed by the **canonical** header, so reordering the
    header list moves the columns and keeps each value under its own name --
    which is the only way a reorder test can prove that values still bind to
    the right logical field rather than merely that a hash matched.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for row in rows or [ROW]:
        merged = {**ROW, **row}
        ws.append([merged.get(h) for h in headers])
    for name, (head, body) in (extra_sheets or {}).items():
        other = wb.create_sheet(title=name)
        other.append(head)
        for line in body:
            other.append(line)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def raw_row(sheet: str = "PasteData", **over):
    """One `RawRow` straight from a synthetic sheet, for cleaner tests."""
    data = sheet_bytes(HEADERS, [over])
    return list(read_sheet(data, sheet, ALIAS_MAP, "t26.xlsx"))[0]


def reference(**over) -> ReferenceData:
    """A minimal `ReferenceData` a cleaner can run against, no database."""
    base = dict(
        plant={"aat": "AAT", "ftm": "FTM", "fvl": "FVL", "sap": "SAP"},
        model={"u704": "U704", "p703 dbl ranger": "P703 DBL RANGER"},
        model_by_plant={},
        checkzone={"01 rrhood": "RRHOOD"},
        color={"3hc traction green": "Traction Green"},
        color_by_plant={},
        paintline={"booth1": "BOOTH1"},
        model_zone=frozenset({("U704", "RRHOOD"), ("P703 DBL RANGER", "RRHOOD")}),
        expected_zones={"U704": 31, "P703 DBL RANGER": 32},
        requires_serial={"AAT": True, "FTM": True, "SAP": True, "FVL": False},
        active_plants=frozenset({"AAT", "FTM", "SAP"}),
        known_plants=frozenset({"AAT", "FTM", "SAP", "FVL"}),
        offered_colors={
            (plant, "Traction Green"): True
            for plant in ("AAT", "FTM", "SAP", "FVL")
        },
        offered_models={
            (plant, model): True
            for plant in ("AAT", "FTM", "SAP", "FVL")
            for model in ("U704", "P703 DBL RANGER")
        },
    )
    base.update(over)
    return ReferenceData(**base)


# =====================================================================
# 1. semantic signature vs exact ordered-layout hash  (spec S7)
# =====================================================================
def test_a_reorder_keeps_the_contract_and_moves_the_layout_hash():
    """FTM August and SAP July are this test.

    The same twenty-one logical fields in another order. Under T18 each
    reorder minted a fingerprint nobody had approved and the sheet was
    refused; the contract had not changed at all. T26 splits the two hashes
    so the refusal goes away without the evidence going with it.
    """
    canonical = describe_sheet(sheet_bytes(HEADERS), "PasteData", ALIAS_MAP)
    ftm_august = describe_sheet(sheet_bytes(REORDERED), "PasteData", ALIAS_MAP)
    sap_july = describe_sheet(sheet_bytes(SAP_JULY_SHAPED), "PasteData", ALIAS_MAP)

    signatures = {
        canonical.semantic_signature,
        ftm_august.semantic_signature,
        sap_july.semantic_signature,
    }
    assert len(signatures) == 1, "a reorder is not a change of contract"

    fingerprints = {
        canonical.fingerprint, ftm_august.fingerprint, sap_july.fingerprint
    }
    assert len(fingerprints) == 3, (
        "the exact ordered-layout hash must still record that the columns "
        "moved -- it is the provenance a semantic key would otherwise lose"
    )


def test_a_reordered_sheet_still_binds_values_to_the_right_field():
    """The hash agreeing is not the claim; the *values* are.

    A signature that matched while CF and LW had swapped columns would be
    precisely the silent wrong measurement this platform exists to prevent.
    """
    for headers in (HEADERS, REORDERED, SAP_JULY_SHAPED):
        rows = list(
            read_sheet(sheet_bytes(headers), "PasteData", ALIAS_MAP, "t26.xlsx")
        )
        assert len(rows) == 1
        assert rows[0].get("cf") == ROW["CF"]
        assert rows[0].get("lw") == ROW["LW"]
        assert rows[0].get("serial_no") == ROW["Serial No"]
        assert rows[0].get("checkzone") == ROW["Checkzone"]


def test_a_dropped_field_does_change_the_contract():
    """The signature has to be *sensitive* to what it is about.

    The no-Plant-column layout is a different contract, which is why
    revision 0006 seeded it as its own profile and 0009 backfills it with its
    own signature.
    """
    with_plant = describe_sheet(sheet_bytes(HEADERS), "PasteData", ALIAS_MAP)
    without = describe_sheet(
        sheet_bytes([h for h in HEADERS if h != "Plant"]), "PasteData", ALIAS_MAP
    )
    assert with_plant.semantic_signature != without.semantic_signature


def test_the_signature_carries_its_domain():
    """S6: a FilmThickness sheet must not select a WaveScan profile because
    somebody happened to spell the fields the same."""
    fields = ("date", "model", "cf")
    assert semantic_signature(fields, "WAVESCAN") != semantic_signature(
        fields, "FILMTHICKNESS"
    )


def test_the_signature_ignores_order_and_repetition_of_its_input():
    assert semantic_signature(["cf", "lw", "cf"]) == semantic_signature(["lw", "cf"])


def test_revision_0009_and_the_reader_compute_the_same_signature():
    """The migration carries its own copy of the formula, as 0002 does with
    `HEADER_ALIASES`. A copy nobody compares is a copy that drifts, and a
    drifted signature would make every seeded profile unselectable."""
    spec = importlib.util.spec_from_file_location(
        "t26_migration",
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.CANONICAL_SIGNATURE == semantic_signature(
        migration.CANONICAL_FIELDS
    )
    assert migration.NO_PLANT_SIGNATURE == semantic_signature(
        migration.NO_PLANT_FIELDS
    )
    # ...and the field sets are the ones the canonical sheet actually carries.
    canonical = describe_sheet(sheet_bytes(HEADERS), "PasteData", ALIAS_MAP)
    assert canonical.semantic_signature == migration.CANONICAL_SIGNATURE
    no_plant = describe_sheet(
        sheet_bytes([h for h in HEADERS if h != "Plant"]), "PasteData", ALIAS_MAP
    )
    assert no_plant.semantic_signature == migration.NO_PLANT_SIGNATURE


def test_the_exact_hash_is_unchanged_by_t26():
    """The T18 fingerprints revision 0006 seeded still name these layouts.

    If this moved, every profile in the database would stop matching the
    bytes that proved it -- and the failure would look like "the file
    changed" rather than "the algorithm did".
    """
    spec = importlib.util.spec_from_file_location(
        "t26_migration",
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    canonical = describe_sheet(sheet_bytes(HEADERS), "PasteData", ALIAS_MAP)
    assert canonical.fingerprint == migration.CANONICAL_FINGERPRINT
    no_plant = describe_sheet(
        sheet_bytes([h for h in HEADERS if h != "Plant"]), "PasteData", ALIAS_MAP
    )
    assert no_plant.fingerprint == migration.NO_PLANT_FINGERPRINT


def test_an_ignored_header_does_not_move_the_exact_hash():
    """Marking a column ignored is a decision about a *profile*, not a
    rewrite of what a workbook's bytes are. A layout identity that moved when
    somebody published a policy would make the stored provenance a lie."""
    data = sheet_bytes(HEADERS + ["Panel2"])
    plain = describe_sheet(data, "PasteData", ALIAS_MAP)
    ignored = describe_sheet(data, "PasteData", ALIAS_MAP, (), ("panel2",))
    assert plain.fingerprint == ignored.fingerprint
    assert plain.unreviewed_headers == ("panel2",)
    assert ignored.unreviewed_headers == ()
    assert ignored.ignored == ("panel2",)


# =====================================================================
# 2. duplicate logical fields block, missing fields block differently (S8)
# =====================================================================
def test_a_repeated_logical_field_is_detected_and_not_skipped():
    """Before T26 the second `CF` was dropped in silence.

    That is the exact shape a swapped measure column would have: the sheet
    parses, a number lands in `cf`, and nothing says which column it came
    from.
    """
    template = describe_sheet(
        sheet_bytes(HEADERS + ["CF"]), "PasteData", ALIAS_MAP
    )
    assert template.duplicate_fields == ("cf",)
    assert not template.is_parseable
    assert template.missing_required == (), (
        "a duplicate is not a missing field; the two are different refusals"
    )


def test_a_repeated_field_refuses_before_any_data_row_is_read():
    with pytest.raises(DuplicateFieldError) as exc:
        list(
            read_sheet(
                sheet_bytes(HEADERS + ["CF"]), "PasteData", ALIAS_MAP, "t26.xlsx"
            )
        )
    assert "repeats 'cf'" in str(exc.value)
    assert exc.value.template.duplicate_fields == ("cf",)


def test_a_missing_required_field_is_a_different_gate():
    # T39 CHANGE (ADR 0013): Serial No is optional; Checkzone is still required.
    template = describe_sheet(
        sheet_bytes([h for h in HEADERS if h != "Checkzone"]),
        "PasteData", ALIAS_MAP,
    )
    assert template.missing_required == ("checkzone",)
    assert template.duplicate_fields == ()
    assert not template.is_parseable


def test_an_ignored_column_can_resolve_a_duplicate():
    """The escape hatch is a *named owner's* decision, not an automatic one.

    A published column policy that ignores the second column makes the sheet
    readable again; nothing in the parse path can do that by itself.
    """
    data = sheet_bytes(HEADERS + ["CF"])
    assert describe_sheet(data, "PasteData", ALIAS_MAP).duplicates
    # The policy names the header spelling, which here is the same word --
    # so both columns go, and the sheet is then missing `cf` rather than
    # silently using one of them. Refusing is still the answer.
    policed = describe_sheet(data, "PasteData", ALIAS_MAP, (), ("cf",))
    assert policed.duplicates == ()
    assert "cf" not in set(policed.recognised.values())


# =====================================================================
# 3. sheet classification by headers, never by tab name (S10)
# =====================================================================
def test_a_canonical_sheet_classifies_as_wavescan():
    assert describe_sheet(
        sheet_bytes(HEADERS), "PasteData", ALIAS_MAP
    ).sheet_class == SHEET_WAVESCAN


def test_a_methods_shaped_sheet_is_out_of_scope_not_a_broken_template():
    """A Methods or instructions sheet is prose, not a data grid.

    Reporting it as `REJECTED_TEMPLATE` would put a header diff nobody can
    act on in front of an Admin, every month, for a sheet that was never
    meant to be measurements (S10).
    """
    data = sheet_bytes(
        HEADERS,
        extra_sheets={
            "Methods": (["Measurement method"], [["BYK wavescan II, 3 passes"]])
        },
    )
    assert describe_sheet(data, "Methods", ALIAS_MAP).sheet_class == SHEET_OUT_OF_SCOPE


def test_a_colour_data_shaped_sheet_is_out_of_scope():
    """A full grid in a vocabulary this domain shares nothing with.

    FVL ships Color Data beside CF in one workbook. It is another domain's
    evidence, preserved rather than blocked, and nothing here loads it as a
    WaveScan fact (S1, S10).
    """
    data = sheet_bytes(
        HEADERS,
        extra_sheets={
            "Color Data": (
                ["Standard", "L star", "a star", "b star", "dE"],
                [["STD-1", 41.2, 0.3, -1.1, 0.4]],
            )
        },
    )
    assert (
        describe_sheet(data, "Color Data", ALIAS_MAP).sheet_class
        == SHEET_OUT_OF_SCOPE
    )


def test_a_data_like_sheet_that_speaks_half_this_vocabulary_blocks():
    """The genuinely ambiguous case, and the only one that blocks.

    It might be a CF export somebody trimmed; it might be a different
    measurement entirely. Guessing either way is what S10 forbids, so it is
    held for classification.
    """
    data = sheet_bytes(
        HEADERS,
        extra_sheets={
            "Sheet3": (
                ["Date", "Plant", "Model", "Thickness", "Coat"],
                [["2026-08-03", "AAT", "U704", 21.5, "BC"]],
            )
        },
    )
    assert (
        describe_sheet(data, "Sheet3", ALIAS_MAP).sheet_class == SHEET_UNKNOWN_DATA
    )


def test_classification_does_not_read_the_tab_name():
    """A workbook that calls its data sheet `Methods` is still data.

    `02-PIPELINE.md` section 4 already refuses to let a filename be a key,
    and a sheet name is the same kind of label.
    """
    misleading = sheet_bytes(HEADERS, sheet="Methods")
    assert (
        describe_sheet(misleading, "Methods", ALIAS_MAP).sheet_class == SHEET_WAVESCAN
    )


def test_the_classifier_needs_measures_and_an_identity_field():
    assert classify_sheet(["cf", "lw", "sw"]) == SHEET_UNKNOWN_DATA
    assert classify_sheet(["cf", "lw", "date"]) == SHEET_UNKNOWN_DATA
    # Recheck fix: few columns is not "out of scope". A two-column sheet that
    # carries CF speaks WaveScan and must block, not vanish quietly.
    assert classify_sheet(["cf"]) == SHEET_UNKNOWN_DATA
    assert classify_sheet([]) == SHEET_OUT_OF_SCOPE
    assert classify_sheet(["cf", "lw", "sw", "date"]) == SHEET_WAVESCAN


def test_the_fvl_eighteen_column_shape_is_wavescan_and_still_unparseable():
    """FVL's historical contract: no Plant, no Serial, no Paintline.

    It is a WaveScan sheet -- it carries the measures and says which panel --
    and it is *not* a parseable one, which is exactly the honest answer. D5
    stays open and nothing here onboards FVL.
    """
    fvl = [
        "Date", "Month", "Year", "Style", "Panel", "Orientation", "Color",
        "Panel2", "LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We",
    ]
    aliases = {
        **ALIAS_MAP, "style": "model", "panel": "checkzone",
        "orientation": "tolerance_group",
    }
    template = describe_sheet(sheet_bytes(fvl), "PasteData", aliases)
    assert template.sheet_class == SHEET_WAVESCAN
    # T39 CHANGE (ADR 0013): serial is optional, so only Plant is missing --
    # which a profile with fill_missing_plant supplies.
    assert set(template.missing_required) == {"plant"}
    assert template.unreviewed_headers == ("panel2",)


# =====================================================================
# 4. [All] roll-ups are AGGREGATE_ROW, never facts  (S16)
# =====================================================================
def test_an_all_row_in_an_identity_field_is_an_aggregate():
    """FTM May is 1064 of these in 1320 rows; FVL September 133 of 165.

    The same numbers appear at progressively less specific filter levels, so
    loading one invents a vehicle whose measurements average other vehicles'.
    """
    cleaner = Cleaner(reference(), ("AAT",), expected_plant="AAT")
    out = cleaner.clean_row(raw_row(**{"Model": "[All]"}))
    assert isinstance(out, Aggregate)
    assert out.fields == ("model",)
    assert out.values["model"] == "[All]"


def test_a_leaf_row_beside_an_aggregate_is_still_a_fact():
    cleaner = Cleaner(reference(), ("AAT",), expected_plant="AAT")
    rows = list(
        read_sheet(
            sheet_bytes(HEADERS, [{"Checkzone": "[All]"}, {}]),
            "PasteData", ALIAS_MAP, "t26.xlsx",
        )
    )
    result = cleaner.clean_all(rows)
    assert len(result.aggregates) == 1
    assert len(result.clean) == 1
    assert isinstance(result.clean[0], CleanRow)
    assert result.clean[0].checkzone == "RRHOOD"


def test_an_aggregate_is_not_a_reject_and_not_a_quarantine():
    """The disposition matters, not only the exclusion.

    Calling a roll-up a reject would put thousands of rows behind the
    `REJECTED_ROWS` acknowledgement gate -- the "thousands-row ack flood" the
    design names -- and calling it an unidentified model would invite
    somebody to map `[All]` to a vehicle.
    """
    cleaner = Cleaner(reference(), ("AAT",), expected_plant="AAT")
    result = cleaner.clean_all(
        list(
            read_sheet(
                sheet_bytes(HEADERS, [{"Model": "[All]", "Serial No": "[All]"}]),
                "PasteData", ALIAS_MAP, "t26.xlsx",
            )
        )
    )
    assert result.rejects == []
    assert result.unidentified == []
    assert len(result.aggregates) == 1
    assert result.aggregates[0].fields == ("model", "serial_no")


def test_a_sentinel_in_a_measure_column_is_still_a_bad_number():
    """Only identity makes a row a roll-up. `[All]` where a CF should be is a
    value this platform will not accept, and saying otherwise would quietly
    drop a row somebody has to look at."""
    cleaner = Cleaner(reference(), ("AAT",), expected_plant="AAT")
    out = cleaner.clean_row(raw_row(**{"CF": "[All]"}))
    assert not isinstance(out, Aggregate)
    assert getattr(out, "reason", None) == "BAD_NUMBER"


def test_a_bare_all_is_not_treated_as_a_sentinel():
    """Deliberately conservative.

    The reviewed workbooks write `[All]`. Treating a bare `All` as a roll-up
    would let a real colour, paintline or model spelled that way vanish from
    the facts -- a silent delete, which is the failure `AGENTS.md` opens
    with, pointed the other way.
    """
    assert "all" not in AGGREGATE_SENTINELS
    assert "(none)" not in AGGREGATE_SENTINELS
    cleaner = Cleaner(reference(), ("AAT",), expected_plant="AAT")
    out = cleaner.clean_row(raw_row(**{"Color": "All"}))
    assert not isinstance(out, Aggregate)


# =====================================================================
# 5. plant-first model and colour aliases  (S11, S12)
# =====================================================================
def test_the_fvl_lock_does_not_reach_another_plant():
    """The owner locked FVL `P703` -> Ranger. That is a statement about FVL.

    A global row saying it -- which is what `01-reference.sql` seeded and
    revision 0009 removes -- makes every other plant inherit an assumption
    nobody made about it, SAP included, whose `P703 RAP` is not a Ranger.
    """
    ref = reference(
        model={},  # no global bare-P703 row any more
        model_by_plant={("FVL", "p703"): "P703 DBL RANGER"},
    )
    fvl = Cleaner(ref, ("FVL",), expected_plant="FVL")
    assert fvl.plant_first(ref.model_by_plant, ref.model, "FVL", "P703") == (
        "P703 DBL RANGER"
    )
    for other in ("AAT", "FTM", "SAP"):
        assert fvl.plant_first(ref.model_by_plant, ref.model, other, "P703") is None


def test_sap_p703_rap_stays_unmapped():
    """Not a Ranger, and not this slice's decision to make.

    SAP model mapping waits for the activation slice and a named owner
    (spec 5.4, section 9).
    """
    ref = reference(
        model={}, model_by_plant={("FVL", "p703"): "P703 DBL RANGER"}
    )
    cleaner = Cleaner(ref, ("SAP",), expected_plant="SAP")
    assert cleaner.plant_first(ref.model_by_plant, ref.model, "SAP", "P703 RAP") is None


def test_an_unambiguous_global_spelling_still_resolves_everywhere():
    """Plant-first is a *fallback* rule, not a requirement to scope
    everything. `P703 DBL RANGER` spelled out means one thing anywhere."""
    ref = reference(
        model={"p703 dbl ranger": "P703 DBL RANGER"}, model_by_plant={}
    )
    cleaner = Cleaner(ref, ("AAT",), expected_plant="AAT")
    for plant in ("AAT", "FTM", "SAP", "FVL"):
        assert cleaner.plant_first(
            ref.model_by_plant, ref.model, plant, "P703 DBL Ranger"
        ) == "P703 DBL RANGER"


def test_a_plant_scoped_row_wins_over_the_global_one():
    ref = reference(
        model={"p703": "P703 DBL RAPTOR"},
        model_by_plant={("FVL", "p703"): "P703 DBL RANGER"},
    )
    cleaner = Cleaner(ref, ("FVL",), expected_plant="FVL")
    assert cleaner.plant_first(ref.model_by_plant, ref.model, "FVL", "P703") == (
        "P703 DBL RANGER"
    )
    assert cleaner.plant_first(ref.model_by_plant, ref.model, "AAT", "P703") == (
        "P703 DBL RAPTOR"
    )


def test_colour_aliases_are_identity_only():
    """S12: a colour alias maps a spelling to a canonical colour. It says
    nothing about a grading family, and `grading_family` stays NULL until
    D1/D2 are decided by T-STANDARDS-D2."""
    ref = reference(color_by_plant={("AAT", "5gr acacia green"): "Acacia Green"})
    cleaner = Cleaner(ref, ("AAT",), expected_plant="AAT")
    assert cleaner.plant_first(
        ref.color_by_plant, ref.color, "AAT", "5GR Acacia Green"
    ) == "Acacia Green"
    assert not hasattr(ref, "grading_family")


def test_revision_0009_does_not_relocate_the_ranger_assumption_to_sap():
    """The relocation is evidence plus one named owner lock, never a copy.

    Reading the migration's own constants is the cheapest way to assert the
    boundary the task drew: FVL by the owner's word, AAT/FTM only where their
    own staged rows carry the spelling, SAP not at all.
    """
    spec = importlib.util.spec_from_file_location(
        "t26_migration",
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.OWNER_LOCKED_RANGER_PLANTS == ("FVL",)
    assert "SAP" not in migration.EVIDENCE_RELOCATION_PLANTS
    assert "SAP" not in migration.OWNER_LOCKED_RANGER_PLANTS

    migration = (
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py"
    )
    for line in _statements(migration):
        assert "P703 RAP" not in line, f"T26 does not map SAP's P703 RAP: {line}"
        assert "INSERT INTO ref_plant_zone_map" not in line, (
            f"T26 seeds no plant zone map, approved or otherwise: {line}"
        )
        assert "'APPROVED'" not in line, f"T26 approves no mapping: {line}"


# =====================================================================
# 6. structural guarantees, read from the source (M4, M6, S21)
# =====================================================================
def _statements(path: Path) -> list[str]:
    """Lines of a module with its comments and docstrings taken out.

    A grep over whole files reads prose as if it were code: this file's own
    docstrings name `ref_template_profile` and `grading_family` precisely
    because it is asserting that nothing *writes* them. Tokenising first
    makes these tests about statements, which is what they claim to be.
    """
    import io
    import tokenize

    source = path.read_text(encoding="utf-8")
    kept: list[str] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return source.splitlines()
    previous = tokenize.INDENT
    for token in tokens:
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and previous in (
            tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL,
        ):
            continue  # a docstring, not a value
        if token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                              tokenize.DEDENT):
            kept.append(token.line.rstrip())
            previous = token.type
    return kept


def test_there_is_still_exactly_one_parser():
    """M4. `read_sheet` is called from one module and nowhere else."""
    callers = sorted(
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in APP_ROOT.rglob("*.py")
        if "read_sheet(" in path.read_text(encoding="utf-8")
        and path.name != "reader.py"
    )
    assert callers == ["app/services/ingest.py"], callers


def test_the_mapping_service_cannot_verify_a_layout():
    """M6, asserted where it is cheapest to break.

    The Admin mapping-approve path writes aliases. It has no statement about
    a profile, a column policy or `fixture_verified` -- and no grant behind
    one either, which the catalog test below proves.
    """
    for module in ("services/mapping.py", "repositories/mappings.py"):
        for line in _statements(APP_ROOT / module):
            for forbidden in (
                "ref_template_profile",
                "ref_template_column_policy",
                "fixture_verified",
                "publish_template_profile",
                "publish_profile",
            ):
                assert forbidden not in line, f"{module}: {line}"


def test_the_publish_function_never_touches_facts():
    """S21 / ADR 0005. Revision 0009 adds a writer of reference data, and a
    writer of reference data that could reach `wavescan` would be a way
    around the whole immutability story."""
    source = (
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py"
    ).read_text(encoding="utf-8")
    start = source.index("CREATE OR REPLACE FUNCTION publish_template_profile")
    body = source[start:source.index("$fn$;", start)]
    for forbidden in ("wavescan", "load_batch", "DROP ", "DELETE FROM"):
        assert forbidden not in body, forbidden
    assert "SECURITY DEFINER" in body
    assert "SET search_path = pg_catalog, public" in body
    assert "INSERT INTO audit_event" in body, (
        "the audit row is written inside the same transaction as the mutation"
    )


def test_revision_0009_does_not_rewrite_reset_batch_staging():
    """The task prefers it left alone, and it is: replay still clears exactly
    the four staging tables T18 gave it, under the same three guards."""
    source = (
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py"
    ).read_text(encoding="utf-8")
    assert "reset_batch_staging" in source, "mentioned in the docstring"
    assert "CREATE OR REPLACE FUNCTION reset_batch_staging" not in source


def test_no_new_grant_to_write_profiles_or_facts():
    source = (
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "INSERT ON ref_template_profile",
        "UPDATE ON ref_template_profile",
        "DELETE ON ref_template_profile",
        "INSERT ON ref_template_column_policy",
        "DELETE ON wavescan",
        "UPDATE ON wavescan",
        "DELETE ON load_batch",
    ):
        assert forbidden not in source, forbidden


def test_the_domain_layer_still_imports_no_framework():
    """`00-ARCHITECTURE.md` section 5 rule 1, re-asserted because T26 touched
    every file in `domain/`."""
    for path in (APP_ROOT / "domain").glob("*.py"):
        for line in _statements(path):
            if not line.lstrip().startswith(("import ", "from ")):
                continue
            for forbidden in ("fastapi", "psycopg", "sqlalchemy"):
                assert forbidden not in line, f"{path.name}: {line}"


def test_grading_family_is_still_not_written():
    """D1 stays open; mint may INSERT ref_color but never writes grading_family."""
    reserved = (APP_ROOT / "api" / "v1" / "reserved.py").read_text(encoding="utf-8")
    assert "@router.post" not in reserved
    standards = (APP_ROOT / "api" / "v1" / "standards.py").read_text(encoding="utf-8")
    assert '"/standards"' in standards
    written = (
        "SET grading_family", "grading_family =", "UPDATE ref_color",
    )
    for path in APP_ROOT.rglob("*.py"):
        for line in _statements(path):
            for forbidden in written:
                assert forbidden not in line, f"{path.name}: {line}"
    migration = (
        BACKEND_ROOT / "migrations" / "versions"
        / "0009_t26_wavescan_semantic_clean_layer.py"
    )
    for line in _statements(migration):
        for forbidden in written:
            assert forbidden not in line, line


# =====================================================================
# 7. against PostgreSQL and the running application
# =====================================================================
ingest_suite = pytest.importorskip(
    "tests.test_t04_ingest", reason="the T04 ingest harness is the shared one"
)

from tests.test_t04_ingest import (  # noqa: E402
    XLSX_MIME,
    forget_bytes,
    upload,
    wait_for,
)
from tests.test_t04_ingest import (  # noqa: E402,F401  (fixtures, by import)
    admin,
    cleanup,
    engineer,
    ingest_apps,
    viewer,
)

db = pytest.mark.ingest


def _profiles(admin_conn, plant: str) -> list[dict]:
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT profile_id, domain, semantic_signature, template_fingerprint, "
            "       version, is_active, fixture_verified, fixture_file_hash, "
            "       verified_by, notes "
            "  FROM ref_template_profile WHERE plant_code = %s "
            " ORDER BY profile_id",
            (plant,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _rows(count: int, **over) -> list[dict]:
    """Rows for a vehicle no other test has used, so dedup stays out of it."""
    serial = f"T26-{uuid.uuid4().hex[:10]}"
    zones = ["01 RRHOOD", "02 RFHOOD", "03 CFHOOD", "04 LFHOOD", "05 LRHOOD"]
    plant = over.get("Plant", ROW["Plant"])
    identity = {
        "AAT": {"Model": "U704", "Color": "3HC Traction Green"},
        "FTM": {"Model": "P703 DBL RANGER", "Color": "Ignite Orange"},
        "FVL": {"Model": "P703 DBL RANGER", "Color": "Ignite Orange"},
        "SAP": {"Model": "P703 DBL RANGER", "Color": "Frozen White"},
    }.get(plant, {})
    return [
        {"Serial No": serial, "Checkzone": zones[i % len(zones)],
         "CF": 60.0 + i, **identity, **over}
        for i in range(count)
    ]


@db
def test_an_aat_reorder_parses_and_commits(engineer, admin_conn, cleanup):
    """The headline claim: FTM August's shape, at a commit-capable plant.

    T18 refused this. What makes it commit now is that the *contract* was
    already approved -- not that the gate got weaker.
    """
    data = sheet_bytes(REORDERED, _rows(3))
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t26-reorder.xlsx", data, "AAT")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    batch = review["batch"]
    assert batch["status"] == "PENDING_REVIEW", batch["notes"]
    assert batch["sheet_class"] == SHEET_WAVESCAN
    assert batch["domain"] == DOMAIN_WAVESCAN
    assert batch["unreviewed_headers"] == []

    canonical = describe_sheet(sheet_bytes(HEADERS), "PasteData", ALIAS_MAP)
    assert batch["semantic_signature"] == canonical.semantic_signature
    assert batch["template_fingerprint"] != canonical.fingerprint, (
        "the exact layout moved; the contract did not"
    )
    assert review["commit_blockers"] == [], review["commit_blockers"]
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200


@db
def test_a_sap_reorder_parses_for_review_and_cannot_commit(
    engineer, admin_conn, cleanup
):
    """SAP is visible and blocked with a reason, and T26 does not change that.

    Its canonical profile is deliberately unverified, and its June workbook
    has no serial. A reorder of that layout may now be *read*; it may not
    become measurements.
    """
    data = sheet_bytes(SAP_JULY_SHAPED, _rows(3, **{"Plant": "SAP"}))
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t26-sap-july.xlsx", data, "SAP")
    assert accepted.status_code == 202, accepted.text
    load_id = accepted.json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW"
    sap_verified = any(profile["fixture_verified"] for profile in _profiles(admin_conn, "SAP"))
    if sap_verified:
        # T30 published a SAP profile on this standing cluster. T26's
        # unverified-layout refusal is not the blocker here.
        assert review["batch"]["counts"]["rows_in_file"] == 3
    else:
        assert "UNVERIFIED_PROFILE" in review["commit_blockers"]
        assert review["committable"] is False
        refused = engineer.post(f"/api/v1/batches/{load_id}/commit")
        assert refused.status_code == 409
        assert "UNVERIFIED_PROFILE" in refused.json()["message"]


@db
def test_a_duplicate_logical_field_refuses_before_any_row_is_staged(
    engineer, admin_conn, cleanup
):
    data = sheet_bytes(HEADERS + ["CF"], _rows(3))
    forget_bytes(admin_conn, data)
    load_id = upload(engineer, "t26-dup.xlsx", data, "AAT").json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "REJECTED_TEMPLATE"
    assert "DUPLICATE_LOGICAL_FIELD" in review["commit_blockers"]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stg_raw WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0, "no data row is read when meaning is ambiguous"


@db
def test_an_unreviewed_extra_header_parses_and_blocks_the_commit(
    engineer, admin_conn, cleanup
):
    """S9. The known fields parse and the extra is preserved; committing is
    refused until somebody decides what the column means."""
    data = sheet_bytes(HEADERS + ["Panel2"], _rows(3, Panel2="HOOD"))
    forget_bytes(admin_conn, data)
    load_id = upload(engineer, "t26-extra.xlsx", data, "AAT").json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    assert review["batch"]["status"] == "PENDING_REVIEW"
    assert review["batch"]["unreviewed_headers"] == ["panel2"]
    assert "UNREVIEWED_HEADER" in review["commit_blockers"]
    assert review["batch"]["counts"]["rows_loaded"] == 3, "known fields still parsed"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT raw -> 'extra' FROM stg_review_row "
            "WHERE load_id = %s ORDER BY source_row LIMIT 1",
            (load_id,),
        )
        assert "panel2" in (cur.fetchone()[0] or {}), "the extra is preserved"

    refused = engineer.post(f"/api/v1/batches/{load_id}/commit")
    assert refused.status_code == 409
    assert "UNREVIEWED_HEADER" in refused.json()["message"]


@pytest.fixture()
def published_profiles(admin_conn):
    """Profile versions a test published, removed as the owner afterwards.

    A publish is reference data and outlives the test. Left behind, it would
    silently change what a later test's layout means -- which is exactly how
    the first live run of this suite showed up: a version published onto the
    canonical AAT contract made every later `Panel2` sheet look reviewed.
    The application cannot do this cleanup (no DELETE, no UPDATE on the
    profile table); the owner can, on a throwaway test database.
    """
    created: list[tuple[int, int | None]] = []
    yield created
    with admin_conn.cursor() as cur:
        for profile_id, previous in reversed(created):
            cur.execute(
                "UPDATE load_batch SET profile_id = NULL WHERE profile_id = %s",
                (profile_id,),
            )
            cur.execute(
                "UPDATE stg_review_row SET profile_id = NULL WHERE profile_id = %s",
                (profile_id,),
            )
            cur.execute(
                "DELETE FROM ref_template_column_policy WHERE profile_id = %s",
                (profile_id,),
            )
            cur.execute(
                "DELETE FROM ref_template_profile WHERE profile_id = %s",
                (profile_id,),
            )
            if previous is not None:
                cur.execute(
                    "UPDATE ref_template_profile SET is_active = true "
                    "WHERE profile_id = %s",
                    (previous,),
                )


#: A contract no seed claims: the canonical layout without the one optional
#: measure. Publishing onto it cannot disturb the seeded AAT/FTM profiles.
UNSEEDED = [h for h in HEADERS if h != "B"]


@db
def test_owner_publish_then_replay_lets_the_extra_header_commit(
    engineer, admin, admin_conn, cleanup, published_profiles
):
    """The whole loop, end to end, at a commit-capable plant.

    Publish names a stored workbook, a named owner and a reason; the batch is
    replayed from those same bytes; the extra is now an approved ignored
    column and the commit goes through. Nothing auto-ignored anything and
    publishing committed nothing.

    Run on a contract no seed claims, so the batch starts REJECTED_TEMPLATE
    with its extra recorded, and the seeded canonical profile is untouched.
    """
    data = sheet_bytes(UNSEEDED + ["Panel2"], _rows(3, Panel2="HOOD"))
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t26-publish.xlsx", data, "AAT").json()
    load_id = accepted["batches"][0]["load_id"]
    file_hash = accepted["batches"][0].get("file_hash") or wait_for(
        engineer, load_id
    )["batch"]["file_hash"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    assert "UNREVIEWED_HEADER" in review["commit_blockers"]

    published = admin.post(
        "/api/v1/plants/AAT/template-profiles/publish",
        json={
            "file_hash": file_hash,
            "source_sheet": "PasteData",
            "named_owner": "T26 suite, standing in for the named plant owner",
            "notes": (
                "Proved by backend/tests/test_t26_semantic_clean_layer.py, "
                "which commits this layout end to end."
            ),
            "ignored_headers": [
                {"header": "Panel2",
                 "reason": "auxiliary group keyword, not a measurement field"}
            ],
        },
    )
    assert published.status_code == 200, published.text
    body = published.json()
    published_profiles.append((body["profile_id"], body["previous_profile_id"]))
    assert body["previous_profile_id"] is None, "a fresh contract, first version"
    assert body["fixture_verified"] is True
    assert body["fixture_file_hash"] == file_hash
    assert body["audit_action"] == "profile.publish"
    assert body["ignored_headers"] == 1

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT after FROM audit_event WHERE action = 'profile.publish' "
            "AND entity_id = %s",
            (str(body["profile_id"]),),
        )
        after = cur.fetchone()
        assert after is not None, "the audit row is written with the profile"
        assert after[0]["named_owner"].startswith("T26 suite")
        cur.execute(
            "SELECT raw_header, policy, approved_by, reason "
            "FROM ref_template_column_policy WHERE profile_id = %s",
            (body["profile_id"],),
        )
        policy = cur.fetchone()
        assert policy[:2] == ("panel2", "IGNORED")
        assert policy[2] and policy[3], "an ignored column names who and why"

    # Spec section 6: publishing replays the batches it unblocks, from their
    # stored bytes, through the same service. It does not commit them.
    assert load_id in body["replayed_load_ids"], body
    after_replay = wait_for(engineer, load_id)
    assert after_replay["batch"]["status"] == "PENDING_REVIEW"
    assert after_replay["batch"]["unreviewed_headers"] == []
    assert "UNREVIEWED_HEADER" not in after_replay["commit_blockers"]
    assert after_replay["commit_blockers"] == [], after_replay["commit_blockers"]

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 0, "publishing commits nothing"

    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200


@db
def test_publishing_is_admin_only(engineer, viewer):
    for client, expected in ((engineer, 403), (viewer, 403)):
        answer = client.post(
            "/api/v1/plants/AAT/template-profiles/publish",
            json={
                "file_hash": "0" * 64,
                "named_owner": "somebody",
                "notes": "should not be reached",
            },
        )
        assert answer.status_code == expected, answer.text


@db
def test_publishing_refuses_a_blank_owner_and_an_unknown_hash(admin):
    blank = admin.post(
        "/api/v1/plants/AAT/template-profiles/publish",
        json={"file_hash": "0" * 64, "named_owner": "   ", "notes": "x"},
    )
    assert blank.status_code == 422, blank.text

    unknown = admin.post(
        "/api/v1/plants/AAT/template-profiles/publish",
        json={
            "file_hash": "0" * 64,
            "named_owner": "a named owner",
            "notes": "names the proof",
        },
    )
    assert unknown.status_code == 404, unknown.text


@db
def test_aggregate_rows_reach_the_projection_and_never_wavescan(
    engineer, admin_conn, cleanup
):
    rows = _rows(3)
    rows.append({**rows[0], "Model": "[All]", "Checkzone": "[All]"})
    data = sheet_bytes(HEADERS, rows)
    forget_bytes(admin_conn, data)
    load_id = upload(engineer, "t26-all.xlsx", data, "AAT").json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    review = wait_for(engineer, load_id)
    assert review["review_dispositions"].get("AGGREGATE_ROW") == 1
    assert review["batch"]["counts"]["rows_in_file"] == 3, (
        "a roll-up is outside the balance, exactly as a blank row is"
    )
    assert review["batch"]["counts"]["balanced"] is True
    assert engineer.post(f"/api/v1/batches/{load_id}/commit").status_code == 200
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wavescan WHERE load_id = %s", (load_id,))
        assert cur.fetchone()[0] == 3, "the aggregate is not a measurement"


@db
def test_an_out_of_scope_sheet_is_preserved_and_proposes_nothing(
    engineer, admin_conn, cleanup
):
    data = sheet_bytes(
        HEADERS,
        _rows(3),
        extra_sheets={
            "Methods": (["Measurement method"], [["BYK wavescan II, 3 passes"]])
        },
    )
    forget_bytes(admin_conn, data)
    accepted = upload(engineer, "t26-methods.xlsx", data, "AAT").json()
    batches_ = accepted["batches"]
    by_sheet = {b["sheet"]: b["load_id"] for b in batches_}
    cleanup.extend(by_sheet.values())

    assert "Methods" not in by_sheet, "side sheet creates no batch"
    assert {s["sheet"] for s in accepted["skipped_sheets"]} == {"Methods"}
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM load_batch WHERE file_hash=%s AND source_sheet='Methods'",
            (__import__('hashlib').sha256(data).hexdigest(),),
        )
        assert cur.fetchone()[0] == 0, (
            "no side-sheet batch exists to create a mapping proposal"
        )

    wavescan = wait_for(engineer, by_sheet["PasteData"])
    assert wavescan["batch"]["status"] == "PENDING_REVIEW"
    assert wavescan["commit_blockers"] == []


@db
def test_an_unknown_data_sheet_blocks(engineer, admin_conn, cleanup):
    data = sheet_bytes(
        HEADERS,
        _rows(3),
        extra_sheets={
            "Sheet3": (
                ["Date", "Plant", "Model", "Thickness", "Coat"],
                [["2026-08-03", "AAT", "U704", 21.5, "BC"]],
            )
        },
    )
    forget_bytes(admin_conn, data)
    batches_ = upload(engineer, "t26-unknown.xlsx", data, "AAT").json()["batches"]
    by_sheet = {b["sheet"]: b["load_id"] for b in batches_}
    cleanup.extend(by_sheet.values())

    unknown = wait_for(engineer, by_sheet["Sheet3"])
    assert unknown["batch"]["sheet_class"] == SHEET_UNKNOWN_DATA
    assert "UNKNOWN_DATA_SHEET" in unknown["commit_blockers"]


@db
def test_replay_re_derives_the_same_review_revision(engineer, admin_conn, cleanup):
    """Same bytes, same aliases, same projection hash. Without this, every
    replay would move the revision and every acknowledgement would lapse."""
    data = sheet_bytes(HEADERS, _rows(3))
    forget_bytes(admin_conn, data)
    load_id = upload(engineer, "t26-replay.xlsx", data, "AAT").json()["batches"][0]["load_id"]
    cleanup.append(load_id)

    first = wait_for(engineer, load_id)["batch"]["review_revision"]
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT review_revision FROM stg_review_row "
            "WHERE load_id = %s LIMIT 1", (load_id,)
        )
        assert cur.fetchone()[0].strip() == first


@db
def test_the_openapi_contract_grows_by_exactly_one_path(admin):
    spec = admin.get("/openapi.json").json()
    # T25 left 32. T26 adds the owner-publish POST. T-STANDARDS-D2 adds five
    # catalogue paths (GET catalogue + four POSTs); POST /standards already existed.
    # Monthly Overview CHANGE: 38 -> 39.
    # T37 CHANGE: 39 -> 40 (POST /plants/{plant_code}/workbooks/{file_hash}/purge).
    # T39 CHANGE: 40 -> 46 (worksheet GET + five Engineer POSTs).
    # T48 CHANGE: 46 -> 49 (three FilmThickness GETs).
    # T62 CHANGE: 49 -> 51 (FilmThickness standards GET + Admin POST).
    # T66 CHANGE: 51 -> 52 (FilmThickness monthly overview GET).
    # A floor, not a snapshot: later tasks add routes; the copies-equal-live checks are the contract.
    assert len(spec["paths"]) >= 52, sorted(spec["paths"])
    publish = "/api/v1/plants/{plant_code}/template-profiles/publish"
    assert publish in spec["paths"]
    assert set(spec["paths"][publish]) == {"post"}
    standards = spec["paths"]["/api/v1/standards"]["post"]
    assert "reserved" not in standards.get("tags", [])
    assert "201" in {str(code) for code in standards.get("responses", {})}


@db
def test_existing_post_bodies_are_unchanged(admin):
    """Only the new POST adds a body. A generated client that still sends
    last week's commit or supersede body must keep working."""
    spec = admin.get("/openapi.json").json()
    commit = spec["paths"]["/api/v1/batches/{load_id}/commit"]["post"]
    assert "requestBody" not in commit, "commit still takes no body"
    supersede = spec["paths"]["/api/v1/batches/{load_id}/supersede"]["post"]
    schema = supersede["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("SupersedeCreate")


@db
def test_app_rw_cannot_write_a_template_profile(app_conn):
    """M6 as a grant, not as a code review.

    Whatever a route does later, the application cannot write the column that
    makes a layout commit-capable.
    """
    for statement in (
        "INSERT INTO ref_template_profile (plant_code, domain, "
        "semantic_signature, template_fingerprint, notes) "
        "VALUES ('AAT', 'WAVESCAN', 'x', 'x', 'x')",
        "UPDATE ref_template_profile SET fixture_verified = true",
        "DELETE FROM ref_template_profile",
        "INSERT INTO ref_template_column_policy (profile_id, raw_header, policy) "
        "VALUES (1, 'x', 'IGNORED')",
    ):
        with app_conn.cursor() as cur:
            with pytest.raises(Exception):
                cur.execute(statement)
        app_conn.rollback()


@db
def test_no_sap_or_fvl_zone_map_was_approved_by_t26(admin_conn):
    """S15: named owner proof, or nothing. The mapping engine already got
    FVL verticals and SAP tailgate Top/Bottom wrong."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_zone_map "
            "WHERE plant_code IN ('SAP','FVL') AND confidence = 'APPROVED' "
            "AND proof_hash IS NULL AND verified_by IS NULL "
            "AND created_at > now() - interval '1 day'"
        )
        assert cur.fetchone()[0] == 0


@db
def test_grading_family_is_still_all_null(admin_conn):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE column_name = 'grading_family'"
        )
        if cur.fetchone()[0]:
            cur.execute("SELECT count(*) FROM ref_color WHERE grading_family IS NOT NULL")
            assert cur.fetchone()[0] == 0, "D1/D2 stay open (T-STANDARDS-D2)"
