from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord, scan_fastqs
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.read_mode import (
    DiagnosticSeverity, ReadLayout, ReadMode, diagnose_read_mode,
)


def record(name, category=InventoryCategory.READ):
    relative = Path(name)
    return InventoryRecord(Path("/scan") / relative, relative,
                           parse_fastq_name(relative.name), category)


@pytest.mark.parametrize("mode", [ReadMode.PAIRED, ReadMode.AUTO])
def test_clean_paired_dataset(mode):
    reads = [record("A_R1.fastq"), record("A_R2.fastq")]
    result = diagnose_read_mode(reads, mode)
    assert result.layout is ReadLayout.PAIRED
    assert result.ok
    assert result.diagnostics == ()
    assert len(result.groups) == 1


@pytest.mark.parametrize("mode", [ReadMode.SINGLE, ReadMode.AUTO])
def test_clean_single_r1_dataset(mode):
    result = diagnose_read_mode([record("A_R1.fastq"), record("B_R1.fastq")], mode)
    assert result.layout is ReadLayout.SINGLE
    assert result.ok
    assert len(result.groups) == 2


@pytest.mark.parametrize("name, code", [
    ("A_R1.fastq", "MISSING_R2"), ("A_R2.fastq", "MISSING_R1"),
])
def test_paired_mode_requires_exact_mate(name, code):
    read = record(name)
    result = diagnose_read_mode([read], ReadMode.PAIRED)
    diagnostic, = result.diagnostics
    assert diagnostic.code == code
    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.records == (read,)
    assert diagnostic.key == result.groups[0].key
    assert not result.ok


def test_single_mode_surfaces_r2_without_discarding_it():
    r1, r2 = record("A_R1.fastq"), record("A_R2.fastq")
    result = diagnose_read_mode([r1, r2], ReadMode.SINGLE)
    diagnostic, = result.diagnostics
    assert diagnostic.code == "UNEXPECTED_R2"
    assert diagnostic.records == (r2,)
    assert result.groups[0].r1 == (r1,)
    assert result.groups[0].r2 == (r2,)
    assert not result.ok


@pytest.mark.parametrize("names", [
    ["A_R1.fastq", "A_R2.fastq", "B_R1.fastq"],
    ["A_R1.fastq", "A_R2.fastq", "B_R2.fastq"],
    ["A_R2.fastq"],
    ["A_R1.fastq", "B_R2.fastq"],
])
def test_auto_mixed_and_orphan_r2_are_unresolved(names):
    reads = [record(name) for name in names]
    result = diagnose_read_mode(reads, ReadMode.AUTO)
    assert result.layout is ReadLayout.UNRESOLVED
    diagnostic, = result.diagnostics
    assert diagnostic.code == "AUTO_UNRESOLVED"
    assert diagnostic.severity is DiagnosticSeverity.WARNING
    assert set(diagnostic.records) == set(reads)
    assert not result.ok


@pytest.mark.parametrize("with_r2", [False, True])
def test_duplicate_role_is_ambiguous(with_r2):
    r1 = record("A_R1.fastq")
    duplicate = replace(r1, path=Path("/other/A_R1.fastq"))
    reads = [r1, duplicate] + ([record("A_R2.fastq")] if with_r2 else [])
    paired = diagnose_read_mode(reads, ReadMode.PAIRED)
    ambiguous = next(d for d in paired.diagnostics if d.code == "AMBIGUOUS_PAIR")
    assert ambiguous.severity is DiagnosticSeverity.ERROR
    assert len(ambiguous.records) == len(reads)
    auto = diagnose_read_mode(reads, ReadMode.AUTO)
    assert auto.layout is ReadLayout.UNRESOLVED
    assert auto.diagnostics[0].severity is DiagnosticSeverity.WARNING


@pytest.mark.parametrize("r2", ["A_L002_R2_001.fastq", "A_L001_R2_002.fastq"])
def test_lane_and_chunk_are_never_nearby_mates(r2):
    reads = [record("A_L001_R1_001.fastq"), record(r2)]
    result = diagnose_read_mode(reads, ReadMode.PAIRED)
    assert len(result.groups) == 2
    assert {d.code for d in result.diagnostics} == {"MISSING_R1", "MISSING_R2"}
    assert all(d.severity is DiagnosticSeverity.ERROR for d in result.diagnostics)


def test_multiple_lanes_remain_independent():
    reads = [record(f"A_L{lane:03d}_{role}_001.fastq")
             for lane in (2, 1) for role in ("R2", "R1")]
    result = diagnose_read_mode(reads, ReadMode.AUTO)
    assert result.layout is ReadLayout.PAIRED
    assert [group.key.lane for group in result.groups] == [1, 2]
    assert result.ok


@pytest.mark.parametrize("mode", list(ReadMode))
def test_non_biological_records_are_excluded_and_preserved(mode):
    excluded = [
        record("A_I1.fastq", InventoryCategory.INDEX),
        record("A_I2.fastq", InventoryCategory.INDEX),
        record("Undetermined_R2.fastq", InventoryCategory.UNDETERMINED),
        record("unknown.fastq", InventoryCategory.UNPARSED),
    ]
    reads = [record("A_R1.fastq"), record("A_R2.fastq")]
    baseline = diagnose_read_mode(reads, mode)
    result = diagnose_read_mode(reads + excluded, mode)
    assert result.layout is baseline.layout
    assert result.groups == baseline.groups
    assert result.diagnostics == baseline.diagnostics
    assert set(result.excluded) == set(excluded)


def test_only_excluded_or_empty_inventory_does_not_infer_paired():
    for reads in ([], [record("A_I1.fastq", InventoryCategory.INDEX)]):
        result = diagnose_read_mode(reads)
        assert result.layout is ReadLayout.UNRESOLVED
        assert result.groups == ()
        assert result.diagnostics[0].records == ()
        assert result.diagnostics[0].severity is DiagnosticSeverity.WARNING


@pytest.mark.parametrize("mode", list(ReadMode))
def test_deterministic_order_and_inputs_unchanged(mode):
    reads = [record("Z_R2.fastq"), record("B_R1.fastq"), record("A_R1.fastq"),
             record("A_R2.fastq"), record("unknown.fq", InventoryCategory.UNPARSED)]
    before = tuple(reads)
    result = diagnose_read_mode(iter(reads), mode)
    assert diagnose_read_mode(reversed(reads), mode) == result
    assert diagnose_read_mode(reads[2:] + reads[:2], mode) == result
    assert tuple(reads) == before


def test_inventory_integration(tmp_path):
    for name in ("A_R1.fastq", "A_R2.fastq", "A_I1.fastq", "unknown.fq"):
        (tmp_path / name).touch()
    result = diagnose_read_mode(scan_fastqs(tmp_path))
    assert result.layout is ReadLayout.PAIRED
    assert len(result.excluded) == 2


def test_result_and_diagnostic_are_immutable():
    result = diagnose_read_mode([record("A_R1.fastq")], ReadMode.PAIRED)
    with pytest.raises(FrozenInstanceError):
        result.layout = ReadLayout.SINGLE
    with pytest.raises(FrozenInstanceError):
        result.diagnostics[0].code = "changed"


def test_invalid_mode_rejected():
    with pytest.raises(ValueError, match="ReadMode"):
        diagnose_read_mode([], "paired")
