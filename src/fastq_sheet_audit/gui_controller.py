"""Thin read-only orchestration for an explicit GUI audit action."""

from pathlib import Path
from dataclasses import dataclass, replace
from typing import Mapping

from .adjudication import PairDecision, RoleDecision, RoleDecisionKind
from .column_mapping import ColumnMappingResult, ColumnRole, map_columns
from .inventory import InventoryRecord, scan_fastqs
from .pairing import PairKey
from .presentation import WorkflowView, present_workflow
from .read_mode import ReadMode
from .sheet import SampleSheet, load_sheet
from .workflow import WorkflowSnapshot, build_workflow_snapshot


def read_mode_from_label(label: str) -> ReadMode:
    modes = {"Auto": ReadMode.AUTO, "Paired": ReadMode.PAIRED, "Single": ReadMode.SINGLE}
    if label not in modes:
        raise ValueError(f"unknown read mode: {label!r}")
    return modes[label]


@dataclass(frozen=True)
class ColumnChoice:
    index: int
    header: str
    display: str


@dataclass(frozen=True)
class ColumnRoleView:
    role: ColumnRole
    candidates: tuple[int, ...]
    automatic: int | None
    selected: int | None
    ambiguous: bool
    explicit: bool


@dataclass(frozen=True)
class SheetMappingView:
    choices: tuple[ColumnChoice, ...]
    roles: tuple[ColumnRoleView, ...]


def inspect_sheet_mapping(sample_sheet: str) -> SheetMappingView:
    if not sample_sheet.strip():
        raise ValueError("Choose a sample sheet.")
    path = Path(sample_sheet)
    if not path.is_file():
        raise ValueError(f"Sample sheet does not exist or is not a file: {path}")
    sheet = load_sheet(path)
    mapping = map_columns(sheet)
    return SheetMappingView(
        tuple(ColumnChoice(index, header, f"[{index}] {header}")
              for index, header in enumerate(sheet.headers)),
        tuple(ColumnRoleView(item.role, tuple(column.index for column in item.candidates),
                             item.automatic.index if item.automatic is not None else None,
                             item.selected.index if item.selected is not None else None,
                             item.ambiguous, item.explicit) for item in mapping.roles),
    )


def mapping_overrides(
    view: SheetMappingView, selections: Mapping[ColumnRole, str],
) -> dict[ColumnRole, int | None]:
    """Convert exact display choices to overrides without interpreting headers."""
    choices = {choice.display: choice.index for choice in view.choices}
    overrides = {}
    for role, selection in selections.items():
        if not isinstance(role, ColumnRole):
            raise ValueError("unknown mapping role")
        if selection == "Automatic":
            continue
        if selection == "Unassigned":
            overrides[role] = None
        elif selection in choices:
            overrides[role] = choices[selection]
        else:
            raise ValueError(f"unknown column choice: {selection!r}")
    return overrides


@dataclass(frozen=True)
class AuditSession:
    sheet: SampleSheet
    mapping: ColumnMappingResult
    inventory: tuple[InventoryRecord, ...]
    fastq_root: Path
    read_mode: ReadMode
    decisions: tuple[PairDecision, ...]
    snapshot: WorkflowSnapshot
    view: WorkflowView


@dataclass(frozen=True)
class PairCandidateChoice:
    index: int
    relative_path: str
    display: str


@dataclass(frozen=True)
class PairAdjudicationView:
    pair_index: int
    key: PairKey
    r1_choices: tuple[PairCandidateChoice, ...]
    r2_choices: tuple[PairCandidateChoice, ...]
    r1_selection: str
    r2_selection: str
    confirmed: bool
    resolved: bool


def audit_session(
    fastq_directory: str, sample_sheet: str, read_mode_label: str,
    overrides: Mapping[ColumnRole, int | None] | None = None,
) -> AuditSession:
    """Audit explicit input paths; propagate errors to the GUI callback boundary."""
    if not fastq_directory.strip() or not sample_sheet.strip():
        raise ValueError("Choose a FASTQ directory and sample sheet.")
    root, sheet_path = Path(fastq_directory), Path(sample_sheet)
    if not root.is_dir():
        raise ValueError(f"FASTQ directory does not exist or is not a directory: {root}")
    if not sheet_path.is_file():
        raise ValueError(f"Sample sheet does not exist or is not a file: {sheet_path}")
    mode = read_mode_from_label(read_mode_label)
    sheet = load_sheet(sheet_path)
    mapping = map_columns(sheet, overrides)
    if mapping.ambiguous:
        roles = ", ".join(item.role.name for item in mapping.ambiguous)
        raise ValueError(f"Ambiguous column mapping: {roles}. Explicit mapping is required.")
    if not mapping.complete:
        raise ValueError("Column mapping requires SAMPLE and R1 columns.")
    root = root.absolute()
    records = scan_fastqs(root)
    snapshot = build_workflow_snapshot(sheet, mapping, records, root, read_mode=mode)
    return AuditSession(sheet, mapping, snapshot.inventory, root, mode, (), snapshot, present_workflow(snapshot))


def audit_inputs(
    fastq_directory: str, sample_sheet: str, read_mode_label: str,
    overrides: Mapping[ColumnRole, int | None] | None = None,
) -> WorkflowView:
    """Compatibility wrapper returning the presentation of a new session."""
    return audit_session(fastq_directory, sample_sheet, read_mode_label, overrides).view


def _candidate_choices(candidates: tuple[InventoryRecord, ...]) -> tuple[PairCandidateChoice, ...]:
    return tuple(PairCandidateChoice(index, record.relative_path.as_posix(),
                                    f"[{index}] {record.relative_path.as_posix()}")
                 for index, record in enumerate(candidates))


def _selection_text(decision: RoleDecision, candidates: tuple[InventoryRecord, ...]) -> str:
    if decision.kind is RoleDecisionKind.AUTOMATIC:
        return "Automatic"
    if decision.kind is RoleDecisionKind.UNASSIGN:
        return "Unassigned"
    return _candidate_choices(candidates)[candidates.index(decision.selected)].display


def pair_adjudication_views(session: AuditSession) -> tuple[PairAdjudicationView, ...]:
    """Expose existing candidate order and decisions, never selecting candidates."""
    return tuple(PairAdjudicationView(
        index, resolution.group.key, _candidate_choices(resolution.group.r1),
        _candidate_choices(resolution.group.r2),
        _selection_text(resolution.decision.r1, resolution.group.r1),
        _selection_text(resolution.decision.r2, resolution.group.r2),
        resolution.confirmed, resolution.resolved,
    ) for index, resolution in enumerate(session.snapshot.pair_resolutions))


def _role_selection(selection: str, candidates: tuple[InventoryRecord, ...]) -> RoleDecision:
    if selection == "Automatic":
        return RoleDecision(RoleDecisionKind.AUTOMATIC, None)
    if selection == "Unassigned":
        return RoleDecision(RoleDecisionKind.UNASSIGN, None)
    for choice in _candidate_choices(candidates):
        if selection == choice.display:
            return RoleDecision(RoleDecisionKind.SELECT, candidates[choice.index])
    raise ValueError(f"unknown candidate display: {selection!r}")


def apply_pair_adjudication(
    session: AuditSession, pair_index: int, r1_selection: str, r2_selection: str, confirmed: bool,
) -> AuditSession:
    """Return rebuilt state using existing workflow checks, without load/scan.

    Only explicit human decisions are stored. Resetting both roles to Automatic
    with confirmed=False removes the explicit entry. Raw evidence is retained.
    """
    if type(pair_index) is not int or not 0 <= pair_index < len(session.snapshot.pair_resolutions):
        raise ValueError("invalid or stale pair index")
    if type(confirmed) is not bool:
        raise ValueError("confirmed must be a boolean")
    group = session.snapshot.pair_resolutions[pair_index].group
    decision = PairDecision(group.key, _role_selection(r1_selection, group.r1),
                            _role_selection(r2_selection, group.r2), confirmed)
    decisions = {item.key: item for item in session.decisions}
    if (decision.r1.kind is RoleDecisionKind.AUTOMATIC
            and decision.r2.kind is RoleDecisionKind.AUTOMATIC and not confirmed):
        decisions.pop(group.key, None)
    else:
        decisions[group.key] = decision
    snapshot = build_workflow_snapshot(session.sheet, session.mapping, session.inventory,
                                       session.fastq_root, read_mode=session.read_mode, decisions=decisions)
    ordered = tuple(decisions[resolution.group.key] for resolution in snapshot.pair_resolutions
                    if resolution.group.key in decisions)
    return replace(session, decisions=ordered, snapshot=snapshot, view=present_workflow(snapshot))
