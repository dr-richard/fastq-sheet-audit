"""Generic, read-only reconciliation of mapped sheets and FASTQ inventory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from .column_mapping import ColumnMappingResult, ColumnRole
from .inventory import InventoryCategory, InventoryRecord
from .naming import ReadRole, parse_fastq_name
from .pairing import pair_key
from .sheet import SampleSheet


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    row_number: int | None = None
    sample: str | None = None
    path: Path | None = None
    related_path: Path | None = None
    role: ColumnRole | None = None


@dataclass(frozen=True)
class Assignment:
    row_number: int
    sample: str
    role: ColumnRole
    cell_value: str
    path: Path
    record: InventoryRecord


@dataclass(frozen=True)
class ReconciliationResult:
    inventory: tuple[InventoryRecord, ...]
    assignments: tuple[Assignment, ...]
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


def _identity(path: Path) -> tuple:
    """Use filesystem identity when available, never casefold filesystem paths."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return ("path", str(path.resolve()))
    return ("file", stat.st_dev, stat.st_ino)


def _reference_record(path: Path, root: Path) -> InventoryRecord:
    parsed = parse_fastq_name(path.name)
    label = parsed.sample if parsed else path.name.split(".", 1)[0]
    if label.casefold() == "undetermined" or (
        parsed is None and label.casefold().startswith("undetermined_")
    ):
        category = InventoryCategory.UNDETERMINED
    elif parsed is None:
        category = InventoryCategory.UNPARSED
    elif parsed.read_role in (ReadRole.I1, ReadRole.I2):
        category = InventoryCategory.INDEX
    else:
        category = InventoryCategory.READ
    return InventoryRecord(path, Path(os.path.relpath(path, root)), parsed, category)


def reconcile(
    sheet: SampleSheet,
    mapping: ColumnMappingResult,
    records: Iterable[InventoryRecord],
    fastq_root: Path,
) -> ReconciliationResult:
    """Check explicit assignments only; do not infer mates or repair inputs.

    A complete SAMPLE/R1 mapping is required; ambiguous mapped roles must be
    adjudicated first. Empty optional R2 cells are left alone. Sample values
    are retained verbatim and stripped only for comparison. Path cell text is
    used verbatim, without expansion or rewriting. Absolute references remain
    absolute. File identity detects aliases (symlinks/hard links), while pair
    identity retains reference directory and filename structure.
    """
    if not mapping.complete or mapping.ambiguous:
        raise ValueError("reconciliation requires resolved SAMPLE/R1 and no ambiguous roles")
    selected = {role: mapping.for_role(role).selected for role in ColumnRole}
    indices = [column.index for column in selected.values() if column is not None]
    if len(set(indices)) != len(indices):
        raise ValueError("one column cannot fill multiple roles")
    for column in selected.values():
        if column is not None and (
            not 0 <= column.index < len(sheet.headers)
            or sheet.headers[column.index] != column.header
        ):
            raise ValueError("mapping does not match sheet headers")
    root = Path(os.path.abspath(fastq_root))
    inventory = tuple(sorted(records, key=lambda record: (
        record.relative_path.as_posix(), record.path.as_posix(),
        record.category.value, repr(record.parsed_name),
    )))
    exact_records = {record.path: record for record in inventory}
    discovered = [(record, _identity(record.path)) for record in inventory]
    referenced: set[tuple] = set()
    used: dict[tuple, Assignment] = {}
    assignments: list[Assignment] = []
    findings: list[Finding] = []

    for row in sheet.rows:
        if len(row.cells) != len(sheet.headers):
            raise ValueError(f"row {row.row_number}: cell count does not match headers")
        sample = row.cells[selected[ColumnRole.SAMPLE].index]
        if not sample.strip():
            findings.append(Finding("EMPTY_SAMPLE", Severity.ERROR, "sample cell is empty",
                                    row.row_number, sample))
        row_reads: dict[ColumnRole, Assignment] = {}
        for role in (ColumnRole.R1, ColumnRole.R2):
            column = selected[role]
            if column is None:
                continue
            value = row.cells[column.index]
            if value == "":
                if role is ColumnRole.R1:
                    findings.append(Finding("EMPTY_R1", Severity.ERROR, "R1 cell is empty",
                                            row.row_number, sample, role=role))
                continue
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            record = exact_records.get(path)
            if record is None:
                record = _reference_record(path, root)
            assignment = Assignment(row.row_number, sample, role, value, path, record)
            assignments.append(assignment)
            row_reads[role] = assignment
            identity = _identity(path)
            referenced.add(identity)

            def add(code: str, severity: Severity, message: str, related: Path | None = None) -> None:
                findings.append(Finding(code, severity, message, row.row_number, sample,
                                        path, related, role))

            previous = used.get(identity)
            if previous is not None:
                add("FASTQ_REUSED", Severity.ERROR,
                    f"FASTQ already assigned at row {previous.row_number} as {previous.role.name}",
                    previous.path)
            else:
                used[identity] = assignment
            if not path.is_file():
                add("MISSING_FILE", Severity.ERROR, f"{role.name} reference is not an existing file")
            if record.category in (InventoryCategory.INDEX, InventoryCategory.UNDETERMINED):
                add("NON_BIOLOGICAL_FASTQ", Severity.ERROR,
                    f"{role.name} references a {record.category.value} FASTQ")
                continue
            parsed = record.parsed_name
            if parsed is not None:
                expected = ReadRole.R1 if role is ColumnRole.R1 else ReadRole.R2
                if parsed.read_role is not expected:
                    add("READ_ROLE_MISMATCH", Severity.ERROR,
                        f"sheet assigns {role.name}, filename role is {parsed.read_role.value}")
                if sample.strip().casefold() != parsed.sample.casefold():
                    add("SAMPLE_NAME_MISMATCH", Severity.WARNING,
                        f"filename sample {parsed.sample!r} differs from sheet sample {sample!r}")
        if ColumnRole.R1 in row_reads and ColumnRole.R2 in row_reads:
            r1, r2 = row_reads[ColumnRole.R1], row_reads[ColumnRole.R2]
            key1, key2 = pair_key(r1.record), pair_key(r2.record)
            if key1 is not None and key2 is not None and key1 != key2:
                findings.append(Finding("PAIR_NAME_MISMATCH", Severity.ERROR,
                                        "R1/R2 structural mate identities differ",
                                        row.row_number, sample, r1.path, r2.path))

    for record, identity in discovered:
        if identity not in referenced:
            findings.append(Finding("UNLISTED_FASTQ", Severity.WARNING,
                                    "discovered FASTQ is absent from the sheet", path=record.path))

    findings.sort(key=lambda finding: (
        0 if finding.severity is Severity.ERROR else 1, finding.code,
        -1 if finding.row_number is None else finding.row_number,
        finding.sample or "", str(finding.path or ""), str(finding.related_path or ""),
        finding.role.value if finding.role else "", finding.message,
    ))
    assignments.sort(key=lambda assignment: (
        assignment.row_number, assignment.role.value, str(assignment.path), assignment.sample,
    ))
    return ReconciliationResult(inventory, tuple(assignments), tuple(findings))
