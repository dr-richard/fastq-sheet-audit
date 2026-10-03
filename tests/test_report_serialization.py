"""The versioned JSON contract retains every field and every evidence record."""

import ast
import inspect
import json
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path

import pytest

from fastq_sheet_audit import report_serialization as serialization
from fastq_sheet_audit.reporting import (
    AssignmentReport, InventoryRecordReport, PairDecisionReport, PairGroupReport,
    PairKeyReport, PairResolutionReport, PathCaseCollisionReport,
    ReadModeDiagnosticReport, ReconciliationFindingReport, RoleDecisionReport,
    WorkflowReport, WorkflowReportSummary,
)


@pytest.fixture
def report():
    first = InventoryRecordReport("/data/项目/A_R1.fastq", "项目/A_R1.fastq", "read", " A α ",
                                  2, 1, "r1", 3, ".fastq", "R")
    alternate = replace(first, path="/alias/A_R1.fastq", relative_path="项目/a_R1.fastq")
    second = replace(first, path="/data/项目/A_R2.fastq", relative_path="项目/A_R2.fastq", read_role="r2")
    unparsed = InventoryRecordReport("/data/unknown.fq", "unknown.fq", "unparsed",
                                    None, None, None, None, None, None, None)
    key = PairKeyReport(" a α ", 2, 1, 3, "R", ".fastq", "项目")
    group = PairGroupReport(key, "ambiguous", (alternate, first), (second,))
    automatic = RoleDecisionReport("automatic", None)
    decision = PairDecisionReport(key, automatic, automatic, True)
    resolution = PairResolutionReport(group, decision, None, second, group.r1, (), True, False)
    return WorkflowReport(
        WorkflowReportSummary(4, 1, 1, 1, 1, 1, 1, "paired", "paired", False),
        (first, alternate, second, unparsed),
        (ReconciliationFindingReport("PAIR_MISMATCH", "error", "exact message α\nnext", 17, " A α ",
                                     first.path, second.path, "r2"),
         ReconciliationFindingReport("UNLISTED", "warning", "unknown", None, None, unparsed.path, None, None)),
        (AssignmentReport(17, " A α ", "r1", " original path ", first.path, first),),
        (ReadModeDiagnosticReport("AMBIGUOUS_PAIR", "error", "all candidates", key, (alternate, first, second)),
         ReadModeDiagnosticReport("AUTO_UNRESOLVED", "warning", "whole dataset", None, (first, alternate, second))),
        (group,), (unparsed,),
        (PathCaseCollisionReport("项目/a_r1.fastq", (alternate, first)),),
        (resolution,),
    )


TOP_LEVEL_KEYS = (
    "schema_version", "summary", "inventory", "reconciliation_findings", "reconciliation_assignments",
    "read_mode_diagnostics", "read_mode_groups", "read_mode_excluded", "case_collisions", "pair_resolutions",
)


def assert_complete_projection(original, projected):
    """Independent exhaustive oracle: every dataclass field must survive in order."""
    if is_dataclass(original):
        assert type(projected) is dict
        assert list(projected) == [field.name for field in fields(original)]
        for field in fields(original):
            assert_complete_projection(getattr(original, field.name), projected[field.name])
    elif isinstance(original, tuple):
        assert type(projected) is list and len(projected) == len(original)
        for old, new in zip(original, projected):
            assert_complete_projection(old, new)
    else:
        assert type(projected) is type(original) and projected == original


def test_schema_version_explicit_sections_and_every_nested_field(report):
    obj = serialization.workflow_report_to_obj(report)
    assert serialization.REPORT_SCHEMA_VERSION == obj["schema_version"] == 1
    assert type(obj["schema_version"]) is int
    assert tuple(obj) == TOP_LEVEL_KEYS
    assert_complete_projection(report, {key: obj[key] for key in TOP_LEVEL_KEYS[1:]})
    assert obj["inventory"][0] == {
        "path": "/data/项目/A_R1.fastq", "relative_path": "项目/A_R1.fastq", "category": "read",
        "sample": " A α ", "sample_number": 2, "lane": 1, "read_role": "r1", "chunk": 3,
        "suffix": ".fastq", "read_style": "R",
    }
    assert obj["read_mode_diagnostics"][0]["key"] == {
        "sample": " a α ", "sample_number": 2, "lane": 1, "chunk": 3,
        "read_style": "R", "suffix": ".fastq", "relative_parent": "项目",
    }
    assert obj["reconciliation_findings"][0]["related_path"] == "/data/项目/A_R2.fastq"
    assert obj["reconciliation_findings"][0]["role"] == "r2"


def test_all_evidence_arrays_order_and_duplicates_survive(report):
    group = report.pair_resolutions[0].group
    report = replace(report, pair_resolutions=(replace(report.pair_resolutions[0],
        group=replace(group, r1=group.r1 + (group.r1[0],)), unresolved_r1=group.r1 + (group.r1[0],)),))
    obj = serialization.workflow_report_to_obj(report)
    assert [r["path"] for r in obj["read_mode_diagnostics"][0]["records"]] == [
        "/alias/A_R1.fastq", "/data/项目/A_R1.fastq", "/data/项目/A_R2.fastq"]
    assert [r["path"] for r in obj["case_collisions"][0]["records"]] == [
        "/alias/A_R1.fastq", "/data/项目/A_R1.fastq"]
    pair = obj["pair_resolutions"][0]
    assert len(pair["group"]["r1"]) == len(pair["unresolved_r1"]) == 3
    assert pair["effective_r1"] is None and pair["effective_r2"]["read_role"] == "r2"
    assert pair["confirmed"] is True and pair["resolved"] is False
    assert pair["decision"]["confirmed"] is True


@pytest.mark.parametrize("kind", ["automatic", "select", "unassign"])
def test_decision_kinds_selected_records_and_absence_preserved(report, kind):
    resolution = report.pair_resolutions[0]
    selected = resolution.group.r1[1] if kind == "select" else None
    decision = replace(resolution.decision, r1=RoleDecisionReport(kind, selected))
    report = replace(report, pair_resolutions=(replace(resolution, decision=decision),))
    obj = serialization.workflow_report_to_obj(report)
    choice = obj["pair_resolutions"][0]["decision"]["r1"]
    assert choice["kind"] == kind
    if selected is None:
        assert choice["selected"] is None
    else:
        assert choice["selected"] == obj["inventory"][0]
    # Serialization copies evidence rather than adjudicating the new decision.
    assert obj["pair_resolutions"][0]["resolved"] is False


def test_unicode_null_pretty_json_final_lf_and_equal_reports(report):
    text = serialization.serialize_workflow_report_json(report)
    assert "项目" in text and "α" in text and "\\u" not in text
    assert '"sample": null' in text and '"key": null' in text
    assert text.startswith('{\n  "schema_version": 1,\n  "summary": {\n')
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert json.loads(text) == serialization.workflow_report_to_obj(report)
    assert text == serialization.serialize_workflow_report_json(report)
    assert text.encode("utf-8") == serialization.serialize_workflow_report_json(replace(report)).encode("utf-8")


def test_json_safe_types_fresh_containers_and_input_unchanged(report):
    before = replace(report)
    def check(value):
        if type(value) is dict:
            assert all(type(key) is str for key in value)
            for item in value.values():
                check(item)
        elif type(value) is list:
            for item in value:
                check(item)
        else:
            assert value is None or type(value) in (str, int, bool)
    obj = serialization.workflow_report_to_obj(report)
    check(obj)
    obj["pair_resolutions"][0]["group"]["r1"].clear()
    obj["inventory"][0]["sample"] = "changed"
    assert report == before
    fresh = serialization.workflow_report_to_obj(report)
    assert len(fresh["pair_resolutions"][0]["group"]["r1"]) == 2
    assert fresh["inventory"][0]["sample"] == " A α "


@dataclass(frozen=True)
class ArbitraryDataclass:
    summary: str = "not a workflow report"


@pytest.mark.parametrize("invalid", [None, {}, [], "report", 1, ArbitraryDataclass()])
@pytest.mark.parametrize("convert", [serialization.workflow_report_to_obj, serialization.serialize_workflow_report_json])
def test_non_report_rejected_consistently(invalid, convert):
    with pytest.raises(TypeError, match="report must be a WorkflowReport"):
        convert(invalid)


def test_purity_no_legacy_or_presentation_dependency(report, monkeypatch):
    from fastq_sheet_audit import inventory, sheet, workflow, reporting
    source = inspect.getsource(serialization)
    imports = [node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
    assert imports == ["__future__", "reporting"]
    def fail(*args, **kwargs):
        pytest.fail("serialization accessed I/O or recomputed domain evidence")
    with monkeypatch.context() as patch:
        for module, name in ((inventory, "scan_fastqs"), (sheet, "load_sheet"),
                             (workflow, "build_workflow_snapshot"), (reporting, "build_workflow_report")):
            patch.setattr(module, name, fail)
        for name in ("open", "stat", "lstat", "resolve", "read_text", "read_bytes", "write_text", "write_bytes"):
            patch.setattr(Path, name, fail)
        patch.setattr("builtins.open", fail)
        patch.setattr("os.stat", fail)
        patch.setattr("os.scandir", fail)
        patch.setattr("socket.socket", fail)
        obj = serialization.workflow_report_to_obj(report)
        text = serialization.serialize_workflow_report_json(report)
    assert json.loads(text) == obj
