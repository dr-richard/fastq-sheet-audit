"""Immutable orchestration snapshots for rendering audit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .adjudication import PairDecision, PairResolution, RoleDecision, RoleDecisionKind, resolve_pair_group
from .column_mapping import ColumnMappingResult
from .inventory import InventoryRecord
from .pairing import PairKey, group_pairs, pair_key
from .portability import PathCaseCollision, find_case_collisions
from .read_mode import DiagnosticSeverity, ReadMode, ReadModeResult, diagnose_read_mode
from .reconciliation import ReconciliationResult, Severity, reconcile
from .sheet import SampleSheet


@dataclass(frozen=True)
class WorkflowSnapshot:
    inventory: tuple[InventoryRecord, ...]
    reconciliation: ReconciliationResult
    read_mode: ReadModeResult
    case_collisions: tuple[PathCaseCollision, ...]
    pair_resolutions: tuple[PairResolution, ...]

    @property
    def has_findings(self) -> bool:
        return bool(
            self.reconciliation.findings or self.read_mode.diagnostics
            or self.case_collisions or self.has_unresolved_pairs
        )

    @property
    def has_errors(self) -> bool:
        return (
            any(finding.severity is Severity.ERROR for finding in self.reconciliation.findings)
            or any(diagnostic.severity is DiagnosticSeverity.ERROR for diagnostic in self.read_mode.diagnostics)
        )

    @property
    def has_warnings(self) -> bool:
        return bool(
            self.case_collisions or self.has_unresolved_pairs
            or any(finding.severity is Severity.WARNING for finding in self.reconciliation.findings)
            or any(diagnostic.severity is DiagnosticSeverity.WARNING for diagnostic in self.read_mode.diagnostics)
        )

    @property
    def has_unresolved_pairs(self) -> bool:
        return any(not resolution.resolved for resolution in self.pair_resolutions)

    @property
    def ready_for_export(self) -> bool:
        return (
            not self.reconciliation.findings
            and not self.read_mode.diagnostics
            and not self.case_collisions
            and not self.has_unresolved_pairs
        )


def build_workflow_snapshot(
    sheet: SampleSheet,
    mapping: ColumnMappingResult,
    records: Iterable[InventoryRecord],
    fastq_root: Path,
    *,
    read_mode: ReadMode = ReadMode.AUTO,
    decisions: Mapping[PairKey, PairDecision] | None = None,
) -> WorkflowSnapshot:
    """Compose existing checks without repairs, inferred decisions, or writes.

    Reconciliation uses filesystem metadata for identity/existence checks;
    this layer never opens FASTQ contents or performs network access. Human
    decisions affect resolutions and effective read-layout diagnosis. Raw
    inventory remains intact for reconciliation, collisions, and pair evidence.
    Stale or mismatched decisions are rejected, never silently ignored.
    """
    inventory = tuple(sorted(records, key=lambda record: (
        record.relative_path.as_posix(), record.path.as_posix(),
        record.category.value, repr(record.parsed_name),
    )))
    groups = tuple(group_pairs(inventory))
    supplied = dict(decisions) if decisions is not None else {}
    keys = {group.key for group in groups}
    for key, decision in supplied.items():
        if key not in keys:
            raise ValueError("decision key is not present in grouped inventory")
        if not isinstance(decision, PairDecision) or decision.key != key:
            raise ValueError("supplied decision key does not match its mapping key")
    automatic = RoleDecision(RoleDecisionKind.AUTOMATIC, None)
    resolutions = tuple(resolve_pair_group(
        group, supplied[group.key] if group.key in supplied else
        PairDecision(group.key, automatic, automatic, False),
    ) for group in groups)
    effective_inventory = tuple(
        record for resolution in resolutions
        for record in (resolution.effective_r1, resolution.effective_r2)
        if record is not None
    ) + tuple(record for record in inventory if pair_key(record) is None)
    return WorkflowSnapshot(
        inventory,
        reconcile(sheet, mapping, inventory, fastq_root),
        diagnose_read_mode(effective_inventory, read_mode),
        tuple(find_case_collisions(inventory)),
        resolutions,
    )
