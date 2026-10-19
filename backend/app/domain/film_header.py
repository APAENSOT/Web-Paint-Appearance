"""FilmThickness header vocabulary: what makes a header row a FilmBuild one.

Split from `film` so `reader` can classify a sheet without importing the
film cleaner (which itself reads `reader.RawRow`). No dependencies at all.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping, Sequence

DOMAIN_FILMTHICKNESS = "FILMTHICKNESS"
SHEET_FILMTHICKNESS = "FILMTHICKNESS"

#: Logical field -> canonical layer code (spec F9).
LAYER_FIELDS: dict[str, str] = {
    "ecoat": "ECOAT",
    "primer": "PRIMER",
    "base": "BASE",
    "clear": "CLEAR",
}
LAYER_CODES = tuple(LAYER_FIELDS.values())

#: T60 (D-60-05). Columns an owner named as **not** dashboard data -- PELT
#: ``Ground-coat`` and a sheet ``Orientation`` (Horizontal / Vertical words,
#: not microns; Film Hor/Ver lives on the gold point). Recognised so the
#: uploader is not asked to Ignore them, never a layer, never a fact. A sheet
#: may carry several; they never count as a duplicated field.
IGNORED_FIELD = "ignored"

#: Read and kept as evidence, never facts (D-FT-03c, T60).
NON_FACT_FIELDS = ("steel", "total_thickness", "status", "file_name", IGNORED_FIELD)

#: A FilmBuild header names a location and at least this many layers (spec section 7).
FILM_MIN_LAYERS = 2

#: PELT puts its header on row 14, AAT August on row 7 (D-FT-10c).
HEADER_SEARCH_ROWS = 20


def classify_film(fields: Iterable[str]) -> bool:
    present = set(fields)
    return "location" in present and len(present & set(LAYER_FIELDS)) >= FILM_MIN_LAYERS


def film_missing(fields: Iterable[str], meta: Mapping[str, object]) -> tuple[str, ...]:
    """What a FilmBuild sheet lacks before any data row can be read.

    Location and at least one layer from columns; date and colour from a
    column **or** the PELT preamble (``Date:`` / ``Layer 2:``) **or** the
    AAT EC1 banner (T56: ``date`` / ``color`` from `parse_ec1_banner`).
    """
    present = set(fields)
    missing: list[str] = []
    if "location" not in present:
        missing.append("location")
    if not present & set(LAYER_FIELDS):
        missing.append("layer")
    # RO18 (B4, RO09): a sheet with no date anywhere is read and asked which
    # month its cars were measured in; it is no longer refused here.
    if "color" not in present and not colour_meta(meta):
        missing.append("color")
    return tuple(missing)


def colour_meta(meta: Mapping[str, object]) -> object | None:
    """The colour a sheet's preamble names: PELT ``Layer 2:``, else the
    AAT EC1 banner swatch (T56). The raw text, never folded here."""
    for key in ("layer 2", BANNER_COLOUR):
        value = meta.get(key)
        if _filled(value):
            return value
    return None


#: T56 (D-56-01..05). Meta keys the AAT EC1 / Byk banner fills. ``date`` and
#: ``job number`` are the same keys the PELT ``Date:`` / ``Job Number:``
#: labels use, so the cleaner reads them unchanged; the swatch gets its own
#: key because it is not a PELT layer block.
BANNER_COLOUR = "banner colour"
EC1_LOCATION_HEADER = "checkzone"


def parse_ec1_banner(rows: Sequence[Sequence[object]]) -> dict[str, object]:
    """Identity from the AAT EC1 (Byk) banner above a ``Checkzone`` header.

    The live Aug/Sep sheets carry no Date / Color column (D-56-01):

    * **banner row** -- the first row above the header holding a date or
      datetime cell. Its first date/datetime is ``date`` (D-56-02; the two
      copies on the live files are one timestamp). Its first text cell is
      the instrument sample line (``2509105 P703 G9Z``) -> ``job number``
      (D-56-05). It is job text only: no model is parsed out of it, and it
      is never a VIN.
    * **swatch** -- row 2, first cell (``Shadow Black_4``) -> the banner
      colour, raw (D-56-03). Taken only when the same text also sits on the
      banner row, as it does on every live tab; a row-2 cell the banner does
      not repeat is not trusted as a colour.

    Nothing is folded or generated here. No banner datetime -> no ``date``
    key, and the sheet stays missing its date (never the upload day).
    """
    found: dict[str, object] = {}
    banner = next(
        (list(r or ()) for r in rows
         if any(isinstance(c, date) for c in (r or ()))),
        None,
    )
    if banner is None:
        return found
    found["date"] = next(c for c in banner if isinstance(c, date))
    job = next((c.strip() for c in banner if isinstance(c, str) and c.strip()), None)
    if job:
        found["job number"] = job
    if len(rows) >= 2 and rows[1]:
        swatch = rows[1][0]
        texts = {c.strip() for c in banner if isinstance(c, str)}
        if isinstance(swatch, str) and swatch.strip() and swatch.strip() in texts:
            found[BANNER_COLOUR] = swatch.strip()
    return found


def _filled(value: object) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def parse_pelt_meta(rows: Sequence[Sequence[object]]) -> dict[str, object]:
    """``Label:`` -> value pairs from the rows above a PELT header.

    Every cell ending in ``:`` is a label; the next non-blank cell on the
    same row is its value (``Date:`` / ``05-Jun-26``, ``Vin:`` / ``0``).
    Labels are lower-cased without the colon. Nothing is interpreted here.
    """
    meta: dict[str, object] = {}
    for row in rows:
        cells = list(row or ())
        for i, cell in enumerate(cells):
            if not isinstance(cell, str) or not cell.strip().endswith(":"):
                continue
            label = cell.strip()[:-1].strip().lower()
            if not label or label in meta:
                continue
            value = next(
                (c for c in cells[i + 1:]
                 if c is not None and not (isinstance(c, str) and not c.strip())),
                None,
            )
            if isinstance(value, str) and value.strip().endswith(":"):
                value = None
            meta[label] = value
    return meta


def layer_block_base_header(meta: Mapping[str, object]) -> str | None:
    """The colour named as PELT ``Layer 2``, normalised as a header.

    Spec 5.5: a colour-named column is Base **by profile** when the PELT
    layer block names Layer 2 as that colour. The column is bound because
    the file's own preamble says which layer it is, not because its header
    looks like a colour.
    """
    return layer_block_header(meta, 2)


def layer_block_header(meta: Mapping[str, object], n: int) -> str | None:
    """PELT ``Layer n``, normalised as a header; None when blank or absent."""
    value = meta.get(f"layer {n}")
    if not _filled(value):
        return None
    return str(value).strip().lower().replace("_", " ")


def layer_block_before(meta: Mapping[str, object], header: str) -> str | None:
    """RO02 (D-RO02-1). The PELT layer directly before the layer named
    ``header`` (a normalised header), normalised the same way.

    Called with the E-coat column's header, this is the Primer layer at
    every measured plant: Layer 3 in a five-layer block, Layer 4 in SAP's
    six-layer one (``Ground-coat`` sits between Base and Primer there).
    """
    n = 2
    while f"layer {n}" in meta:
        if layer_block_header(meta, n) == header:
            return layer_block_header(meta, n - 1)
        n += 1
    return None
