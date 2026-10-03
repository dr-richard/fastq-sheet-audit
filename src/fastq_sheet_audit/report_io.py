"""Thin adapter for protected atomic publication of workflow-report JSON."""

from pathlib import Path
from typing import Iterable

from .export_io import write_text_atomic
from .report_serialization import serialize_workflow_report_json
from .reporting import WorkflowReport


def write_workflow_report_json(
    report: WorkflowReport,
    destination: Path,
    *,
    protected_paths: Iterable[Path] = (),
    overwrite: bool = False,
) -> Path:
    """Serialize first and delegate publication, preserving options and exceptions."""
    text = serialize_workflow_report_json(report)
    return write_text_atomic(text, destination, protected_paths=protected_paths, overwrite=overwrite)
