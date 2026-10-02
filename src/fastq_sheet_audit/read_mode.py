"""Explicit read-layout diagnostics over exact biological pair identities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .inventory import InventoryRecord
from .pairing import PairGroup, PairKey, PairStatus, group_pairs, pair_key


class ReadMode(Enum):
    AUTO = "auto"
    PAIRED = "paired"
    SINGLE = "single"


class ReadLayout(Enum):
    PAIRED = "paired"
    SINGLE = "single"
    UNRESOLVED = "unresolved"


class DiagnosticSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ReadModeDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    key: PairKey | None
    records: tuple[InventoryRecord, ...]


@dataclass(frozen=True)
class ReadModeResult:
    mode: ReadMode
    layout: ReadLayout
    groups: tuple[PairGroup, ...]
    excluded: tuple[InventoryRecord, ...]
    diagnostics: tuple[ReadModeDiagnostic, ...]

    @property
    def ok(self) -> bool:
        return not self.diagnostics


def diagnose_read_mode(
    records: Iterable[InventoryRecord], mode: ReadMode = ReadMode.AUTO,
) -> ReadModeResult:
    """Validate a requested layout or infer AUTO without inventing mates.

    Explicit modes report the requested layout even if diagnostics show that
    it is violated. AUTO with no biological reads is unresolved. Nonpairable
    inventory records are retained in excluded and never influence inference.
    No filesystem access or mutation occurs.
    """
    if not isinstance(mode, ReadMode):
        raise ValueError("mode must be a ReadMode")
    ordered = tuple(sorted(records, key=lambda record: (
        record.relative_path.as_posix(), record.path.as_posix(),
        record.category.value, repr(record.parsed_name),
    )))
    groups = tuple(group_pairs(ordered))
    excluded = tuple(record for record in ordered if pair_key(record) is None)
    diagnostics: list[ReadModeDiagnostic] = []

    if mode is ReadMode.PAIRED:
        layout = ReadLayout.PAIRED
        for group in groups:
            if group.status is PairStatus.AMBIGUOUS:
                diagnostics.append(ReadModeDiagnostic(
                    "AMBIGUOUS_PAIR", DiagnosticSeverity.ERROR,
                    "multiple biological files occupy the same exact read role",
                    group.key, group.r1 + group.r2,
                ))
            if not group.r2:
                diagnostics.append(ReadModeDiagnostic(
                    "MISSING_R2", DiagnosticSeverity.ERROR,
                    "biological R1 has no exact R2 mate", group.key, group.r1,
                ))
            if not group.r1:
                diagnostics.append(ReadModeDiagnostic(
                    "MISSING_R1", DiagnosticSeverity.ERROR,
                    "biological R2 has no exact R1 mate", group.key, group.r2,
                ))
    elif mode is ReadMode.SINGLE:
        layout = ReadLayout.SINGLE
        for group in groups:
            if group.r2:
                diagnostics.append(ReadModeDiagnostic(
                    "UNEXPECTED_R2", DiagnosticSeverity.ERROR,
                    "biological R2 is present in single-read mode", group.key, group.r2,
                ))
    else:
        statuses = {group.status for group in groups}
        if statuses == {PairStatus.COMPLETE}:
            layout = ReadLayout.PAIRED
        elif statuses == {PairStatus.R1_ONLY}:
            layout = ReadLayout.SINGLE
        else:
            layout = ReadLayout.UNRESOLVED
            biological = tuple(record for record in ordered if pair_key(record) is not None)
            diagnostics.append(ReadModeDiagnostic(
                "AUTO_UNRESOLVED", DiagnosticSeverity.WARNING,
                ("no pairable biological reads to infer a layout" if not groups else
                 "biological groups are mixed, orphaned, or ambiguous; layout is unresolved"),
                None, biological,
            ))

    # Group order comes from exact pairing; code breaks ties within a group.
    group_indices = {group.key: index for index, group in enumerate(groups)}
    diagnostics.sort(key=lambda diagnostic: (
        group_indices.get(diagnostic.key, -1), diagnostic.code,
    ))
    return ReadModeResult(mode, layout, groups, excluded, tuple(diagnostics))
