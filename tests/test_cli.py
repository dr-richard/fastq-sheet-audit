"""v0.2 CLI pipeline, terminal output, and report-publication boundary."""

import ast
import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from fastq_sheet_audit import __version__, cli
from fastq_sheet_audit.column_mapping import map_columns
from fastq_sheet_audit.inventory import scan_fastqs
from fastq_sheet_audit.presentation import present_workflow
from fastq_sheet_audit.report_serialization import workflow_report_to_obj
from fastq_sheet_audit.reporting import build_workflow_report
from fastq_sheet_audit.sheet import load_sheet
from fastq_sheet_audit.workflow import build_workflow_snapshot


def inputs(tmp_path, *, paired=True, sample="A"):
    root = tmp_path / "reads"
    root.mkdir()
    r1 = root / f"{sample}_R1.fastq"
    r1.write_bytes(b"never read FASTQ contents")
    r2 = root / f"{sample}_R2.fastq"
    if paired:
        r2.write_bytes(b"never read FASTQ contents")
    sheet = tmp_path / "sheet.csv"
    sheet.write_text(f"sample,r1,r2\n{sample},{r1.name},{r2.name if paired else ''}\n", encoding="utf-8")
    return sheet, root, r1, r2


def args(sheet, root, *options):
    return ["check", str(sheet), "--fastq-dir", str(root), *options]


def assert_error(capsys):
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert captured.err.startswith("fastq-sheet-audit: error:")
    return captured.err


def test_clean_paired_terminal_summary_is_deterministic(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    assert cli.main(args(sheet, root)) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert first.out == ("Inventory: 2 | Errors: 0 | Warnings: 0 | Unresolved pairs: 0 | "
                         "Read layout: paired | Ready for export: yes\n")
    assert cli.main(args(sheet, root)) == 0
    assert capsys.readouterr().out == first.out


def test_findings_render_existing_view_in_order(tmp_path, capsys):
    sheet, root, _, r2 = inputs(tmp_path)
    r2.unlink()
    assert cli.main(args(sheet, root)) == 1
    output = capsys.readouterr().out
    loaded = load_sheet(sheet)
    snapshot = build_workflow_snapshot(loaded, map_columns(loaded), scan_fastqs(root), root)
    view = present_workflow(snapshot)
    lines = output.splitlines()[1:]
    assert len(lines) == len(view.findings)
    for line, finding in zip(lines, view.findings):
        assert line.startswith(f"{finding.severity} {finding.source} {finding.code}:")
        assert finding.message in line
        if finding.row_number is not None:
            assert f"row={finding.row_number}" in line
        if finding.sample is not None:
            assert f"sample={finding.sample!r}" in line
        if finding.path is not None:
            assert f"path={finding.path!r}" in line


def test_automatic_ambiguity_remains_unresolved_and_preserves_candidates(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    alternate = root / "a_R1.fastq"
    alternate.write_bytes(b"alternate evidence")
    destination = tmp_path / "report.json"
    assert cli.main(args(sheet, root, "--json", str(destination))) == 1
    output = capsys.readouterr().out
    assert "Unresolved pairs: 1" in output and "Ready for export: no" in output
    assert "warning adjudication UNRESOLVED_PAIR" in output
    report = json.loads(destination.read_text())
    pair = report["pair_resolutions"][0]
    assert len(pair["group"]["r1"]) == len(pair["unresolved_r1"]) == 2
    assert pair["decision"]["r1"]["kind"] == "automatic"
    assert pair["effective_r1"] is None and pair["resolved"] is False


def test_warning_only_audit_exits_one(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    (root / "unrecognized.fastq").write_bytes(b"unknown filename")
    assert cli.main(args(sheet, root)) == 1
    output = capsys.readouterr().out
    assert "Errors: 0" in output and "Warnings: 1" in output
    assert "warning reconciliation" in output


def test_newline_in_error_path_still_produces_one_stderr_line(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    missing = tmp_path / "missing\nname.csv"
    assert cli.main(args(missing, root)) == 2
    assert_error(capsys)


@pytest.mark.parametrize("paired,mode,exit_code,layout,code", [
    (True, "auto", 0, "paired", None), (True, "paired", 0, "paired", None),
    (True, "single", 1, "single", "UNEXPECTED_R2"),
    (False, "single", 0, "single", None), (False, "auto", 0, "single", None),
    (False, "paired", 1, "paired", "MISSING_R2"),
])
def test_requested_read_modes_observable_behavior(tmp_path, capsys, paired, mode, exit_code, layout, code):
    sheet, root, _, _ = inputs(tmp_path, paired=paired)
    assert cli.main(args(sheet, root, "--read-mode", mode)) == exit_code
    output = capsys.readouterr().out
    assert f"Read layout: {layout}" in output
    if code:
        assert f"error read_mode {code}" in output


@pytest.mark.parametrize("text", ['sample,r1\nA,"unterminated', "sample,r1\nA,a,extra\n", "", "sample,sample,r1\n"])
def test_invalid_sheet_returns_two_without_report(tmp_path, capsys, text):
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text(text)
    destination = tmp_path / "report.json"
    assert cli.main(args(sheet, root, "--json", str(destination))) == 2
    assert_error(capsys)
    assert not destination.exists()


@pytest.mark.parametrize("which", ["missing_sheet", "directory_sheet", "missing_root", "file_root"])
def test_invalid_input_paths(tmp_path, capsys, which):
    sheet, root, r1, _ = inputs(tmp_path)
    if which == "missing_sheet":
        sheet = tmp_path / "absent.csv"
    elif which == "directory_sheet":
        sheet = root
    elif which == "missing_root":
        root = tmp_path / "absent"
    else:
        root = r1
    assert cli.main(args(sheet, root)) == 2
    assert_error(capsys)


@pytest.mark.parametrize("headers,message", [
    ("sample,sampleid,r1", "Explicit mapping is required"),
    ("sample,r1,read1", "Explicit mapping is required"),
    ("sample,r1,r2,read2", "Explicit mapping is required"),
    ("sample", "SAMPLE and R1"), ("r1", "SAMPLE and R1"),
])
def test_mapping_refused_before_scan(tmp_path, monkeypatch, capsys, headers, message):
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text(headers + "\n")
    scan = Mock(side_effect=AssertionError("mapping refusal must precede scan"))
    monkeypatch.setattr(cli, "scan_fastqs", scan)
    assert cli.main(args(sheet, root)) == 2
    assert message in assert_error(capsys)
    scan.assert_not_called()


@pytest.mark.parametrize("findings", [False, True])
def test_json_full_v2_schema_unicode_and_findings(tmp_path, findings):
    sheet, root, _, r2 = inputs(tmp_path, sample="项目α")
    if findings:
        r2.unlink()
    destination = tmp_path / "report.json"
    assert cli.main(args(sheet, root, "--json", str(destination))) == (1 if findings else 0)
    obj = json.loads(destination.read_text(encoding="utf-8"))
    loaded = load_sheet(sheet)
    expected = build_workflow_report(build_workflow_snapshot(loaded, map_columns(loaded), scan_fastqs(root), root))
    assert obj == workflow_report_to_obj(expected)
    assert obj["schema_version"] == 1
    assert "项目α" in destination.read_text(encoding="utf-8")


def test_report_overwrite_opt_in(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous report")
    assert cli.main(args(sheet, root, "--json", str(destination))) == 2
    assert_error(capsys)
    assert destination.read_bytes() == b"previous report"
    assert cli.main(args(sheet, root, "--json", str(destination), "--overwrite-report")) == 0
    assert json.loads(destination.read_text())["schema_version"] == 1


@pytest.mark.parametrize("kind", ["sheet", "discovered", "outside", "missing", "relative", "symlink", "hardlink"])
def test_report_input_protection(tmp_path, monkeypatch, capsys, kind):
    sheet, root, r1, r2 = inputs(tmp_path)
    destination = sheet if kind == "sheet" else r1
    if kind in ("outside", "missing"):
        destination = tmp_path / "A_R1.fastq"
        if kind == "outside":
            destination.write_bytes(b"external input")
        sheet.write_text(f"sample,r1,r2\nA,{destination},{r2}\n")
    elif kind == "relative":
        monkeypatch.chdir(tmp_path)
        destination = Path("sheet.csv")
    elif kind in ("symlink", "hardlink"):
        destination = tmp_path / "alias.json"
        try:
            if kind == "symlink":
                destination.symlink_to(sheet)
            else:
                destination.hardlink_to(r1)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"links unsupported: {error}")
    protected = (sheet, r1, r2) + ((destination,) if kind == "outside" else ())
    before = {path: path.read_bytes() for path in protected}
    assert cli.main(args(sheet, root, "--json", str(destination), "--overwrite-report")) == 2
    assert "protected" in assert_error(capsys)
    assert {path: path.read_bytes() for path in protected} == before
    if kind == "missing":
        assert not destination.exists()


def test_report_exclusively_delegated_with_all_protected_paths(tmp_path, monkeypatch):
    sheet, root, _, _ = inputs(tmp_path)
    original_build = cli.build_workflow_report
    captured = []
    def build(snapshot):
        report = original_build(snapshot)
        captured.append((snapshot, report))
        return report
    writer = Mock()
    monkeypatch.setattr(cli, "build_workflow_report", build)
    monkeypatch.setattr(cli, "write_workflow_report_json", writer)
    destination = Path(" exact report.json ")
    assert cli.main(args(sheet, root, "--json", str(destination))) == 0
    snapshot, report = captured[0]
    protected = (sheet, *(r.path for r in snapshot.inventory), *(a.path for a in snapshot.reconciliation.assignments))
    writer.assert_called_once_with(report, destination, protected_paths=protected, overwrite=False)
    assert writer.call_args.args[0] is report


@pytest.mark.parametrize("error", [OSError("disk failure"), PermissionError("permission denied")])
def test_expected_report_failures_are_concise(tmp_path, monkeypatch, capsys, error):
    sheet, root, _, _ = inputs(tmp_path)
    monkeypatch.setattr(cli, "write_workflow_report_json", Mock(side_effect=error))
    assert cli.main(args(sheet, root, "--json", str(tmp_path / "report.json"))) == 2
    assert_error(capsys)


@pytest.mark.parametrize("function", ["build_workflow_snapshot", "build_workflow_report", "write_workflow_report_json"])
def test_unexpected_programmer_errors_propagate(tmp_path, monkeypatch, function):
    sheet, root, _, _ = inputs(tmp_path)
    monkeypatch.setattr(cli, function, Mock(side_effect=RuntimeError("programmer bug")))
    with pytest.raises(RuntimeError, match="programmer bug"):
        cli.main(args(sheet, root, "--json", str(tmp_path / "report.json")))


def test_no_fastq_content_reads_or_network(tmp_path, monkeypatch):
    sheet, root, _, _ = inputs(tmp_path)
    destination = tmp_path / "report.json"
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        assert path == sheet, "FASTQ contents accessed"
        return original_open(path, *args, **kwargs)
    def fail(*args, **kwargs):
        pytest.fail("network or FASTQ content read")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded_open)
        patch.setattr(Path, "read_bytes", fail)
        patch.setattr(Path, "read_text", fail)
        patch.setattr("socket.socket", fail)
        assert cli.main(args(sheet, root, "--json", str(destination))) == 0
    assert json.loads(destination.read_text())["schema_version"] == 1


def test_parser_version_and_rejects_tsv(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"fastq-sheet-audit {__version__}\n"
    sheet, root, _, _ = inputs(tmp_path)
    with pytest.raises(SystemExit) as caught:
        cli.build_parser().parse_args(args(sheet, root, "--tsv", "out.tsv"))
    assert caught.value.code == 2


def test_cli_only_uses_v2_pipeline_and_publication_apis():
    tree = ast.parse(inspect.getsource(cli))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports <= {"__future__", "pathlib", None, "column_mapping", "inventory", "presentation",
                       "read_mode", "report_io", "reporting", "sheet", "workflow"}
    assert {node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)} == {"argparse", "csv", "sys"}
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert {"build_workflow_report", "write_workflow_report_json"} <= calls
    assert not calls.intersection({"open", "serialize_workflow_report_json", "write_text_atomic", "write_sheet_atomic"})
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not attributes.intersection({"dumps", "dump", "replace", "NamedTemporaryFile"})


@pytest.mark.parametrize("headers,cells,options", [
    ("sample,sampleid,r1,r2", "wrong,A,A_R1.fastq,A_R2.fastq", ["--sample-column", "2"]),
    ("sample,r1,read1,r2", "A,missing.fastq,A_R1.fastq,A_R2.fastq", ["--r1-column", "3"]),
    ("sample,r1,r2,read2", "A,A_R1.fastq,missing.fastq,A_R2.fastq", ["--r2-column", "4"]),
    ("specimen,forward,reverse", "A,A_R1.fastq,A_R2.fastq",
     ["--sample-column", "1", "--r1-column", "2", "--r2-column", "3"]),
    ("r1,r2,specimen", "A_R1.fastq,A_R2.fastq,A", ["--sample-column", "3"]),
])
def test_explicit_mapping_success_and_report_evidence(tmp_path, capsys, headers, cells, options):
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text(headers + "\n" + cells + "\n")
    destination = tmp_path / "mapped.json"
    assert cli.main(args(sheet, root, *options, "--json", str(destination))) == 0
    terminal = capsys.readouterr()
    assert terminal.err == ""
    assert terminal.out == ("Inventory: 2 | Errors: 0 | Warnings: 0 | Unresolved pairs: 0 | "
                            "Read layout: paired | Ready for export: yes\n")
    report = json.loads(destination.read_text())
    assert report["summary"]["ready_for_export"] is True
    assignments = report["reconciliation_assignments"]
    assert [(a["sample"], a["role"], a["cell_value"]) for a in assignments] == [
        ("A", "r1", "A_R1.fastq"), ("A", "r2", "A_R2.fastq")]


def test_ambiguous_optional_r2_explicitly_unmapped_retains_disk_evidence(tmp_path, capsys):
    sheet, root, _, r2 = inputs(tmp_path)
    sheet.write_text("sample,r1,r2,read2\nA,A_R1.fastq,A_R2.fastq,missing.fastq\n")
    destination = tmp_path / "report.json"
    assert cli.main(args(sheet, root, "--no-r2-column", "--json", str(destination))) == 1
    output = capsys.readouterr().out
    assert "warning reconciliation UNLISTED_FASTQ" in output
    report = json.loads(destination.read_text())
    assert [a["role"] for a in report["reconciliation_assignments"]] == ["r1"]
    assert report["reconciliation_findings"][0]["path"] == str(r2)
    assert report["summary"]["read_layout"] == "paired"


@pytest.mark.parametrize("flag", ["--sample-column", "--r1-column", "--r2-column"])
@pytest.mark.parametrize("number", ["0", "-1", "word", "1.5"])
def test_nonpositive_or_noninteger_numbers_are_parser_errors(tmp_path, capsys, flag, number):
    sheet, root, _, _ = inputs(tmp_path)
    with pytest.raises(SystemExit) as caught:
        cli.main(args(sheet, root, flag, number))
    assert caught.value.code == 2
    assert "positive 1-based integer" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--sample-column", "--r1-column", "--r2-column"])
def test_out_of_range_rejected_before_scan(tmp_path, capsys, monkeypatch, flag):
    sheet, root, _, _ = inputs(tmp_path)
    scan = Mock()
    monkeypatch.setattr(cli, "scan_fastqs", scan)
    assert cli.main(args(sheet, root, flag, "4")) == 2
    assert "invalid column index" in assert_error(capsys)
    scan.assert_not_called()


@pytest.mark.parametrize("options", [
    ["--sample-column", "2"],  # explicit SAMPLE conflicts with automatic R1
    ["--r1-column", "1"],
    ["--sample-column", "1", "--r1-column", "1"],
    ["--r1-column", "2", "--r2-column", "2"],
])
def test_physical_column_conflict_not_silently_adjusted(tmp_path, capsys, monkeypatch, options):
    sheet, root, _, _ = inputs(tmp_path)
    scan = Mock()
    monkeypatch.setattr(cli, "scan_fastqs", scan)
    assert cli.main(args(sheet, root, *options)) == 2
    assert "assigned to multiple roles" in assert_error(capsys)
    scan.assert_not_called()


def test_r2_flags_mutually_exclusive_at_parser_level(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    with pytest.raises(SystemExit) as caught:
        cli.main(args(sheet, root, "--r2-column", "3", "--no-r2-column"))
    assert caught.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_partial_override_remaining_ambiguity_lists_exact_candidates(tmp_path, capsys, monkeypatch):
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text(" sample ,sampleid,r1,read1,r2\n")
    scan = Mock()
    monkeypatch.setattr(cli, "scan_fastqs", scan)
    assert cli.main(args(sheet, root, "--r1-column", "3")) == 2
    assert assert_error(capsys) == (
        "fastq-sheet-audit: error: Ambiguous column mapping: SAMPLE. Explicit mapping is required. "
        "SAMPLE candidates: 1:' sample ', 2:'sampleid'\n")
    scan.assert_not_called()


def test_multiple_ambiguous_roles_all_listed(tmp_path, capsys):
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text("sample,sampleid,r1,read1,r2,read2\n")
    assert cli.main(args(sheet, root)) == 2
    error = assert_error(capsys)
    assert "SAMPLE candidates: 1:'sample', 2:'sampleid'" in error
    assert "R1 candidates: 3:'r1', 4:'read1'" in error
    assert "R2 candidates: 5:'r2', 6:'read2'" in error


@pytest.mark.parametrize("options,missing", [([], "SAMPLE, R1"), (["--sample-column", "1"], "R1")])
def test_incomplete_mapping_lists_missing_roles_and_all_exact_headers(tmp_path, capsys, monkeypatch, options, missing):
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text(" specimen ,forward,read-2\n")
    scan = Mock()
    monkeypatch.setattr(cli, "scan_fastqs", scan)
    assert cli.main(args(sheet, root, *options)) == 2
    assert assert_error(capsys) == (
        f"fastq-sheet-audit: error: Column mapping requires SAMPLE and R1 mappings. Missing required roles: {missing}. "
        "Available columns: 1:' specimen ', 2:'forward', 3:'read-2'\n")
    scan.assert_not_called()


def test_exact_one_based_translation_and_omitted_roles(tmp_path, monkeypatch):
    from fastq_sheet_audit.column_mapping import ColumnRole
    sheet, root, _, _ = inputs(tmp_path)
    sheet.write_text("identifier,r1,r2\nA,A_R1.fastq,A_R2.fastq\n")
    mapper = Mock(wraps=map_columns)
    monkeypatch.setattr(cli, "map_columns", mapper)
    assert cli.main(args(sheet, root, "--sample-column", "1", "--r2-column", "3")) == 0
    assert mapper.call_args.args[1] == {ColumnRole.SAMPLE: 0, ColumnRole.R2: 2}


def test_flag_help_describes_one_based_columns():
    parser = cli.build_parser()
    check = next(action for action in parser._actions if isinstance(action, cli.argparse._SubParsersAction)).choices["check"]
    for flag in ("--sample-column", "--r1-column", "--r2-column"):
        action = next(action for action in check._actions if flag in action.option_strings)
        assert "1-based" in action.help
    assert not {"--no-sample-column", "--no-r1-column"}.intersection(
        flag for action in check._actions for flag in action.option_strings)
