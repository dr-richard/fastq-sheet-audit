"""Deterministic header aliases and explicit, index-based human mapping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .sheet import SampleSheet


class ColumnRole(Enum):
    SAMPLE = "sample"
    R1 = "r1"
    R2 = "r2"


@dataclass(frozen=True)
class ColumnReference:
    index: int
    header: str


@dataclass(frozen=True)
class RoleMapping:
    role: ColumnRole
    candidates: tuple[ColumnReference, ...]
    automatic: ColumnReference | None
    selected: ColumnReference | None
    explicit: bool

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1 and not self.explicit


@dataclass(frozen=True)
class ColumnMappingResult:
    roles: tuple[RoleMapping, ...]

    def for_role(self, role: ColumnRole) -> RoleMapping:
        return next(mapping for mapping in self.roles if mapping.role is role)

    @property
    def ambiguous(self) -> tuple[RoleMapping, ...]:
        return tuple(mapping for mapping in self.roles if mapping.ambiguous)

    @property
    def unresolved(self) -> tuple[ColumnRole, ...]:
        return tuple(mapping.role for mapping in self.roles if mapping.selected is None)

    @property
    def complete(self) -> bool:
        return all(
            self.for_role(role).selected is not None
            for role in (ColumnRole.SAMPLE, ColumnRole.R1)
        )


_ALIASES = {
    ColumnRole.SAMPLE: ("sample", "sample_id", "sampleid"),
    ColumnRole.R1: ("r1", "fastq_1", "fastq1", "read1", "read_1"),
    ColumnRole.R2: ("r2", "fastq_2", "fastq2", "read2", "read_2"),
}


def map_columns(
    sheet: SampleSheet,
    overrides: Mapping[ColumnRole, int | None] | None = None,
    *,
    require_complete: bool = False,
) -> ColumnMappingResult:
    """Map headers using only strip/casefold and the documented aliases.

    Indices are zero-based. Overrides may select any existing column, even
    without an alias; None explicitly leaves a role unmapped. Candidate and
    automatic assignments remain available after overrides for display.
    Ordinary incomplete/ambiguous mappings are returned as data. Set
    require_complete to validate that SAMPLE and R1 have selected columns;
    R2 is optional. Selected columns must be distinct across all roles.
    """
    overrides = dict(overrides) if overrides is not None else {}
    for role, index in overrides.items():
        if not isinstance(role, ColumnRole):
            raise ValueError(f"unknown column role: {role!r}")
        if index is not None and (
            type(index) is not int or not 0 <= index < len(sheet.headers)
        ):
            raise ValueError(f"{role.name}: invalid column index {index!r}")

    references = tuple(ColumnReference(i, header) for i, header in enumerate(sheet.headers))
    mappings: list[RoleMapping] = []
    used: dict[int, ColumnRole] = {}
    for role in ColumnRole:
        candidates = tuple(
            column for column in references
            if column.header.strip().casefold() in _ALIASES[role]
        )
        automatic = candidates[0] if len(candidates) == 1 else None
        explicit = role in overrides
        index = overrides.get(role)
        selected = (references[index] if index is not None else None) if explicit else automatic
        if selected is not None:
            if selected.index in used:
                raise ValueError(
                    f"column {selected.index} assigned to multiple roles: "
                    f"{used[selected.index].name} and {role.name}"
                )
            used[selected.index] = role
        mappings.append(RoleMapping(role, candidates, automatic, selected, explicit))

    result = ColumnMappingResult(tuple(mappings))
    if require_complete and not result.complete:
        missing = [role.name for role in (ColumnRole.SAMPLE, ColumnRole.R1)
                   if result.for_role(role).selected is None]
        raise ValueError("complete mapping requires resolved roles: " + ", ".join(missing))
    return result
