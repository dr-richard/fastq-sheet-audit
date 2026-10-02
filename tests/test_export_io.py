import os
from pathlib import Path

import pytest

from fastq_sheet_audit import export_io
from fastq_sheet_audit.export_io import write_sheet_atomic
from fastq_sheet_audit.serialization import SheetFormat, serialize_sheet
from fastq_sheet_audit.sheet import SampleSheet, SheetRow


def candidate():
    return SampleSheet(("sample", "r1"), (SheetRow(2, (" α-A ", "run/001.fastq")),))


@pytest.mark.parametrize("format", list(SheetFormat))
def test_successful_exact_utf8_write(tmp_path, format):
    destination = tmp_path / ("output." + format.value)
    result = write_sheet_atomic(candidate(), destination, format)
    assert result == destination
    assert result.is_absolute()
    assert destination.read_bytes() == serialize_sheet(candidate(), format).encode("utf-8")
    assert list(tmp_path.iterdir()) == [destination]


def test_overwrite_false_rejects_existing_before_temp(tmp_path, monkeypatch):
    destination = tmp_path / "sheet.csv"
    destination.write_bytes(b"original")
    def fail(*args, **kwargs):
        pytest.fail("temporary file created during preflight")
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(FileExistsError):
        write_sheet_atomic(candidate(), destination, SheetFormat.CSV)
    assert destination.read_bytes() == b"original"


def test_overwrite_true_replaces_ordinary_output(tmp_path):
    destination = tmp_path / "sheet.csv"
    destination.write_bytes(b"old")
    write_sheet_atomic(candidate(), destination, SheetFormat.CSV, overwrite=True)
    assert destination.read_bytes() == serialize_sheet(candidate(), SheetFormat.CSV).encode()


def test_overwrite_true_rejects_nonprotected_symlink(tmp_path):
    target = tmp_path / "ordinary.csv"
    target.write_bytes(b"original target bytes\r\n")
    destination = tmp_path / "output.csv"
    try:
        destination.symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks unsupported: {error}")
    with pytest.raises(ValueError, match="ordinary file"):
        write_sheet_atomic(candidate(), destination, SheetFormat.CSV, overwrite=True)
    assert destination.is_symlink()
    assert target.read_bytes() == b"original target bytes\r\n"
    assert set(tmp_path.iterdir()) == {target, destination}


@pytest.mark.parametrize("exists", [False, True])
def test_exact_protected_destination_rejected(tmp_path, exists):
    destination = tmp_path / "input.fastq"
    if exists:
        destination.write_bytes(b"protected input")
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="protected"):
        write_sheet_atomic(candidate(), destination, SheetFormat.CSV,
                           protected_paths=[destination], overwrite=True)
    assert set(tmp_path.iterdir()) == before
    if exists:
        assert destination.read_bytes() == b"protected input"


def test_relative_absolute_protected_alias(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="protected"):
        write_sheet_atomic(candidate(), Path("input.fastq"), SheetFormat.CSV,
                           protected_paths=[tmp_path / "input.fastq"])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_link_alias_protects_unchanged_input(tmp_path, kind):
    protected = tmp_path / "input.fastq"
    protected.write_bytes(b"FASTQ protected bytes\r\n")
    destination = tmp_path / "output.csv"
    try:
        if kind == "symlink":
            destination.symlink_to(protected)
        else:
            destination.hardlink_to(protected)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"links unsupported: {error}")
    with pytest.raises(ValueError, match="protected"):
        write_sheet_atomic(candidate(), destination, SheetFormat.CSV,
                           protected_paths=[protected], overwrite=True)
    assert protected.read_bytes() == destination.read_bytes() == b"FASTQ protected bytes\r\n"
    assert len(list(tmp_path.iterdir())) == 2


def test_directory_and_missing_parent_rejected(tmp_path):
    with pytest.raises(IsADirectoryError):
        write_sheet_atomic(candidate(), tmp_path, SheetFormat.CSV)
    with pytest.raises(FileNotFoundError):
        write_sheet_atomic(candidate(), tmp_path / "missing/sheet.csv", SheetFormat.CSV)
    assert list(tmp_path.iterdir()) == []


def test_non_directory_parent_rejected(tmp_path):
    parent = tmp_path / "file"
    parent.touch()
    with pytest.raises(NotADirectoryError):
        write_sheet_atomic(candidate(), parent / "sheet.csv", SheetFormat.CSV)


def test_serialization_failure_creates_no_artifact(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("temporary file created before serialization")
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", fail)
    invalid = SampleSheet(("a", "b"), (SheetRow(2, ("a",)),))
    with pytest.raises(ValueError, match="cell count"):
        write_sheet_atomic(invalid, tmp_path / "output.csv", SheetFormat.CSV)
    assert list(tmp_path.iterdir()) == []


def test_write_failure_cleans_temp(tmp_path, monkeypatch):
    original = export_io.tempfile.NamedTemporaryFile
    def failing_file(*args, **kwargs):
        stream = original(*args, **kwargs)
        def fail_write(text):
            raise OSError("write failed")
        stream.write = fail_write
        return stream
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", failing_file)
    with pytest.raises(OSError, match="write failed"):
        write_sheet_atomic(candidate(), tmp_path / "output.csv", SheetFormat.CSV)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("overwrite", [False, True])
def test_replace_failure_cleans_temp_and_reservation(tmp_path, monkeypatch, overwrite):
    destination = tmp_path / "output.csv"
    if overwrite:
        destination.write_bytes(b"original")
    def fail(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(export_io.os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        write_sheet_atomic(candidate(), destination, SheetFormat.CSV, overwrite=overwrite)
    if overwrite:
        assert destination.read_bytes() == b"original"
        assert list(tmp_path.iterdir()) == [destination]
    else:
        assert list(tmp_path.iterdir()) == []


def test_fsync_failure_cleans_temp(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("fsync failed")
    monkeypatch.setattr(export_io.os, "fsync", fail)
    with pytest.raises(OSError, match="fsync failed"):
        write_sheet_atomic(candidate(), tmp_path / "output.csv", SheetFormat.CSV)
    assert list(tmp_path.iterdir()) == []


def test_no_overwrite_when_destination_appears_during_write(tmp_path, monkeypatch):
    destination = tmp_path / "output.csv"
    original = os.fsync
    def concurrent_create(descriptor):
        original(descriptor)
        destination.write_bytes(b"concurrent output")
    monkeypatch.setattr(export_io.os, "fsync", concurrent_create)
    with pytest.raises(FileExistsError):
        write_sheet_atomic(candidate(), destination, SheetFormat.CSV)
    assert destination.read_bytes() == b"concurrent output"
    assert list(tmp_path.iterdir()) == [destination]


def test_relative_destination_returns_absolute_and_preserves_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    destination = Path(" 输出 sheet.csv")
    returned = write_sheet_atomic(candidate(), destination, SheetFormat.CSV)
    assert returned == tmp_path / destination


def test_no_network_or_fastq_content_reads(tmp_path, monkeypatch):
    protected = tmp_path / "input.fastq"
    original_bytes = b"protected FASTQ content"
    protected.write_bytes(original_bytes)
    def fail(*args, **kwargs):
        pytest.fail("unexpected network access or input content read")
    with monkeypatch.context() as patch:
        patch.setattr("socket.socket", fail)
        patch.setattr(Path, "read_bytes", fail)
        patch.setattr(Path, "read_text", fail)
        patch.setattr(Path, "open", fail)
        write_sheet_atomic(candidate(), tmp_path / "output.csv", SheetFormat.CSV,
                           protected_paths=[protected])
    assert protected.read_bytes() == original_bytes
