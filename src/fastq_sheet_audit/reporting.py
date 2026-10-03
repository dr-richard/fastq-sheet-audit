"""Pure, structured machine reports over existing v0.2 workflow evidence.

Paths are copied with str(), without resolution or filesystem access. Enum
labels use lowercase values; filename spelling and read_style remain exact.
Sequence order and readiness belong to the snapshot, not this projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, overload

from .adjudication import PairResolution, RoleDecision
from .inventory import InventoryRecord
from .pairing import PairGroup, PairKey
from .read_mode import DiagnosticSeverity
from .reconciliation import Severity
from .workflow import WorkflowSnapshot


SeverityLabel = Literal["error", "warning"]
RoleLabel = Literal["sample", "r1", "r2"]
ModeLabel = Literal["auto", "paired", "single"]
LayoutLabel = Literal["paired", "single", "unresolved"]


@dataclass(frozen=True)
class InventoryRecordReport:
    path: str
    relative_path: str
    category: Literal["read", "index", "undetermined", "unparsed"]
    sample: str | None
    sample_number: int | None
    lane: int | None
    read_role: Literal["r1", "r2", "i1", "i2"] | None
    chunk: int | None
    suffix: str | None
    read_style: str | None


@dataclass(frozen=True)
class PairKeyReport:
    sample: str
    sample_number: int | None
    lane: int | None
    chunk: int | None
    read_style: str
    suffix: str
    relative_parent: str


@dataclass(frozen=True)
class PairGroupReport:
    key: PairKeyReport
    status: Literal["complete", "r1_only", "r2_only", "ambiguous"]
    r1: tuple[InventoryRecordReport, ...]
    r2: tuple[InventoryRecordReport, ...]


@dataclass(frozen=True)
class RoleDecisionReport:
    kind: Literal["automatic", "select", "unassign"]
    selected: InventoryRecordReport | None


@dataclass(frozen=True)
class PairDecisionReport:
    key: PairKeyReport
    r1: RoleDecisionReport
    r2: RoleDecisionReport
    confirmed: bool


@dataclass(frozen=True)
class PairResolutionReport:
    group: PairGroupReport
    decision: PairDecisionReport
    effective_r1: InventoryRecordReport | None
    effective_r2: InventoryRecordReport | None
    unresolved_r1: tuple[InventoryRecordReport, ...]
    unresolved_r2: tuple[InventoryRecordReport, ...]
    confirmed: bool
    resolved: bool


@dataclass(frozen=True)
class ReconciliationFindingReport:
    code: str
    severity: SeverityLabel
    message: str
    row_number: int | None
    sample: str | None
    path: str | None
    related_path: str | None
    role: RoleLabel | None


@dataclass(frozen=True)
class AssignmentReport:
    row_number: int
    sample: str
    role: RoleLabel
    cell_value: str
    path: str
    record: InventoryRecordReport


@dataclass(frozen=True)
class ReadModeDiagnosticReport:
    code: str
    severity: SeverityLabel
    message: str
    key: PairKeyReport | None
    records: tuple[InventoryRecordReport, ...]


@dataclass(frozen=True)
class PathCaseCollisionReport:
    normalized_key: str
    records: tuple[InventoryRecordReport, ...]


@dataclass(frozen=True)
class WorkflowReportSummary:
    inventory_count: int
    reconciliation_error_count: int
    reconciliation_warning_count: int
    read_mode_error_count: int
    read_mode_warning_count: int
    case_collision_count: int
    unresolved_pair_count: int
    requested_read_mode: ModeLabel
    read_layout: LayoutLabel
    ready_for_export: bool


@dataclass(frozen=True)
class WorkflowReport:
    summary: WorkflowReportSummary
    inventory: tuple[InventoryRecordReport, ...]
    reconciliation_findings: tuple[ReconciliationFindingReport, ...]
    reconciliation_assignments: tuple[AssignmentReport, ...]
    read_mode_diagnostics: tuple[ReadModeDiagnosticReport, ...]
    read_mode_groups: tuple[PairGroupReport, ...]
    read_mode_excluded: tuple[InventoryRecordReport, ...]
    case_collisions: tuple[PathCaseCollisionReport, ...]
    pair_resolutions: tuple[PairResolutionReport, ...]


@overload
def _record(record: InventoryRecord) -> InventoryRecordReport: ...


@overload
def _record(record: None) -> None: ...


def _record(record: InventoryRecord | None) -> InventoryRecordReport | None:
    if record is None:
        return None
    parsed = record.parsed_name
    return InventoryRecordReport(
        str(record.path), str(record.relative_path), record.category.value,
        parsed.sample if parsed else None, parsed.sample_number if parsed else None,
        parsed.lane if parsed else None, parsed.read_role.value.lower() if parsed else None,
        parsed.chunk if parsed else None, parsed.suffix if parsed else None,
        parsed.read_style if parsed else None,
    )


def _records(records: tuple[InventoryRecord, ...]) -> tuple[InventoryRecordReport, ...]:
    return tuple(_record(record) for record in records)


def _key(key: PairKey) -> PairKeyReport:
    return PairKeyReport(key.sample, key.sample_number, key.lane, key.chunk,
                         key.read_style, key.suffix, str(key.relative_parent))


def _group(group: PairGroup) -> PairGroupReport:
    return PairGroupReport(_key(group.key), group.status.value, _records(group.r1), _records(group.r2))


def _decision(decision: RoleDecision) -> RoleDecisionReport:
    return RoleDecisionReport(decision.kind.value, _record(decision.selected))


def _resolution(resolution: PairResolution) -> PairResolutionReport:
    decision = resolution.decision
    return PairResolutionReport(
        _group(resolution.group), PairDecisionReport(
            _key(decision.key), _decision(decision.r1), _decision(decision.r2), decision.confirmed),
        _record(resolution.effective_r1), _record(resolution.effective_r2),
        _records(resolution.unresolved_r1), _records(resolution.unresolved_r2),
        resolution.confirmed, resolution.resolved,
    )


def build_workflow_report(snapshot: WorkflowSnapshot) -> WorkflowReport:
    """Copy structured evidence, preserving supplied order and authoritative readiness."""
    findings = snapshot.reconciliation.findings
    diagnostics = snapshot.read_mode.diagnostics
    summary = WorkflowReportSummary(
        len(snapshot.inventory),
        sum(f.severity is Severity.ERROR for f in findings),
        sum(f.severity is Severity.WARNING for f in findings),
        sum(d.severity is DiagnosticSeverity.ERROR for d in diagnostics),
        sum(d.severity is DiagnosticSeverity.WARNING for d in diagnostics),
        len(snapshot.case_collisions), sum(not r.resolved for r in snapshot.pair_resolutions),
        snapshot.read_mode.mode.value, snapshot.read_mode.layout.value, snapshot.ready_for_export,
    )
    return WorkflowReport(
        summary, _records(snapshot.inventory),
        tuple(ReconciliationFindingReport(
            f.code, f.severity.value, f.message, f.row_number, f.sample,
            str(f.path) if f.path is not None else None,
            str(f.related_path) if f.related_path is not None else None,
            f.role.value if f.role is not None else None,
        ) for f in findings),
        tuple(AssignmentReport(a.row_number, a.sample, a.role.value, a.cell_value,
                               str(a.path), _record(a.record)) for a in snapshot.reconciliation.assignments),
        tuple(ReadModeDiagnosticReport(d.code, d.severity.value, d.message,
                                       _key(d.key) if d.key is not None else None,
                                       _records(d.records)) for d in diagnostics),
        tuple(_group(group) for group in snapshot.read_mode.groups),
        _records(snapshot.read_mode.excluded),
        tuple(PathCaseCollisionReport(c.normalized_key, _records(c.records)) for c in snapshot.case_collisions),
        tuple(_resolution(resolution) for resolution in snapshot.pair_resolutions),
    )
