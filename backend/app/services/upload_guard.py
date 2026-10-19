"""Door checks. Every upload is treated as hostile.

`02-PIPELINE.md` §2 and `03-SECURITY.md` §7. The table there is implemented
here, one function per row, and the rule that matters most is the last line
of that section: **failure refuses the request and does not create a
`load_batch`.** A rejected file leaves no trace in the schema beyond the
request log, because a batch row for a file that was never accepted is a
batch a reviewer has to explain.

An `.xlsx` is a ZIP archive, which is why three of these checks exist at all:
a zip bomb is a small upload that becomes a large one only after the parser
starts, and by then the damage is memory, not disk. `openpyxl` is never
handed the bytes until every check below has passed.

No database, no FastAPI: this takes bytes and a filename and returns a
verdict, so it is testable with a handful of literals.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO

#: `02-PIPELINE.md` §2 defaults. Overridable through Settings.
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 40
#: A workbook that expands past this is refused before it is parsed.
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
#: Total uncompressed / total compressed. Ordinary spreadsheet XML compresses
#: around 10:1; a zip bomb is orders of magnitude beyond this.
MAX_COMPRESSION_RATIO = 200.0
#: An xlsx has one entry per sheet plus a handful of parts. Thousands means
#: something other than a spreadsheet.
MAX_ARCHIVE_ENTRIES = 2000

#: T46 (spec F15): SAP sends its PELT Quick Summary as OpenDocument. It is a
#: ZIP too, so every archive check below applies to it unchanged.
ALLOWED_EXTENSIONS = (".xlsx", ".xlsm", ".ods")
#: Local file header of every ZIP archive, and therefore of every xlsx.
ZIP_MAGIC = b"PK\x03\x04"


class UploadRejected(Exception):
    """A file did not get through the door. Carries a reason for the client."""

    def __init__(self, filename: str, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.filename = filename
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class GuardLimits:
    max_file_bytes: int = MAX_FILE_BYTES
    max_files: int = MAX_FILES
    max_uncompressed_bytes: int = MAX_UNCOMPRESSED_BYTES
    max_compression_ratio: float = MAX_COMPRESSION_RATIO
    max_archive_entries: int = MAX_ARCHIVE_ENTRIES


def check_request_size(file_count: int, limits: GuardLimits) -> None:
    if file_count == 0:
        raise UploadRejected("", "NO_FILES", "No files were uploaded.")
    if file_count > limits.max_files:
        raise UploadRejected(
            "", "TOO_MANY_FILES",
            f"{file_count} files in one request; the limit is "
            f"{limits.max_files} (docs/02-PIPELINE.md section 2).",
        )


def check_file(filename: str, data: bytes, limits: GuardLimits) -> None:
    """Run every door check on one file, in cheapest-first order."""
    _check_extension(filename)
    _check_size(filename, data, limits)
    _check_magic(filename, data)
    _check_archive(filename, data, limits)


def _check_extension(filename: str) -> None:
    lowered = (filename or "").lower()
    if not lowered.endswith(ALLOWED_EXTENSIONS):
        raise UploadRejected(
            filename, "BAD_EXTENSION",
            f"{filename!r} is not one of {', '.join(ALLOWED_EXTENSIONS)}. "
            f".xls is out of scope for v1 (docs/02-PIPELINE.md section 2).",
        )


def _check_size(filename: str, data: bytes, limits: GuardLimits) -> None:
    if not data:
        raise UploadRejected(filename, "EMPTY_FILE", f"{filename!r} is empty.")
    if len(data) > limits.max_file_bytes:
        raise UploadRejected(
            filename, "TOO_LARGE",
            f"{filename!r} is {len(data) / 1048576:.1f} MB; the limit is "
            f"{limits.max_file_bytes / 1048576:.0f} MB.",
        )


def _check_magic(filename: str, data: bytes) -> None:
    """The extension is a claim; the first four bytes are evidence."""
    if not data.startswith(ZIP_MAGIC):
        raise UploadRejected(
            filename, "NOT_A_WORKBOOK",
            f"{filename!r} does not begin with a ZIP header, so it is not an "
            f"xlsx whatever its name says.",
        )


def _check_archive(filename: str, data: bytes, limits: GuardLimits) -> None:
    """Inspect the archive's own table of contents. Nothing is extracted."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise UploadRejected(
            filename, "CORRUPT_ARCHIVE",
            f"{filename!r} is not a readable ZIP archive: {exc}",
        ) from exc

    if len(entries) > limits.max_archive_entries:
        raise UploadRejected(
            filename, "TOO_MANY_ENTRIES",
            f"{filename!r} contains {len(entries)} archive entries; the limit "
            f"is {limits.max_archive_entries}.",
        )

    uncompressed = sum(e.file_size for e in entries)
    if uncompressed > limits.max_uncompressed_bytes:
        raise UploadRejected(
            filename, "ZIP_BOMB",
            f"{filename!r} expands to {uncompressed / 1048576:.0f} MB; the "
            f"limit is {limits.max_uncompressed_bytes / 1048576:.0f} MB.",
        )

    compressed = sum(e.compress_size for e in entries) or 1
    ratio = uncompressed / compressed
    if ratio > limits.max_compression_ratio:
        raise UploadRejected(
            filename, "ZIP_BOMB",
            f"{filename!r} has a compression ratio of {ratio:.0f}:1; the limit "
            f"is {limits.max_compression_ratio:.0f}:1.",
        )

    # An entry whose name escapes the archive root has no business in a
    # workbook and is the classic path-traversal payload. Nothing here
    # extracts to disk, but openpyxl is about to walk these names.
    for name in names:
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            raise UploadRejected(
                filename, "UNSAFE_ENTRY",
                f"{filename!r} contains an archive entry with a traversing "
                f"path ({name!r}).",
            )

    is_ods = "mimetype" in names and "content.xml" in names
    if not any(n.startswith("xl/") for n in names) and not is_ods:
        raise UploadRejected(
            filename, "NOT_A_WORKBOOK",
            f"{filename!r} is a ZIP archive but has no xl/ part and no "
            f"OpenDocument content.xml, so it is not a spreadsheet.",
        )
