import csv
import json
from pathlib import Path

import pytest

from fastq_sheet_audit import cli, core
from fastq_sheet_audit.cli import main


def test_cli_clean(tmp_path: Path):
    fq = tmp_path / "fq"
    fq.mkdir()
    (fq / "S_R1.fastq.gz").write_bytes(b"")
    (fq / "S_R2.fastq.gz").write_bytes(b"")
    sheet = tmp_path / "s.tsv"
    sheet.write_text("sample\tr1\tr2\nS\tS_R1.fastq.gz\tS_R2.fastq.gz\n")
    assert main(["check", str(sheet), "--fastq-dir", str(fq)]) == 0


def test_cli_invalid_sheet(tmp_path: Path):
    fq = tmp_path / "fq"
    fq.mkdir()
    sheet = tmp_path / "bad.tsv"
    sheet.write_text("id\tfile\nA\ta.fastq.gz\n")
    assert main(["check", str(sheet), "--fastq-dir", str(fq)]) == 2


def test_cli_writes_json_and_tsv(tmp_path: Path):
    fq = tmp_path / "fq"
    fq.mkdir()
    (fq / "X_R1.fastq.gz").write_bytes(b"")
    sheet = tmp_path / "s.tsv"
    sheet.write_text("sample\tr1\tr2\nX\tX_R1.fastq.gz\tX_R2.fastq.gz\n")
    js = tmp_path / "report.json"
    ts = tmp_path / "report.tsv"
    assert main(["check", str(sheet), "--fastq-dir", str(fq), "--json", str(js), "--tsv", str(ts)]) == 1
    assert '"MISSING_FILE"' in js.read_text()
    assert "MISSING_FILE" in ts.read_text()


def make_inputs(tmp_path: Path):
    fq = tmp_path / "fq"
    fq.mkdir()
    r1 = fq / "S_R1.fastq.gz"
    r2 = fq / "S_R2.fastq.gz"
    r1.write_bytes(b"original R1 bytes")
    r2.write_bytes(b"original R2 bytes")
    sheet = tmp_path / "samples.tsv"
    sheet.write_text("sample\tr1\tr2\nS\tS_R1.fastq.gz\tS_R2.fastq.gz\n")
    return sheet, fq, r1, r2


@pytest.mark.parametrize("flag", ["--json", "--tsv"])
@pytest.mark.parametrize("destination", [
    "sheet", "fastq", "discovered", "referenced", "missing_reference",
    "same", "alias", "symlink", "hardlink", "report_symlink", "parent_symlink",
])
def test_report_collisions_write_nothing(tmp_path: Path, capsys, flag: str, destination: str):
    sheet, fq, r1, r2 = make_inputs(tmp_path)
    protected = [sheet, r1, r2]
    safe = tmp_path / "safe.report"
    safe.write_bytes(b"original report bytes")
    if destination == "sheet":
        target = sheet
    elif destination == "fastq":
        target = r1
    elif destination == "discovered":
        target = fq / "EXTRA_R1.fastq.gz"
        target.write_bytes(b"unlisted FASTQ bytes")
        protected.append(target)
    elif destination in ("referenced", "missing_reference"):
        target = tmp_path / "S_R1.fastq.gz"
        sheet.write_text(f"sample\tr1\tr2\nS\t{target}\t{r2}\n")
        if destination == "referenced":
            target.write_bytes(b"external FASTQ bytes")
            protected.append(target)
    elif destination == "same":
        target = safe
    elif destination == "alias":
        target = fq / ".." / sheet.name
    elif destination in ("symlink", "hardlink", "report_symlink"):
        target = tmp_path / "alias.report"
        source = safe if destination == "report_symlink" else sheet
        try:
            if destination == "hardlink":
                target.hardlink_to(source)
            else:
                target.symlink_to(source)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"filesystem aliases unavailable: {exc}")
    else:
        alias_dir = tmp_path / "alias-dir"
        try:
            alias_dir.symlink_to(fq, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
        target = alias_dir / r1.name
    before = {path: path.read_bytes() for path in protected + [safe]}
    other_flag = "--tsv" if flag == "--json" else "--json"
    assert main([
        "check", str(sheet), "--fastq-dir", str(fq),
        other_flag, str(safe), flag, str(target),
    ]) == 2
    assert {path: path.read_bytes() for path in before} == before
    if destination == "missing_reference":
        assert not target.exists()
    assert not list(tmp_path.rglob(".fastq-sheet-audit-*"))
    stderr = capsys.readouterr().err
    assert "fastq-sheet-audit: error:" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize("text,expected", [
    ("sample\tr1\t r1 \nS\tS_R1.fastq.gz\tother.fastq.gz\n", "duplicate headers"),
    ("sample\tr1\nS\tS_R1.fastq.gz\textra\n", "more fields"),
    ('sample,r1\nS,"S_R1.fastq.gz\n', "error:"),
    ('sample,r1\nS,"S_R1.fastq.gz"extra\n', "error:"),
])
def test_malformed_sheet_returns_usage_error(tmp_path: Path, capsys, text: str, expected: str):
    fq = tmp_path / "fq"
    fq.mkdir()
    sheet = tmp_path / ("bad.csv" if "," in text else "bad.tsv")
    sheet.write_text(text)
    report = tmp_path / "report.json"
    assert main(["check", str(sheet), "--fastq-dir", str(fq), "--json", str(report)]) == 2
    assert not report.exists()
    stderr = capsys.readouterr().err
    assert expected in stderr
    assert "Traceback" not in stderr


def test_parser_error_is_concise(tmp_path: Path, monkeypatch, capsys):
    sheet, fq, _, _ = make_inputs(tmp_path)

    def fail_reader(*args, **kwargs):
        raise csv.Error("parser failure")

    monkeypatch.setattr(core.csv, "DictReader", fail_reader)
    assert main(["check", str(sheet), "--fastq-dir", str(fq)]) == 2
    stderr = capsys.readouterr().err
    assert "parser failure" in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize("destination", ["missing_parent", "directory"])
def test_invalid_output_destination_writes_nothing(tmp_path: Path, capsys, destination: str):
    sheet, fq, r1, r2 = make_inputs(tmp_path)
    safe = tmp_path / "report.json"
    safe.write_bytes(b"existing report")
    target = tmp_path / "missing" / "report.tsv"
    if destination == "directory":
        target = tmp_path / "directory"
        target.mkdir()
    before = {p: p.read_bytes() for p in (sheet, r1, r2, safe)}
    assert main([
        "check", str(sheet), "--fastq-dir", str(fq),
        "--json", str(safe), "--tsv", str(target),
    ]) == 2
    assert {p: p.read_bytes() for p in before} == before
    assert not list(tmp_path.rglob(".fastq-sheet-audit-*"))
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("writer", ["write_json", "write_tsv"])
def test_serialization_failure_preserves_both_reports(tmp_path: Path, monkeypatch, capsys, writer: str):
    sheet, fq, r1, r2 = make_inputs(tmp_path)
    js = tmp_path / "report.json"
    ts = tmp_path / "report.tsv"
    js.write_bytes(b"old JSON")
    ts.write_bytes(b"old TSV")
    before = {p: p.read_bytes() for p in (sheet, r1, r2, js, ts)}

    def fail_write(payload, path):
        path.write_bytes(b"partially serialized report")
        raise OSError("report write denied")

    monkeypatch.setattr(cli, writer, fail_write)
    assert main([
        "check", str(sheet), "--fastq-dir", str(fq),
        "--json", str(js), "--tsv", str(ts),
    ]) == 2
    assert {p: p.read_bytes() for p in before} == before
    assert not list(tmp_path.rglob(".fastq-sheet-audit-*"))
    stderr = capsys.readouterr().err
    assert "report write denied" in stderr
    assert "Traceback" not in stderr


def test_reports_staged_in_destination_directories(tmp_path: Path, monkeypatch):
    sheet, fq, _, _ = make_inputs(tmp_path)
    json_dir = tmp_path / "json"
    tsv_dir = tmp_path / "tsv"
    json_dir.mkdir()
    tsv_dir.mkdir()
    js, ts = json_dir / "report.json", tsv_dir / "report.tsv"
    js.write_bytes(b"old JSON")
    ts.write_bytes(b"old TSV")
    original_json, original_tsv = cli.write_json, cli.write_tsv

    def staged_json(payload, path):
        assert path.parent == json_dir
        assert path != js
        assert js.read_bytes() == b"old JSON"
        original_json(payload, path)

    def staged_tsv(payload, path):
        assert path.parent == tsv_dir
        assert path != ts
        assert js.read_bytes() == b"old JSON"
        assert ts.read_bytes() == b"old TSV"
        original_tsv(payload, path)

    monkeypatch.setattr(cli, "write_json", staged_json)
    monkeypatch.setattr(cli, "write_tsv", staged_tsv)
    assert main([
        "check", str(sheet), "--fastq-dir", str(fq),
        "--json", str(js), "--tsv", str(ts),
    ]) == 0
    assert json.loads(js.read_text())["ok"] is True
    assert ts.read_text() == "severity\tcode\tsample\tpath\tmessage\n"
    assert not list(tmp_path.rglob(".fastq-sheet-audit-*"))


@pytest.mark.parametrize("operation", ["create", "replace"])
def test_filesystem_report_failure_is_concise(tmp_path: Path, monkeypatch, capsys, operation: str):
    sheet, fq, _, _ = make_inputs(tmp_path)
    report = tmp_path / "report.json"
    report.write_bytes(b"old report")

    def denied(*args, **kwargs):
        raise PermissionError("filesystem operation denied")

    if operation == "create":
        monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", denied)
    else:
        monkeypatch.setattr(Path, "replace", denied)
    assert main([
        "check", str(sheet), "--fastq-dir", str(fq), "--json", str(report),
    ]) == 2
    assert report.read_bytes() == b"old report"
    assert not list(tmp_path.rglob(".fastq-sheet-audit-*"))
    stderr = capsys.readouterr().err
    assert "filesystem operation denied" in stderr
    assert "Traceback" not in stderr
