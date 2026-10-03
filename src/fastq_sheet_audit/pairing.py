"""Group biological FASTQs by exact parsed mate identity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable

from .inventory import InventoryCategory, InventoryRecord
from .naming import ReadRole


@dataclass(frozen=True)
class PairKey:
    """Mate identity with exact, host-independent relative directory spelling.

    Only sample and suffix are casefolded. Pure POSIX directory equality and
    hashing preserve case even when inventory paths came from Windows.
    """

    sample: str
    sample_number: int | None
    lane: int | None
    chunk: int | None
    read_style: str
    suffix: str
    relative_parent: PurePosixPath

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample", self.sample.casefold())
        object.__setattr__(self, "suffix", self.suffix.casefold())
        object.__setattr__(self, "relative_parent", PurePosixPath(self.relative_parent.as_posix()))


class PairStatus(Enum):
    COMPLETE = "complete"
    R1_ONLY = "r1_only"
    R2_ONLY = "r2_only"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PairGroup:
    key: PairKey
    r1: tuple[InventoryRecord, ...]
    r2: tuple[InventoryRecord, ...]

    @property
    def status(self) -> PairStatus:
        if len(self.r1) > 1 or len(self.r2) > 1:
            return PairStatus.AMBIGUOUS
        if self.r1 and self.r2:
            return PairStatus.COMPLETE
        return PairStatus.R1_ONLY if self.r1 else PairStatus.R2_ONLY


def pair_key(record: InventoryRecord) -> PairKey | None:
    """Return identity only for READ records with parsed R1/R2 roles.

    Sample and suffix use Unicode casefold for identity comparison; parsed
    names retain their original spelling. All other fields remain exact.
    The relative parent uses the inventory entry's location, not a symlink
    target. Excluded inventory records remain available to the caller.
    """
    parsed = record.parsed_name
    if (
        record.category is not InventoryCategory.READ
        or parsed is None
        or parsed.read_role not in (ReadRole.R1, ReadRole.R2)
    ):
        return None
    return PairKey(
        sample=parsed.sample,
        sample_number=parsed.sample_number,
        lane=parsed.lane,
        chunk=parsed.chunk,
        read_style=parsed.read_style,
        suffix=parsed.suffix,
        relative_parent=PurePosixPath(record.relative_path.parent.as_posix()),
    )


def group_pairs(records: Iterable[InventoryRecord]) -> list[PairGroup]:
    """Group exact identities deterministically, retaining unmatched reads.

    Nonpairable records are excluded. Multiple records for the same role are
    retained and marked ambiguous rather than choosing an arbitrary mate.
    """
    groups: dict[PairKey, tuple[list[InventoryRecord], list[InventoryRecord]]] = {}
    for record in records:
        key = pair_key(record)
        if key is None:
            continue
        r1, r2 = groups.setdefault(key, ([], []))
        if record.parsed_name.read_role is ReadRole.R1:
            r1.append(record)
        else:
            r2.append(record)

    def key_order(key: PairKey) -> tuple:
        return (
            key.relative_parent.as_posix(), key.sample,
            -1 if key.sample_number is None else key.sample_number,
            -1 if key.lane is None else key.lane,
            -1 if key.chunk is None else key.chunk,
            key.read_style, key.suffix,
        )

    def record_order(record: InventoryRecord) -> tuple[str, str]:
        return record.relative_path.as_posix(), record.path.as_posix()

    return [
        PairGroup(
            key=key,
            r1=tuple(sorted(groups[key][0], key=record_order)),
            r2=tuple(sorted(groups[key][1], key=record_order)),
        )
        for key in sorted(groups, key=key_order)
    ]
