"""Pure construction of candidate profile output sheets from explicit values."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .profile_validation import ProfileValidationResult, validate_profile_sheet
from .profiles import Profile
from .sheet import SampleSheet, SheetRow


@dataclass(frozen=True)
class OutputRow:
    row_number: int
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        # Snapshot caller-owned dictionaries; frozen fields alone do not make
        # a mutable mapping immutable.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True)
class OutputBuildResult:
    sheet: SampleSheet
    validation: ProfileValidationResult


def build_profile_sheet(profile: Profile, rows: Iterable[OutputRow]) -> OutputBuildResult:
    """Build and validate without defaults, normalization, or external access.

    Required headers always appear. Optional headers appear only if explicitly
    supplied by at least one row (including an explicit empty string). Header
    order follows the profile; row order and row numbers follow the input.
    Missing included values become empty strings for contract validation.
    """
    ordered_rows = tuple(rows)
    known = {column.name for column in profile.columns}
    supplied: set[str] = set()
    row_numbers: set[int] = set()
    for row in ordered_rows:
        if type(row.row_number) is not int:
            raise ValueError("row_number must be an integer, not a boolean")
        if row.row_number in row_numbers:
            raise ValueError(f"duplicate row_number: {row.row_number}")
        row_numbers.add(row.row_number)
        for key, value in row.values.items():
            if key not in known:
                raise ValueError(f"row {row.row_number}: unknown column key {key!r}")
            if not isinstance(value, str):
                raise ValueError(f"row {row.row_number}: {key!r} value must be a string")
            supplied.add(key)

    headers = tuple(column.name for column in profile.columns
                    if column.required_column or column.name in supplied)
    sheet = SampleSheet(headers, tuple(
        SheetRow(row.row_number, tuple(row.values.get(name, "") for name in headers))
        for row in ordered_rows
    ))
    return OutputBuildResult(sheet, validate_profile_sheet(sheet, profile))
