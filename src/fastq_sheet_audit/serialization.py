"""Deterministic, exact CSV/TSV text serialization without external access."""

from __future__ import annotations

import csv
import io
from enum import Enum

from .sheet import SampleSheet


class SheetFormat(Enum):
    CSV = "csv"
    TSV = "tsv"


def serialize_sheet(sheet: SampleSheet, format: SheetFormat) -> str:
    """Serialize headers and ordered cells verbatim with LF record terminators.

    Standard minimal CSV quoting preserves delimiters, quotes, and embedded
    newlines. Formula-like text is not sanitized. Source row numbers are
    metadata and are not emitted. Even an empty header tuple is emitted as
    an empty header record. No defaults or transformations are applied.
    """
    if not isinstance(format, SheetFormat):
        raise ValueError("format must be a SheetFormat")
    for row in sheet.rows:
        if len(row.cells) != len(sheet.headers):
            raise ValueError(f"row {row.row_number}: cell count does not match headers")
    stream = io.StringIO(newline="")
    writer = csv.writer(
        stream,
        delimiter="," if format is SheetFormat.CSV else "\t",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writerow(sheet.headers)
    writer.writerows(row.cells for row in sheet.rows)
    return stream.getvalue()
