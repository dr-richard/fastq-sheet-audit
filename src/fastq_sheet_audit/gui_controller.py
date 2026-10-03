"""Thin read-only orchestration for an explicit GUI audit action."""

from pathlib import Path
from dataclasses import dataclass, replace
from typing import Mapping

from .adjudication import PairDecision, RoleDecision, RoleDecisionKind
from .column_mapping import ColumnMappingResult, ColumnRole, map_columns
from .inventory import InventoryRecord, scan_fastqs
from .export_plan import ExportPlan, build_export_plan
from .export_io import write_sheet_atomic
from .pairing import PairKey
from .pathmap import ExportMode, TargetStyle
from .presentation import WorkflowView, present_workflow
from .profiles import Profile, list_profile_ids, load_profile
from .read_mode import ReadMode
from .sheet import SampleSheet, load_sheet
from .serialization import SheetFormat
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
    sample_sheet_path: Path


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
    return AuditSession(sheet, mapping, snapshot.inventory, root, mode, (), snapshot,
                        present_workflow(snapshot), sheet_path.absolute())


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


@dataclass(frozen=True)
class ExportProfileColumnView:
    name: str
    required_column: bool
    required_value: bool
    value_type: str
    allowed_values: tuple[str, ...] | tuple[int, ...] | None
    source_role: str | None


@dataclass(frozen=True)
class ExportProfileView:
    profile_id: str
    display_name: str
    input_kind: str
    columns: tuple[ExportProfileColumnView, ...]
    notes: str


def _export_profile_view(profile: Profile) -> ExportProfileView:
    return ExportProfileView(profile.profile_id, profile.display_name, profile.input_kind, tuple(
        ExportProfileColumnView(column.name, column.required_column, column.required_value,
                                column.value_type, column.allowed_values, column.source_role)
        for column in profile.columns
    ), profile.notes)


def export_profile_views() -> tuple[ExportProfileView, ...]:
    return tuple(_export_profile_view(load_profile(profile_id)) for profile_id in list_profile_ids())


PATH_MODE_CHOICES = (
    ("Local absolute", ExportMode.LOCAL_ABSOLUTE),
    ("Relative to FASTQ root", ExportMode.RELATIVE_TO_ROOT),
    ("Rebased root", ExportMode.REBASED_ROOT),
)
TARGET_STYLE_CHOICES = (("POSIX", TargetStyle.POSIX), ("Windows", TargetStyle.WINDOWS))


def path_mode_from_label(label: str) -> ExportMode:
    for display, mode in PATH_MODE_CHOICES:
        if label == display:
            return mode
    raise ValueError(f"unknown path mode: {label!r}")


def target_style_from_label(label: str) -> TargetStyle:
    for display, style in TARGET_STYLE_CHOICES:
        if label == display:
            return style
    raise ValueError(f"unknown target style: {label!r}")


def manual_profile_columns(profile_view: ExportProfileView) -> tuple[ExportProfileColumnView, ...]:
    return tuple(column for column in profile_view.columns if column.source_role is None)


@dataclass(frozen=True)
class ManualMetadataRowView:
    row_number: int
    sample: str


@dataclass(frozen=True)
class ManualMetadataView:
    profile_view: ExportProfileView
    columns: tuple[ExportProfileColumnView, ...]
    rows: tuple[ManualMetadataRowView, ...]


def manual_metadata_view(session: AuditSession, profile_id: str) -> ManualMetadataView:
    """Present manual columns and exact source samples without loading audit inputs."""
    profile_view = _export_profile_view(load_profile(profile_id))
    sample_roles = tuple(item for item in session.mapping.roles if item.role is ColumnRole.SAMPLE)
    if len(sample_roles) != 1 or sample_roles[0].selected is None:
        raise ValueError("mapping requires a selected SAMPLE column")
    selected = sample_roles[0].selected
    headers = session.sheet.headers
    if type(selected.index) is not int or not 0 <= selected.index < len(headers):
        raise ValueError("invalid SAMPLE column index")
    if selected.header != headers[selected.index]:
        raise ValueError("selected SAMPLE header does not match the sheet")
    rows = []
    seen = set()
    for row in session.sheet.rows:
        if len(row.cells) != len(headers):
            raise ValueError("source row cell count does not match headers")
        if type(row.row_number) is not int:
            raise ValueError("source row number must be an integer")
        if row.row_number in seen:
            raise ValueError("duplicate source row number")
        seen.add(row.row_number)
        rows.append(ManualMetadataRowView(row.row_number, row.cells[selected.index]))
    return ManualMetadataView(profile_view, manual_profile_columns(profile_view), tuple(rows))


@dataclass(frozen=True)
class SessionExportPlan:
    profile_view: ExportProfileView
    plan: ExportPlan


def plan_session_export(
    session: AuditSession,
    profile_id: str,
    path_mode_label: str,
    *,
    target_root: str = "",
    target_style_label: str = "",
    explicit_values: Mapping[int, Mapping[str, str]] | None = None,
) -> SessionExportPlan:
    """Delegate pure planning; bundled profile loading is the only resource I/O.

    Missing/invalid manual values remain profile validation findings in the
    returned plan. No sheet reload, FASTQ rescan, or output write occurs.
    """
    profile = load_profile(profile_id)
    mode = path_mode_from_label(path_mode_label)
    if mode is ExportMode.REBASED_ROOT:
        if not target_root:
            raise ValueError("Rebased root requires a target root")
        style = target_style_from_label(target_style_label)
        root = target_root
    else:
        if target_root or target_style_label:
            raise ValueError("target root/style apply only to Rebased root")
        style, root = None, None
    plan = build_export_plan(session.sheet, session.mapping, session.snapshot, profile, mode,
                             target_root=root, target_style=style, explicit_values=explicit_values)
    return SessionExportPlan(_export_profile_view(profile), plan)


OUTPUT_FORMAT_CHOICES = (("CSV", SheetFormat.CSV), ("TSV", SheetFormat.TSV))


def output_format_from_label(label: str) -> SheetFormat:
    for display, format in OUTPUT_FORMAT_CHOICES:
        if label == display:
            return format
    raise ValueError(f"unknown output format: {label!r}")


@dataclass(frozen=True)
class SessionExportWriteResult:
    plan: SessionExportPlan
    destination: Path
    format: SheetFormat


def write_session_export(
    session: AuditSession,
    profile_id: str,
    path_mode_label: str,
    destination: str,
    format_label: str,
    *,
    target_root: str = "",
    target_style_label: str = "",
    explicit_values: Mapping[int, Mapping[str, str]] | None = None,
    overwrite: bool = False,
) -> SessionExportWriteResult:
    """Freshly plan and validate, then delegate publication with all inputs protected."""
    if not isinstance(destination, str) or not destination:
        raise ValueError("destination must be a non-empty string")
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a boolean")
    format = output_format_from_label(format_label)
    plan = plan_session_export(session, profile_id, path_mode_label, target_root=target_root,
                               target_style_label=target_style_label, explicit_values=explicit_values)
    if not plan.plan.result.validation.ok:
        raise ValueError("export plan has profile validation findings")
    protected_paths = (
        session.sample_sheet_path,
        *(record.path for record in session.inventory),
        *(assignment.path for assignment in session.snapshot.reconciliation.assignments),
    )
    written = write_sheet_atomic(plan.plan.result.sheet, Path(destination), format,
                                 protected_paths=protected_paths, overwrite=overwrite)
    return SessionExportWriteResult(plan, written, format)
