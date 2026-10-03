from dataclasses import FrozenInstanceError, replace
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord, scan_fastqs
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.pairing import PairKey, PairStatus, group_pairs, pair_key


def record(name: str, category=InventoryCategory.READ) -> InventoryRecord:
    relative = Path(name)
    return InventoryRecord(
        Path("/scan") / relative, relative, parse_fastq_name(relative.name), category
    )


def test_exact_complete_pair_and_key():
    r1 = record("run/A_S1_L001_R1_001.fastq.gz")
    r2 = record("run/A_S1_L001_R2_001.fastq.gz")
    expected = PairKey("A", 1, 1, 1, "R", ".fastq.gz", PurePosixPath("run"))
    assert pair_key(r1) == pair_key(r2) == expected
    group, = group_pairs([r2, r1])
    assert group.key == expected
    assert group.r1 == (r1,)
    assert group.r2 == (r2,)
    assert group.status is PairStatus.COMPLETE


@pytest.mark.parametrize("r1, r2", [
    ("A_S1_L001_R1_001.fastq.gz", "A_S1_L002_R2_001.fastq.gz"),
    ("A_L001_R1_001.fastq.gz", "A_L001_R2_002.fastq.gz"),
    ("A_S1_R1.fastq.gz", "A_S2_R2.fastq.gz"),
    ("A_S1_R1.fastq.gz", "A_R2.fastq.gz"),
    ("A_R1.fastq.gz", "A_2.fastq.gz"),
    ("A_R1.fastq.gz", "A_R2.fq.gz"),
    ("A_R1.fastq.gz", "A_R2.fastq"),
    ("A-B_R1.fastq.gz", "AB_R2.fastq.gz"),
    ("A_L001_R1.fastq.gz", "A_R2.fastq.gz"),
    ("A_R1_001.fastq.gz", "A_R2.fastq.gz"),
    ("one/A_R1.fastq.gz", "two/A_R2.fastq.gz"),
    ("Run/A_R1.fastq.gz", "run/a_R2.FASTQ.GZ"),
])
def test_mismatched_identity_never_pairs(r1, r2):
    groups = group_pairs([record(r2), record(r1)])
    assert len(groups) == 2
    assert {group.status for group in groups} == {PairStatus.R1_ONLY, PairStatus.R2_ONLY}
    assert sum(len(group.r1) + len(group.r2) for group in groups) == 2


@pytest.mark.parametrize("r1_name, r2_name", [
    ("A_R1.fastq.gz", "a_R2.fastq.gz"),
    ("A_R1.fastq.gz", "A_R2.FASTQ.GZ"),
    ("A_R1.fastq.gz", "a_R2.FASTQ.GZ"),
    ("Straße_R1.fastq.gz", "STRASSE_R2.FASTQ.GZ"),
])
def test_sample_and_suffix_casefold_without_changing_parsed_names(r1_name, r2_name):
    r1, r2 = record(r1_name), record(r2_name)
    original_r1, original_r2 = r1.parsed_name, r2.parsed_name
    key1, key2 = pair_key(r1), pair_key(r2)
    assert key1 == key2
    assert hash(key1) == hash(key2)
    group, = group_pairs([r1, r2])
    assert group.status is PairStatus.COMPLETE
    assert group.r1 == (r1,)
    assert group.r2 == (r2,)
    assert group_pairs([r2, r1]) == [group]
    assert r1.parsed_name is original_r1
    assert r2.parsed_name is original_r2
    assert r1.parsed_name.sample == r1_name.split("_R1")[0]
    assert r2.parsed_name.sample == r2_name.split("_R2")[0]
    assert r1.parsed_name.suffix == r1_name.split("_R1")[1]
    assert r2.parsed_name.suffix == r2_name.split("_R2")[1]


@pytest.mark.parametrize("role, status", [("R1", PairStatus.R1_ONLY), ("R2", PairStatus.R2_ONLY)])
def test_unmatched_read(role, status):
    read = record(f"A_{role}.fastq.gz")
    group, = group_pairs([read])
    assert group.status is status
    assert group.r1 + group.r2 == (read,)


def test_multiple_lanes_are_independent_pairs():
    records = [record(f"A_L{lane:03d}_{role}_001.fastq.gz")
               for lane in (2, 1) for role in ("R2", "R1")]
    groups = group_pairs(records)
    assert [group.key.lane for group in groups] == [1, 2]
    assert all(group.status is PairStatus.COMPLETE for group in groups)
    assert all(len(group.r1) == len(group.r2) == 1 for group in groups)


def test_same_filenames_in_different_directories_remain_separate():
    groups = group_pairs(record(f"{parent}/A_{role}.fastq")
                         for parent in ("two", "one") for role in ("R1", "R2"))
    assert [group.key.relative_parent for group in groups] == [PurePosixPath("one"), PurePosixPath("two")]
    assert all(group.status is PairStatus.COMPLETE for group in groups)


@pytest.mark.parametrize("name, category", [
    ("A_I1_001.fastq.gz", InventoryCategory.INDEX),
    ("A_I2_001.fastq.gz", InventoryCategory.INDEX),
    ("Undetermined_R1.fastq.gz", InventoryCategory.UNDETERMINED),
    ("Undetermined_R2.fastq.gz", InventoryCategory.UNDETERMINED),
    ("unknown.fastq.gz", InventoryCategory.UNPARSED),
    ("A_R1.fastq.gz", InventoryCategory.INDEX),
    ("A_R1.fastq.gz", InventoryCategory.UNPARSED),
    ("A_I1.fastq.gz", InventoryCategory.READ),
    ("unknown.fastq.gz", InventoryCategory.READ),
])
def test_only_parsed_biological_read_records_are_pairable(name, category):
    excluded = record(name, category)
    assert pair_key(excluded) is None
    assert group_pairs([excluded]) == []


def test_bare_style_pair():
    group, = group_pairs([record("A_2.fq"), record("A_1.fq")])
    assert group.key.read_style == "bare"
    assert group.status is PairStatus.COMPLETE


def test_order_is_independent_of_input_and_optional_components():
    records = [record(name) for name in [
        "z/B_R2.fq", "A_S2_R1.fastq", "A_R1.fastq", "A_S1_R2.fastq",
        "A_R2.fastq", "z/B_R1.fq",
    ]]
    expected = group_pairs(records)
    assert group_pairs(reversed(records)) == expected
    assert group_pairs(iter(records[2:] + records[:2])) == expected
    assert [group.key.sample_number for group in expected[:3]] == [None, 1, 2]


def test_duplicate_role_is_retained_as_ambiguous():
    r1 = record("A_R1.fastq")
    duplicate = replace(r1, path=Path("/another_scan/A_R1.fastq"))
    r2 = record("A_R2.fastq")
    group, = group_pairs([r1, r2, duplicate])
    assert group.status is PairStatus.AMBIGUOUS
    assert len(group.r1) == 2
    assert group.r2 == (r2,)
    assert group_pairs([duplicate, r2, r1]) == [group]


def test_inventory_integration(tmp_path):
    for name in ["A_R1.fastq", "A_R2.fastq", "B_R1.fastq", "C_R2.fastq",
                 "A_I1.fastq", "A_I2.fastq", "Undetermined_R1.fastq", "unknown.fq"]:
        (tmp_path / name).touch()
    inventory = scan_fastqs(tmp_path)
    groups = group_pairs(inventory)
    assert len(inventory) == 8
    assert [group.status for group in groups] == [
        PairStatus.COMPLETE, PairStatus.R1_ONLY, PairStatus.R2_ONLY
    ]


def test_pair_key_and_group_are_immutable():
    group, = group_pairs([record("A_R1.fastq")])
    assert hash(group.key) == hash(pair_key(record("A_R2.fastq")))
    with pytest.raises(FrozenInstanceError):
        group.key.lane = 2
    with pytest.raises(FrozenInstanceError):
        group.r1 = ()


def test_empty_inventory():
    assert group_pairs([]) == []


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath, Path])
def test_case_only_parent_identity_is_exact_across_path_flavors(path_type):
    r1 = replace(record("Run/A_R1.fastq"), relative_path=path_type("Run/A_R1.fastq"))
    r2 = replace(record("run/a_R2.FASTQ"), relative_path=path_type("run/a_R2.FASTQ"))
    upper, lower = pair_key(r1), pair_key(r2)
    assert upper != lower
    assert type(upper.relative_parent) is type(lower.relative_parent) is PurePosixPath
    assert upper.relative_parent.as_posix() == "Run"
    assert lower.relative_parent.as_posix() == "run"
    assert upper.sample == lower.sample == "a"
    assert upper.suffix == lower.suffix == ".fastq"
    assert len({upper, lower}) == 2
    assert hash(upper) == hash(pair_key(r1))
    assert hash(lower) == hash(pair_key(r2))
    groups = group_pairs([r2, r1])
    assert [group.status for group in groups] == [PairStatus.R1_ONLY, PairStatus.R2_ONLY]
    assert [group.key for group in groups] == [upper, lower]
    assert group_pairs([r1, r2]) == groups
    same_parent_r2 = replace(r2, relative_path=path_type("Run/a_R2.FASTQ"))
    complete, = group_pairs([same_parent_r2, r1])
    assert complete.status is PairStatus.COMPLETE
    assert complete.key == upper


def test_direct_pair_key_construction_also_enforces_exact_parent_identity():
    upper = PairKey("A", 2, 3, 4, "R", ".FASTQ", PureWindowsPath("Run/项目"))
    lower = replace(upper, relative_parent=PureWindowsPath("run/项目"))
    equivalent = replace(upper, relative_parent=PurePosixPath("Run/项目"))
    assert upper != lower
    assert upper == equivalent and hash(upper) == hash(equivalent)
    assert type(upper.relative_parent) is PurePosixPath
    assert upper.relative_parent.as_posix() == "Run/项目"
    assert len({upper: "upper", lower: "lower", equivalent: "same upper"}) == 2


def test_report_and_presentation_preserve_exact_parent_spelling_without_io(monkeypatch):
    from fastq_sheet_audit.adjudication import PairDecision, RoleDecision, RoleDecisionKind, resolve_pair_group
    from fastq_sheet_audit.presentation import present_workflow
    from fastq_sheet_audit.read_mode import diagnose_read_mode
    from fastq_sheet_audit.reconciliation import ReconciliationResult
    from fastq_sheet_audit.reporting import build_workflow_report
    from fastq_sheet_audit.workflow import WorkflowSnapshot

    records = (record("Run/项目/A_R1.fastq"), record("run/项目/A_R2.fastq"))
    def fail(*args, **kwargs):
        pytest.fail("pairing or consumers accessed filesystem/network")
    with monkeypatch.context() as patch:
        for method in ("open", "stat", "lstat", "resolve", "read_bytes", "read_text"):
            patch.setattr(Path, method, fail)
        patch.setattr("socket.socket", fail)
        groups = group_pairs(records)
        automatic = RoleDecision(RoleDecisionKind.AUTOMATIC, None)
        resolutions = tuple(resolve_pair_group(group, PairDecision(group.key, automatic, automatic, False))
                            for group in groups)
        snapshot = WorkflowSnapshot(records, ReconciliationResult(records, (), ()),
                                    diagnose_read_mode(records), (), resolutions)
        report = build_workflow_report(snapshot)
        view = present_workflow(snapshot)
    assert [r.group.key.relative_parent for r in report.pair_resolutions] == ["Run/项目", "run/项目"]
    assert "relative_parent='Run/项目'" in view.pairs[0].key_text
    assert "relative_parent='run/项目'" in view.pairs[1].key_text
    assert [r.group.key.relative_parent for r in resolutions] == [PurePosixPath("Run/项目"), PurePosixPath("run/项目")]
