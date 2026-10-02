from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastq_sheet_audit.adjudication import PairDecision, RoleDecision, RoleDecisionKind, resolve_pair_group
from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.pairing import group_pairs
from fastq_sheet_audit.portability import PathCaseCollision
from fastq_sheet_audit.presentation import present_workflow
from fastq_sheet_audit.read_mode import DiagnosticSeverity, ReadLayout, ReadMode, ReadModeDiagnostic, ReadModeResult
from fastq_sheet_audit.reconciliation import Finding, ReconciliationResult, Severity
from fastq_sheet_audit.workflow import WorkflowSnapshot


def record(name):
    relative = Path(name)
    return InventoryRecord(Path("/scan") / relative, relative,
                           parse_fastq_name(relative.name), InventoryCategory.READ)


def snapshot(ambiguous=False):
    r1 = record("run α/A_S1_L002_R1_003.fastq.gz")
    r2 = record("run α/A_S1_L002_R2_003.fastq.gz")
    records = (r2, r1, replace(r1, path=Path("/other") / r1.relative_path)) if ambiguous else (r2, r1)
    groups = tuple(group_pairs(records))
    auto = RoleDecision(RoleDecisionKind.AUTOMATIC, None)
    resolutions = tuple(resolve_pair_group(group, PairDecision(group.key, auto, auto, False)) for group in groups)
    return WorkflowSnapshot(records, ReconciliationResult(records, (), ()),
                            ReadModeResult(ReadMode.AUTO, ReadLayout.PAIRED, groups, (), ()), (), resolutions)


def test_clean_paired_presentation():
    evidence = snapshot()
    view = present_workflow(evidence)
    assert view.summary.inventory_count == 2
    assert view.summary.error_count == view.summary.warning_count == view.summary.unresolved_pair_count == 0
    assert view.summary.ready_for_export
    assert view.findings == ()
    pair, = view.pairs
    assert pair.r1_candidate_count == pair.r2_candidate_count == 1
    assert pair.effective_r1 == "run α/A_S1_L002_R1_003.fastq.gz"
    assert pair.effective_r2 == "run α/A_S1_L002_R2_003.fastq.gz"
    assert pair.resolved
    assert not pair.confirmed


def test_reconciliation_findings_preserve_values_and_order():
    evidence = snapshot()
    findings = (
        Finding("MISSING_FILE", Severity.ERROR, "missing file", 8, " α-A ", Path("relative/A.fastq")),
        Finding("SAMPLE_NAME_MISMATCH", Severity.WARNING, "sample mismatch", 3, "B", None),
    )
    evidence = replace(evidence, reconciliation=replace(evidence.reconciliation, findings=findings))
    view = present_workflow(evidence)
    assert [row.code for row in view.findings] == [finding.code for finding in findings]
    assert [row.severity for row in view.findings] == ["error", "warning"]
    assert view.findings[0].row_number == 8
    assert view.findings[0].sample == " α-A "
    assert view.findings[0].path == "relative/A.fastq"
    assert view.findings[1].path is None
    assert view.summary.error_count == view.summary.warning_count == 1


def test_read_mode_diagnostic_rendering():
    evidence = snapshot()
    r2 = evidence.inventory[0]
    diagnostic = ReadModeDiagnostic("UNEXPECTED_R2", DiagnosticSeverity.ERROR,
                                    "unexpected R2", evidence.pair_resolutions[0].group.key, (r2,))
    evidence = replace(evidence, read_mode=replace(evidence.read_mode, diagnostics=(diagnostic,)))
    view = present_workflow(evidence)
    row, = view.findings
    assert (row.source, row.severity, row.code, row.message) == ("read_mode", "error", "UNEXPECTED_R2", "unexpected R2")
    assert row.path == str(r2.path)
    assert row.sample == "a"
    assert row.row_number is None


def test_collision_warning_contains_every_path():
    evidence = snapshot()
    collision = PathCaseCollision("run α/a", evidence.inventory)
    evidence = replace(evidence, case_collisions=(collision,))
    view = present_workflow(evidence)
    row, = view.findings
    assert (row.source, row.code, row.severity) == ("portability", "PATH_CASE_COLLISION", "warning")
    assert collision.normalized_key in row.message
    assert all(str(record.path) in row.message for record in collision.records)
    assert view.summary.warning_count == 1
    assert not view.summary.ready_for_export


def test_unresolved_pair_and_candidate_rendering():
    evidence = snapshot(ambiguous=True)
    view = present_workflow(evidence)
    row, = view.findings
    assert (row.source, row.code, row.severity) == ("adjudication", "UNRESOLVED_PAIR", "warning")
    assert view.summary.unresolved_pair_count == 1
    pair, = view.pairs
    assert pair.r1_candidate_count == pair.unresolved_r1_count == 2
    assert pair.effective_r1 is None
    assert pair.effective_r2 is not None
    assert pair.unresolved_r2_count == 0
    assert not pair.resolved


def test_all_sources_in_order_and_summary_matches_displayed_rows():
    evidence = snapshot(ambiguous=True)
    reconciliation = replace(evidence.reconciliation, findings=(
        Finding("E", Severity.ERROR, "error"), Finding("W", Severity.WARNING, "warning"),
    ))
    mode = replace(evidence.read_mode, diagnostics=(
        ReadModeDiagnostic("MODE", DiagnosticSeverity.WARNING, "mixed", None, ()),
    ))
    evidence = replace(evidence, reconciliation=reconciliation, read_mode=mode,
                       case_collisions=(PathCaseCollision("x", evidence.inventory),))
    view = present_workflow(evidence)
    assert [row.source for row in view.findings] == [
        "reconciliation", "reconciliation", "read_mode", "portability", "adjudication",
    ]
    assert view.summary.error_count == sum(row.severity == "error" for row in view.findings) == 1
    assert view.summary.warning_count == sum(row.severity == "warning" for row in view.findings) == 4
    assert view.summary.ready_for_export is evidence.ready_for_export


def test_inventory_metadata_and_unparsed_records():
    evidence = snapshot()
    unknown = replace(record(" unknown 空间.fq"), category=InventoryCategory.UNPARSED, parsed_name=None)
    evidence = replace(evidence, inventory=evidence.inventory + (unknown,))
    view = present_workflow(evidence)
    assert [row.relative_path for row in view.inventory] == [record.relative_path.as_posix() for record in evidence.inventory]
    first = view.inventory[0]
    assert (first.category, first.sample, first.read_role, first.lane, first.chunk) == ("read", "A", "R2", 2, 3)
    last = view.inventory[-1]
    assert last.relative_path == " unknown 空间.fq"
    assert last.category == "unparsed"
    assert last.sample is last.read_role is last.lane is last.chunk is None


def test_pair_key_text_contains_all_structural_identity():
    text = present_workflow(snapshot()).pairs[0].key_text
    assert text == (
        "sample='a'; sample_number=1; lane=2; chunk=3; read_style='R'; "
        "suffix='.fastq.gz'; relative_parent='run α'"
    )


def test_pair_order_and_confirmation_follow_snapshot():
    evidence = snapshot()
    resolution = evidence.pair_resolutions[0]
    confirmed = replace(resolution.decision, confirmed=True)
    other_group = replace(resolution.group, key=replace(resolution.group.key, lane=5))
    other_decision = replace(resolution.decision, key=other_group.key)
    first = resolve_pair_group(other_group, other_decision)
    second = resolve_pair_group(resolution.group, confirmed)
    evidence = replace(evidence, pair_resolutions=(first, second))
    view = present_workflow(evidence)
    assert "lane=5" in view.pairs[0].key_text
    assert "lane=2" in view.pairs[1].key_text
    assert view.pairs[1].confirmed


def test_immutable_outputs_and_inputs_unchanged():
    evidence = snapshot()
    original = replace(evidence)
    view = present_workflow(evidence)
    assert present_workflow(evidence) == view
    assert evidence == original
    assert evidence.inventory is original.inventory
    for obj, field, value in [(view, "pairs", ()), (view.summary, "ready_for_export", False),
                              (view.inventory[0], "sample", "changed"), (view.pairs[0], "resolved", False)]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
    warning_view = present_workflow(snapshot(ambiguous=True))
    with pytest.raises(FrozenInstanceError):
        warning_view.findings[0].code = "changed"


def test_no_filesystem_network_or_content_access(monkeypatch):
    evidence = snapshot()
    def fail(*args, **kwargs):
        pytest.fail("presentation accessed external state")
    for method in ("open", "stat", "resolve", "exists", "read_bytes", "read_text"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    assert present_workflow(evidence).summary.ready_for_export
