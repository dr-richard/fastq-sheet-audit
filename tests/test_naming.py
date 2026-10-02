from dataclasses import FrozenInstanceError

import pytest

from fastq_sheet_audit.naming import ParsedFastqName, ReadRole, parse_fastq_name


@pytest.mark.parametrize("role", [ReadRole.R1, ReadRole.R2])
def test_illumina_style(role):
    assert parse_fastq_name(f"A_S1_L001_{role.value}_001.fastq.gz") == ParsedFastqName(
        "A", 1, 1, role, 1, ".fastq.gz", "R"
    )


@pytest.mark.parametrize("role", [ReadRole.R1, ReadRole.R2])
def test_simple_r_style(role):
    assert parse_fastq_name(f"A_{role.value}.fastq.gz") == ParsedFastqName(
        "A", None, None, role, None, ".fastq.gz", "R"
    )


@pytest.mark.parametrize("digit, role", [(1, ReadRole.R1), (2, ReadRole.R2)])
def test_bare_style(digit, role):
    assert parse_fastq_name(f"A_{digit}.fastq") == ParsedFastqName(
        "A", None, None, role, None, ".fastq", "bare"
    )


@pytest.mark.parametrize("lane, chunk", [(1, 1), (2, 1), (1, 2)])
def test_lane_and_chunk_without_sample_number(lane, chunk):
    assert parse_fastq_name(f"A_L{lane:03d}_R1_{chunk:03d}.fq.gz") == ParsedFastqName(
        "A", None, lane, ReadRole.R1, chunk, ".fq.gz", "R"
    )


def test_sample_number_without_lane():
    assert parse_fastq_name("A_S12_R2.fastq") == ParsedFastqName(
        "A", 12, None, ReadRole.R2, None, ".fastq", "R"
    )


@pytest.mark.parametrize("role", [ReadRole.I1, ReadRole.I2])
@pytest.mark.parametrize("prefix, sample_number, lane", [("A", None, None), ("A_S3_L002", 3, 2)])
def test_index_reads(role, prefix, sample_number, lane):
    assert parse_fastq_name(f"{prefix}_{role.value}_001.fastq.gz") == ParsedFastqName(
        "A", sample_number, lane, role, 1, ".fastq.gz", "I"
    )


@pytest.mark.parametrize("name", [
    "A.fastq.gz", "A_reads.fq", "A_R3.fastq.gz", "A_I3.fastq.gz",
    "_R1.fastq", "A_R1_01.fastq", "A_R1.txt", "A_R1.fastq.gz.bak",
    "A_R1.fastq\n", "directory/A_R1.fastq",
])
def test_unrecognized_filename(name):
    assert parse_fastq_name(name) is None


@pytest.mark.parametrize("sample", ["A-B", "A.B", "A+B", "A_B", "A_R1_part", "A (control)"])
def test_sample_punctuation_is_preserved(sample):
    parsed = parse_fastq_name(f"{sample}_S1_L001_R1_001.fastq.gz")
    assert parsed is not None
    assert parsed.sample == sample


@pytest.mark.parametrize("suffix", [".fastq", ".fastq.gz", ".fq", ".fq.gz", ".FASTQ.GZ"])
def test_suffix_is_preserved(suffix):
    parsed = parse_fastq_name(f"A_r1{suffix}")
    assert parsed is not None
    assert parsed.suffix == suffix
    assert parsed.read_role is ReadRole.R1
    assert parsed.read_style == "R"


def test_parsed_name_is_immutable():
    parsed = parse_fastq_name("A_R1.fastq.gz")
    assert parsed is not None
    with pytest.raises(FrozenInstanceError):
        parsed.sample = "B"
