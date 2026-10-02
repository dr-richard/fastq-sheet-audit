"""Diagnose case-only relative path collisions without changing inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .inventory import InventoryRecord


@dataclass(frozen=True)
class PathCaseCollision:
    normalized_key: str
    records: tuple[InventoryRecord, ...]


def find_case_collisions(
    records: Iterable[InventoryRecord],
) -> list[PathCaseCollision]:
    """Report distinct relative path spellings with identical Unicode casefold.

    Keys include all directory components in POSIX form. Repeated identical
    paths alone do not cause a collision. Every input record in a conflicting
    group is retained, including duplicates. Groups and their records are
    sorted independently of input order. No filesystem access is performed.
    """
    groups: dict[str, list[InventoryRecord]] = {}
    for record in records:
        key = record.relative_path.as_posix().casefold()
        groups.setdefault(key, []).append(record)

    def record_order(record: InventoryRecord) -> tuple[str, str, str, str]:
        return (
            record.relative_path.as_posix(),
            record.path.as_posix(),
            record.category.value,
            repr(record.parsed_name),
        )

    return [
        PathCaseCollision(key, tuple(sorted(groups[key], key=record_order)))
        for key in sorted(groups)
        if len({record.relative_path.as_posix() for record in groups[key]}) > 1
    ]
