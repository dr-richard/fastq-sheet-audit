"""Discover FASTQ paths and classify filename structure without reading contents."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .naming import ParsedFastqName, ReadRole, parse_fastq_name


class InventoryCategory(Enum):
    READ = "read"
    INDEX = "index"
    UNDETERMINED = "undetermined"
    UNPARSED = "unparsed"


@dataclass(frozen=True)
class InventoryRecord:
    path: Path
    relative_path: Path
    parsed_name: ParsedFastqName | None
    category: InventoryCategory


_FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def _category(stem: str, parsed: ParsedFastqName | None) -> InventoryCategory:
    # Undetermined is a filename label, not an inference from sequence contents.
    sample = parsed.sample if parsed is not None else stem
    if sample.casefold() == "undetermined" or (
        parsed is None and sample.casefold().startswith("undetermined_")
    ):
        return InventoryCategory.UNDETERMINED
    if parsed is None:
        return InventoryCategory.UNPARSED
    if parsed.read_role in (ReadRole.I1, ReadRole.I2):
        return InventoryCategory.INDEX
    return InventoryCategory.READ


def scan_fastqs(root: Path) -> list[InventoryRecord]:
    """Return FASTQs sorted by their case-sensitive relative POSIX paths.

    Directory symlinks are not traversed. File symlinks are included when
    they point to regular files; their inventory paths retain the symlink's
    location rather than resolving to its target. Filesystem errors propagate.
    Undetermined filename labels take precedence over read-role categories;
    parsed roles remain available on the record.
    """
    root = Path(os.path.abspath(root))
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    def raise_walk_error(error: OSError) -> None:
        raise error

    records: list[InventoryRecord] = []
    for directory, _, filenames in os.walk(
        root, followlinks=False, onerror=raise_walk_error
    ):
        for name in filenames:
            suffix = next(
                (suffix for suffix in _FASTQ_SUFFIXES if name.lower().endswith(suffix)),
                None,
            )
            if suffix is None:
                continue
            path = Path(directory) / name
            if not path.is_file():
                continue
            parsed = parse_fastq_name(name)
            records.append(InventoryRecord(
                path=path,
                relative_path=path.relative_to(root),
                parsed_name=parsed,
                category=_category(name[:-len(suffix)], parsed),
            ))
    return sorted(records, key=lambda record: record.relative_path.as_posix())
