"""Direct safety coverage for the reusable protected UTF-8 text writer."""

import os
from pathlib import Path

import pytest

from fastq_sheet_audit import export_io
from fastq_sheet_audit.export_io import write_text_atomic


@pytest.mark.parametrize("text", ["", " 项目 α \r\n=SUM(A1)\n", "no final newline", "one\n", "two\n\n"])
def test_exact_utf8_text_and_newlines(tmp_path, text):
    destination = tmp_path / " 输出.txt"
    returned = write_text_atomic(text, destination)
    assert returned == destination and returned.is_absolute()
    assert destination.read_bytes() == text.encode("utf-8")
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("text", [None, b"bytes", 7, True, [], Path("text")])
def test_non_string_rejected_before_temp(tmp_path, monkeypatch, text):
    def fail(*args, **kwargs):
        pytest.fail("temporary file created for invalid text")
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(TypeError, match="^text must be a string$"):
        write_text_atomic(text, tmp_path / "out.txt")
    assert list(tmp_path.iterdir()) == []


def test_invalid_utf8_and_existing_destination_preflight(tmp_path, monkeypatch):
    destination = tmp_path / "out.txt"
    def fail(*args, **kwargs):
        pytest.fail("preflight created a temporary file")
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(UnicodeEncodeError):
        write_text_atomic("\ud800", destination)
    assert list(tmp_path.iterdir()) == []
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        write_text_atomic("replacement", destination)
    assert destination.read_bytes() == b"original"


def test_ordinary_overwrite(tmp_path):
    destination = tmp_path / "out.txt"
    destination.write_bytes(b"old")
    write_text_atomic("new α", destination, overwrite=True)
    assert destination.read_bytes() == "new α".encode()


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_nonordinary_overwrite_refused_before_temp(tmp_path, monkeypatch, kind):
    destination = tmp_path / "out.txt"
    target = tmp_path / "target.txt"
    target.write_bytes(b"original")
    try:
        if kind == "symlink":
            destination.symlink_to(target)
        else:
            if not hasattr(os, "mkfifo"):
                pytest.skip("FIFO unsupported")
            os.mkfifo(destination)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"special object unsupported: {error}")
    def fail(*args, **kwargs):
        pytest.fail("temporary created for nonordinary destination")
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", fail)
    with pytest.raises(ValueError, match="ordinary file"):
        write_text_atomic("new", destination, overwrite=True)
    assert target.read_bytes() == b"original"
    assert set(tmp_path.iterdir()) == {target, destination}


@pytest.mark.parametrize("kind", ["same", "nonexistent", "relative", "symlink", "hardlink"])
def test_protected_paths_and_link_aliases(tmp_path, monkeypatch, kind):
    protected = tmp_path / "input.fastq"
    destination = protected
    if kind != "nonexistent":
        protected.write_bytes(b"original FASTQ")
    if kind == "relative":
        monkeypatch.chdir(tmp_path)
        destination = Path("input.fastq")
    elif kind in ("symlink", "hardlink"):
        destination = tmp_path / "out.txt"
        try:
            if kind == "symlink":
                destination.symlink_to(protected)
            else:
                destination.hardlink_to(protected)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"links unsupported: {error}")
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="protected"):
        write_text_atomic("new", destination, protected_paths=(protected,), overwrite=True)
    assert set(tmp_path.iterdir()) == before
    if kind != "nonexistent":
        assert protected.read_bytes() == b"original FASTQ"


def test_parent_and_directory_rejection(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_text_atomic("text", tmp_path / "missing/out.txt")
    with pytest.raises(IsADirectoryError):
        write_text_atomic("text", tmp_path)
    parent = tmp_path / "file"
    parent.touch()
    with pytest.raises(NotADirectoryError):
        write_text_atomic("text", parent / "out.txt")
    assert list(tmp_path.iterdir()) == [parent]


@pytest.mark.parametrize("failure", ["write", "flush", "fsync", "replace"])
@pytest.mark.parametrize("overwrite", [False, True])
def test_failures_clean_temp_and_own_reservation(tmp_path, monkeypatch, failure, overwrite):
    destination = tmp_path / "out.txt"
    if overwrite:
        destination.write_bytes(b"original")
    original_temp = export_io.tempfile.NamedTemporaryFile
    def fail(*args, **kwargs):
        raise OSError(f"{failure} failed")
    def temporary(*args, **kwargs):
        assert kwargs["dir"] == destination.parent
        assert kwargs["encoding"] == "utf-8" and kwargs["newline"] == ""
        stream = original_temp(*args, **kwargs)
        if failure in ("write", "flush"):
            setattr(stream, failure, fail)
        return stream
    monkeypatch.setattr(export_io.tempfile, "NamedTemporaryFile", temporary)
    if failure in ("fsync", "replace"):
        monkeypatch.setattr(export_io.os, failure, fail)
    with pytest.raises(OSError, match=f"{failure} failed"):
        write_text_atomic("text", destination, overwrite=overwrite)
    assert list(tmp_path.iterdir()) == ([destination] if overwrite else [])
    if overwrite:
        assert destination.read_bytes() == b"original"


def test_concurrent_destination_preserved(tmp_path, monkeypatch):
    destination = tmp_path / "out.txt"
    original_fsync = export_io.os.fsync
    def concurrent(descriptor):
        original_fsync(descriptor)
        destination.write_bytes(b"concurrent output")
    monkeypatch.setattr(export_io.os, "fsync", concurrent)
    with pytest.raises(FileExistsError):
        write_text_atomic("new", destination)
    assert destination.read_bytes() == b"concurrent output"
    assert list(tmp_path.iterdir()) == [destination]


def test_replace_failure_does_not_remove_replaced_reservation(tmp_path, monkeypatch):
    destination = tmp_path / "out.txt"
    other = tmp_path / "other.txt"
    other.write_bytes(b"concurrent file")
    original_replace = export_io.os.replace
    def concurrent_replace(source, target):
        original_replace(other, target)
        raise OSError("replace failed after reservation was replaced")
    monkeypatch.setattr(export_io.os, "replace", concurrent_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_text_atomic("new", destination)
    assert destination.read_bytes() == b"concurrent file"
    assert list(tmp_path.iterdir()) == [destination]


def test_protected_paths_rechecked_before_publication(tmp_path, monkeypatch):
    destination = tmp_path / "out.txt"
    protected = tmp_path / "input.fastq"
    protected.write_bytes(b"protected")
    original_fsync = export_io.os.fsync
    def link_after_write(descriptor):
        original_fsync(descriptor)
        destination.hardlink_to(protected)
    monkeypatch.setattr(export_io.os, "fsync", link_after_write)
    with pytest.raises(ValueError, match="protected"):
        write_text_atomic("new", destination, protected_paths=(protected,))
    assert protected.read_bytes() == destination.read_bytes() == b"protected"
    assert set(tmp_path.iterdir()) == {protected, destination}


def test_relative_destination_and_no_network_or_protected_reads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    protected = tmp_path / "input.fastq"
    protected.write_bytes(b"FASTQ contents")
    def fail(*args, **kwargs):
        pytest.fail("network access or protected content read")
    with monkeypatch.context() as patch:
        patch.setattr("socket.socket", fail)
        for name in ("open", "read_text", "read_bytes"):
            patch.setattr(Path, name, fail)
        result = write_text_atomic("exact", Path(" 输出.txt"), protected_paths=(protected,))
    assert result == tmp_path / " 输出.txt"
    assert result.read_bytes() == b"exact"
    assert protected.read_bytes() == b"FASTQ contents"


def test_sheet_adapter_serializes_first_and_delegates_exactly(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from fastq_sheet_audit.serialization import SheetFormat
    from fastq_sheet_audit.sheet import SampleSheet
    sheet = SampleSheet(("sample",), ())
    events = []
    def serialize(candidate, format):
        assert candidate is sheet and format is SheetFormat.CSV
        events.append("serialize")
        return "exact α\r\n"
    def write(*args, **kwargs):
        assert events == ["serialize"]
        return tmp_path / "writer-returned.txt"
    writer = Mock(side_effect=write)
    monkeypatch.setattr(export_io, "serialize_sheet", serialize)
    monkeypatch.setattr(export_io, "write_text_atomic", writer)
    protected = (tmp_path / "input.fastq",)
    destination = tmp_path / "out.txt"
    result = export_io.write_sheet_atomic(sheet, destination, SheetFormat.CSV,
                                         protected_paths=protected, overwrite=True)
    writer.assert_called_once_with("exact α\r\n", destination, protected_paths=protected, overwrite=True)
    assert result == tmp_path / "writer-returned.txt"
