"""RO02 -- the PELT layer directly before E-coat is Primer; no column is dropped.

Claims (`docs/tasks/RO02-film-primer-from-layer-block.md`):

* D-RO02-1/2: AAT's repeated-colour shape binds Base on the first colour
  column and Primer on the second; an own-name pre-E-coat layer
  (``L48 Prime``, ``Med Gray``) binds as Primer.
* D-RO02-4: an alias-recognised primer (FTM / FVL ``Dk Grey Prime``, SAP
  six-layer ``Mid Grey``, AAT ``L28 BC1``), a sheet without a layer block,
  a block that disagrees with the header and a sheet without an E-coat
  column are not bound.
* D-RO02-3: every non-empty header cell is recognised, ignored or
  unrecognised, exactly once.

Pure: synthetic workbooks, the seeded alias words inline, no database.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.domain.reader import describe_film_sheet, normalise_header, read_film_sheet

#: The seeded FILMTHICKNESS aliases these shapes touch (0017, 0023, ...).
ALIAS = {
    "location": "location", "checkzone": "location", "clearcoat": "clear",
    "e-coat": "ecoat", "epic": "ecoat", "ec1": "ecoat", "bc1": "primer",
    "bc2": "base", "cc1": "clear", "steel": "steel",
    "thickness": "total_thickness", "dk grey prime": "primer",
    "mid grey": "primer", "l28 bc1": "primer", "ground-coat": "ignored",
}
SHEET = "Quick Summary"


def pelt(layers, header, row) -> bytes:
    """A PELT Quick Summary: ``Layer n:`` block (when given), header, one row."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(["Ford - PELT Filmbuild Report"])
    ws.append(["Date:", "05-Sep-26"])
    for n, name in enumerate(layers, start=1):
        ws.append([f"Layer {n}:", name])
    ws.append(header)
    ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def describe(layers, header, row=None):
    data = pelt(layers, header, row or ["001HOOD"] + [1.0] * (len(header) - 1))
    template = describe_film_sheet(data, SHEET, ALIAS)
    assert template is not None
    return data, template


def assert_every_cell_accounted(template, header):
    """D-RO02-3: no non-empty header cell is neither mapped nor listed."""
    cells = [normalise_header(c) for c in header if normalise_header(c)]
    assert len(template.recognised) + len(template.unrecognised) + len(template.ignored) \
        == len(cells), (template.recognised, template.unrecognised, template.ignored)


AAT_REPEATED = (
    ["Clearcoat", "Meteor Gray", "Meteor Gray", "E-coat", "Steel", ""],
    ["Location", "Clearcoat", "Meteor Gray", "Meteor Gray", "E-coat", "Steel", "Thickness"],
)


def test_aat_repeated_colour_base_first_primer_second():
    layers, header = AAT_REPEATED
    data, t = describe(layers, header, ["001HOOD", 40.1, 7.66, 7.90, 21.4, None, 77.06])
    assert t.recognised[2] == "base" and t.recognised[3] == "primer"
    assert t.base_from_layer_block and t.primer_from_layer_block
    assert t.unrecognised == () and t.as_json()["primer_from_layer_block"] is True
    (row,) = read_film_sheet(data, SHEET, t, "2504170 P703 42A.xlsx")
    got = {f: row.get(f) for f in ("clear", "base", "primer", "ecoat")}
    assert got == {"clear": 40.1, "base": 7.66, "primer": 7.90, "ecoat": 21.4}
    assert_every_cell_accounted(t, header)


@pytest.mark.parametrize("own", ["L48 Prime", "Med Gray", "L48 BC1", "Arctic White"])
def test_aat_own_name_pre_ecoat_layer_is_primer(own):
    layers = ["Clearcoat", "Acacia Green", own, "E-Coat", "Steel", ""]
    header = ["Location", "Clearcoat", "Acacia Green", own, "E-Coat", "Steel", "Thickness"]
    _, t = describe(layers, header)
    assert t.recognised[3] == "primer" and t.primer_from_layer_block
    assert t.unrecognised == ()
    assert_every_cell_accounted(t, header)


UNCHANGED = {
    "ftm_fvl_dk_grey_prime": (
        ["Clearcoat", "Absolute Black", "Dk Grey Prime", "E-Coat", "Steel", ""],
        ["Location", "Clearcoat", "Absolute Black", "Dk Grey Prime", "E-Coat", "Steel",
         "Thickness"],
    ),
    "sap_six_layer": (
        ["Clearcoat", "Ignite Orange 3", "Ground-coat", "Mid Grey", "EPIC", "Steel"],
        ["Location", "Clearcoat", "Ignite Orange 3", "Ground-coat", "Mid Grey", "EPIC",
         "Steel", "Thickness"],
    ),
    "aat_l28_bc1": (
        ["Clearcoat", "Traction Green", "L28 BC1", "E-Coat", "Steel", ""],
        ["Location", "Clearcoat", "Traction Green", "L28 BC1", "E-Coat", "Steel",
         "Thickness"],
    ),
}


@pytest.mark.parametrize("shape", sorted(UNCHANGED))
def test_alias_recognised_primer_is_untouched(shape):
    layers, header = UNCHANGED[shape]
    _, t = describe(layers, header)
    primers = [i for i, f in t.recognised.items() if f == "primer"]
    assert primers == [header.index(layers[-3] if shape == "sap_six_layer" else layers[2])]
    assert not t.primer_from_layer_block and t.base_from_layer_block
    assert t.unrecognised == ()
    if shape == "sap_six_layer":
        assert t.recognised[3] == "ignored", "Ground-coat stays a named non-fact"
    assert_every_cell_accounted(t, header)


def test_no_layer_block_is_untouched():
    header = AAT_REPEATED[1]
    _, t = describe([], header)
    assert "primer" not in t.recognised.values() and "base" not in t.recognised.values()
    assert not t.primer_from_layer_block
    assert t.unrecognised == ("meteor gray", "meteor gray"), "both still asked"
    assert_every_cell_accounted(t, header)


def test_ec1_banner_shape_is_untouched():
    header = ["Checkzone", "CC1", "BC2", "BC1", "EC1"]
    _, t = describe([], header)
    assert sorted(t.recognised.values()) == ["base", "clear", "ecoat", "location", "primer"]
    assert not t.primer_from_layer_block and not t.base_from_layer_block
    assert_every_cell_accounted(t, header)


def test_block_disagreeing_with_header_is_asked_not_bound():
    layers = ["Clearcoat", "Acacia Green", "L48 Prime", "E-Coat", "Steel", ""]
    header = ["Location", "Clearcoat", "Acacia Green", "L48 Primer", "E-Coat", "Steel",
              "Thickness"]
    _, t = describe(layers, header)
    assert "primer" not in t.recognised.values() and not t.primer_from_layer_block
    assert t.unrecognised == ("l48 primer",)
    assert_every_cell_accounted(t, header)


def test_no_ecoat_column_not_bound_and_repeat_still_asked():
    layers = AAT_REPEATED[0]
    header = ["Location", "Clearcoat", "Meteor Gray", "Meteor Gray", "Steel", "Thickness"]
    _, t = describe(layers, header)
    assert t.recognised[2] == "base" and "primer" not in t.recognised.values()
    # D-RO02-3: before RO02 the Base binding removed this second entry too.
    assert t.unrecognised == ("meteor gray",)
    assert_every_cell_accounted(t, header)


def test_pre_ecoat_layer_that_is_base_is_not_bound_twice():
    layers = ["Clearcoat", "Meteor Gray", "E-coat", "Steel"]
    header = ["Location", "Clearcoat", "Meteor Gray", "E-coat", "Steel", "Thickness"]
    _, t = describe(layers, header)
    assert t.recognised[2] == "base" and "primer" not in t.recognised.values()
    assert_every_cell_accounted(t, header)
