"""Pure deterministic JSON serialization of the versioned machine-report schema."""

from __future__ import annotations

import json

from .reporting import (
    AssignmentReport, InventoryRecordReport, PairDecisionReport, PairGroupReport,
    PairKeyReport, PairResolutionReport, PathCaseCollisionReport,
    ReadModeDiagnosticReport, ReconciliationFindingReport, RoleDecisionReport,
    WorkflowReport, WorkflowReportSummary,
)


REPORT_SCHEMA_VERSION = 1


def _inventory(record: InventoryRecordReport | None) -> dict[str, object] | None:
    if record is None:
        return None
    return {
        "path": record.path,
        "relative_path": record.relative_path,
        "category": record.category,
        "sample": record.sample,
        "sample_number": record.sample_number,
        "lane": record.lane,
        "read_role": record.read_role,
        "chunk": record.chunk,
        "suffix": record.suffix,
        "read_style": record.read_style,
    }


def _key(key: PairKeyReport | None) -> dict[str, object] | None:
    if key is None:
        return None
    return {
        "sample": key.sample,
        "sample_number": key.sample_number,
        "lane": key.lane,
        "chunk": key.chunk,
        "read_style": key.read_style,
        "suffix": key.suffix,
        "relative_parent": key.relative_parent,
    }


def _group(group: PairGroupReport) -> dict[str, object]:
    return {
        "key": _key(group.key),
        "status": group.status,
        "r1": [_inventory(record) for record in group.r1],
        "r2": [_inventory(record) for record in group.r2],
    }


def _role(decision: RoleDecisionReport) -> dict[str, object]:
    return {"kind": decision.kind, "selected": _inventory(decision.selected)}


def _decision(decision: PairDecisionReport) -> dict[str, object]:
    return {
        "key": _key(decision.key),
        "r1": _role(decision.r1),
        "r2": _role(decision.r2),
        "confirmed": decision.confirmed,
    }


def _resolution(resolution: PairResolutionReport) -> dict[str, object]:
    return {
        "group": _group(resolution.group),
        "decision": _decision(resolution.decision),
        "effective_r1": _inventory(resolution.effective_r1),
        "effective_r2": _inventory(resolution.effective_r2),
        "unresolved_r1": [_inventory(record) for record in resolution.unresolved_r1],
        "unresolved_r2": [_inventory(record) for record in resolution.unresolved_r2],
        "confirmed": resolution.confirmed,
        "resolved": resolution.resolved,
    }


def _finding(finding: ReconciliationFindingReport) -> dict[str, object]:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "row_number": finding.row_number,
        "sample": finding.sample,
        "path": finding.path,
        "related_path": finding.related_path,
        "role": finding.role,
    }


def _assignment(assignment: AssignmentReport) -> dict[str, object]:
    return {
        "row_number": assignment.row_number,
        "sample": assignment.sample,
        "role": assignment.role,
        "cell_value": assignment.cell_value,
        "path": assignment.path,
        "record": _inventory(assignment.record),
    }


def _diagnostic(diagnostic: ReadModeDiagnosticReport) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "key": _key(diagnostic.key),
        "records": [_inventory(record) for record in diagnostic.records],
    }


def _collision(collision: PathCaseCollisionReport) -> dict[str, object]:
    return {
        "normalized_key": collision.normalized_key,
        "records": [_inventory(record) for record in collision.records],
    }


def _summary(summary: WorkflowReportSummary) -> dict[str, object]:
    return {
        "inventory_count": summary.inventory_count,
        "reconciliation_error_count": summary.reconciliation_error_count,
        "reconciliation_warning_count": summary.reconciliation_warning_count,
        "read_mode_error_count": summary.read_mode_error_count,
        "read_mode_warning_count": summary.read_mode_warning_count,
        "case_collision_count": summary.case_collision_count,
        "unresolved_pair_count": summary.unresolved_pair_count,
        "requested_read_mode": summary.requested_read_mode,
        "read_layout": summary.read_layout,
        "ready_for_export": summary.ready_for_export,
    }


def workflow_report_to_obj(report: WorkflowReport) -> dict[str, object]:
    """Return a fresh JSON-safe schema object, preserving every evidence array's order."""
    if not isinstance(report, WorkflowReport):
        raise TypeError("report must be a WorkflowReport")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "summary": _summary(report.summary),
        "inventory": [_inventory(record) for record in report.inventory],
        "reconciliation_findings": [_finding(finding) for finding in report.reconciliation_findings],
        "reconciliation_assignments": [_assignment(assignment) for assignment in report.reconciliation_assignments],
        "read_mode_diagnostics": [_diagnostic(diagnostic) for diagnostic in report.read_mode_diagnostics],
        "read_mode_groups": [_group(group) for group in report.read_mode_groups],
        "read_mode_excluded": [_inventory(record) for record in report.read_mode_excluded],
        "case_collisions": [_collision(collision) for collision in report.case_collisions],
        "pair_resolutions": [_resolution(resolution) for resolution in report.pair_resolutions],
    }


def serialize_workflow_report_json(report: WorkflowReport) -> str:
    """Render schema insertion order as readable Unicode JSON with one final LF."""
    return json.dumps(workflow_report_to_obj(report), ensure_ascii=False, indent=2) + "\n"
