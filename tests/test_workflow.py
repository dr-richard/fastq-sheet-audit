from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastq_sheet_audit.adjudication import PairDecision, RoleDecision, RoleDecisionKind, resolve_pair_group
from fastq_sheet_audit.column_mapping import map_columns
from fastq_sheet_audit.inventory import scan_fastqs
from fastq_sheet_audit.pairing import group_pairs
from fastq_sheet_audit.portability import PathCaseCollision
from fastq_sheet_audit.read_mode import DiagnosticSeverity, ReadLayout, ReadMode, ReadModeDiagnostic
from fastq_sheet_audit.reconciliation import Finding, Severity
from fastq_sheet_audit.sheet import SampleSheet, SheetRow
from fastq_sheet_audit.workflow import build_workflow_snapshot


AUTO = RoleDecision(RoleDecisionKind.AUTOMATIC, None)
UNASSIGN = RoleDecision(RoleDecisionKind.UNASSIGN, None)


def setup_case(root, names=("A_R1.fastq", "A_R2.fastq"), rows=None):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"do not read FASTQ contents")
    if rows is None:
        rows = [("A", "A_R1.fastq", "A_R2.fastq")]
    sheet = SampleSheet(("sample", "r1", "r2"), tuple(
        SheetRow(i, tuple(cells)) for i, cells in enumerate(rows, 2)
    ))
    return sheet, map_columns(sheet), scan_fastqs(root)


def test_clean_paired_snapshot(tmp_path):
    args = setup_case(tmp_path)
    snapshot = build_workflow_snapshot(*args, tmp_path)
    assert snapshot.ready_for_export
    assert not snapshot.has_findings
    assert not snapshot.has_errors
    assert not snapshot.has_warnings
    assert not snapshot.has_unresolved_pairs
    resolution, = snapshot.pair_resolutions
    assert resolution.resolved
    assert not resolution.confirmed
    assert resolution.decision.r1.kind is RoleDecisionKind.AUTOMATIC


def test_clean_single_snapshot(tmp_path):
    args = setup_case(tmp_path, ("A_R1.fastq",), [("A", "A_R1.fastq", "")])
    snapshot = build_workflow_snapshot(*args, tmp_path)
    assert snapshot.ready_for_export
    assert snapshot.pair_resolutions[0].effective_r2 is None


def test_automatic_ambiguity_and_explicit_selection_preserve_audit_evidence(tmp_path):
    sheet, mapping, records = setup_case(tmp_path)
    records.append(records[0])
    automatic = build_workflow_snapshot(sheet, mapping, records, tmp_path)
    assert automatic.has_unresolved_pairs
    assert automatic.has_warnings
    assert not automatic.ready_for_export
    group, = group_pairs(records)
    selection = PairDecision(group.key, RoleDecision(RoleDecisionKind.SELECT, group.r1[0]), AUTO, True)
    adjudicated = build_workflow_snapshot(sheet, mapping, records, tmp_path, decisions={group.key: selection})
    assert not adjudicated.has_unresolved_pairs
    assert adjudicated.pair_resolutions[0].resolved
    assert len(adjudicated.pair_resolutions[0].group.r1) == 2
    assert adjudicated.inventory == automatic.inventory
    assert len(adjudicated.inventory) == 3
    assert adjudicated.read_mode.layout is ReadLayout.PAIRED
    assert adjudicated.read_mode.diagnostics == ()
    assert adjudicated.reconciliation == automatic.reconciliation
    assert not adjudicated.has_warnings
    assert adjudicated.ready_for_export


@pytest.mark.parametrize("role", ["r1", "r2"])
def test_explicit_unassign(role, tmp_path):
    args = setup_case(tmp_path)
    group, = group_pairs(args[2])
    choices = PairDecision(group.key, UNASSIGN if role == "r1" else AUTO,
                           UNASSIGN if role == "r2" else AUTO, True)
    snapshot = build_workflow_snapshot(*args, tmp_path, decisions={group.key: choices})
    resolution, = snapshot.pair_resolutions
    assert getattr(resolution, "effective_" + role) is None
    assert getattr(resolution, "unresolved_" + role) == ()
    assert resolution.group == group
    assert snapshot.has_unresolved_pairs is (role == "r1")
    assert snapshot.ready_for_export is (role == "r2")
    if role == "r2":
        assert snapshot.read_mode.layout is ReadLayout.SINGLE
        assert snapshot.read_mode.diagnostics == ()


def test_paired_mode_r2_unassign_requires_missing_mate(tmp_path):
    args = setup_case(tmp_path)
    group, = group_pairs(args[2])
    choices = PairDecision(group.key, AUTO, UNASSIGN, True)
    snapshot = build_workflow_snapshot(*args, tmp_path, read_mode=ReadMode.PAIRED,
                                       decisions={group.key: choices})
    assert snapshot.pair_resolutions[0].resolved
    assert snapshot.read_mode.diagnostics[0].code == "MISSING_R2"
    assert snapshot.has_errors
    assert not snapshot.ready_for_export
    assert snapshot.inventory == tuple(args[2])
    assert snapshot.pair_resolutions[0].group.r2 == group.r2


def test_effective_inventory_retains_nonpairable_records_and_raw_unlisted_finding(tmp_path):
    args = setup_case(tmp_path, ("A_R1.fastq", "A_R2.fastq", "A_I1.fastq", "unknown.fq"))
    group, = group_pairs(args[2])
    choices = PairDecision(group.key, AUTO, UNASSIGN, True)
    snapshot = build_workflow_snapshot(*args, tmp_path, decisions={group.key: choices})
    assert snapshot.read_mode.layout is ReadLayout.SINGLE
    assert {record.path.name for record in snapshot.read_mode.excluded} == {"A_I1.fastq", "unknown.fq"}
    assert len(snapshot.inventory) == 4
    assert len(snapshot.reconciliation.inventory) == 4
    assert {finding.path.name for finding in snapshot.reconciliation.findings} == {"A_I1.fastq", "unknown.fq"}
    assert snapshot.has_warnings
    assert not snapshot.ready_for_export


def test_selection_does_not_suppress_raw_case_collisions(tmp_path):
    args = setup_case(tmp_path, ("A_R1.fastq", "a_R1.fastq", "A_R2.fastq"), [
        ("A", "A_R1.fastq", "A_R2.fastq"), ("a", "a_R1.fastq", ""),
    ])
    if (tmp_path / "A_R1.fastq").samefile(tmp_path / "a_R1.fastq"):
        pytest.skip("filesystem cannot represent distinct case-only filenames")
    group, = group_pairs(args[2])
    choices = PairDecision(group.key, RoleDecision(RoleDecisionKind.SELECT, group.r1[0]), AUTO, True)
    snapshot = build_workflow_snapshot(*args, tmp_path, decisions={group.key: choices})
    assert snapshot.read_mode.diagnostics == ()
    assert not snapshot.has_unresolved_pairs
    assert snapshot.reconciliation.findings == ()
    assert len(snapshot.case_collisions) == 1
    assert len(snapshot.inventory) == 3
    assert snapshot.has_warnings
    assert not snapshot.ready_for_export


def test_stale_and_mismatched_decisions_rejected(tmp_path):
    args = setup_case(tmp_path)
    group, = group_pairs(args[2])
    stale_key = replace(group.key, lane=2)
    stale = PairDecision(stale_key, AUTO, AUTO, False)
    with pytest.raises(ValueError, match="not present"):
        build_workflow_snapshot(*args, tmp_path, decisions={stale_key: stale})
    with pytest.raises(ValueError, match="mapping key"):
        build_workflow_snapshot(*args, tmp_path, decisions={group.key: stale})


def test_reconciliation_error_propagates(tmp_path):
    args = setup_case(tmp_path, (), [("A", "missing_R1.fastq", "")])
    snapshot = build_workflow_snapshot(*args, tmp_path, read_mode=ReadMode.SINGLE)
    assert snapshot.has_errors
    assert snapshot.has_findings
    assert not snapshot.ready_for_export
    assert snapshot.reconciliation.findings[0].code == "MISSING_FILE"


def test_reconciliation_warning_propagates(tmp_path):
    args = setup_case(tmp_path, rows=[("B", "A_R1.fastq", "A_R2.fastq")])
    snapshot = build_workflow_snapshot(*args, tmp_path)
    assert snapshot.has_warnings
    assert snapshot.has_findings
    assert not snapshot.has_errors
    assert not snapshot.ready_for_export


@pytest.mark.parametrize("mode, error", [(ReadMode.AUTO, False), (ReadMode.PAIRED, True)])
def test_read_mode_warning_and_error_propagate(tmp_path, mode, error):
    args = setup_case(tmp_path, ("A_R2.fastq",), [("A", "", "A_R2.fastq")])
    snapshot = build_workflow_snapshot(*args, tmp_path, read_mode=mode)
    assert snapshot.read_mode.diagnostics[0].severity is (
        DiagnosticSeverity.ERROR if error else DiagnosticSeverity.WARNING
    )
    assert snapshot.has_findings
    assert snapshot.has_unresolved_pairs
    assert snapshot.has_warnings
    assert not snapshot.ready_for_export


def test_case_collision_affects_summary(tmp_path):
    args = setup_case(tmp_path, ("A_R1.fastq", "a_R1.fastq"), [
        ("A", "A_R1.fastq", ""), ("a", "a_R1.fastq", ""),
    ])
    if (tmp_path / "A_R1.fastq").samefile(tmp_path / "a_R1.fastq"):
        pytest.skip("filesystem cannot represent distinct case-only filenames")
    snapshot = build_workflow_snapshot(*args, tmp_path, read_mode=ReadMode.SINGLE)
    assert len(snapshot.case_collisions) == 1
    assert snapshot.has_warnings
    assert snapshot.has_findings
    assert not snapshot.ready_for_export


def test_each_export_readiness_condition_independently_blocks(tmp_path):
    args = setup_case(tmp_path)
    clean = build_workflow_snapshot(*args, tmp_path)
    group = clean.pair_resolutions[0].group
    blocked = [
        replace(clean, reconciliation=replace(clean.reconciliation, findings=(
            Finding("TEST", Severity.WARNING, "test evidence"),))),
        replace(clean, read_mode=replace(clean.read_mode, diagnostics=(
            ReadModeDiagnostic("TEST", DiagnosticSeverity.WARNING, "test evidence", None, ()),))),
        replace(clean, case_collisions=(PathCaseCollision("a", group.r1),)),
        replace(clean, pair_resolutions=(resolve_pair_group(
            group, PairDecision(group.key, UNASSIGN, AUTO, True)),)),
    ]
    assert clean.ready_for_export
    for snapshot in blocked:
        assert not snapshot.ready_for_export
        assert snapshot.has_findings
        assert snapshot.has_warnings


def test_deterministic_order_and_inputs_unchanged(tmp_path):
    names = [f"A_L{lane:03d}_{role}_001.fastq" for lane in (2, 1) for role in ("R1", "R2")]
    args = setup_case(tmp_path, names, [("A", names[0], names[1]), ("A", names[2], names[3])])
    sheet, mapping, records = args
    original = (sheet, mapping, tuple(records))
    groups = group_pairs(records)
    decisions = {group.key: PairDecision(group.key, AUTO, AUTO, True) for group in reversed(groups)}
    snapshot = build_workflow_snapshot(*args, tmp_path, decisions=decisions)
    assert [resolution.group for resolution in snapshot.pair_resolutions] == groups
    assert build_workflow_snapshot(sheet, mapping, reversed(records), tmp_path,
                                   decisions=dict(reversed(tuple(decisions.items())))) == snapshot
    assert (sheet, mapping, tuple(records)) == original
    assert all(resolution.decision is decisions[resolution.group.key] for resolution in snapshot.pair_resolutions)


def test_snapshot_is_immutable(tmp_path):
    snapshot = build_workflow_snapshot(*setup_case(tmp_path), tmp_path)
    with pytest.raises(FrozenInstanceError):
        snapshot.inventory = ()
    assert isinstance(snapshot.inventory, tuple)
    assert isinstance(snapshot.case_collisions, tuple)
    assert isinstance(snapshot.pair_resolutions, tuple)


def test_no_network_fastq_reads_or_writes(tmp_path, monkeypatch):
    args = setup_case(tmp_path)
    def fail(*args, **kwargs):
        pytest.fail("workflow attempted content access, write, or network access")
    for method in ("open", "read_bytes", "read_text", "write_bytes", "write_text", "rename", "unlink"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    assert build_workflow_snapshot(*args, tmp_path).ready_for_export
