from dataclasses import FrozenInstanceError, replace
from itertools import permutations
from pathlib import Path

import pytest

from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.portability import PathCaseCollision, find_case_collisions


def record(name: str, category=InventoryCategory.READ) -> InventoryRecord:
    relative = Path(name)
    return InventoryRecord(
        Path("/scan") / relative, relative, parse_fastq_name(relative.name), category
    )


def test_no_collision():
    assert find_case_collisions([]) == []
    assert find_case_collisions([
        record("A_R1.fastq.gz"), record("A_R2.fastq.gz"),
        record("one/B_R1.fastq"), record("two/B_R1.fastq"),
    ]) == []


def test_filename_case_collision():
    upper = record("Sample_R1.fastq.gz")
    lower = record("sample_R1.fastq.gz")
    assert find_case_collisions([lower, upper]) == [
        PathCaseCollision("sample_r1.fastq.gz", (upper, lower))
    ]


def test_directory_case_collision():
    upper = record("Run1/nested/A_R1.fastq.gz")
    lower = record("run1/nested/A_R1.fastq.gz")
    assert find_case_collisions([lower, upper]) == [
        PathCaseCollision("run1/nested/a_r1.fastq.gz", (upper, lower))
    ]


def test_three_way_collision():
    names = ["sample_R1.fastq.gz", "Sample_R1.fastq.gz", "SAMPLE_R1.FASTQ.GZ"]
    records = [record(name) for name in names]
    collision, = find_case_collisions(records)
    assert collision.normalized_key == "sample_r1.fastq.gz"
    assert [r.relative_path.as_posix() for r in collision.records] == sorted(names)
    assert len(collision.records) == 3


def test_punctuation_remains_distinct():
    assert find_case_collisions([
        record("A-B_R1.fastq.gz"), record("AB_R1.fastq.gz"),
        record("A.B_R1.fastq.gz"), record("A_B_R1.fastq.gz"),
    ]) == []


def test_deterministic_group_and_record_order():
    records = [record(name) for name in [
        "z/B_R1.fastq", "Z/B_R1.fastq", "a_R1.fastq", "A_R1.fastq",
    ]]
    expected = find_case_collisions(records)
    assert [collision.normalized_key for collision in expected] == [
        "a_r1.fastq", "z/b_r1.fastq"
    ]
    for ordered in permutations(records):
        assert find_case_collisions(iter(ordered)) == expected


def test_identical_record_duplicates_do_not_create_collision():
    original = record("A_R1.fastq")
    assert find_case_collisions([original, original, replace(original)]) == []


def test_identical_relative_paths_do_not_create_collision():
    original = record("A_R1.fastq")
    other = replace(original, path=Path("/other/A_R1.fastq"))
    assert find_case_collisions([original, other]) == []


def test_real_collision_preserves_all_original_records_including_duplicates():
    upper = record("A_R1.fastq")
    lower = record("a_R1.fastq")
    collision, = find_case_collisions([upper, lower, upper])
    assert len(collision.records) == 3
    assert collision.records[0] is upper
    assert collision.records[1] is upper
    assert collision.records[2] is lower
    assert upper.relative_path == Path("A_R1.fastq")
    assert lower.relative_path == Path("a_R1.fastq")


def test_unicode_casefold():
    first = record("Straße_R1.fastq")
    second = record("STRASSE_R1.fastq")
    collision, = find_case_collisions([first, second])
    assert collision.normalized_key == "strasse_r1.fastq"
    assert set(collision.records) == {first, second}


def test_no_broader_filename_normalization():
    assert find_case_collisions([
        record("é_R1.fastq"), record("e\u0301_R1.fastq"),
        record("A_R1.fastq"), record("A_R1.fastq."),
        record("A_R1.fastq "),
    ]) == []


@pytest.mark.parametrize("names, category", [
    (["A_I1.fastq", "a_I1.fastq"], InventoryCategory.INDEX),
    (["Undetermined_R1.fastq", "undetermined_R1.fastq"], InventoryCategory.UNDETERMINED),
    (["Unknown.fastq", "unknown.fastq"], InventoryCategory.UNPARSED),
])
def test_all_inventory_categories_are_checked(names, category):
    records = [record(name, category) for name in names]
    collision, = find_case_collisions(records)
    assert set(collision.records) == set(records)


def test_deterministic_order_with_same_relative_path():
    original = record("A_R1.fastq")
    other_root = replace(original, path=Path("/other/A_R1.fastq"))
    lower = record("a_R1.fastq")
    expected = find_case_collisions([original, other_root, lower])
    assert find_case_collisions([lower, other_root, original]) == expected


def test_collision_is_immutable():
    collision, = find_case_collisions([record("A_R1.fastq"), record("a_R1.fastq")])
    assert isinstance(collision.records, tuple)
    with pytest.raises(FrozenInstanceError):
        collision.normalized_key = "changed"
