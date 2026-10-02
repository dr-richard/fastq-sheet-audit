"""Lossless column and cell import for CSV/TSV sample sheets."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SheetRow:
    row_number: int
    cells: tuple[str, ...]


@dataclass(frozen=True)
class SampleSheet:
    headers: tuple[str, ...]
    rows: tuple[SheetRow, ...]


def _validate_quoting(text: str, delimiter: str) -> None:
    """Reject misplaced quotes that csv.reader(strict=True) accepts as text."""
    state = "start"
    line = 1
    for character in text:
        if state == "quoted":
            if character == '"':
                state = "closed"
        elif state == "closed":
            if character == '"':
                state = "quoted"  # Escaped double quote.
            elif character == delimiter or character in "\r\n":
                state = "start"
            else:
                raise ValueError(f"line {line}: malformed CSV quoting")
        elif character == delimiter or character in "\r\n":
            state = "start"
        elif character == '"':
            if state != "start":
                raise ValueError(f"line {line}: malformed CSV quoting")
            state = "quoted"
        else:
            state = "unquoted"
        if character == "\n":
            line += 1
    if state == "quoted":
        raise ValueError(f"line {line}: unterminated quoted field")


def load_sheet(path: Path) -> SampleSheet:
    """Load .csv or .tsv as UTF-8 (optionally BOM-prefixed), without mapping.

    Headers and cell text are preserved verbatim. Header whitespace is trimmed
    only when checking duplicates. Row numbers are the starting physical line
    numbers, including for multiline records. Short rows receive empty trailing
    cells; surplus fields are rejected. Only entirely empty rows are skipped.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".tsv"):
        raise ValueError("sample sheet must have a .csv or .tsv extension")
    delimiter = "," if suffix == ".csv" else "\t"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        text = stream.read()
    _validate_quoting(text, delimiter)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header = next(reader, None)
        if not header or not any(value.strip() for value in header):
            raise ValueError("sample sheet has no header")
        trimmed = [value.strip() for value in header]
        if len(set(trimmed)) != len(trimmed):
            raise ValueError("sample sheet has duplicate headers after trimming whitespace")

        rows: list[SheetRow] = []
        while True:
            row_number = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if len(cells) > len(header):
                raise ValueError(f"row {row_number}: more fields than the header")
            if not any(cell != "" for cell in cells):
                continue
            cells.extend([""] * (len(header) - len(cells)))
            rows.append(SheetRow(row_number, tuple(cells)))
    except csv.Error as error:
        raise ValueError(f"line {reader.line_num}: malformed CSV: {error}") from error
    return SampleSheet(tuple(header), tuple(rows))
