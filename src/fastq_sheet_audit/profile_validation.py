"""Validate candidate output sheets against declarative profile contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .profiles import Profile
from .sheet import SampleSheet


@dataclass(frozen=True)
class ProfileFinding:
    code: str
    message: str
    row_number: int | None
    column: str | None
    value: str | None


@dataclass(frozen=True)
class ProfileValidationResult:
    profile_id: str
    findings: tuple[ProfileFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


_INTEGER = re.compile(r"[+-]?[0-9]+")


def validate_profile_sheet(sheet: SampleSheet, profile: Profile) -> ProfileValidationResult:
    """Validate exact output names and values without rewriting or defaults.

    Findings follow profile column order, then input sheet row order (not
    sorted row numbers). Missing/duplicate column diagnostics have no row or
    value. Duplicate profile columns are not used for cell validation. Extra
    columns are ignored. Manually constructed rows must match header width.
    """
    for row in sheet.rows:
        if len(row.cells) != len(sheet.headers):
            raise ValueError(f"row {row.row_number}: cell count does not match headers")

    findings: list[ProfileFinding] = []
    for column in profile.columns:
        indices = [index for index, header in enumerate(sheet.headers) if header == column.name]
        if len(indices) > 1:
            findings.append(ProfileFinding(
                "DUPLICATE_PROFILE_COLUMN", f"profile column {column.name!r} occurs more than once",
                None, column.name, None,
            ))
            continue
        if not indices:
            if column.required_column:
                findings.append(ProfileFinding(
                    "MISSING_REQUIRED_COLUMN", f"required column {column.name!r} is missing",
                    None, column.name, None,
                ))
            continue
        for row in sheet.rows:
            value = row.cells[indices[0]]
            code: str | None = None
            message = ""
            if value == "":
                if column.required_value:
                    code = "EMPTY_REQUIRED_VALUE"
                    message = "required cell value is empty"
            elif column.value_type == "integer":
                if _INTEGER.fullmatch(value) is None:
                    code = "INVALID_INTEGER"
                    message = "value must be an optional sign followed by ASCII decimal digits"
                elif column.allowed_values is not None and int(value) not in column.allowed_values:
                    code = "VALUE_NOT_ALLOWED"
                    message = "integer value is not in allowed_values"
            elif column.allowed_values is not None and value not in column.allowed_values:
                code = "VALUE_NOT_ALLOWED"
                message = "exact cell value is not in allowed_values"
            if code is not None:
                findings.append(ProfileFinding(code, message, row.row_number, column.name, value))
    return ProfileValidationResult(profile.profile_id, tuple(findings))
