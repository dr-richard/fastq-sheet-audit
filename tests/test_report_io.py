"""Delegation and real publication through the established serializer/writer."""

import ast
import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from fastq_sheet_audit import report_io
from fastq_sheet_audit.report_serialization import serialize_workflow_report_json, workflow_report_to_obj
from fastq_sheet_audit.reporting import WorkflowReport, WorkflowReportSummary, InventoryRecordReport


@pytest.fixture
def report():
    return WorkflowReport(
        WorkflowReportSummary(1, 0, 0, 0, 0, 0, 0, "auto", "single", True),
        (InventoryRecordReport("/data/项目/α_R1.fastq", "项目/α_R1.fastq", "read", "α", None,
                               None, "r1", None, ".fastq", "R"),),
        (), (), (), (), (), (), (),
    )


@pytest.mark.parametrize("overwrite", [None, False, True])
def test_exact_delegation_options_identity_and_return(report, monkeypatch, overwrite):
    destination = Path(" relative 项目.json ")
    returned = Path("/writer/returned.json")
    # A generator must not be consumed, copied, or normalized by the adapter.
    protected = (path for path in (Path("relative.fastq"), Path("../sheet.csv")))
    writer = Mock(return_value=returned)
    monkeypatch.setattr(report_io, "write_text_atomic", writer)
    options = {} if overwrite is None else {"overwrite": overwrite}
    result = report_io.write_workflow_report_json(report, destination, protected_paths=protected, **options)
    writer.assert_called_once_with(serialize_workflow_report_json(report), destination,
                                   protected_paths=protected, overwrite=False if overwrite is None else overwrite)
    assert writer.call_args.args[1] is destination
    assert writer.call_args.kwargs["protected_paths"] is protected
    assert list(protected) == [Path("relative.fastq"), Path("../sheet.csv")]
    assert result is returned


def test_default_protected_paths_and_serialize_before_write(report, monkeypatch):
    events = []
    text = "exact serialized α\n"
    destination = Path("output.json")
    def serialize(value):
        assert value is report
        events.append("serialize")
        return text
    def write(value, path, **options):
        assert events == ["serialize"]
        assert value is text and path is destination
        assert options == {"protected_paths": (), "overwrite": False}
        events.append("write")
        return path
    monkeypatch.setattr(report_io, "serialize_workflow_report_json", serialize)
    monkeypatch.setattr(report_io, "write_text_atomic", write)
    assert report_io.write_workflow_report_json(report, destination) is destination
    assert events == ["serialize", "write"]


@pytest.mark.parametrize("invalid", [None, {}, "report", 1])
def test_non_report_fails_through_serializer_without_writer(invalid, monkeypatch):
    writer = Mock()
    monkeypatch.setattr(report_io, "write_text_atomic", writer)
    with pytest.raises(TypeError, match="report must be a WorkflowReport"):
        report_io.write_workflow_report_json(invalid, Path("out.json"))
    writer.assert_not_called()


def test_serialization_exception_propagates_without_publication(report, monkeypatch):
    error = ValueError("serialization failed")
    writer = Mock()
    monkeypatch.setattr(report_io, "serialize_workflow_report_json", Mock(side_effect=error))
    monkeypatch.setattr(report_io, "write_text_atomic", writer)
    with pytest.raises(ValueError) as caught:
        report_io.write_workflow_report_json(report, Path("out.json"))
    assert caught.value is error
    writer.assert_not_called()


@pytest.mark.parametrize("error", [ValueError("protected"), FileExistsError("exists"),
                                      PermissionError("permission"), RuntimeError("writer bug")])
def test_writer_exception_propagates_unchanged(report, monkeypatch, error):
    monkeypatch.setattr(report_io, "write_text_atomic", Mock(side_effect=error))
    with pytest.raises(type(error)) as caught:
        report_io.write_workflow_report_json(report, Path("out.json"))
    assert caught.value is error


def test_real_utf8_publication_and_overwrite(report, tmp_path):
    destination = tmp_path / "报告.json"
    result = report_io.write_workflow_report_json(report, destination)
    assert result == destination and result.is_absolute()
    assert destination.read_bytes() == serialize_workflow_report_json(report).encode("utf-8")
    assert "项目" in destination.read_text(encoding="utf-8")
    assert json.loads(destination.read_text(encoding="utf-8")) == workflow_report_to_obj(report)
    original = destination.read_bytes()
    with pytest.raises(FileExistsError):
        report_io.write_workflow_report_json(report, destination)
    assert destination.read_bytes() == original
    destination.write_bytes(b"ordinary old report")
    report_io.write_workflow_report_json(report, destination, overwrite=True)
    assert destination.read_bytes() == original
    assert list(tmp_path.iterdir()) == [destination]


def test_real_protected_destination_rejected(report, tmp_path):
    destination = tmp_path / "source.fastq"
    destination.write_bytes(b"protected content")
    with pytest.raises(ValueError, match="protected"):
        report_io.write_workflow_report_json(report, destination, protected_paths=(destination,), overwrite=True)
    assert destination.read_bytes() == b"protected content"
    assert list(tmp_path.iterdir()) == [destination]


def test_no_input_reads_network_or_domain_reexecution(report, tmp_path, monkeypatch):
    from fastq_sheet_audit import inventory, sheet, workflow, reporting
    protected = tmp_path / "input.fastq"
    protected.write_bytes(b"FASTQ unchanged")
    destination = tmp_path / "out.json"
    def fail(*args, **kwargs):
        pytest.fail("report publication read inputs, accessed network, or reran domain pipeline")
    with monkeypatch.context() as patch:
        for module, name in ((inventory, "scan_fastqs"), (sheet, "load_sheet"),
                             (workflow, "build_workflow_snapshot"), (reporting, "build_workflow_report")):
            patch.setattr(module, name, fail)
        for name in ("open", "read_text", "read_bytes"):
            patch.setattr(Path, name, fail)
        patch.setattr("socket.socket", fail)
        result = report_io.write_workflow_report_json(report, destination, protected_paths=(protected,))
    assert result == destination
    assert protected.read_bytes() == b"FASTQ unchanged"
    assert json.loads(destination.read_text(encoding="utf-8")) == workflow_report_to_obj(report)


def test_adapter_contains_no_legacy_presentation_or_direct_publication_logic():
    source = inspect.getsource(report_io)
    tree = ast.parse(source)
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imports == ["pathlib", "typing", "export_io", "report_serialization", "reporting"]
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert calls == ["serialize_workflow_report_json", "write_text_atomic"]
    assert not any(isinstance(node, (ast.Try, ast.With)) for node in ast.walk(tree))
