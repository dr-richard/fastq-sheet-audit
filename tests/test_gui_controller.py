from pathlib import Path

import pytest

from fastq_sheet_audit import gui_controller as controller
from fastq_sheet_audit.column_mapping import map_columns
from fastq_sheet_audit.inventory import scan_fastqs
from fastq_sheet_audit.presentation import present_workflow
from fastq_sheet_audit.read_mode import ReadMode
from fastq_sheet_audit.sheet import load_sheet
from fastq_sheet_audit.workflow import build_workflow_snapshot


def inputs(tmp_path, paired=True):
    root = tmp_path / "fastqs"
    root.mkdir()
    (root / "A_R1.fastq").write_bytes(b"not read")
    if paired:
        (root / "A_R2.fastq").write_bytes(b"not read")
    sheet = tmp_path / "sheet.csv"
    sheet.write_text("sample,r1,r2\nA,A_R1.fastq," + ("A_R2.fastq" if paired else "") + "\n")
    return root, sheet


@pytest.mark.parametrize("paired, label", [(True, "Paired"), (False, "Single"), (True, "Auto")])
def test_audit_matches_existing_workflow_presentation(tmp_path, paired, label):
    root, path = inputs(tmp_path, paired)
    sheet = load_sheet(path)
    expected = present_workflow(build_workflow_snapshot(
        sheet, map_columns(sheet), scan_fastqs(root), root, read_mode=controller.read_mode_from_label(label),
    ))
    view = controller.audit_inputs(str(root), str(path), label)
    assert view == expected
    assert view.summary.ready_for_export


@pytest.mark.parametrize("label, mode", [("Auto", ReadMode.AUTO), ("Paired", ReadMode.PAIRED), ("Single", ReadMode.SINGLE)])
def test_mode_mapping(label, mode):
    assert controller.read_mode_from_label(label) is mode


@pytest.mark.parametrize("which", ["empty_root", "empty_sheet", "missing_root", "missing_sheet", "malformed"])
def test_input_errors(tmp_path, which):
    root, sheet = inputs(tmp_path)
    if which == "malformed":
        sheet.write_text('sample,r1\nA,"unterminated')
    directory = "" if which == "empty_root" else str(root / "missing") if which == "missing_root" else str(root)
    source = "" if which == "empty_sheet" else str(sheet.parent / "missing.csv") if which == "missing_sheet" else str(sheet)
    with pytest.raises(ValueError):
        controller.audit_inputs(directory, source, "Auto")


@pytest.mark.parametrize("headers", ["sample,sample_id,r1", "sample,r1,read1", "sample", "r1", "sample,r1,r2,read2"])
def test_mapping_refuses_before_scan_and_reconciliation(tmp_path, monkeypatch, headers):
    root, path = inputs(tmp_path)
    path.write_text(headers + "\n")
    def fail(*args, **kwargs):
        pytest.fail("audit continued past unresolved mapping")
    monkeypatch.setattr(controller, "scan_fastqs", fail)
    monkeypatch.setattr(controller, "build_workflow_snapshot", fail)
    with pytest.raises(ValueError, match="mapping"):
        controller.audit_inputs(str(root), str(path), "Auto")


def test_no_network_writes_or_fastq_reads(tmp_path, monkeypatch):
    root, path = inputs(tmp_path)
    before = {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    original_open = Path.open
    def guarded_open(self, mode="r", *args, **kwargs):
        assert self == path, "FASTQ contents were accessed"
        assert mode == "r", "file write attempted"
        return original_open(self, mode, *args, **kwargs)
    def fail(*args, **kwargs):
        pytest.fail("network or user-file write attempted")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded_open)
        for method in ("write_bytes", "write_text", "rename", "unlink", "mkdir"):
            patch.setattr(Path, method, fail)
        patch.setattr("socket.socket", fail)
        assert controller.audit_inputs(str(root), str(path), "Auto").summary.ready_for_export
    assert {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()} == before


def test_unexpected_controller_errors_are_not_swallowed(tmp_path, monkeypatch):
    root, path = inputs(tmp_path)
    def fail(*args):
        raise RuntimeError("programmer error")
    monkeypatch.setattr(controller, "load_sheet", fail)
    with pytest.raises(RuntimeError, match="programmer error"):
        controller.audit_inputs(str(root), str(path), "Auto")
