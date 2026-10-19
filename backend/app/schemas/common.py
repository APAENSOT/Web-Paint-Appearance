"""Shared DTO base and pagination.

Every DTO in this package inherits `StrictModel`, so `extra="forbid"` is the
default rather than something each model has to remember (T03 spec item 3).
T03 has no JSON request bodies -- every implemented route is a GET -- so the
rule has no surface to bite on yet; inheriting it now means the first body
T04 adds is strict without anyone deciding to make it so.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResponse(StrictModel):
    """The only error body this API produces (03-SECURITY.md section 7)."""

    statusCode: int = Field(examples=[404])  # noqa: N815 - contract field name
    error: str = Field(examples=["Not Found"])
    message: str
    correlationId: str = Field(  # noqa: N815 - contract field name
        description="Echoes X-Correlation-ID when the client sends one.",
    )


class PageInfo(StrictModel):
    limit: int
    offset: int
    total: int = Field(description="Rows matching the filters, before paging.")
    returned: int


MEASURE_DESCRIPTION = (
    "A NUMERIC measurement carried as a decimal STRING, e.g. \"62.4\". "
    "L12 stores these at full precision and rounds only in views and UI; a "
    "JSON number is parsed as an IEEE-754 double by every browser, which is "
    "the rounding T02 removed from the database. Convert at the point of "
    "display, never on the way in."
)


def _decimal_to_text(value: Decimal) -> str:
    # `format(..., "f")` never emits scientific notation, so a value the
    # database holds as 1E+2 crosses the wire as "100".
    return format(value, "f")


#: The wire type for every measurement column.
MeasureValue = Annotated[
    Decimal,
    PlainSerializer(_decimal_to_text, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "description": MEASURE_DESCRIPTION, "examples": ["62.4"]},
        mode="serialization",
    ),
]
