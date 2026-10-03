"""Thin read-only orchestration for an explicit GUI audit action."""

from pathlib import Path

from .column_mapping import map_columns
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


def audit_inputs(fastq_directory: str, sample_sheet: str, read_mode_label: str) -> WorkflowView:
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
    mapping = map_columns(sheet)
    if mapping.ambiguous:
        roles = ", ".join(item.role.name for item in mapping.ambiguous)
        raise ValueError(f"Ambiguous column mapping: {roles}. Explicit mapping is required.")
    if not mapping.complete:
        raise ValueError("Column mapping requires SAMPLE and R1 columns.")
    records = scan_fastqs(root)
    return present_workflow(build_workflow_snapshot(sheet, mapping, records, root, read_mode=mode))
