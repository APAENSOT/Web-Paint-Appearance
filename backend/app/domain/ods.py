"""Read an OpenDocument spreadsheet (`.ods`) as rows of cell values.

T46 (spec F15, section 7): SAP sends its PELT Quick Summary as `.ods`. The
spec leaves the library to discretion "as long as SHA-256 is of the uploaded
bytes". This module is the smallest reader that satisfies that: the standard
library's ``zipfile`` and ``xml.etree`` over the bytes ingest already stored,
so no new dependency and no conversion step that could write a second copy
of the workbook anywhere.

It returns the same shape the openpyxl path does -- tuples of Python values
per row, one row per spreadsheet row -- so `reader` can treat both formats
as one iterator. It interprets nothing: a float cell is a ``float`` exactly
as openpyxl would give it, a date cell is a ``datetime``, a time cell a
``datetime.time`` (T75), text is text.

Pure: no FastAPI, no psycopg.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, time
from io import BytesIO
from typing import Iterator

ODS_MIMETYPE = b"application/vnd.oasis.opendocument.spreadsheet"

_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"

#: A PELT sheet is a few hundred rows. Blank rows or columns repeated past
#: these limits are the sheet's trailing emptiness, never data, and are not
#: materialised (LibreOffice writes `number-rows-repeated="1048000"`).
_MAX_BLANK_RUN = 5000

#: ``office:time-value`` is an ISO 8601 duration (``PT11H25M0S``).
_DURATION = re.compile(r"^-?PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")


class OdsError(ValueError):
    """The bytes are a ZIP but not a readable OpenDocument spreadsheet."""


def is_ods(data: bytes) -> bool:
    """True when the archive declares the ODS mimetype (its first entry)."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            return archive.read("mimetype").strip() == ODS_MIMETYPE
    except (zipfile.BadZipFile, KeyError):
        return False


def _content(data: bytes) -> ET.Element:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        try:
            xml = archive.read("content.xml")
        except KeyError as exc:
            raise OdsError("ODS archive has no content.xml") from exc
    # A spreadsheet has no business declaring entities. Refusing any DOCTYPE
    # closes the entity-expansion family before the parser sees it.
    if b"<!DOCTYPE" in xml[:4096].upper() or b"<!ENTITY" in xml.upper():
        raise OdsError("ODS content.xml declares a DOCTYPE; refused")
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise OdsError(f"ODS content.xml is not well-formed: {exc}") from exc


def _tables(root: ET.Element) -> list[ET.Element]:
    return list(root.iter(f"{_TABLE}table"))


def sheet_names(data: bytes) -> list[str]:
    return [t.get(f"{_TABLE}name") or "" for t in _tables(_content(data))]


def _cell_value(cell: ET.Element) -> object:
    kind = cell.get(f"{_OFFICE}value-type")
    if kind in ("float", "percentage", "currency"):
        raw = cell.get(f"{_OFFICE}value")
        return float(raw) if raw is not None else None
    if kind == "date":
        raw = cell.get(f"{_OFFICE}date-value")
        try:
            return datetime.fromisoformat(raw) if raw else None
        except ValueError:
            return raw
    if kind == "time":
        # T75: openpyxl gives ``datetime.time`` for a time cell in .xlsx; the
        # SAP PELT ``Time:`` label is one. The time of day is what LibreOffice
        # shows (``PT80H2M0S`` reads "8:02 am"); unreadable -> the cell text.
        found = _time_of_day(cell.get(f"{_OFFICE}time-value"))
        if found is not None:
            return found
    if kind == "boolean":
        return cell.get(f"{_OFFICE}boolean-value") == "true"
    paragraphs = cell.findall(f"{_TEXT}p")
    if not paragraphs:
        return None
    return "\n".join(_paragraph_text(p) for p in paragraphs)


def _time_of_day(raw: str | None) -> time | None:
    match = _DURATION.match(raw or "")
    if not match or raw.startswith("-"):
        return None
    hours, minutes, seconds = match.groups()
    whole = float(seconds or 0)
    micro = round((whole - int(whole)) * 1_000_000)
    return time(int(hours or 0) % 24, int(minutes or 0) % 60, int(whole) % 60,
                min(micro, 999_999))


def _paragraph_text(node: ET.Element) -> str:
    """Text of one ``text:p``: ``text:s`` expanded to its spaces, and (T75)
    ``text:line-break`` / ``text:tab`` as a newline / tab character, which is
    what openpyxl returns for the same cell in ``.xlsx``."""
    parts = [node.text or ""]
    for child in node:
        if child.tag == f"{_TEXT}s":
            parts.append(" " * int(child.get(f"{_TEXT}c", "1")))
        elif child.tag == f"{_TEXT}line-break":
            parts.append("\n")
        elif child.tag == f"{_TEXT}tab":
            parts.append("\t")
        else:
            parts.append(_paragraph_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _row_cells(row: ET.Element) -> tuple:
    cells: list[object] = []
    pending_blank = 0
    for cell in row:
        if cell.tag not in (f"{_TABLE}table-cell", f"{_TABLE}covered-table-cell"):
            continue
        repeat = int(cell.get(f"{_TABLE}number-columns-repeated", "1"))
        value = None if cell.tag.endswith("covered-table-cell") else _cell_value(cell)
        if value is None or value == "":
            pending_blank += repeat
            continue
        if pending_blank:
            cells.extend([None] * min(pending_blank, _MAX_BLANK_RUN))
            pending_blank = 0
        cells.extend([value] * min(repeat, _MAX_BLANK_RUN))
    return tuple(cells)


def iter_rows(data: bytes, sheet: str, max_row: int | None = None) -> Iterator[tuple]:
    """Every row of one table, in spreadsheet order, as a tuple of values.

    Row *n* of the iterator is spreadsheet row *n*, so a source row number
    means the same cell a person opens. Trailing blank runs are dropped.
    """
    for table in _tables(_content(data)):
        if (table.get(f"{_TABLE}name") or "") != sheet:
            continue
        emitted = 0
        pending_blank = 0
        for row in table.iter(f"{_TABLE}table-row"):
            repeat = int(row.get(f"{_TABLE}number-rows-repeated", "1"))
            cells = _row_cells(row)
            if not cells:
                pending_blank += repeat
                continue
            for _ in range(min(pending_blank, _MAX_BLANK_RUN)):
                if max_row is not None and emitted >= max_row:
                    return
                yield ()
                emitted += 1
            pending_blank = 0
            for _ in range(min(repeat, _MAX_BLANK_RUN)):
                if max_row is not None and emitted >= max_row:
                    return
                yield cells
                emitted += 1
        return
    raise KeyError(f"no sheet named {sheet!r}")
