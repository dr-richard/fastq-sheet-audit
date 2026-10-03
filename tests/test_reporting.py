"""Machine reports preserve domain evidence without I/O or presentation logic."""

from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from pathlib import Path
import ast
import inspect

import pytest

from fastq_sheet_audit import reporting
from fastq_sheet_audit.adjudication import PairDecision, RoleDecision, RoleDecisionKind, resolve_pair_group
from fastq_sheet_audit.column_mapping import ColumnRole, map_columns
from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.pairing import group_pairs
from fastq_sheet_audit.portability import find_case_collisions
from fastq_sheet_audit.read_mode import ReadMode, diagnose_read_mode
from fastq_sheet_audit.reconciliation import Assignment, Finding, ReconciliationResult, Severity
from fastq_sheet_audit.sheet import SampleSheet, SheetRow
from fastq_sheet_audit.workflow import WorkflowSnapshot, build_workflow_snapshot


AUTO = RoleDecision(RoleDecisionKind.AUTOMATIC, None)


def record(name, category=InventoryCategory.READ):
    return InventoryRecord(Path("/unopened/α") / name, Path(name), parse_fastq_name(Path(name).name), category)


def snapshot_for(records, *, decision=None, mode=ReadMode.AUTO):
    records = tuple(records)
    groups = group_pairs(records)
    resolutions = tuple(resolve_pair_group(group, decision or PairDecision(group.key, AUTO, AUTO, False))
                        for group in groups)
    return WorkflowSnapshot(records, ReconciliationResult(records, (), ()), diagnose_read_mode(records, mode),
                            tuple(find_case_collisions(records)), resolutions)


def test_clean_paired_structure_original_paths_and_summary():
    records = (record("run/Α_S7_L001_R1_002.FASTQ.GZ"), record("run/Α_S7_L001_R2_002.FASTQ.GZ"))
    snapshot = snapshot_for(records)
    report = reporting.build_workflow_report(snapshot)
    assert report.summary == reporting.WorkflowReportSummary(2, 0, 0, 0, 0, 0, 0, "auto", "paired", True)
    first = report.inventory[0]
    assert first == reporting.InventoryRecordReport(
        str(records[0].path), str(records[0].relative_path), "read", "Α", 7, 1, "r1", 2, ".FASTQ.GZ", "R")
    pair = report.pair_resolutions[0]
    assert pair.group.key == reporting.PairKeyReport("α", 7, 1, 2, "R", ".fastq.gz", "run")
    assert pair.group.status == "complete" and pair.resolved and not pair.confirmed
    assert pair.group.r1 == (first,) and pair.effective_r1 == first
    assert pair.decision.r1 == reporting.RoleDecisionReport("automatic", None)
    assert pair.unresolved_r1 == pair.unresolved_r2 == ()
    assert report.read_mode_groups == (pair.group,)


def test_unparsed_index_undetermined_evidence_and_exclusions():
    records = (record("unknown.fastq", InventoryCategory.UNPARSED),
               record("A_I1_001.fq", InventoryCategory.INDEX),
               record("Undetermined_R1.fastq", InventoryCategory.UNDETERMINED))
    report = reporting.build_workflow_report(snapshot_for(records))
    unknown = report.inventory[0]
    assert all(getattr(unknown, name) is None for name in
               ("sample", "sample_number", "lane", "read_role", "chunk", "suffix", "read_style"))
    assert report.inventory[1].read_role == "i1"
    assert report.inventory[2].category == "undetermined"
    assert set(report.read_mode_excluded) == set(report.inventory)
    assert report.summary.read_layout == "unresolved"
    assert report.read_mode_diagnostics[0].key is None


def test_all_reconciliation_fields_assignments_and_separate_counts():
    records = (record("A_R1.fastq"), record("A_R2.fastq"))
    snapshot = snapshot_for(records, mode=ReadMode.SINGLE)
    findings = (Finding("E", Severity.ERROR, "exact message", 9, " A ", Path("./relative α"),
                        Path("/related/B"), ColumnRole.R2),
                Finding("W", Severity.WARNING, "warning"))
    assignment = Assignment(9, " A ", ColumnRole.R1, " original cell ", Path("relative α"), records[0])
    snapshot = replace(snapshot, reconciliation=ReconciliationResult(records, (assignment,), findings))
    report = reporting.build_workflow_report(snapshot)
    assert report.reconciliation_findings == (
        reporting.ReconciliationFindingReport("E", "error", "exact message", 9, " A ",
                                               "relative α", "/related/B", "r2"),
        reporting.ReconciliationFindingReport("W", "warning", "warning", None, None, None, None, None))
    assert report.reconciliation_assignments == (reporting.AssignmentReport(
        9, " A ", "r1", " original cell ", "relative α", report.inventory[0]),)
    assert (report.summary.reconciliation_error_count, report.summary.reconciliation_warning_count,
            report.summary.read_mode_error_count, report.summary.read_mode_warning_count) == (1, 1, 1, 0)
    assert not report.summary.ready_for_export


def test_read_diagnostic_retains_all_records_structured_key_and_message():
    records = (record("A_R1.fastq"), record("a_R1.fastq"), record("A_R2.fastq"))
    snapshot = snapshot_for(records, mode=ReadMode.PAIRED)
    report = reporting.build_workflow_report(snapshot)
    diagnostic = report.read_mode_diagnostics[0]
    original = snapshot.read_mode.diagnostics[0]
    assert diagnostic.code == original.code == "AMBIGUOUS_PAIR"
    assert diagnostic.severity == "error" and diagnostic.message == original.message
    assert diagnostic.key == report.pair_resolutions[0].group.key
    assert tuple(r.path for r in diagnostic.records) == tuple(str(r.path) for r in original.records)
    assert len(diagnostic.records) == 3
    assert report.summary.case_collision_count == 1
    collision = report.case_collisions[0]
    assert collision.normalized_key == snapshot.case_collisions[0].normalized_key
    assert tuple(r.path for r in collision.records) == tuple(str(r.path) for r in snapshot.case_collisions[0].records)
    assert len(collision.records) == 2


@pytest.mark.parametrize("kind", list(RoleDecisionKind))
def test_adjudication_evidence_decision_confirmation_independent(kind):
    records = (record("A_R1.fastq"), record("A_R1.fastq"), record("A_R2.fastq"))
    group = group_pairs(records)[0]
    choice = RoleDecision(kind, group.r1[1] if kind is RoleDecisionKind.SELECT else None)
    decision = PairDecision(group.key, choice, AUTO, True)
    snapshot = snapshot_for(records, decision=decision)
    report = reporting.build_workflow_report(snapshot)
    resolution = report.pair_resolutions[0]
    assert resolution.group.status == "ambiguous"
    assert len(resolution.group.r1) == 2 and len(resolution.group.r2) == 1
    assert resolution.decision.r1.kind == kind.value
    assert resolution.decision.key == resolution.group.key
    assert resolution.confirmed and resolution.decision.confirmed
    if kind is RoleDecisionKind.AUTOMATIC:
        assert resolution.unresolved_r1 == resolution.group.r1
        assert resolution.effective_r1 is None and not resolution.resolved
    elif kind is RoleDecisionKind.SELECT:
        assert resolution.decision.r1.selected == resolution.group.r1[1]
        assert resolution.effective_r1 == resolution.group.r1[1]
        assert resolution.unresolved_r1 == () and resolution.resolved
    else:
        assert resolution.unresolved_r1 == () and resolution.effective_r1 is None
        assert resolution.decision.r1.selected is None and not resolution.resolved
    assert report.summary.ready_for_export == snapshot.ready_for_export
    assert report.summary.unresolved_pair_count == sum(not r.resolved for r in snapshot.pair_resolutions)
    assert report.summary.read_mode_warning_count == 1


def test_domain_normalized_iterable_order_produces_equal_reports(tmp_path):
    records = []
    for name in ("B_R2.fastq", "A_R1.fastq", "B_R1.fastq", "A_R2.fastq"):
        path = tmp_path / name
        path.touch()
        records.append(replace(record(name), path=path))
    sheet = SampleSheet(("sample", "r1", "r2"), (
        SheetRow(7, ("B", "B_R1.fastq", "B_R2.fastq")), SheetRow(2, ("A", "A_R1.fastq", "A_R2.fastq"))))
    mapping = map_columns(sheet)
    first = build_workflow_snapshot(sheet, mapping, records, tmp_path)
    second = build_workflow_snapshot(sheet, mapping, reversed(records), tmp_path)
    assert reporting.build_workflow_report(first) == reporting.build_workflow_report(second)


def test_report_is_recursively_immutable_and_inputs_unchanged():
    snapshot = snapshot_for((record("A_R1.fastq"), record("A_R2.fastq")))
    before = replace(snapshot)
    report = reporting.build_workflow_report(snapshot)
    def check(value):
        if is_dataclass(value):
            first = fields(value)[0]
            with pytest.raises(FrozenInstanceError):
                setattr(value, first.name, None)
            for field in fields(value):
                check(getattr(value, field.name))
        elif isinstance(value, tuple):
            for item in value:
                check(item)
        else:
            assert value is None or type(value) in (str, bool, int)
    check(report)
    assert snapshot == before
    assert reporting.build_workflow_report(snapshot) == report


def test_reporting_has_no_io_domain_reexecution_or_legacy_dependency(monkeypatch):
    from fastq_sheet_audit import inventory, sheet, workflow, reconciliation
    snapshot = snapshot_for((record("A_R1.fastq"), record("A_R2.fastq")))
    source = inspect.getsource(reporting)
    def fail(*args, **kwargs):
        pytest.fail("reporting accessed I/O or reran domain pipeline")
    with monkeypatch.context() as patch:
        for module, name in ((inventory, "scan_fastqs"), (sheet, "load_sheet"),
                             (workflow, "build_workflow_snapshot"), (reconciliation, "reconcile")):
            patch.setattr(module, name, fail)
        for name in ("open", "stat", "lstat", "resolve", "read_text", "read_bytes", "write_text", "write_bytes"):
            patch.setattr(Path, name, fail)
        patch.setattr("builtins.open", fail)
        patch.setattr("os.scandir", fail)
        patch.setattr("os.stat", fail)
        patch.setattr("socket.socket", fail)
        report = reporting.build_workflow_report(snapshot)
    assert report.summary.ready_for_export
    imports = [node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
    assert "core" not in imports and "presentation" not in imports
