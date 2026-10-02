from pathlib import Path

import pytest

from fastq_sheet_audit.core import audit, parse_fastq_name


def touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def write_sheet(p: Path, rows: str) -> None:
    p.write_text("sample\tr1\tr2\n" + rows, encoding="utf-8")


def test_parse_common_illumina_name():
    assert parse_fastq_name(Path("Alpha_S1_L001_R1_001.fastq.gz")) == ("Alpha", 1)
    assert parse_fastq_name(Path("Alpha_R2.fastq.gz")) == ("Alpha", 2)


def test_clean_pair(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_R1.fastq.gz")
    touch(fq / "A_R2.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_R1.fastq.gz\tA_R2.fastq.gz\n")
    result = audit(sheet, fq)
    assert result.ok


def test_missing_r2(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_R1.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_R1.fastq.gz\tA_R2.fastq.gz\n")
    result = audit(sheet, fq)
    assert any(f.code == "MISSING_FILE" for f in result.findings)


def test_duplicate_sample_and_reused_fastq(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_R1.fastq.gz")
    touch(fq / "A_R2.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_R1.fastq.gz\tA_R2.fastq.gz\nA\tA_R1.fastq.gz\tA_R2.fastq.gz\n")
    result = audit(sheet, fq)
    codes = {f.code for f in result.findings}
    assert "DUPLICATE_SAMPLE" in codes
    assert "FASTQ_REUSED" in codes


def test_pair_name_mismatch(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_R1.fastq.gz")
    touch(fq / "B_R2.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_R1.fastq.gz\tB_R2.fastq.gz\n")
    result = audit(sheet, fq)
    assert any(f.code == "PAIR_NAME_MISMATCH" for f in result.findings)


def test_unlisted_fastq(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_R1.fastq.gz")
    touch(fq / "A_R2.fastq.gz")
    touch(fq / "B_R1.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_R1.fastq.gz\tA_R2.fastq.gz\n")
    result = audit(sheet, fq)
    assert any(f.code == "UNLISTED_FASTQ" and f.path.endswith("B_R1.fastq.gz") for f in result.findings)


def test_unlisted_mate(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_R1.fastq.gz")
    touch(fq / "A_R2.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_R1.fastq.gz\t\n")
    result = audit(sheet, fq)
    assert any(f.code == "UNLISTED_MATE" for f in result.findings)


def test_sample_name_mismatch(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "OTHER_R1.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tOTHER_R1.fastq.gz\t\n")
    result = audit(sheet, fq)
    assert any(f.code == "SAMPLE_NAME_MISMATCH" for f in result.findings)


def test_csv_input(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "S_S1_L001_R1_001.fastq.gz")
    touch(fq / "S_S1_L001_R2_001.fastq.gz")
    sheet = tmp_path / "samples.csv"
    sheet.write_text("sample,r1,r2\nS,S_S1_L001_R1_001.fastq.gz,S_S1_L001_R2_001.fastq.gz\n")
    assert audit(sheet, fq).ok


def test_read_role_mismatch(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "S_R2.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "S\tS_R2.fastq.gz\t\n")
    result = audit(sheet, fq)
    assert any(f.code == "READ_ROLE_MISMATCH" for f in result.findings)


@pytest.mark.parametrize("r2", [
    "A_S1_L002_R2_001.fastq.gz",
    "A_S1_L001_R2_002.fastq.gz",
    "A_S2_L001_R2_001.fastq.gz",
    "A_L001_R2_001.fastq.gz",
    "A_S1_L001_2_001.fastq.gz",
])
def test_pair_components_must_match(tmp_path: Path, r2: str):
    fq = tmp_path / "fastq"
    r1 = "A_S1_L001_R1_001.fastq.gz"
    touch(fq / r1)
    touch(fq / r2)
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, f"A\t{r1}\t{r2}\n")
    assert any(f.code == "PAIR_NAME_MISMATCH" for f in audit(sheet, fq).findings)


def test_wrong_lane_is_not_inferred_as_mate(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_L001_R1_001.fastq.gz")
    touch(fq / "A_L002_R2_001.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_L001_R1_001.fastq.gz\t\n")
    codes = {f.code for f in audit(sheet, fq).findings}
    assert "UNLISTED_MATE" not in codes
    assert "UNLISTED_FASTQ" in codes


def test_exact_mate_among_multiple_candidates(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "A_L001_R1_001.fastq.gz")
    exact = fq / "A_L001_R2_001.fastq.gz"
    other = fq / "A_L002_R2_001.fastq.gz"
    touch(exact)
    touch(other)
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "A\tA_L001_R1_001.fastq.gz\t\n")
    result = audit(sheet, fq)
    assert [f.path for f in result.findings if f.code == "UNLISTED_MATE"] == [str(exact)]
    assert [f.path for f in result.findings if f.code == "UNLISTED_FASTQ"] == [str(other.resolve())]


def test_sample_punctuation_is_preserved(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "AB_R1.fastq.gz")
    touch(fq / "A-B_R2.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "AB\tAB_R1.fastq.gz\tA-B_R2.fastq.gz\n")
    codes = {f.code for f in audit(sheet, fq).findings}
    assert "SAMPLE_NAME_MISMATCH" in codes
    assert "PAIR_NAME_MISMATCH" in codes


def test_distinct_punctuated_sample_ids_are_not_duplicates(tmp_path: Path):
    fq = tmp_path / "fastq"
    touch(fq / "AB_R1.fastq.gz")
    touch(fq / "A-B_R1.fastq.gz")
    sheet = tmp_path / "samples.tsv"
    write_sheet(sheet, "AB\tAB_R1.fastq.gz\t\nA-B\tA-B_R1.fastq.gz\t\n")
    assert audit(sheet, fq).ok
