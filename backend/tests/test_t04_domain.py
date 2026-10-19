"""T04 -- the domain, tested without a database.

This file is the ported spirit of the vault's `test_cleaner.py`,
`test_dedup.py` and `test_mapping_engine.py`, plus the parts of T04 that are
pure: the header/template reader, the door checks, and the raw store.

**No database is needed for any of it, and that is the point.** The vault's
`ReferenceData` opened a connection in its constructor, so the cleaning rules
-- the part of this system most worth testing -- could not be exercised
without one. `00-ARCHITECTURE.md` §5 rule 1 forbids that coupling and
`AGENTS.md` §4 names it; these tests are what the fix buys.

The invariants asserted here are the ones the vault's own tests recorded from
real data: the HOOD/ROOF tolerance rule verified on 49/49 zones, the 80%
duplicate threshold validated against 255 true duplicate groups, and the
"keep the most complete row" rule that exists because FTM June carries B on
only the first copy of 224 duplicated rows.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.domain import mapping_engine as me
from app.domain.cleaner import (
    Cleaner,
    CleanRow,
    PAINTLINE_OMITTED_SENTINEL,
    PlantNotOnboarded,
    Reject,
    RejectReason,
    Unidentified,
    derive_tolerance,
    parse_date,
    parse_measure,
)
from app.domain.dedup import Deduplicator, ExistingMeasurement, similarity
from app.domain.reader import (
    RawRow,
    TemplateError,
    describe_sheet,
    normalise_header,
    read_sheet,
    sha256_hex,
    sheet_names,
)
from app.domain.references import ReferenceData
from app.services.raw_store import RawStore
from app.services.upload_guard import (
    GuardLimits,
    UploadRejected,
    check_file,
    check_request_size,
)

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_PACKAGE = BACKEND_ROOT / "app"

#: The seed of `ref_column_alias` (`01-DATA-MODEL.md` §6.3), as a lookup.
ALIAS_MAP = {
    "date": "date", "painted date": "date", "month": "month", "year": "year",
    "plant": "plant", "model": "model", "checkzone": "checkzone",
    "check zone": "checkzone", "color": "color", "colour": "color",
    "tolerance group": "tolerance_group", "paintline": "paintline",
    "serial no": "serial_no", "serial no.": "serial_no",
    "lw": "lw", "sw": "sw", "cf": "cf", "doi": "doi", "du": "du",
    "wa": "wa", "wb": "wb", "wc": "wc", "wd": "wd", "we": "we", "b": "b",
}

HEADERS = [
    "Date", "Month", "Year", "Plant", "Model", "Checkzone", "Color",
    "Tolerance Group", "Paintline", "Serial No",
    "LW", "SW", "CF", "DOI", "du", "Wa", "Wb", "Wc", "Wd", "We", "B",
]


def workbook_bytes(rows, headers=HEADERS, sheet="PasteData") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def data_row(**over) -> list:
    values = {
        "Date": datetime(2026, 6, 17), "Month": "June", "Year": 2026,
        "Plant": "AAT", "Model": "U704", "Checkzone": "01 RRHOOD",
        "Color": "3HC Traction Green", "Tolerance Group": "Horizontal",
        "Paintline": "BOOTH1", "Serial No": 2483403,
        "LW": 3.7, "SW": 15.7, "CF": 60.9, "DOI": 87.5, "du": 15.9,
        "Wa": 13.4, "Wb": 21.5, "Wc": 11.6, "Wd": 12.7, "We": 6.7, "B": -0.2,
    }
    values.update(over)
    return [values[h] for h in HEADERS]


def make_raw(**values) -> RawRow:
    return RawRow(source_file="t.xlsx", source_sheet="s", source_row=2, values=values)


REFERENCE = ReferenceData(
    plant={"aat": "AAT", "ftm": "FTM"},
    model={"u704": "U704", "p703": "P703 DBL RANGER"},
    checkzone={"01 rrhood": "RRHOOD", "06 lffender": "LFFENDER"},
    color={"3hc traction green": "Traction Green"},
    paintline={"booth1": "BOOTH1"},
    model_zone=frozenset({("U704", "RRHOOD"), ("U704", "LFFENDER")}),
    expected_zones={"U704": 31, "P703 DBL RANGER": 32},
    requires_serial={"AAT": True, "FTM": True, "FVL": False},
    active_plants=frozenset({"AAT", "FTM"}),
    known_plants=frozenset({"AAT", "FTM", "FVL"}),
    column_alias=ALIAS_MAP,
    offered_colors={
        ("AAT", "Traction Green"): True,
        ("FTM", "Traction Green"): True,
        ("AAT", "Frozen White"): True,
        ("FVL", "Vapor Blue"): True,
    },
    offered_models={
        ("AAT", "U704"): True,
        ("FTM", "U704"): True,
        ("AAT", "P703 DBL RANGER"): True,
        ("FTM", "P703 DBL RANGER"): True,
        ("FVL", "P703 DBL RANGER"): True,
    },
)


@pytest.fixture()
def cleaner() -> Cleaner:
    return Cleaner(REFERENCE, ("AAT", "FTM"))


# =====================================================================
# 1. the dependency rule
# =====================================================================
def test_the_domain_package_imports_no_framework():
    """`00-ARCHITECTURE.md` §5 rule 1, and T04's first acceptance criterion.

    openpyxl is allowed: it is a file parser, not a framework, and the rule
    names the three that make a module untestable without infrastructure.
    """
    banned = re.compile(r"^\s*(?:import|from)\s+(fastapi|psycopg|sqlalchemy)\b", re.M)
    offenders = []
    for path in (APP_PACKAGE / "domain").rglob("*.py"):
        hit = banned.search(path.read_text(encoding="utf-8"))
        if hit:
            offenders.append(f"{path.name}: {hit.group(1)}")
    assert not offenders, offenders


def test_the_domain_package_reads_no_configuration():
    """A pure module that calls os.getenv is still coupled, just invisibly."""
    for path in (APP_PACKAGE / "domain").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "os.getenv" not in source and "os.environ" not in source, path.name


# =====================================================================
# 2. reader and template fingerprint
# =====================================================================
def test_headers_are_normalised_the_way_the_alias_table_stores_them():
    assert normalise_header("  Serial_No ") == "serial no"
    assert normalise_header(None) == ""


def test_a_known_template_is_parseable():
    data = workbook_bytes([data_row()])
    template = describe_sheet(data, "PasteData", ALIAS_MAP)
    assert template.is_parseable
    assert template.missing_required == ()
    assert set(template.recognised.values()) >= {
        "date", "plant", "model", "checkzone", "color", "serial_no"
    }


def test_a_missing_required_column_is_reported_not_guessed():
    """`02-PIPELINE.md` §4: show the header diff, do not parse data rows.

    T39 CHANGE (ADR 0013): Serial No is no longer a required column -- a
    sheet without it parses and its serials are NULL. Checkzone still is.
    """
    headers = [h for h in HEADERS if h != "Checkzone"]
    data = workbook_bytes([[v for h, v in zip(HEADERS, data_row()) if h != "Checkzone"]],
                          headers=headers)
    template = describe_sheet(data, "PasteData", ALIAS_MAP)
    assert not template.is_parseable
    assert template.missing_required == ("checkzone",)

    with pytest.raises(TemplateError) as exc:
        list(read_sheet(data, "PasteData", ALIAS_MAP, "t.xlsx"))
    assert "checkzone" in str(exc.value)

    no_serial = [h for h in HEADERS if h != "Serial No"]
    serialless = workbook_bytes(
        [[v for h, v in zip(HEADERS, data_row()) if h != "Serial No"]],
        headers=no_serial,
    )
    assert describe_sheet(serialless, "PasteData", ALIAS_MAP).is_parseable


def test_two_spellings_of_the_same_template_fingerprint_alike():
    """An alias is what makes two spellings one template, so the fingerprint
    must not change when a plant renames a column it already maps."""
    a = describe_sheet(workbook_bytes([data_row()]), "PasteData", ALIAS_MAP)
    renamed = list(HEADERS)
    renamed[0] = "Painted Date"
    renamed[6] = "Colour"
    b = describe_sheet(
        workbook_bytes([data_row()], headers=renamed), "PasteData", ALIAS_MAP
    )
    assert a.fingerprint == b.fingerprint


def test_a_reordered_template_fingerprints_differently():
    reordered = HEADERS[10:] + HEADERS[:10]
    values = data_row()
    row = values[10:] + values[:10]
    a = describe_sheet(workbook_bytes([values]), "PasteData", ALIAS_MAP)
    b = describe_sheet(
        workbook_bytes([row], headers=reordered), "PasteData", ALIAS_MAP
    )
    assert a.fingerprint != b.fingerprint


def test_an_unrecognised_column_is_kept_not_dropped():
    """`01-DATA-MODEL.md` §4: nothing a file said is lost because no alias
    existed yet. It lands in stg_raw.extra."""
    headers = HEADERS + ["Operator Initials"]
    data = workbook_bytes([data_row() + ["JW"]], headers=headers)
    rows = list(read_sheet(data, "PasteData", ALIAS_MAP, "t.xlsx"))
    assert rows[0].extra == {"operator initials": "JW"}


def test_blank_rows_are_skipped():
    data = workbook_bytes([data_row(), [None] * len(HEADERS), data_row(**{"Serial No": 7})])
    rows = list(read_sheet(data, "PasteData", ALIAS_MAP, "t.xlsx"))
    assert [r.source_row for r in rows] == [2, 4], (
        "source_row must stay the spreadsheet's own row number"
    )


def test_the_hash_is_of_the_bytes():
    data = workbook_bytes([data_row()])
    assert sha256_hex(data) == sha256_hex(bytes(data))
    assert sha256_hex(data) != sha256_hex(data + b" ")


def test_sheet_names_are_read_without_parsing_rows():
    assert sheet_names(workbook_bytes([data_row()], sheet="Jul2026")) == ["Jul2026"]


# =====================================================================
# 3. cleaner: tolerance, dates, numbers
# =====================================================================
@pytest.mark.parametrize(
    "zone,expected",
    [
        ("RRHOOD", "Horizontal"), ("CFHOOD", "Horizontal"),
        ("LCROOF", "Horizontal"), ("RCROOF", "Horizontal"),
        ("LFFENDER", "Vertical"), ("LCPILLAR", "Vertical"),
        ("LIFTGATEHILH", "Vertical"), ("LFBOX", "Vertical"),
        ("LTTAILGATE", "Vertical"),
    ],
)
def test_tolerance_rule(zone, expected):
    assert derive_tolerance(zone) == expected


def test_tolerance_ignores_the_value_in_the_file():
    """The file says LCROOF is Vertical on nine rows. `02-PIPELINE.md` §5:
    "Do not reverse that"."""
    assert derive_tolerance("LCROOF") == "Horizontal"


def test_date_from_an_excel_datetime():
    d, err = parse_date(make_raw(date=datetime(2026, 7, 2, 13, 28)))
    assert err is None and d == date(2026, 7, 2)


def test_date_text_takes_its_year_from_the_year_column():
    """AAT writes '6/17 8:04 AM' with the year in a separate column."""
    d, err = parse_date(make_raw(date="6/17 8:04 AM", year=2026))
    assert err is None and d == date(2026, 6, 17)


def test_date_text_without_a_year_is_an_error_not_a_guess():
    d, err = parse_date(make_raw(date="6/17 8:04 AM", year=None))
    assert d is None and "no year" in err


def test_an_unparseable_date_is_named():
    d, err = parse_date(make_raw(date="last tuesday"))
    assert d is None and "unrecognised date format" in err


def test_measurements_are_not_rounded_on_the_way_in():
    """`AGENTS.md` §4 and L12. The vault rounded to one decimal here; a
    workbook's float4 artefact is what the file says, and the platform stores
    what the file says."""
    value, err = parse_measure(2.70000004768372)
    assert err is None
    assert value == Decimal("2.70000004768372")


def test_a_blank_measurement_is_none_not_zero():
    assert parse_measure(None) == (None, None)
    assert parse_measure("   ") == (None, None)


def test_a_non_numeric_measurement_is_an_error():
    value, err = parse_measure("n/a")
    assert value is None and "not a number" in err


# =====================================================================
# 4. cleaner: rows
# =====================================================================
def test_a_good_row_cleans(cleaner):
    row = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="aat", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no=2483403,
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(row, CleanRow)
    assert row.plant == "AAT" and row.checkzone == "RRHOOD"
    assert row.tolerance_group == "Horizontal"
    assert row.serial_no == "2483403", "a numeric serial must not become '2483403.0'"
    assert row.src_zone_text == "01 RRHOOD" and row.src_zone_no == 1


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("color", "Not A Colour", RejectReason.UNKNOWN_COLOR),
        ("model", "Q999", RejectReason.UNKNOWN_MODEL),
        ("checkzone", "99 NOWHERE", RejectReason.UNKNOWN_CHECKZONE),
        ("paintline", "BOOTH9", RejectReason.UNKNOWN_PAINTLINE),
    ],
)
def test_an_unknown_value_is_rejected_never_guessed(cleaner, field, value, reason):
    """`AGENTS.md` rule 6. A new spelling is one INSERT in an alias table."""
    values = dict(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    )
    values[field] = value
    out = cleaner.clean_row(make_raw(**values))
    assert isinstance(out, Reject) and out.reason == reason


def test_a_unique_colour_fold_loads_without_an_exact_alias():
    """Paint-code suffix onto one catalogue name is identity, not a guess."""
    folding = replace(
        REFERENCE,
        known_color_names=frozenset({"Traction Green", "Frozen White", "Shadow Black"}),
    )
    out = Cleaner(folding, ("AAT", "FTM")).clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="Frozen White 7VTAWWA", paintline="BOOTH1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, CleanRow)
    assert out.color == "Frozen White"


def test_an_ambiguous_colour_fold_stays_unknown():
    folding = replace(
        REFERENCE,
        known_color_names=frozenset({"Shadow Black", "Agate Black"}),
    )
    out = Cleaner(folding, ("AAT", "FTM")).clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="AB - Absolute Black", paintline="BOOTH1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, Reject) and out.reason == RejectReason.UNKNOWN_COLOR


def test_resolved_colour_not_offered_is_held():
    ref = replace(
        REFERENCE,
        color={"ignite orange": "Ignite Orange"},
        known_color_names=frozenset({"Ignite Orange"}),
        offered_colors={("SAP", "Ignite Orange"): False},
        offered_models={("SAP", "P703 DBL RANGER"): True},
        model={"p703 dbl ranger": "P703 DBL RANGER"},
        plant={"sap": "SAP", **dict(REFERENCE.plant)},
        model_zone=frozenset(REFERENCE.model_zone | {("P703 DBL RANGER", "RRHOOD")}),
        active_plants=frozenset(set(REFERENCE.active_plants) | {"SAP"}),
        known_plants=frozenset(set(REFERENCE.known_plants) | {"SAP"}),
        requires_serial={**REFERENCE.requires_serial, "SAP": True},
    )
    out = Cleaner(ref, ("AAT", "FTM", "SAP")).clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="SAP", model="P703 DBL RANGER",
        checkzone="01 RRHOOD", color="Ignite Orange", paintline="BOOTH1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, Reject) and out.reason == RejectReason.COLOR_NOT_OFFERED


def test_resolved_model_not_offered_is_held():
    ref = replace(
        REFERENCE,
        offered_models={("AAT", "P703 DBL RANGER"): False, ("AAT", "U704"): True},
    )
    out = Cleaner(ref, ("AAT", "FTM")).clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="P703",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, Reject) and out.reason == RejectReason.MODEL_NOT_OFFERED


def test_paintline_whitespace_folds_onto_the_booth_alias(cleaner):
    out = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH  1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, CleanRow)
    assert out.paintline == "BOOTH1"


def test_a_zone_that_does_not_exist_on_the_model_is_rejected(cleaner):
    """`ref_model_zone` is what makes a U704 liftgate on a pickup impossible."""
    out = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="P703",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1",
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, Reject)
    assert out.reason == RejectReason.ZONE_NOT_VALID_FOR_MODEL


def test_an_unnamed_model_is_quarantined_not_rejected(cleaner):
    """Quarantine, because the measurement is probably fine and only the
    model is missing -- a human resolves it and the rows replay."""
    out = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="(none)",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1",
    ))
    assert isinstance(out, Unidentified) and out.raw_model == "(none)"


def test_a_missing_measurement_is_rejected(cleaner):
    out = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1", lw=1.0,
    ))
    assert isinstance(out, Reject)
    assert out.reason == RejectReason.MISSING_MEASUREMENT


def test_a_blank_serial_loads_null_even_where_the_plant_used_to_require_one(cleaner):
    """T39 CHANGE (ADR 0013 decision 2): blank serial loads NULL at every
    plant, including AAT whose `requires_serial` is true. Never generated."""
    out = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no=None,
        **{m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")},
    ))
    assert isinstance(out, CleanRow), out
    assert out.serial_no is None


def test_fvl_none_paintline_is_blank_not_a_booth_and_not_a_roll_up():
    """Paintline `(None)` is a documented sentinel, not BOOTH1 and not `[All]`.

    Mapping it to a booth would invent a production line. Treating it as
    `[All]` would drop the 32 leaf rows of the named September file. The
    cleaner loads the leaf with paintline NULL and records that the cell was
    a sentinel. T39 CHANGE (ADR 0013 decision 2): a truly blank paintline at
    AAT now loads NULL too, with no sentinel marker.
    """
    ref = replace(
        REFERENCE,
        plant={**dict(REFERENCE.plant), "fvl": "FVL"},
        color={
            **dict(REFERENCE.color),
            "vb - vapor blue bc": "Vapor Blue",
        },
        model={
            **dict(REFERENCE.model),
            "p703 dbl": "P703 DBL RANGER",
        },
        model_zone=frozenset(REFERENCE.model_zone | {("P703 DBL RANGER", "RRHOOD")}),
        plant_zone_map={("FVL", "P703 DBL RANGER", "01hood"): "RRHOOD"},
        active_plants=frozenset(set(REFERENCE.active_plants) | {"FVL"}),
        known_plants=frozenset(set(REFERENCE.known_plants) | {"FVL"}),
    )
    fvl = Cleaner(ref, ("AAT", "FTM", "FVL"), expected_plant="FVL")
    measures = {m: 1.5 for m in ("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we")}
    out = fvl.clean_row(make_raw(
        date=datetime(2026, 9, 8), plant="FVL", model="P703 DBL",
        checkzone="01HOOD", color="VB - VAPOR BLUE BC", paintline="(None)",
        serial_no="leaf",
        **measures,
    ))
    assert isinstance(out, CleanRow), out
    assert out.paintline is None
    assert out.paintline_omitted_reason == PAINTLINE_OMITTED_SENTINEL
    assert out.color == "Vapor Blue"
    assert out.checkzone == "RRHOOD"
    assert out.model == "P703 DBL RANGER"

    blank_fvl = fvl.clean_row(make_raw(
        date=datetime(2026, 9, 8), plant="FVL", model="P703 DBL",
        checkzone="01HOOD", color="VB - VAPOR BLUE BC", paintline=None,
        serial_no="leaf",
        **measures,
    ))
    assert isinstance(blank_fvl, CleanRow), blank_fvl
    assert blank_fvl.paintline is None
    assert blank_fvl.paintline_omitted_reason is None

    aat = Cleaner(REFERENCE, ("AAT", "FTM"))
    sentinel = aat.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="(None)",
        serial_no="1",
        **measures,
    ))
    assert isinstance(sentinel, CleanRow), sentinel
    assert sentinel.paintline is None
    assert sentinel.paintline_omitted_reason == PAINTLINE_OMITTED_SENTINEL

    missing = aat.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="AAT", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline=None,
        serial_no="1",
        **measures,
    ))
    assert isinstance(missing, CleanRow), missing
    assert missing.paintline is None
    assert missing.paintline_omitted_reason is None


def test_a_plant_out_of_scope_is_rejected(cleaner):
    out = cleaner.clean_row(make_raw(
        date=datetime(2026, 6, 17), plant="SAP", model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1",
    ))
    assert isinstance(out, Reject)


# =====================================================================
# 4b. T17 -- a blank Plant cell inherits the upload's expected_plant
# =====================================================================
def scoped_cleaner(expected_plant: str) -> Cleaner:
    """A cleaner for an upload that declared its plant.

    The code is passed in as a string. That is the whole coupling: no route,
    no Settings, no connection, so the fill rule is testable here with no
    infrastructure at all (`00-ARCHITECTURE.md` §5 rule 1).
    """
    return Cleaner(REFERENCE, ("AAT", "FTM"), expected_plant=expected_plant)


def blank_plant_row(**over):
    base = dict(
        date=datetime(2026, 6, 17), plant=None, model="U704",
        checkzone="01 RRHOOD", color="3HC Traction Green", paintline="BOOTH1",
        serial_no="1", lw=1.0, sw=1.0, cf=60.0, doi=80.0, du=1.0,
        wa=1.0, wb=1.0, wc=1.0, wd=1.0, we=1.0,
    )
    base.update(over)
    return make_raw(**base)


def test_a_blank_plant_cell_is_filled_from_the_expected_plant(cleaner):
    """Without a declared plant this is still MISSING_REQUIRED_FIELD; with
    one it is the plant the person uploading named."""
    blank = blank_plant_row()

    unscoped = cleaner.clean_row(blank)
    assert isinstance(unscoped, Reject)
    assert unscoped.reason == RejectReason.MISSING_REQUIRED_FIELD
    assert unscoped.column == "plant"

    scoped = scoped_cleaner("AAT").clean_row(blank)
    assert isinstance(scoped, CleanRow)
    assert scoped.plant == "AAT"
    assert scoped.plant_filled is True, "the fill must be visible on the row"


def test_a_nonblank_plant_cell_is_never_overwritten_by_the_expected_plant():
    """The cleaner's job is to not relabel.

    T39 CHANGE (ADR 0013 decision 3): a cell saying FTM on an AAT upload is
    held as PLANT_MISMATCH and asked about -- neither written as FTM under an
    AAT batch nor silently relabelled AAT.
    """
    out = scoped_cleaner("AAT").clean_row(blank_plant_row(plant="FTM"))
    assert isinstance(out, Reject)
    assert out.reason == RejectReason.PLANT_MISMATCH
    assert out.value == "FTM"


def test_the_filled_cells_are_counted_over_a_whole_sheet():
    rows = [blank_plant_row(serial_no="1"), blank_plant_row(serial_no="2"),
            blank_plant_row(serial_no="3", plant="AAT")]
    result = scoped_cleaner("AAT").clean_all(rows)
    assert len(result.clean) == 3
    assert {r.plant for r in result.clean} == {"AAT"}
    assert result.plant_cells_filled == 2, "a cell that already said AAT is not a fill"


# =====================================================================
# 5. the D5 gate
# =====================================================================
def test_a_known_but_inactive_plant_refuses_the_whole_file(cleaner):
    """D5. One clear answer beats 1504 identical per-row rejects."""
    with pytest.raises(PlantNotOnboarded) as exc:
        cleaner.check_plant_is_onboarded({"FVL"})
    assert exc.value.plant_code == "FVL"
    assert "D5" in exc.value.detail


def test_an_active_plant_passes_the_gate(cleaner):
    cleaner.check_plant_is_onboarded({"AAT", "FTM"})


def test_an_entirely_unknown_plant_is_not_the_gate_s_business(cleaner):
    """A plant nobody has heard of is a per-row reject, not a D5 refusal:
    the file may be a typo, and refusing the whole upload would hide the
    rows that are fine."""
    cleaner.check_plant_is_onboarded({"ZZZ"})


def test_the_gate_is_driven_by_data_not_by_a_plant_name_in_code():
    """`AGENTS.md` rule 6: never guess a plant, and never special-case one.

    The gate reads `ref_plant.is_active`. Prose may name FVL -- explaining
    why a rule exists is the job of a docstring -- but no branch may.
    """
    docstrings = re.compile(r'"""(?:.|\n)*?"""')
    for path in (APP_PACKAGE / "domain").rglob("*.py"):
        code = docstrings.sub("", path.read_text(encoding="utf-8"))
        code = "\n".join(
            line for line in code.splitlines() if not line.lstrip().startswith("#")
        )
        # T76 CHANGE: a branch on a plant *compares* against its literal
        # (`== "FVL"`, `!= 'FVL'`, `in ("FVL", ...)`). T46/T47 name catalogue
        # constants after the walk they were proved from
        # (`film_catalog.FVL_GOLD_94`, keyed by model), and T28's offline
        # `zone_audit` transcribes migration 0009's owner lock as data -- neither
        # is a branch. A comparison against the plant name still fails here.
        branch = re.compile(
            r"""(==|!=|\bin\b|\bnot in\b)\s*[\(\[{]?[^\n]*?["']FVL["']"""
        )
        hit = branch.search(code)
        assert hit is None, f"{path.name} branches on a plant name: {hit and hit.group(0)}"


# =====================================================================
# 6. dedup
# =====================================================================
def dedup_row(source_row: int, b=None, cf=Decimal("60.9"), **over) -> CleanRow:
    measures = {
        "lw": Decimal("3.7"), "sw": Decimal("15.7"), "cf": cf,
        "doi": Decimal("87.5"), "du": Decimal("15.9"), "wa": Decimal("13.4"),
        "wb": Decimal("21.5"), "wc": Decimal("11.6"), "wd": Decimal("12.7"),
        "we": Decimal("6.7"), "b": b,
    }
    measures.update({k: Decimal(str(v)) for k, v in over.items()})
    return CleanRow(
        measured_date=date(2026, 6, 17), plant="FTM", model="P703 DBL RAPTOR",
        checkzone="RRHOOD", color="Meteor Grey", tolerance_group="Horizontal",
        paintline="BOOTH1", serial_no="1943732", measures=measures,
        source_file="f.xlsx", source_sheet="s", source_row=source_row,
    )


def test_identical_rows_score_100():
    assert similarity(dedup_row(2), dedup_row(9)) == 100.0


def test_different_measurements_score_low():
    other = dedup_row(9, lw=99, sw=88, cf=77, doi=66, du=55,
                      wa=44, wb=33, wc=22, wd=11, we=1)
    assert similarity(dedup_row(2), other) == 0.0


def test_float4_noise_does_not_stop_two_rows_matching():
    """The reason rounding moved out of the cleaner and into here: a workbook
    stores 2.7 as 2.70000004768372, and two copies of the same measurement
    must still be one measurement."""
    noisy = dedup_row(9, lw=Decimal("3.70000004768372"))
    assert similarity(dedup_row(2), noisy) == 100.0


def test_a_duplicate_is_dropped():
    result = Deduplicator(80.0).run([dedup_row(2, b=Decimal("-0.2")), dedup_row(9)])
    assert len(result.keep) == 1 and len(result.duplicates) == 1


def test_the_most_complete_row_wins():
    """FTM June: only the first copy carries B. Keeping the wrong one would
    destroy 224 B values."""
    result = Deduplicator(80.0).run([dedup_row(2, b=Decimal("-0.2")), dedup_row(9)])
    assert result.keep[0].measures["b"] == Decimal("-0.2")


def test_a_genuine_re_measurement_is_kept():
    """Same vehicle and zone, different numbers: not a duplicate."""
    other = dedup_row(9, lw=99, sw=88, cf=77, doi=66, du=55,
                      wa=44, wb=33, wc=22, wd=11, we=1)
    result = Deduplicator(80.0).run([dedup_row(2), other])
    assert len(result.keep) == 2 and not result.duplicates


def test_a_row_already_in_the_database_is_a_duplicate():
    """The cross-file case: AAT June car 2478750 reappears in July."""
    row = dedup_row(2)
    existing = {
        row.key(): [ExistingMeasurement(
            measures={m: row.measures[m] for m in row.measures if m != "b"},
            source="June.xlsx [PasteData] row 5",
        )]
    }
    result = Deduplicator(80.0).run([row], existing)
    assert not result.keep
    assert "already loaded from June.xlsx" in result.duplicates[0].kept_description


def test_a_different_vehicle_is_not_a_duplicate_of_this_one():
    """`key()` is (plant, serial, zone): serial alone is not unique across
    plants."""
    a = dedup_row(2)
    b = dedup_row(3)
    object.__setattr__(b, "plant", "AAT")
    assert a.key() != b.key()


# =====================================================================
# 7. mapping engine
# =====================================================================
def test_panel_group_is_guessed_from_a_keyword():
    assert me.guess_panel_group("17 Liftgate Hi LH") == "LIFTGATE"
    assert me.guess_panel_group("01RHS Hood Rr28") == "HOOD"
    assert me.guess_panel_group("something else entirely") is None


def test_the_position_number_is_provenance_only():
    assert me.extract_position("01RHS Hood Rr28") == 1
    assert me.extract_position("RRHOOD") is None


def test_a_count_mismatch_is_unresolved_not_a_guess():
    canonical = [me.CanonicalZone("RRHOOD", 1, "HOOD", "Horizontal", "RR Hood")]
    raw = [me.RawZone("01 Hood A", 1), me.RawZone("02 Hood B", 2)]
    result = me.propose_mapping(canonical, raw)
    assert not result.proposals
    assert all("counts" in u.reason for u in result.unresolved)


def test_a_matching_group_is_proposed_with_the_canonical_name_for_review():
    canonical = [
        me.CanonicalZone("RRHOOD", 1, "HOOD", "Horizontal", "RR Hood"),
        me.CanonicalZone("RFHOOD", 2, "HOOD", "Horizontal", "RF Hood"),
    ]
    raw = [me.RawZone("01RHS Hood Rr28", 1), me.RawZone("02RHS Hood Frnt29", 2)]
    result = me.propose_mapping(canonical, raw)
    assert len(result.proposals) == 2
    assert "RR Hood" in result.proposals[0].note, (
        "the reviewer needs the canonical name to catch a swapped pair"
    )


# =====================================================================
# 8. door checks
# =====================================================================
LIMITS = GuardLimits()


def test_a_good_workbook_passes():
    check_file("june.xlsx", workbook_bytes([data_row()]), LIMITS)


def test_an_empty_request_is_refused():
    with pytest.raises(UploadRejected) as exc:
        check_request_size(0, LIMITS)
    assert exc.value.reason == "NO_FILES"


def test_too_many_files_is_refused():
    with pytest.raises(UploadRejected) as exc:
        check_request_size(41, LIMITS)
    assert exc.value.reason == "TOO_MANY_FILES"


def test_the_extension_is_checked():
    with pytest.raises(UploadRejected) as exc:
        check_file("payroll.xls", workbook_bytes([data_row()]), LIMITS)
    assert exc.value.reason == "BAD_EXTENSION"


def test_the_extension_is_not_trusted():
    """`02-PIPELINE.md` §2: sniff the magic bytes; the name is a claim."""
    with pytest.raises(UploadRejected) as exc:
        check_file("evil.xlsx", b"#!/bin/sh\nrm -rf /\n", LIMITS)
    assert exc.value.reason == "NOT_A_WORKBOOK"


def test_an_empty_file_is_refused():
    with pytest.raises(UploadRejected) as exc:
        check_file("empty.xlsx", b"", LIMITS)
    assert exc.value.reason == "EMPTY_FILE"


def test_an_oversized_file_is_refused():
    limits = GuardLimits(max_file_bytes=1024)
    with pytest.raises(UploadRejected) as exc:
        check_file("big.xlsx", workbook_bytes([data_row()] * 50), limits)
    assert exc.value.reason == "TOO_LARGE"


def test_a_zip_bomb_is_refused_before_it_is_parsed():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"0" * (8 * 1024 * 1024))
    with pytest.raises(UploadRejected) as exc:
        check_file("bomb.xlsx", buffer.getvalue(), GuardLimits())
    assert exc.value.reason == "ZIP_BOMB"


def test_a_zip_that_is_not_a_workbook_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", b"hello")
    with pytest.raises(UploadRejected) as exc:
        check_file("notes.xlsx", buffer.getvalue(), LIMITS)
    assert exc.value.reason == "NOT_A_WORKBOOK"


def test_a_traversing_archive_entry_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", b"<x/>")
        archive.writestr("../../etc/passwd", b"root")
    with pytest.raises(UploadRejected) as exc:
        check_file("traverse.xlsx", buffer.getvalue(), LIMITS)
    assert exc.value.reason == "UNSAFE_ENTRY"


def test_a_corrupt_archive_is_refused():
    with pytest.raises(UploadRejected) as exc:
        check_file("torn.xlsx", b"PK\x03\x04" + b"\x00" * 200, LIMITS)
    assert exc.value.reason == "CORRUPT_ARCHIVE"


# =====================================================================
# 9. raw store
# =====================================================================
def test_the_store_is_content_addressed(tmp_path):
    store = RawStore(tmp_path)
    data = b"some bytes"
    key = store.put(sha256_hex(data), data)
    assert store.get(key) == data
    # Writing the same bytes again is a no-op, so a retry cannot corrupt it.
    assert store.put(sha256_hex(data), data) == key


def test_a_key_cannot_escape_the_store_root(tmp_path):
    store = RawStore(tmp_path)
    for bad in ("wavescan/raw/../../etc/passwd", "wavescan/raw/nope", "elsewhere/x"):
        with pytest.raises(ValueError):
            store.path_for(bad)


def test_a_missing_object_says_what_it_blocks(tmp_path):
    store = RawStore(tmp_path)
    with pytest.raises(FileNotFoundError) as exc:
        store.get("wavescan/raw/" + "0" * 64)
    assert "replayed or committed" in str(exc.value)


def test_the_store_reports_its_own_health(tmp_path):
    assert RawStore(tmp_path).health()["status"] == "ok"
