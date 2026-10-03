from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastq_sheet_audit.adjudication import PairDecision, RoleDecision, RoleDecisionKind, resolve_pair_group
from fastq_sheet_audit.column_mapping import ColumnRole, map_columns
from fastq_sheet_audit.export_plan import build_export_plan
from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.pairing import group_pairs
from fastq_sheet_audit.pathmap import ExportMode, TargetStyle
from fastq_sheet_audit.profiles import load_profile
from fastq_sheet_audit.read_mode import ReadMode, diagnose_read_mode
from fastq_sheet_audit.reconciliation import Assignment, Finding, ReconciliationResult, Severity
from fastq_sheet_audit.sheet import SampleSheet, SheetRow
from fastq_sheet_audit.workflow import WorkflowSnapshot


AUTO = RoleDecision(RoleDecisionKind.AUTOMATIC, None)
UNASSIGN = RoleDecision(RoleDecisionKind.UNASSIGN, None)


def record(name):
    relative = Path(name)
    return InventoryRecord(Path.cwd() / "scan" / relative, relative, parse_fastq_name(relative.name), InventoryCategory.READ)


def evidence(single=False, mixed=False, selected=False, unassign=False):
    r1, r2 = record("run/A_S1_R1.fastq"), record("run/A_S1_R2.fastq")
    inventory = [r1] if single else [r1, r2]
    if selected:
        inventory += [record("run/A_S01_R1.fastq"), record("run/A_S01_R2.fastq")]
    rows = [SheetRow(8, (" A ", r1.relative_path.as_posix(), "" if single else r2.relative_path.as_posix()))]
    assignments = [Assignment(8, " A ", ColumnRole.R1, rows[0].cells[1], r1.path, r1)]
    if mixed:
        b = record("B_R1.fastq")
        inventory.append(b)
        rows.append(SheetRow(3, ("B", "B_R1.fastq", "")))
        assignments.append(Assignment(3, "B", ColumnRole.R1, "B_R1.fastq", b.path, b))
    sheet = SampleSheet(("sample", "r1", "r2"), tuple(rows))
    resolutions = []
    for group in group_pairs(inventory):
        if selected and group.key.sample == "a":
            decision = PairDecision(group.key, RoleDecision(RoleDecisionKind.SELECT, inventory[2]),
                                    RoleDecision(RoleDecisionKind.SELECT, inventory[3]), False)
        else:
            decision = PairDecision(group.key, AUTO, UNASSIGN if unassign else AUTO, False)
        resolutions.append(resolve_pair_group(group, decision))
    effective = [item for resolution in resolutions for item in (resolution.effective_r1, resolution.effective_r2) if item]
    # SINGLE accepts mixed complete/R1-only groups without inventing a mode:
    # for the mixed export test use an explicit diagnostic-free result as loaded evidence.
    mode = diagnose_read_mode(effective)
    if mixed:
        mode = replace(mode, diagnostics=())
    snapshot = WorkflowSnapshot(tuple(inventory), ReconciliationResult(tuple(inventory), tuple(assignments), ()),
                                mode, (), tuple(resolutions))
    return sheet, map_columns(sheet), snapshot


def plan(args, profile="generic", mode=ExportMode.RELATIVE_TO_ROOT, **kwargs):
    return build_export_plan(*args, load_profile(profile), mode, **kwargs)


def test_generic_paired_and_exact_sample_text():
    result = plan(evidence())
    assert result.result.sheet.headers == ("sample", "r1", "r2")
    assert result.result.sheet.rows[0].cells == (" A ", str(Path("run/A_S1_R1.fastq")), str(Path("run/A_S1_R2.fastq")))
    assert result.result.validation.ok


@pytest.mark.parametrize("mode, options, expected", [
    (ExportMode.LOCAL_ABSOLUTE, {}, str(record("run/A_S1_R1.fastq").path)),
    (ExportMode.RELATIVE_TO_ROOT, {}, str(Path("run/A_S1_R1.fastq"))),
    (ExportMode.REBASED_ROOT, {"target_root": "/data/项目", "target_style": TargetStyle.POSIX}, "/data/项目/run/A_S1_R1.fastq"),
    (ExportMode.REBASED_ROOT, {"target_root": "D:\\项目", "target_style": TargetStyle.WINDOWS}, "D:\\项目\\run\\A_S1_R1.fastq"),
])
def test_rendered_path_modes(mode, options, expected):
    result = plan(evidence(), mode=mode, **options)
    assert result.rows[0].values["r1"] == expected
    assert result.rows[0].values["sample"] == " A "


def test_selected_reads_exported_instead_of_original_reconciliation_cells():
    args = evidence(selected=True)
    result = plan(args)
    assert result.rows[0].values["r1"] == str(Path("run/A_S01_R1.fastq"))
    assert result.rows[0].values["r2"] == str(Path("run/A_S01_R2.fastq"))
    assert result.rows[0].values["r1"] != args[0].rows[0].cells[1]
    assert result.rows[0].values["r2"] != args[0].rows[0].cells[2]


@pytest.mark.parametrize("args", [evidence(single=True), evidence(unassign=True)])
def test_no_effective_r2_omits_optional_header(args):
    result = plan(args)
    assert result.result.sheet.headers == ("sample", "r1")
    assert "r2" not in result.rows[0].values


def test_mixed_rows_keep_header_order_and_original_row_numbers():
    result = plan(evidence(mixed=True))
    assert result.result.sheet.headers == ("sample", "r1", "r2")
    assert [row.row_number for row in result.result.sheet.rows] == [8, 3]
    assert result.result.sheet.rows[1].cells == ("B", "B_R1.fastq", "")


def test_required_r2_header_and_missing_manual_strandedness():
    result = plan(evidence(single=True), "nfcore-rnaseq-3.27.0")
    assert result.result.sheet.headers == ("sample", "fastq_1", "fastq_2", "strandedness")
    assert result.result.sheet.rows[0].cells[2:] == ("", "")
    finding, = result.result.validation.findings
    assert (finding.code, finding.column) == ("EMPTY_REQUIRED_VALUE", "strandedness")


@pytest.mark.parametrize("value, ok", [("reverse", True), ("Reverse", False)])
def test_explicit_strandedness_is_validated(value, ok):
    result = plan(evidence(), "nfcore-rnaseq-3.27.0", explicit_values={8: {"strandedness": value}})
    assert result.result.validation.ok is ok
    if not ok:
        assert result.result.validation.findings[0].code == "VALUE_NOT_ALLOWED"


def test_defaults_not_applied_and_roles_not_inferred_from_names():
    profile = load_profile("nfcore-rnaseq-3.27.0")
    profile = replace(profile, columns=tuple(replace(column, name="unusual_" + str(i),
                                                   default_value="auto" if column.source_role is None else None)
                                            for i, column in enumerate(profile.columns)))
    result = build_export_plan(*evidence(), profile, ExportMode.RELATIVE_TO_ROOT)
    assert result.rows[0].values == {"unusual_0": " A ", "unusual_1": str(Path("run/A_S1_R1.fastq")),
                                    "unusual_2": str(Path("run/A_S1_R2.fastq"))}
    assert result.result.sheet.rows[0].cells[-1] == ""
    assert result.result.validation.findings[0].column == "unusual_3"


@pytest.mark.parametrize("manual", [{99: {"genome": "x"}}, {True: {"genome": "x"}},
    {"8": {"genome": "x"}}, {8: {"unknown": "x"}}, {8: {"sample": "x"}},
    {8: {"fastq_1": "x"}}, {8: {"fastq_2": "x"}}, {8: {"genome": 1}}])
def test_invalid_manual_values_rejected(manual):
    with pytest.raises(ValueError):
        plan(evidence(), "nfcore-methylseq-4.2.0", explicit_values=manual)


def test_manual_text_and_caller_inputs_remain_exact_and_immutable():
    args = evidence()
    manual = {8: {"genome": " 001 α =+@- "}}
    result = plan(args, "nfcore-methylseq-4.2.0", explicit_values=manual)
    assert result.result.sheet.rows[0].cells[-1] == " 001 α =+@- "
    assert manual == {8: {"genome": " 001 α =+@- "}}
    manual[8]["genome"] = "changed"
    assert result.rows[0].values["genome"] == " 001 α =+@- "
    with pytest.raises(FrozenInstanceError):
        result.rows = ()


def test_barcode_and_nonready_workflows_rejected():
    args = evidence()
    with pytest.raises(ValueError, match="barcode_mapping"):
        plan(args, "nfcore-viralrecon-3.0.0-nanopore")
    snapshot = replace(args[2], reconciliation=replace(args[2].reconciliation, findings=(
        Finding("WARNING", Severity.WARNING, "keep evidence"),)))
    with pytest.raises(ValueError, match="^workflow is not ready for export$"):
        plan((args[0], args[1], snapshot))


@pytest.mark.parametrize("issue", ["missing_assignment", "duplicate_assignment", "missing_resolution", "wrong_cell", "wrong_header", "incomplete_mapping"])
def test_inconsistent_internal_state_rejected(issue):
    sheet, mapping, snapshot = evidence()
    rec = snapshot.reconciliation
    if issue == "missing_assignment":
        snapshot = replace(snapshot, reconciliation=replace(rec, assignments=()))
    elif issue == "duplicate_assignment":
        snapshot = replace(snapshot, reconciliation=replace(rec, assignments=rec.assignments * 2))
    elif issue == "missing_resolution":
        snapshot = replace(snapshot, pair_resolutions=())
    elif issue == "wrong_cell":
        snapshot = replace(snapshot, reconciliation=replace(rec, assignments=(replace(rec.assignments[0], cell_value="wrong"),)))
    elif issue == "wrong_header":
        sheet = replace(sheet, headers=("SAMPLE", "r1", "r2"))
    else:
        mapping = map_columns(sheet, {ColumnRole.R1: None})
    with pytest.raises(ValueError):
        plan((sheet, mapping, snapshot))


def test_no_external_access_and_inputs_unchanged(monkeypatch):
    args = evidence(selected=True)
    profile = load_profile("generic")
    def fail(*args, **kwargs):
        pytest.fail("planner accessed external state")
    for method in ("open", "stat", "resolve", "exists", "read_bytes", "write_bytes", "write_text"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    result = build_export_plan(*args, profile, ExportMode.RELATIVE_TO_ROOT)
    assert build_export_plan(*args, profile, ExportMode.RELATIVE_TO_ROOT) == result
    assert args[2].inventory[0].relative_path.as_posix() == "run/A_S1_R1.fastq"
    assert args[0].rows[0].cells[0] == " A "
