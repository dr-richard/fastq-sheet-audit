from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fastq_sheet_audit.column_mapping import map_columns
from fastq_sheet_audit.inventory import scan_fastqs
from fastq_sheet_audit.reconciliation import Severity, reconcile
from fastq_sheet_audit.sheet import SampleSheet, SheetRow


def setup_case(root, files, rows, headers=("sample", "r1", "r2")):
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"contents are irrelevant")
    sheet = SampleSheet(headers, tuple(SheetRow(i, tuple(row)) for i, row in enumerate(rows, 2)))
    mapping = map_columns(sheet, require_complete=True)
    inventory = scan_fastqs(root)
    return sheet, mapping, inventory


def codes(result):
    return [finding.code for finding in result.findings]


def test_clean_pair(tmp_path):
    files = ["A_S1_L001_R1_001.fastq.gz", "a_S1_L001_R2_001.FASTQ.GZ"]
    sheet, mapping, inventory = setup_case(tmp_path, files, [(" A ", *files)])
    result = reconcile(sheet, mapping, inventory, tmp_path)
    assert result.ok
    assert result.findings == ()
    assert len(result.assignments) == 2
    assert result.assignments[0].sample == " A "
    assert result.inventory == tuple(inventory)


def test_repeated_sample_with_distinct_lane_pairs_is_clean(tmp_path):
    lane1 = ("A_S1_L001_R1_001.fastq.gz", "A_S1_L001_R2_001.fastq.gz")
    lane2 = ("A_S1_L002_R1_001.fastq.gz", "A_S1_L002_R2_001.fastq.gz")
    sheet, mapping, inventory = setup_case(
        tmp_path, (*lane1, *lane2), [("A", *lane1), ("A", *lane2)],
    )
    result = reconcile(sheet, mapping, inventory, tmp_path)
    assert result.ok
    assert result.findings == ()
    assert len(result.assignments) == 4
    assert {assignment.sample for assignment in result.assignments} == {"A"}
    assert {assignment.row_number for assignment in result.assignments} == {2, 3}
    assert len({assignment.path for assignment in result.assignments}) == 4
    assert {assignment.record.parsed_name.lane for assignment in result.assignments} == {1, 2}


def test_missing_listed_file(tmp_path):
    sheet, mapping, inventory = setup_case(tmp_path, [], [("A", "A_R1.fastq", "")])
    result = reconcile(sheet, mapping, inventory, tmp_path)
    finding, = result.findings
    assert finding.code == "MISSING_FILE"
    assert finding.severity is Severity.ERROR
    assert not result.ok
    assert finding.row_number == 2
    assert finding.sample == "A"
    assert finding.path == tmp_path / "A_R1.fastq"


def test_duplicate_assignment(tmp_path):
    args = setup_case(tmp_path, ["A_R1.fastq"], [
        ("A", "A_R1.fastq", ""), ("A", "A_R1.fastq", ""),
    ])
    result = reconcile(*args, tmp_path)
    finding, = result.findings
    assert finding.code == "FASTQ_REUSED"
    assert finding.row_number == 3
    assert "row 2" in finding.message
    assert len(result.assignments) == 2


def test_unlisted_unknown_index_and_undetermined_remain_visible(tmp_path):
    files = ["A_R1.fastq", "unknown.fq", "A_I1.fastq", "Undetermined_R1.fastq"]
    args = setup_case(tmp_path, files, [("A", "A_R1.fastq", "")])
    result = reconcile(*args, tmp_path)
    assert len(result.inventory) == 4
    assert codes(result) == ["UNLISTED_FASTQ"] * 3
    assert {finding.path.name for finding in result.findings} == set(files[1:])


@pytest.mark.parametrize("sample, filename", [("B", "A_R1.fastq"), ("AB", "A-B_R1.fastq")])
def test_conservative_sample_mismatch(tmp_path, sample, filename):
    args = setup_case(tmp_path, [filename], [(sample, filename, "")])
    result = reconcile(*args, tmp_path)
    assert codes(result) == ["SAMPLE_NAME_MISMATCH"]
    assert result.findings[0].sample == sample
    assert result.findings[0].severity is Severity.WARNING
    assert not result.ok


def test_unicode_casefold_sample_match(tmp_path):
    args = setup_case(tmp_path, ["Straße_R1.fastq"], [(" STRASSE ", "Straße_R1.fastq", "")])
    assert reconcile(*args, tmp_path).findings == ()


def test_read_role_disagreement(tmp_path):
    args = setup_case(tmp_path, ["A_R1.fastq", "A_R2.fastq"],
                      [("A", "A_R2.fastq", "A_R1.fastq")])
    result = reconcile(*args, tmp_path)
    assert codes(result) == ["READ_ROLE_MISMATCH"] * 2
    assert {finding.role.value for finding in result.findings} == {"r1", "r2"}


@pytest.mark.parametrize("r1, r2", [
    ("A_S1_L001_R1_001.fastq.gz", "A_S1_L002_R2_001.fastq.gz"),
    ("A_L001_R1_001.fastq.gz", "A_L001_R2_002.fastq.gz"),
    ("A_S1_R1.fastq", "A_S2_R2.fastq"),
    ("A_R1.fastq", "A_2.fastq"),
    ("one/A_R1.fastq", "two/A_R2.fastq"),
])
def test_structural_mismatch(tmp_path, r1, r2):
    args = setup_case(tmp_path, [r1, r2], [("A", r1, r2)])
    result = reconcile(*args, tmp_path)
    assert codes(result) == ["PAIR_NAME_MISMATCH"]
    assert result.findings[0].path == tmp_path / r1
    assert result.findings[0].related_path == tmp_path / r2


@pytest.mark.parametrize("name", ["A_I1.fastq", "A_I2.fastq", "Undetermined_R1.fastq"])
def test_non_biological_assignment_is_explicitly_rejected(tmp_path, name):
    args = setup_case(tmp_path, [name], [("A", name, "")])
    result = reconcile(*args, tmp_path)
    assert codes(result) == ["NON_BIOLOGICAL_FASTQ"]
    assert not result.ok
    assert len(result.inventory) == len(result.assignments) == 1


def test_unknown_listed_filename_is_not_inferred(tmp_path):
    args = setup_case(tmp_path, ["unknown.fq"], [("A", "unknown.fq", "")])
    result = reconcile(*args, tmp_path)
    assert result.findings == ()
    assert result.assignments[0].record.parsed_name is None


def test_optional_r2_does_not_infer_mate(tmp_path):
    args = setup_case(tmp_path, ["A_R1.fastq", "A_R2.fastq"],
                      [("A", "A_R1.fastq")], headers=("sample", "r1"))
    result = reconcile(*args, tmp_path)
    assert codes(result) == ["UNLISTED_FASTQ"]
    assert len(result.assignments) == 1


def test_absolute_reference_outside_root(tmp_path):
    root = tmp_path / "scan"
    root.mkdir()
    external = tmp_path / "A_R1.fastq"
    external.touch()
    args = setup_case(root, [], [("A", str(external), "")])
    result = reconcile(*args, root)
    assert result.findings == ()
    assert result.assignments[0].path == external


@pytest.mark.parametrize("link_type", ["symlink", "hardlink"])
def test_filesystem_aliases_detect_reuse(tmp_path, link_type):
    target = tmp_path / "A_R1.fastq"
    target.touch()
    alias = tmp_path / "alias.fastq"
    try:
        if link_type == "symlink":
            alias.symlink_to(target)
        else:
            alias.hardlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"links unavailable: {error}")
    sheet = SampleSheet(("sample", "r1"), (
        SheetRow(2, ("A", "A_R1.fastq")), SheetRow(3, ("A", "alias.fastq")),
    ))
    inventory = scan_fastqs(tmp_path)
    result = reconcile(sheet, map_columns(sheet), inventory, tmp_path)
    assert codes(result) == ["FASTQ_REUSED"]
    assert result.assignments[1].path == alias
    assert len(result.inventory) == 2


def test_deterministic_order_and_inputs_unchanged(tmp_path):
    args = setup_case(tmp_path, ["unknown.fq", "A_R2.fastq", "A_R1.fastq"], [
        ("B", "A_R2.fastq", ""), ("A", "missing_R1.fastq", ""),
    ])
    sheet, mapping, inventory = args
    original = (sheet, mapping, tuple(inventory))
    result = reconcile(*args, tmp_path)
    assert reconcile(sheet, mapping, reversed(inventory), tmp_path) == result
    assert (sheet, mapping, tuple(inventory)) == original
    assert all(finding.message for finding in result.findings)


def test_result_is_immutable(tmp_path):
    args = setup_case(tmp_path, [], [("A", "A_R1.fastq", "")])
    result = reconcile(*args, tmp_path)
    with pytest.raises(FrozenInstanceError):
        result.findings = ()
    with pytest.raises(FrozenInstanceError):
        result.findings[0].code = "changed"


def test_incomplete_mapping_rejected(tmp_path):
    sheet = SampleSheet(("unknown",), ())
    with pytest.raises(ValueError, match="resolved"):
        reconcile(sheet, map_columns(sheet), [], tmp_path)
