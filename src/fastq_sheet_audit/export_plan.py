"""Pure candidate export planning from effective workflow evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .column_mapping import ColumnMappingResult, ColumnRole
from .output import OutputBuildResult, OutputRow, build_profile_sheet
from .pairing import pair_key
from .pathmap import ExportMode, TargetStyle, preview_paths, render_path
from .profiles import Profile
from .sheet import SampleSheet
from .workflow import WorkflowSnapshot


@dataclass(frozen=True)
class ExportPlan:
    profile: Profile
    path_mode: ExportMode
    target_style: TargetStyle | None
    target_root: str | None
    rows: tuple[OutputRow, ...]
    result: OutputBuildResult


def build_export_plan(
    sheet: SampleSheet,
    mapping: ColumnMappingResult,
    snapshot: WorkflowSnapshot,
    profile: Profile,
    path_mode: ExportMode,
    *,
    target_root: str | None = None,
    target_style: TargetStyle | None = None,
    explicit_values: Mapping[int, Mapping[str, str]] | None = None,
) -> ExportPlan:
    """Plan exact source text and effective reads; never write or apply defaults.

    Source row association uses reconciliation R1 evidence and existing pair
    keys. All path rendering and output validation are delegated. Manual values
    may supply only columns without a declared source role. Profile validation
    findings remain in the returned plan rather than being silently repaired.
    """
    if not snapshot.ready_for_export:
        raise ValueError("workflow is not ready for export")
    if profile.input_kind != "fastq_samplesheet":
        raise ValueError("export planning supports only fastq_samplesheet profiles, not barcode_mapping")
    if not mapping.complete or mapping.ambiguous:
        raise ValueError("mapping must be complete and non-ambiguous")
    selected = {role: mapping.for_role(role).selected for role in ColumnRole}
    for column in selected.values():
        if column is not None and (
            not 0 <= column.index < len(sheet.headers)
            or sheet.headers[column.index] != column.header
        ):
            raise ValueError("mapping does not match supplied sheet headers")
    indices = [column.index for column in selected.values() if column is not None]
    if len(set(indices)) != len(indices):
        raise ValueError("mapping assigns one column to multiple roles")
    row_numbers = set()
    for row in sheet.rows:
        if type(row.row_number) is not int or row.row_number in row_numbers:
            raise ValueError("source row numbers must be unique integers")
        row_numbers.add(row.row_number)
        if len(row.cells) != len(sheet.headers):
            raise ValueError(f"row {row.row_number}: cell count does not match headers")

    columns = {column.name: column for column in profile.columns}
    manual: dict[int, dict[str, str]] = {}
    for number, values in (explicit_values.items() if explicit_values is not None else ()):
        if type(number) is not int or number not in row_numbers:
            raise ValueError(f"unknown or invalid source row number: {number!r}")
        manual[number] = {}
        for name, value in values.items():
            if name not in columns:
                raise ValueError(f"unknown profile column: {name!r}")
            if columns[name].source_role is not None:
                raise ValueError(f"manual value cannot override source-role column: {name!r}")
            if not isinstance(value, str):
                raise ValueError(f"manual value for {name!r} must be a string")
            manual[number][name] = value

    # Public pathmap validation also validates options for an empty sheet.
    preview_paths((), path_mode, target_root=target_root, target_style=target_style)
    resolutions = {}
    for resolution in snapshot.pair_resolutions:
        if resolution.group.key in resolutions:
            raise ValueError("duplicate pair resolution identity")
        resolutions[resolution.group.key] = resolution
    assignments = {}
    for assignment in snapshot.reconciliation.assignments:
        if assignment.role is ColumnRole.R1:
            if assignment.row_number not in row_numbers or assignment.row_number in assignments:
                raise ValueError("duplicate or inconsistent R1 reconciliation assignment")
            assignments[assignment.row_number] = assignment

    rows = []
    for row in sheet.rows:
        sample = row.cells[selected[ColumnRole.SAMPLE].index]
        assignment = assignments.get(row.row_number)
        if assignment is None:
            raise ValueError(f"row {row.row_number}: missing R1 reconciliation assignment")
        if (assignment.sample != sample
                or assignment.cell_value != row.cells[selected[ColumnRole.R1].index]):
            raise ValueError(f"row {row.row_number}: inconsistent R1 reconciliation assignment")
        key = pair_key(assignment.record)
        resolution = resolutions.get(key)
        if key is None or resolution is None:
            raise ValueError(f"row {row.row_number}: R1 assignment has no pair resolution")
        if assignment.record not in resolution.group.r1:
            raise ValueError(f"row {row.row_number}: R1 assignment is not original group evidence")
        if resolution.effective_r1 is None or not resolution.resolved:
            raise ValueError(f"row {row.row_number}: no resolved effective R1")
        source = {"sample": sample}
        for role, record in (("r1", resolution.effective_r1), ("r2", resolution.effective_r2)):
            if record is not None:
                source[role] = render_path(record, path_mode, target_root=target_root, target_style=target_style)
        values = dict(manual.get(row.row_number, {}))
        for column in profile.columns:
            if column.source_role is not None and column.source_role in source:
                values[column.name] = source[column.source_role]
        rows.append(OutputRow(row.row_number, values))
    output_rows = tuple(rows)
    return ExportPlan(profile, path_mode, target_style, target_root, output_rows,
                      build_profile_sheet(profile, output_rows))
