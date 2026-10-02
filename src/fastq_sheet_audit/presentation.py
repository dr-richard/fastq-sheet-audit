"""Pure immutable table views of workflow evidence, without audit decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .pairing import PairKey
from .workflow import WorkflowSnapshot


@dataclass(frozen=True)
class SummaryView:
    inventory_count: int
    error_count: int
    warning_count: int
    unresolved_pair_count: int
    ready_for_export: bool


@dataclass(frozen=True)
class FindingView:
    source: str
    severity: str
    code: str
    message: str
    row_number: int | None
    sample: str | None
    path: str | None


@dataclass(frozen=True)
class InventoryView:
    relative_path: str
    category: str
    sample: str | None
    read_role: str | None
    lane: int | None
    chunk: int | None


@dataclass(frozen=True)
class PairView:
    key_text: str
    r1_candidate_count: int
    r2_candidate_count: int
    effective_r1: str | None
    effective_r2: str | None
    unresolved_r1_count: int
    unresolved_r2_count: int
    confirmed: bool
    resolved: bool


@dataclass(frozen=True)
class WorkflowView:
    summary: SummaryView
    findings: tuple[FindingView, ...]
    inventory: tuple[InventoryView, ...]
    pairs: tuple[PairView, ...]


def _key_text(key: PairKey) -> str:
    return (
        f"sample={key.sample!r}; sample_number={key.sample_number}; lane={key.lane}; "
        f"chunk={key.chunk}; read_style={key.read_style!r}; suffix={key.suffix!r}; "
        f"relative_parent={key.relative_parent.as_posix()!r}"
    )


def present_workflow(snapshot: WorkflowSnapshot) -> WorkflowView:
    """Render evidence in snapshot order; counts reflect displayed rows only.

    Sources are reconciliation, read_mode, portability, and adjudication.
    Synthetic warning rows represent collisions and unresolved resolutions
    only. Multi-record evidence is displayed in messages rather than choosing
    one representative path. Readiness is copied from the workflow snapshot.
    """
    findings = [FindingView(
        "reconciliation", finding.severity.value, finding.code, finding.message,
        finding.row_number, finding.sample,
        str(finding.path) if finding.path is not None else None,
    ) for finding in snapshot.reconciliation.findings]
    for diagnostic in snapshot.read_mode.diagnostics:
        findings.append(FindingView(
            "read_mode", diagnostic.severity.value, diagnostic.code, diagnostic.message,
            None, diagnostic.key.sample if diagnostic.key is not None else None,
            str(diagnostic.records[0].path) if len(diagnostic.records) == 1 else None,
        ))
    for collision in snapshot.case_collisions:
        paths = ", ".join(repr(str(record.path)) for record in collision.records)
        findings.append(FindingView(
            "portability", "warning", "PATH_CASE_COLLISION",
            f"casefold path collision {collision.normalized_key!r}: {paths}", None, None, None,
        ))

    pairs: list[PairView] = []
    for resolution in snapshot.pair_resolutions:
        resolved = resolution.resolved
        key_text = _key_text(resolution.group.key)
        pairs.append(PairView(
            key_text, len(resolution.group.r1), len(resolution.group.r2),
            resolution.effective_r1.relative_path.as_posix() if resolution.effective_r1 is not None else None,
            resolution.effective_r2.relative_path.as_posix() if resolution.effective_r2 is not None else None,
            len(resolution.unresolved_r1), len(resolution.unresolved_r2),
            resolution.confirmed, resolved,
        ))
        if not resolved:
            r1 = ", ".join(repr(str(record.path)) for record in resolution.unresolved_r1)
            r2 = ", ".join(repr(str(record.path)) for record in resolution.unresolved_r2)
            findings.append(FindingView(
                "adjudication", "warning", "UNRESOLVED_PAIR",
                f"unresolved pair: {key_text}; unresolved R1=[{r1}]; unresolved R2=[{r2}]",
                None, resolution.group.key.sample, None,
            ))

    inventory = tuple(InventoryView(
        record.relative_path.as_posix(), record.category.value,
        record.parsed_name.sample if record.parsed_name is not None else None,
        record.parsed_name.read_role.value if record.parsed_name is not None else None,
        record.parsed_name.lane if record.parsed_name is not None else None,
        record.parsed_name.chunk if record.parsed_name is not None else None,
    ) for record in snapshot.inventory)
    summary = SummaryView(
        len(inventory), sum(finding.severity == "error" for finding in findings),
        sum(finding.severity == "warning" for finding in findings),
        sum(not pair.resolved for pair in pairs), snapshot.ready_for_export,
    )
    return WorkflowView(summary, tuple(findings), inventory, tuple(pairs))
