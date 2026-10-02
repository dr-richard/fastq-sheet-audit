from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fastq_sheet_audit.inventory import InventoryCategory, scan_fastqs
from fastq_sheet_audit.naming import ReadRole


def make_file(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not FASTQ contents")
    return path


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks unavailable: {error}")


def test_recursive_discovery_and_deterministic_order(tmp_path):
    names = ["z/A_R2.fastq.gz", "A_R1.fastq.gz", "a/deeper/B_1.fq"]
    for name in names:
        make_file(tmp_path, name)
    records = scan_fastqs(tmp_path)
    assert [record.relative_path.as_posix() for record in records] == sorted(names)
    assert all(record.path == tmp_path / record.relative_path for record in records)
    assert all(record.path.is_absolute() for record in records)
    assert all(record.category is InventoryCategory.READ for record in records)
    assert records[0].parsed_name.read_role is ReadRole.R1
    assert scan_fastqs(tmp_path) == records


@pytest.mark.parametrize("suffix", [
    ".fastq.gz", ".fq.gz", ".fastq", ".fq",
    ".FASTQ.GZ", ".FQ.GZ", ".FASTQ", ".Fq",
])
def test_supported_suffixes(tmp_path, suffix):
    path = make_file(tmp_path, "A_R1" + suffix)
    records = scan_fastqs(tmp_path)
    assert len(records) == 1
    assert records[0].path == path
    assert records[0].parsed_name.suffix == suffix


def test_unparsed_fastq_is_retained(tmp_path):
    make_file(tmp_path, "unknown.fastq.gz")
    record, = scan_fastqs(tmp_path)
    assert record.relative_path == Path("unknown.fastq.gz")
    assert record.parsed_name is None
    assert record.category is InventoryCategory.UNPARSED


@pytest.mark.parametrize("role", [ReadRole.I1, ReadRole.I2])
def test_index_reads_are_retained(tmp_path, role):
    make_file(tmp_path, f"A_S1_L001_{role.value}_001.fastq.gz")
    record, = scan_fastqs(tmp_path)
    assert record.category is InventoryCategory.INDEX
    assert record.parsed_name.read_role is role


@pytest.mark.parametrize("name, role", [
    ("Undetermined_S0_L001_R1_001.fastq.gz", ReadRole.R1),
    ("undetermined_L002_R2_001.fq.gz", ReadRole.R2),
    ("Undetermined_I1_001.fastq.gz", ReadRole.I1),
    ("Undetermined.fastq", None),
    ("Undetermined_unknown.fq", None),
])
def test_undetermined_is_visible(tmp_path, name, role):
    make_file(tmp_path, name)
    record, = scan_fastqs(tmp_path)
    assert record.category is InventoryCategory.UNDETERMINED
    if role is None:
        assert record.parsed_name is None
    else:
        assert record.parsed_name.read_role is role


def test_undetermined_label_does_not_match_arbitrary_prefix(tmp_path):
    make_file(tmp_path, "UndeterminedSample_R1.fastq")
    record, = scan_fastqs(tmp_path)
    assert record.category is InventoryCategory.READ


def test_non_fastq_ignored(tmp_path):
    for name in ["notes.txt", "A_R1.fastq.gz.bak", "A_R1.fa", "reads.gz"]:
        make_file(tmp_path, name)
    (tmp_path / "directory.fastq").mkdir()
    assert scan_fastqs(tmp_path) == []


def test_directory_symlinks_are_not_followed(tmp_path):
    root = tmp_path / "scan"
    root.mkdir()
    make_file(root, "nested/A_R1.fastq")
    external = tmp_path / "external"
    make_file(external, "B_R1.fastq")
    make_symlink(root / "external_link", external, directory=True)
    make_symlink(root / "nested" / "cycle", root, directory=True)
    assert [record.relative_path for record in scan_fastqs(root)] == [
        Path("nested/A_R1.fastq")
    ]


def test_file_symlink_keeps_its_local_path(tmp_path):
    root = tmp_path / "scan"
    root.mkdir()
    target = make_file(tmp_path, "external/A_R1.fastq")
    link = root / "B_R2.fastq"
    make_symlink(link, target)
    record, = scan_fastqs(root)
    assert record.path == link
    assert record.relative_path == Path("B_R2.fastq")
    assert record.parsed_name.sample == "B"
    assert record.parsed_name.read_role is ReadRole.R2


def test_contents_are_never_opened(tmp_path, monkeypatch):
    make_file(tmp_path, "A_R1.fastq.gz")

    def fail_open(*args, **kwargs):
        pytest.fail("inventory opened a file")

    monkeypatch.setattr("builtins.open", fail_open)
    monkeypatch.setattr(Path, "open", fail_open)
    assert len(scan_fastqs(tmp_path)) == 1


def test_relative_scan_root(tmp_path, monkeypatch):
    make_file(tmp_path, "scan/A_R1.fastq")
    monkeypatch.chdir(tmp_path)
    record, = scan_fastqs(Path("scan"))
    assert record.path == tmp_path / "scan/A_R1.fastq"
    assert record.relative_path == Path("A_R1.fastq")


def test_record_is_immutable(tmp_path):
    make_file(tmp_path, "A_R1.fastq")
    record, = scan_fastqs(tmp_path)
    with pytest.raises(FrozenInstanceError):
        record.category = InventoryCategory.UNPARSED


def test_invalid_scan_roots(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_fastqs(tmp_path / "missing")
    path = make_file(tmp_path, "file.txt")
    with pytest.raises(NotADirectoryError):
        scan_fastqs(path)
