"""Thin read-only orchestration for an explicit GUI audit action."""

from pathlib import Path
from dataclasses import dataclass
from typing import Mapping

from .column_mapping import ColumnRole, map_columns
from .inventory import scan_fastqs
from .presentation import WorkflowView, present_workflow
from .read_mode import ReadMode
from .sheet import load_sheet
from .workflow import build_workflow_snapshot


def read_mode_from_label(label: str) -> ReadMode:
    modes = {"Auto": ReadMode.AUTO, "Paired": ReadMode.PAIRED, "Single": ReadMode.SINGLE}
    if label not in modes:
        raise ValueError(f"unknown read mode: {label!r}")
    return modes[label]


@dataclass(frozen=True)
class ColumnChoice:
    index: int
    header: str
    display: str


@dataclass(frozen=True)
class ColumnRoleView:
    role: ColumnRole
    candidates: tuple[int, ...]
    automatic: int | None
    selected: int | None
    ambiguous: bool
    explicit: bool


@dataclass(frozen=True)
class SheetMappingView:
    choices: tuple[ColumnChoice, ...]
    roles: tuple[ColumnRoleView, ...]


def inspect_sheet_mapping(sample_sheet: str) -> SheetMappingView:
    if not sample_sheet.strip():
        raise ValueError("Choose a sample sheet.")
    path = Path(sample_sheet)
    if not path.is_file():
        raise ValueError(f"Sample sheet does not exist or is not a file: {path}")
    sheet = load_sheet(path)
    mapping = map_columns(sheet)
    return SheetMappingView(
        tuple(ColumnChoice(index, header, f"[{index}] {header}")
              for index, header in enumerate(sheet.headers)),
        tuple(ColumnRoleView(item.role, tuple(column.index for column in item.candidates),
                             item.automatic.index if item.automatic is not None else None,
                             item.selected.index if item.selected is not None else None,
                             item.ambiguous, item.explicit) for item in mapping.roles),
    )


def mapping_overrides(
    view: SheetMappingView, selections: Mapping[ColumnRole, str],
) -> dict[ColumnRole, int | None]:
    """Convert exact display choices to overrides without interpreting headers."""
    choices = {choice.display: choice.index for choice in view.choices}
    overrides = {}
    for role, selection in selections.items():
        if not isinstance(role, ColumnRole):
            raise ValueError("unknown mapping role")
        if selection == "Automatic":
            continue
        if selection == "Unassigned":
            overrides[role] = None
        elif selection in choices:
            overrides[role] = choices[selection]
        else:
            raise ValueError(f"unknown column choice: {selection!r}")
    return overrides


def audit_inputs(
    fastq_directory: str, sample_sheet: str, read_mode_label: str,
    overrides: Mapping[ColumnRole, int | None] | None = None,
) -> WorkflowView:
    """Audit explicit input paths; propagate errors to the GUI callback boundary."""
    if not fastq_directory.strip() or not sample_sheet.strip():
        raise ValueError("Choose a FASTQ directory and sample sheet.")
    root, sheet_path = Path(fastq_directory), Path(sample_sheet)
    if not root.is_dir():
        raise ValueError(f"FASTQ directory does not exist or is not a directory: {root}")
    if not sheet_path.is_file():
        raise ValueError(f"Sample sheet does not exist or is not a file: {sheet_path}")
    mode = read_mode_from_label(read_mode_label)
    sheet = load_sheet(sheet_path)
    mapping = map_columns(sheet, overrides)
    if mapping.ambiguous:
        roles = ", ".join(item.role.name for item in mapping.ambiguous)
        raise ValueError(f"Ambiguous column mapping: {roles}. Explicit mapping is required.")
    if not mapping.complete:
        raise ValueError("Column mapping requires SAMPLE and R1 columns.")
    records = scan_fastqs(root)
    return present_workflow(build_workflow_snapshot(sheet, mapping, records, root, read_mode=mode))
