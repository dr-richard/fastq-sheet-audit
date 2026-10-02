"""Explicit human role decisions preserving automatic pairing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .inventory import InventoryRecord
from .pairing import PairGroup, PairKey


class RoleDecisionKind(Enum):
    AUTOMATIC = "automatic"
    SELECT = "select"
    UNASSIGN = "unassign"


@dataclass(frozen=True)
class RoleDecision:
    kind: RoleDecisionKind
    selected: InventoryRecord | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RoleDecisionKind):
            raise ValueError("kind must be a RoleDecisionKind")
        if self.kind is RoleDecisionKind.SELECT:
            if not isinstance(self.selected, InventoryRecord):
                raise ValueError("SELECT requires an InventoryRecord")
        elif self.selected is not None:
            raise ValueError(f"{self.kind.name} requires selected=None")


@dataclass(frozen=True)
class PairDecision:
    key: PairKey
    r1: RoleDecision
    r2: RoleDecision
    confirmed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.key, PairKey):
            raise ValueError("key must be a PairKey")
        if not isinstance(self.r1, RoleDecision) or not isinstance(self.r2, RoleDecision):
            raise ValueError("r1 and r2 must be RoleDecision objects")
        if type(self.confirmed) is not bool:
            raise ValueError("confirmed must be a boolean")


@dataclass(frozen=True)
class PairResolution:
    group: PairGroup
    decision: PairDecision
    effective_r1: InventoryRecord | None
    effective_r2: InventoryRecord | None
    unresolved_r1: tuple[InventoryRecord, ...]
    unresolved_r2: tuple[InventoryRecord, ...]
    confirmed: bool

    @property
    def resolved(self) -> bool:
        """Require valid evidence, no unresolved candidates, and effective R1.

        An unambiguous R1-only group meets this definition; this property does
        not impose a paired-read layout or require human confirmation.
        """
        try:
            expected = resolve_pair_group(self.group, self.decision)
        except ValueError:
            return False
        return (
            self == expected
            and self.effective_r1 is not None
            and not self.unresolved_r1
            and not self.unresolved_r2
            and type(self.confirmed) is bool
        )


def _resolve_role(
    candidates: tuple[InventoryRecord, ...], decision: RoleDecision,
) -> tuple[InventoryRecord | None, tuple[InventoryRecord, ...]]:
    if decision.kind is RoleDecisionKind.AUTOMATIC:
        if len(candidates) == 1:
            return candidates[0], ()
        return None, candidates
    if decision.kind is RoleDecisionKind.UNASSIGN:
        return None, ()
    if decision.selected not in candidates:
        raise ValueError("selected record is not a candidate for this role")
    return decision.selected, ()


def resolve_pair_group(group: PairGroup, decision: PairDecision) -> PairResolution:
    """Resolve explicit role choices without mutation, reordering, or I/O.

    Membership uses complete InventoryRecord equality. SELECT and UNASSIGN
    adjudicate their role, clearing unresolved candidates while retaining all
    evidence in group. Confirmation is copied verbatim and never overrides
    AUTOMATIC ambiguity or missing effective R1.
    """
    if not isinstance(decision, PairDecision):
        raise ValueError("decision must be a PairDecision")
    if decision.key != group.key:
        raise ValueError("decision key does not match group key")
    r1, unresolved_r1 = _resolve_role(group.r1, decision.r1)
    r2, unresolved_r2 = _resolve_role(group.r2, decision.r2)
    return PairResolution(group, decision, r1, r2, unresolved_r1, unresolved_r2, decision.confirmed)
