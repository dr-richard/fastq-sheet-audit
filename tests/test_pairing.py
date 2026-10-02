from dataclasses import FrozenInstanceError, replace
from pathlib import Path

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
    expected = PairKey("A", 1, 1, 1, "R", ".fastq.gz", Path("run"))
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
    assert [group.key.relative_parent for group in groups] == [Path("one"), Path("two")]
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
