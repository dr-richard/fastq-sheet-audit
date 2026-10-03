"""Native audit, adjudication, preview, and explicit safe export GUI.

Manual smoke command: python -m fastq_sheet_audit.gui
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


APPLICATION_TITLE = "FASTQ Sheet Audit"
MINIMUM_SIZE = (900, 600)
INITIAL_STATUS = "Choose a FASTQ directory and sample sheet."
TAB_NAMES = ("Summary", "Findings", "FASTQ Inventory", "Pairing / Adjudication", "Export")
READ_MODE_CHOICES = (("Auto", "auto"), ("Paired", "paired"), ("Single", "single"))
SUMMARY_FIELDS = (
    ("inventory_count", "Inventory count"), ("error_count", "Errors"),
    ("warning_count", "Warnings"), ("unresolved_pair_count", "Unresolved pairs"),
    ("ready_for_export", "Ready for export"),
)


@dataclass(frozen=True)
class TableColumn:
    key: str
    label: str
    width: int = 120


FINDING_COLUMNS = (
    TableColumn("source", "Source"), TableColumn("severity", "Severity", 90),
    TableColumn("code", "Code", 180), TableColumn("message", "Message", 360),
    TableColumn("row", "Row", 60), TableColumn("sample", "Sample"), TableColumn("path", "Path", 300),
)
INVENTORY_COLUMNS = (
    TableColumn("relative_path", "Relative path", 320), TableColumn("category", "Category"),
    TableColumn("sample", "Sample"), TableColumn("read_role", "Read role", 90),
    TableColumn("lane", "Lane", 70), TableColumn("chunk", "Chunk", 70),
)
PAIR_COLUMNS = (
    TableColumn("key", "Key", 360), TableColumn("r1_candidate_count", "R1 candidates"),
    TableColumn("r2_candidate_count", "R2 candidates"), TableColumn("effective_r1", "Effective R1", 280),
    TableColumn("effective_r2", "Effective R2", 280), TableColumn("unresolved_r1_count", "Unresolved R1"),
    TableColumn("unresolved_r2_count", "Unresolved R2"), TableColumn("confirmed", "Confirmed", 90),
    TableColumn("resolved", "Resolved", 90),
)


def read_mode_value(display: str) -> Any:
    from .gui_controller import read_mode_from_label

    return read_mode_from_label(display)


@dataclass(frozen=True)
class ApplicationWindow:
    """Widget handles for future controller attachment; no audit state."""
    root: Any
    fastq_directory: Any
    sample_sheet: Any
    read_mode: Any
    status: Any
    notebook: Any
    findings_table: Any
    inventory_table: Any
    pairing_table: Any
    summary_values: tuple[tuple[str, Any], ...]
    audit_button: Any
    export_button: Any
    mapping_variables: tuple[tuple[Any, Any], ...] = ()
    mapping_boxes: tuple[Any, ...] = ()
    load_columns_button: Any = None
    mapping_state: dict = field(default_factory=dict)
    session_state: dict = field(default_factory=dict)
    r1_selection: Any = None
    r2_selection: Any = None
    confirmation: Any = None
    r1_box: Any = None
    r2_box: Any = None
    confirmation_check: Any = None
    apply_button: Any = None
    reset_button: Any = None
    profile: Any = None
    profile_box: Any = None
    path_mode: Any = None
    path_mode_box: Any = None
    target_style: Any = None
    target_style_box: Any = None
    target_root: Any = None
    target_root_entry: Any = None
    profile_notes: Any = None
    manual_fields: Any = None
    preview_button: Any = None
    output_preview: Any = None
    validation_preview: Any = None
    export_state: dict = field(default_factory=dict)
    manual_table: Any = None
    manual_column: Any = None
    manual_column_box: Any = None
    manual_value: Any = None
    manual_value_entry: Any = None
    manual_value_status: Any = None
    manual_set_button: Any = None
    manual_clear_button: Any = None
    output_format: Any = None
    output_format_box: Any = None
    output_file: Any = None
    output_file_entry: Any = None
    output_browse_button: Any = None


def disable_manual_editor(application: ApplicationWindow) -> None:
    application.manual_column.set("")
    application.manual_value.set("")
    application.manual_value_status.set("Unset")
    for control in (application.manual_column_box, application.manual_value_entry,
                    application.manual_set_button, application.manual_clear_button):
        control.configure(state="disabled")


def clear_manual_editor(application: ApplicationWindow) -> None:
    for key in ("manual_view", "manual_values", "manual_row_index"):
        application.export_state.pop(key, None)
    disable_manual_editor(application)
    children = application.manual_table.get_children()
    if children:
        application.manual_table.delete(*children)
    application.manual_table.configure(columns=())
    application.manual_column_box.configure(values=())


def render_manual_table(application: ApplicationWindow) -> None:
    view = application.export_state["manual_view"]
    children = application.manual_table.get_children()
    if children:
        application.manual_table.delete(*children)
    labels = ("row", "sample") + tuple(column.name for column in view.columns)
    application.manual_table.configure(columns=labels)
    for label in labels:
        application.manual_table.heading(label, text=label)
        application.manual_table.column(label, width=160, minwidth=50)
    values = application.export_state["manual_values"]
    for index, row in enumerate(view.rows):
        application.manual_table.insert("", "end", iid=f"manual:{index}", values=(
            row.row_number, row.sample,
            *(values.get(row.row_number, {}).get(column.name, "") for column in view.columns)))
    index = application.export_state.get("manual_row_index")
    if type(index) is int and 0 <= index < len(view.rows):
        application.manual_table.selection_set(f"manual:{index}")


def manual_row_selection_action(application: ApplicationWindow) -> None:
    selected = application.manual_table.selection()
    previous = application.export_state.get("manual_row_index")
    if type(previous) is int and selected == (f"manual:{previous}",):
        view = application.export_state.get("manual_view")
        if view is not None and 0 <= previous < len(view.rows) and application.session_state.get("session") is not None:
            return
    application.export_state.pop("manual_row_index", None)
    disable_manual_editor(application)
    view = application.export_state.get("manual_view")
    if application.session_state.get("session") is None or view is None or len(selected) != 1:
        return
    identity = selected[0]
    try:
        index = int(identity.removeprefix("manual:"))
    except (ValueError, AttributeError):
        return
    if identity != f"manual:{index}" or not 0 <= index < len(view.rows):
        return
    application.export_state["manual_row_index"] = index
    if view.columns:
        application.manual_column_box.configure(state="readonly")


def _manual_cell(application: ApplicationWindow) -> tuple[int, str]:
    view = application.export_state.get("manual_view")
    index = application.export_state.get("manual_row_index")
    column = application.manual_column.get()
    if (application.session_state.get("session") is None or view is None
            or type(index) is not int or not 0 <= index < len(view.rows)
            or column not in tuple(item.name for item in view.columns)):
        raise ValueError("Select a manual metadata row and column.")
    return view.rows[index].row_number, column


def manual_column_selection_action(application: ApplicationWindow) -> None:
    try:
        row_number, column = _manual_cell(application)
    except ValueError:
        disable_manual_editor(application)
        return
    values = application.export_state["manual_values"].get(row_number, {})
    value = values.get(column, "")
    application.manual_value.set(value)
    application.manual_value_status.set("Unset" if column not in values else
                                        "Set (empty)" if value == "" else "Set")
    for control in (application.manual_value_entry, application.manual_set_button, application.manual_clear_button):
        control.configure(state="normal")


def _edit_manual_value(application: ApplicationWindow, *, clear: bool) -> None:
    try:
        row_number, column = _manual_cell(application)
    except ValueError as error:
        application.status.set(str(error))
        return
    values = application.export_state["manual_values"]
    if clear:
        row = values.get(row_number)
        if row is not None:
            row.pop(column, None)
            if not row:
                values.pop(row_number)
    else:
        values.setdefault(row_number, {})[column] = application.manual_value.get()
    manual_column_selection_action(application)
    render_manual_table(application)
    invalidate_export_preview(application)


def set_manual_value_action(application: ApplicationWindow) -> None:
    _edit_manual_value(application, clear=False)


def clear_manual_value_action(application: ApplicationWindow) -> None:
    _edit_manual_value(application, clear=True)


def manual_edit_is_dirty(application: ApplicationWindow) -> bool:
    try:
        row_number, column = _manual_cell(application)
    except ValueError:
        return False
    stored = application.export_state["manual_values"].get(row_number, {}).get(column, "")
    return application.manual_value.get() != stored


def manual_values_snapshot(application: ApplicationWindow) -> dict[int, dict[str, str]] | None:
    view = application.export_state.get("manual_view")
    values = application.export_state.get("manual_values", {})
    result = {}
    if view is not None:
        for row in view.rows:
            stored = values.get(row.row_number, {})
            explicit = {column.name: stored[column.name] for column in view.columns if column.name in stored}
            if explicit:
                result[row.row_number] = explicit
    return result or None


def manual_metadata_signature(application: ApplicationWindow) -> tuple:
    view = application.export_state.get("manual_view")
    values = application.export_state.get("manual_values", {})
    if view is None:
        return ()
    return tuple((row.row_number, tuple(
        (column.name, column.name in values.get(row.row_number, {}),
         values.get(row.row_number, {}).get(column.name)) for column in view.columns)) for row in view.rows)


def invalidate_export_preview(application: ApplicationWindow) -> None:
    application.export_state.pop("plan", None)
    application.export_state.pop("signature", None)
    for table in (application.output_preview, application.validation_preview):
        children = table.get_children()
        if children:
            table.delete(*children)
    application.output_preview.configure(columns=())
    application.export_button.configure(state="disabled")
    for control in (application.output_format_box, application.output_file_entry, application.output_browse_button):
        control.configure(state="disabled")


def preview_signature(application: ApplicationWindow) -> tuple:
    return (application.session_state.get("session"), application.profile.get(), application.path_mode.get(),
            application.target_root.get(), application.target_style.get(), manual_metadata_signature(application))


def refresh_publication_controls(application: ApplicationWindow) -> None:
    from .gui_controller import OUTPUT_FORMAT_CHOICES

    plan = application.export_state.get("plan")
    session = application.session_state.get("session")
    current = (session is not None and plan is not None and plan.plan.result.validation.ok
               and audit_input_signature(application) == application.session_state.get("signature")
               and application.export_state.get("signature") == preview_signature(application)
               and not manual_edit_is_dirty(application))
    application.output_format_box.configure(values=tuple(label for label, _ in OUTPUT_FORMAT_CHOICES),
                                            state="readonly" if current else "disabled")
    for control in (application.output_file_entry, application.output_browse_button):
        control.configure(state="normal" if current else "disabled")
    enabled = (current and application.output_format.get() in tuple(label for label, _ in OUTPUT_FORMAT_CHOICES)
               and isinstance(application.output_file.get(), str) and application.output_file.get() != "")
    application.export_button.configure(state="normal" if enabled else "disabled")


def browse_output_file(application: ApplicationWindow) -> None:
    from tkinter import filedialog

    selected = filedialog.asksaveasfilename(parent=application.root, title="Choose output file",
                                           confirmoverwrite=False)
    if selected:
        application.output_file.set(selected)
        refresh_publication_controls(application)


def export_action(application: ApplicationWindow) -> None:
    from .gui_controller import OUTPUT_FORMAT_CHOICES, write_session_export

    try:
        session = application.session_state.get("session")
        if session is None:
            raise ValueError("Preview a valid export before writing.")
        if audit_input_signature(application) != application.session_state.get("signature"):
            raise ValueError("Inputs changed. Run Audit again before exporting.")
        if manual_edit_is_dirty(application):
            raise ValueError("Apply or clear the current manual metadata edit before export.")
        plan = application.export_state.get("plan")
        if plan is None or not plan.plan.result.validation.ok:
            raise ValueError("Preview a valid export before writing.")
        if application.export_state.get("signature") != preview_signature(application):
            raise ValueError("Export options changed. Preview again before writing.")
        format_label = application.output_format.get()
        if format_label not in tuple(label for label, _ in OUTPUT_FORMAT_CHOICES):
            raise ValueError("Choose an output format.")
        destination = application.output_file.get()
        if not isinstance(destination, str) or destination == "":
            raise ValueError("Choose an output file.")
        result = write_session_export(
            session, application.profile.get(), application.path_mode.get(), destination, format_label,
            target_root=application.target_root.get(), target_style_label=application.target_style.get(),
            explicit_values=manual_values_snapshot(application), overwrite=False)
    except (OSError, ValueError) as error:
        refresh_publication_controls(application)
        application.status.set(f"Export failed: {error}")
        return
    application.export_state.update(plan=result.plan, signature=preview_signature(application))
    render_export_plan(application, result.plan)
    refresh_publication_controls(application)
    application.status.set(f"Export written: {result.destination}")


def profile_selection_action(application: ApplicationWindow) -> None:
    from .gui_controller import manual_profile_columns, manual_metadata_view

    invalidate_export_preview(application)
    clear_manual_editor(application)
    profile = next((item for item in application.export_state.get("profiles", ())
                    if item.profile_id == application.profile.get()), None)
    application.profile_notes.set(profile.notes if profile else "")
    application.manual_fields.set("Manual fields: " + (
        ", ".join(column.name for column in manual_profile_columns(profile)) or "none"
    ) if profile else "")
    session = application.session_state.get("session")
    if profile is not None and session is not None:
        try:
            view = manual_metadata_view(session, profile.profile_id)
        except (OSError, ValueError) as error:
            application.status.set(f"Manual metadata failed: {error}")
            return
        application.export_state.update(manual_view=view, manual_values={})
        application.manual_column_box.configure(values=tuple(column.name for column in view.columns))
        render_manual_table(application)


def path_mode_action(application: ApplicationWindow) -> None:
    invalidate_export_preview(application)
    session = application.session_state.get("session")
    rebased = (session is not None and session.snapshot.ready_for_export
               and application.path_mode.get() == "Rebased root")
    application.target_root_entry.configure(state="normal" if rebased else "disabled")
    application.target_style_box.configure(state="readonly" if rebased else "disabled")
    if not rebased:
        application.target_root.set("")
        application.target_style.set("")


def refresh_export_controls(application: ApplicationWindow) -> None:
    from .gui_controller import export_profile_views, PATH_MODE_CHOICES, TARGET_STYLE_CHOICES

    invalidate_export_preview(application)
    application.output_format.set("")
    application.output_file.set("")
    profiles = export_profile_views()
    application.export_state["profiles"] = profiles
    session = application.session_state["session"]
    ready = session.snapshot.ready_for_export
    application.profile.set("")
    application.profile_box.configure(values=tuple(item.profile_id for item in profiles),
                                      state="readonly" if ready else "disabled")
    application.path_mode.set("Relative to FASTQ root")
    application.path_mode_box.configure(values=tuple(label for label, _ in PATH_MODE_CHOICES),
                                        state="readonly" if ready else "disabled")
    application.target_style_box.configure(values=tuple(label for label, _ in TARGET_STYLE_CHOICES))
    application.preview_button.configure(state="normal" if ready else "disabled")
    profile_selection_action(application)
    path_mode_action(application)


def preview_export_action(application: ApplicationWindow) -> None:
    from .gui_controller import plan_session_export

    invalidate_export_preview(application)
    try:
        session = application.session_state.get("session")
        if session is None:
            raise ValueError("Run Audit before planning export.")
        if audit_input_signature(application) != application.session_state.get("signature"):
            raise ValueError("Inputs changed. Run Audit again before planning export.")
        if not session.snapshot.ready_for_export:
            raise ValueError("workflow is not ready for export")
        profile_id = application.profile.get()
        if not profile_id:
            raise ValueError("Choose an export profile.")
        if manual_edit_is_dirty(application):
            raise ValueError("Apply or clear the current manual metadata edit before preview.")
        explicit_values = manual_values_snapshot(application)
        options = (application.path_mode.get(), application.target_root.get(), application.target_style.get())
        plan = plan_session_export(session, profile_id, options[0], target_root=options[1],
                                   target_style_label=options[2], explicit_values=explicit_values)
    except (OSError, ValueError) as error:
        application.status.set(f"Export preview failed: {error}")
        return
    application.export_state.update(plan=plan, signature=preview_signature(application))
    render_export_plan(application, plan)
    refresh_publication_controls(application)
    validation = plan.plan.result.validation
    application.status.set("Export preview valid. Choose an output format and file to export." if validation.ok else
                           f"Export preview has {len(validation.findings)} profile validation finding(s).")


def render_export_plan(application: ApplicationWindow, plan: Any) -> None:
    for table in (application.output_preview, application.validation_preview):
        children = table.get_children()
        if children:
            table.delete(*children)
    sheet = plan.plan.result.sheet
    application.output_preview.configure(columns=sheet.headers)
    for header in sheet.headers:
        application.output_preview.heading(header, text=header)
        application.output_preview.column(header, width=160, minwidth=50)
    for row in sheet.rows:
        application.output_preview.insert("", "end", values=row.cells)
    validation = plan.plan.result.validation
    for finding in validation.findings:
        application.validation_preview.insert("", "end", values=tuple(
            "" if value is None else value for value in
            (finding.code, finding.row_number, finding.column, finding.value, finding.message)))


def browse_fastq_directory(variable: Any, *, parent: Any = None, on_selected: Any = None) -> None:
    from tkinter import filedialog

    selected = filedialog.askdirectory(parent=parent, title="Choose FASTQ directory")
    if selected:
        variable.set(selected)
        if on_selected is not None:
            on_selected()


def browse_sample_sheet(variable: Any, *, parent: Any = None, on_selected: Any = None) -> None:
    from tkinter import filedialog

    selected = filedialog.askopenfilename(
        parent=parent, title="Choose sample sheet",
        filetypes=(("CSV sheets", "*.csv"), ("TSV sheets", "*.tsv")),
    )
    if selected:
        variable.set(selected)
        if on_selected is not None:
            on_selected()


def clear_column_mapping(application: ApplicationWindow) -> None:
    invalidate_audit_session(application)
    application.mapping_state.clear()
    for _, variable in application.mapping_variables:
        variable.set("Automatic")
    for box in application.mapping_boxes:
        box.configure(state="disabled", values=())


def audit_input_signature(application: ApplicationWindow) -> tuple:
    """Exact GUI inputs only; never read files to check session freshness."""
    return (
        application.fastq_directory.get(), application.sample_sheet.get(), application.read_mode.get(),
        tuple((role, variable.get()) for role, variable in application.mapping_variables),
        application.mapping_state.get("path"), application.mapping_state.get("view"),
    )


def disable_pair_editor(application: ApplicationWindow) -> None:
    application.session_state.pop("pair_index", None)
    application.r1_selection.set("Automatic")
    application.r2_selection.set("Automatic")
    application.confirmation.set(False)
    for box in (application.r1_box, application.r2_box):
        box.configure(state="disabled", values=())
    for control in (application.confirmation_check, application.apply_button, application.reset_button):
        control.configure(state="disabled")


def invalidate_audit_session(application: ApplicationWindow) -> None:
    application.session_state.clear()
    disable_pair_editor(application)
    application.export_button.configure(state="disabled")
    invalidate_export_preview(application)
    clear_manual_editor(application)
    application.export_state.clear()
    application.output_format.set("")
    application.output_file.set("")
    for variable in (application.profile, application.path_mode, application.target_root,
                     application.target_style, application.profile_notes, application.manual_fields):
        variable.set("")
    for control in (application.profile_box, application.path_mode_box, application.target_root_entry,
                    application.target_style_box, application.preview_button):
        control.configure(state="disabled")


def load_pair_editor(application: ApplicationWindow, pair_index: int) -> None:
    from .gui_controller import pair_adjudication_views

    session = application.session_state.get("session")
    if session is None or type(pair_index) is not int:
        disable_pair_editor(application)
        return
    views = pair_adjudication_views(session)
    if not 0 <= pair_index < len(views):
        disable_pair_editor(application)
        return
    view = views[pair_index]
    application.session_state["pair_index"] = view.pair_index
    application.r1_box.configure(state="readonly", values=("Automatic", "Unassigned") +
                                 tuple(choice.display for choice in view.r1_choices))
    application.r2_box.configure(state="readonly", values=("Automatic", "Unassigned") +
                                 tuple(choice.display for choice in view.r2_choices))
    application.r1_selection.set(view.r1_selection)
    application.r2_selection.set(view.r2_selection)
    application.confirmation.set(view.confirmed)
    for control in (application.confirmation_check, application.apply_button, application.reset_button):
        control.configure(state="normal")


def pair_selection_action(application: ApplicationWindow) -> None:
    selected = application.pairing_table.selection()
    if len(selected) != 1:
        disable_pair_editor(application)
        return
    identity = selected[0]
    try:
        index = int(identity.removeprefix("pair:"))
    except (ValueError, AttributeError):
        disable_pair_editor(application)
        return
    if identity != f"pair:{index}":
        disable_pair_editor(application)
        return
    load_pair_editor(application, index)


def _apply_pair_action(application: ApplicationWindow, *, reset: bool) -> None:
    from .gui_controller import apply_pair_adjudication, pair_adjudication_views

    invalidate_export_preview(application)
    try:
        session = application.session_state.get("session")
        if session is None:
            raise ValueError("Run Audit and select a pair before adjudicating.")
        if audit_input_signature(application) != application.session_state.get("signature"):
            raise ValueError("Inputs changed. Run Audit again before adjudicating.")
        index = application.session_state.get("pair_index")
        if type(index) is not int or not 0 <= index < len(pair_adjudication_views(session)):
            raise ValueError("Select a valid pair before adjudicating.")
        new_session = apply_pair_adjudication(
            session, index, "Automatic" if reset else application.r1_selection.get(),
            "Automatic" if reset else application.r2_selection.get(),
            False if reset else application.confirmation.get(),
        )
    except (ValueError, OSError) as error:
        application.status.set(str(error))
        application.export_button.configure(state="disabled")
        return
    application.session_state["session"] = new_session
    render_workflow(application, new_session.view)
    refresh_export_controls(application)
    application.pairing_table.selection_set(f"pair:{index}")
    application.pairing_table.see(f"pair:{index}")
    load_pair_editor(application, index)
    application.status.set("Pair decision reset to automatic. Workflow revalidated." if reset else
                           "Pair decision applied. Workflow revalidated.")


def apply_pair_action(application: ApplicationWindow) -> None:
    _apply_pair_action(application, reset=False)


def reset_pair_action(application: ApplicationWindow) -> None:
    _apply_pair_action(application, reset=True)


def load_columns_action(application: ApplicationWindow) -> None:
    from .gui_controller import inspect_sheet_mapping

    clear_column_mapping(application)
    path = application.sample_sheet.get()
    try:
        view = inspect_sheet_mapping(path)
    except (OSError, ValueError) as error:
        application.status.set(f"Load columns failed: {error}")
        return
    application.mapping_state.update(path=path, view=view)
    choices = ("Automatic", "Unassigned") + tuple(choice.display for choice in view.choices)
    roles = {item.role: item for item in view.roles}
    for (role, variable), box in zip(application.mapping_variables, application.mapping_boxes):
        box.configure(state="readonly", values=choices)
        selected = roles[role].selected
        variable.set(view.choices[selected].display if selected is not None else "Automatic")
    unresolved = ", ".join(item.role.name for item in view.roles if item.selected is None)
    application.status.set(f"Columns loaded. Unresolved roles: {unresolved}." if unresolved else "Columns loaded.")


def clear_audit_view(application: ApplicationWindow) -> None:
    for table in (application.findings_table, application.inventory_table, application.pairing_table):
        children = table.get_children()
        if children:
            table.delete(*children)
    for _, variable in application.summary_values:
        variable.set("—")
    application.export_button.configure(state="disabled")


def render_workflow(application: ApplicationWindow, view: Any) -> None:
    """Render a presentation view with no scientific interpretation."""
    clear_audit_view(application)
    for key, variable in application.summary_values:
        value = getattr(view.summary, key)
        variable.set(("Ready" if value else "Not ready") if key == "ready_for_export" else str(value))
    def cells(values: tuple) -> tuple:
        return tuple("" if value is None else value for value in values)
    for row in view.findings:
        application.findings_table.insert("", "end", values=cells((
            row.source, row.severity, row.code, row.message, row.row_number, row.sample, row.path,
        )))
    for row in view.inventory:
        application.inventory_table.insert("", "end", values=cells((
            row.relative_path, row.category, row.sample, row.read_role, row.lane, row.chunk,
        )))
    for index, row in enumerate(view.pairs):
        application.pairing_table.insert("", "end", iid=f"pair:{index}", values=cells((
            row.key_text, row.r1_candidate_count, row.r2_candidate_count, row.effective_r1,
            row.effective_r2, row.unresolved_r1_count, row.unresolved_r2_count, row.confirmed, row.resolved,
        )))


def audit_action(application: ApplicationWindow) -> None:
    from .gui_controller import audit_session, inspect_sheet_mapping, mapping_overrides

    invalidate_audit_session(application)
    clear_audit_view(application)
    application.status.set("Auditing…")
    try:
        overrides = None
        if application.mapping_state:
            path = application.sample_sheet.get()
            if path != application.mapping_state["path"]:
                clear_column_mapping(application)
                raise ValueError("Sample-sheet path changed. Load columns again.")
            view = application.mapping_state["view"]
            if inspect_sheet_mapping(path) != view:
                clear_column_mapping(application)
                raise ValueError("Sample-sheet columns changed. Load columns again.")
            overrides = mapping_overrides(view, {role: variable.get() for role, variable in application.mapping_variables})
        session = audit_session(application.fastq_directory.get(), application.sample_sheet.get(),
                            application.read_mode.get(), overrides=overrides)
    except (OSError, ValueError) as error:
        application.status.set(f"Audit failed: {error}")
        return
    application.session_state.update(session=session, signature=audit_input_signature(application))
    view = session.view
    render_workflow(application, view)
    refresh_export_controls(application)
    application.status.set(
        f"Audit complete: {view.summary.inventory_count} FASTQs, "
        f"{view.summary.error_count} errors, {view.summary.warning_count} warnings."
    )


def build_application(root: Any) -> ApplicationWindow:
    """Construct widgets on an existing root without scanning or loading data."""
    import tkinter as tk
    from tkinter import ttk
    from .gui_controller import ColumnRole

    root.title(APPLICATION_TITLE)
    root.minsize(*MINIMUM_SIZE)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    frame = ttk.Frame(root, padding=12)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)
    inputs = ttk.LabelFrame(frame, text="Inputs", padding=8)
    inputs.grid(row=0, column=0, sticky="ew", pady=(0, 10))
    inputs.columnconfigure(1, weight=1)
    fastq_directory = tk.StringVar(root, value="")
    sample_sheet = tk.StringVar(root, value="")
    read_mode = tk.StringVar(root, value="Auto")
    status = tk.StringVar(root, value=INITIAL_STATUS)
    for row, (label, variable) in enumerate((
        ("FASTQ directory", fastq_directory), ("Sample sheet", sample_sheet),
    )):
        ttk.Label(inputs, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(inputs, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        if row == 0:
            command = lambda: browse_fastq_directory(fastq_directory, parent=root,
                                                     on_selected=lambda: invalidate_audit_session(application))
        else:
            command = lambda: browse_sample_sheet(sample_sheet, parent=root,
                                                  on_selected=lambda: clear_column_mapping(application))
        ttk.Button(inputs, text="Browse", command=command).grid(row=row, column=2, padx=(8, 0), pady=4)
    ttk.Label(inputs, text="Read mode").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Combobox(inputs, textvariable=read_mode, state="readonly",
                 values=tuple(label for label, _ in READ_MODE_CHOICES)).grid(row=2, column=1, sticky="w")
    audit_button = ttk.Button(inputs, text="Audit")
    audit_button.grid(row=2, column=2, padx=(8, 0))
    mapping_frame = ttk.LabelFrame(inputs, text="Column mapping", padding=8)
    mapping_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
    mapping_variables, mapping_boxes = [], []
    for column, (role, label) in enumerate((
        (ColumnRole.SAMPLE, "Sample column"), (ColumnRole.R1, "R1 column"), (ColumnRole.R2, "R2 column"),
    )):
        mapping_frame.columnconfigure(column, weight=1)
        ttk.Label(mapping_frame, text=label).grid(row=0, column=column, sticky="w")
        variable = tk.StringVar(root, value="Automatic")
        box = ttk.Combobox(mapping_frame, textvariable=variable, state="disabled")
        box.grid(row=1, column=column, sticky="ew", padx=(0, 8))
        mapping_variables.append((role, variable))
        mapping_boxes.append(box)
    load_columns_button = ttk.Button(mapping_frame, text="Load columns")
    load_columns_button.grid(row=1, column=3)

    notebook = ttk.Notebook(frame)
    notebook.grid(row=1, column=0, sticky="nsew")
    tabs = []
    for name in TAB_NAMES:
        tab = ttk.Frame(notebook, padding=8)
        tab.columnconfigure(0, weight=1)
        notebook.add(tab, text=name)
        tabs.append(tab)
    summary_values = []
    for row, (key, label) in enumerate(SUMMARY_FIELDS):
        variable = tk.StringVar(root, value="—")
        ttk.Label(tabs[0], text=label).grid(row=row, column=0, sticky="w", pady=8)
        ttk.Label(tabs[0], textvariable=variable).grid(row=row, column=1, sticky="w", padx=24)
        summary_values.append((key, variable))

    def table(tab: Any, columns: tuple[TableColumn, ...]) -> Any:
        tab.rowconfigure(0, weight=1)
        tree = ttk.Treeview(tab, columns=tuple(column.key for column in columns), show="headings")
        for column in columns:
            tree.heading(column.key, text=column.label)
            tree.column(column.key, width=column.width, minwidth=50, stretch=True)
        vertical = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(tab, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return tree

    findings_table = table(tabs[1], FINDING_COLUMNS)
    inventory_table = table(tabs[2], INVENTORY_COLUMNS)
    pairing_table = table(tabs[3], PAIR_COLUMNS)
    controls = ttk.Frame(tabs[3])
    controls.grid(row=2, column=0, sticky="w", pady=(8, 0))
    controls.columnconfigure(0, weight=1)
    controls.columnconfigure(1, weight=1)
    controls.grid_configure(sticky="ew")
    r1_selection = tk.StringVar(root, value="Automatic")
    r2_selection = tk.StringVar(root, value="Automatic")
    confirmation = tk.BooleanVar(root, value=False)
    ttk.Label(controls, text="R1 selection").grid(row=0, column=0, sticky="w")
    ttk.Label(controls, text="R2 selection").grid(row=0, column=1, sticky="w")
    r1_box = ttk.Combobox(controls, textvariable=r1_selection, state="disabled")
    r2_box = ttk.Combobox(controls, textvariable=r2_selection, state="disabled")
    r1_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
    r2_box.grid(row=1, column=1, sticky="ew", padx=(0, 8))
    confirmation_check = ttk.Checkbutton(controls, text="Confirmed", variable=confirmation, state="disabled")
    confirmation_check.grid(row=1, column=2, padx=(0, 8))
    apply_button = ttk.Button(controls, text="Apply decision", state="disabled")
    apply_button.grid(row=1, column=3, padx=(0, 8))
    reset_button = ttk.Button(controls, text="Reset automatic", state="disabled")
    reset_button.grid(row=1, column=4)

    export_tab = tabs[4]
    export_tab.columnconfigure(1, weight=1)
    export_variables = [tk.StringVar(root, value="") for _ in range(5)]
    export_widgets = []
    for row, (label, variable) in enumerate(zip(
            ("Profile", "Path mode", "Target style", "Target root", "Output file"), export_variables)):
        ttk.Label(export_tab, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=8)
        widget = (ttk.Combobox(export_tab, textvariable=variable, state="disabled") if row < 3
                  else ttk.Entry(export_tab, textvariable=variable, state="disabled"))
        widget.grid(row=row, column=1, sticky="ew", pady=8)
        export_widgets.append(widget)
    profile_notes = tk.StringVar(root, value="")
    manual_fields = tk.StringVar(root, value="")
    ttk.Label(export_tab, textvariable=profile_notes, wraplength=800).grid(row=6, column=0, columnspan=2, sticky="ew")
    ttk.Label(export_tab, textvariable=manual_fields).grid(row=7, column=0, columnspan=2, sticky="w")
    preview_button = ttk.Button(export_tab, text="Preview export", state="disabled")
    preview_button.grid(row=5, column=0, sticky="w")
    output_format = tk.StringVar(root, value="")
    ttk.Label(export_tab, text="Output format").grid(row=11, column=0, sticky="w")
    output_format_box = ttk.Combobox(export_tab, textvariable=output_format, state="disabled")
    output_format_box.grid(row=11, column=1, sticky="ew")
    output_browse_button = ttk.Button(export_tab, text="Browse", state="disabled")
    output_browse_button.grid(row=4, column=2, padx=8)
    manual_frame = ttk.LabelFrame(export_tab, text="Manual metadata", padding=4)
    manual_frame.grid(row=8, column=0, columnspan=2, sticky="nsew")
    manual_frame.columnconfigure(0, weight=1)
    export_tab.rowconfigure(8, weight=1)
    manual_table = table(manual_frame, ())
    editor = ttk.Frame(manual_frame)
    editor.grid(row=2, column=0, columnspan=2, sticky="ew")
    editor.columnconfigure(1, weight=1)
    manual_column = tk.StringVar(root, value="")
    manual_value = tk.StringVar(root, value="")
    manual_value_status = tk.StringVar(root, value="Unset")
    manual_column_box = ttk.Combobox(editor, textvariable=manual_column, state="disabled")
    manual_column_box.grid(row=0, column=0, padx=(0, 8))
    manual_value_entry = ttk.Entry(editor, textvariable=manual_value, state="disabled")
    manual_value_entry.grid(row=0, column=1, sticky="ew")
    ttk.Label(editor, textvariable=manual_value_status).grid(row=0, column=2, padx=8)
    manual_set_button = ttk.Button(editor, text="Set", state="disabled")
    manual_set_button.grid(row=0, column=3)
    manual_clear_button = ttk.Button(editor, text="Clear", state="disabled")
    manual_clear_button.grid(row=0, column=4)
    preview_tables = []
    for row, label, columns in (
        (9, "Candidate output", ()),
        (10, "Profile validation", tuple(TableColumn(key, key.title()) for key in
                                        ("code", "row", "column", "value", "message"))),
    ):
        container = ttk.LabelFrame(export_tab, text=label, padding=4)
        container.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=4)
        container.columnconfigure(0, weight=1)
        export_tab.rowconfigure(row, weight=1)
        preview_tables.append(table(container, columns))
    export_button = ttk.Button(export_tab, text="Export", state="disabled")
    export_button.grid(row=5, column=1, sticky="e", pady=8)
    ttk.Label(frame, textvariable=status, wraplength=850).grid(row=2, column=0, sticky="ew", pady=(10, 0))
    application = ApplicationWindow(root, fastq_directory, sample_sheet, read_mode, status, notebook,
                             findings_table, inventory_table, pairing_table, tuple(summary_values),
                             audit_button, export_button, tuple(mapping_variables), tuple(mapping_boxes),
                             load_columns_button, session_state={}, r1_selection=r1_selection,
                             r2_selection=r2_selection, confirmation=confirmation, r1_box=r1_box, r2_box=r2_box,
                             confirmation_check=confirmation_check, apply_button=apply_button, reset_button=reset_button,
                             profile=export_variables[0], profile_box=export_widgets[0],
                             path_mode=export_variables[1], path_mode_box=export_widgets[1],
                             target_style=export_variables[2], target_style_box=export_widgets[2],
                             target_root=export_variables[3], target_root_entry=export_widgets[3],
                             profile_notes=profile_notes, manual_fields=manual_fields, preview_button=preview_button,
                             output_preview=preview_tables[0], validation_preview=preview_tables[1],
                             manual_table=manual_table, manual_column=manual_column, manual_column_box=manual_column_box,
                             manual_value=manual_value, manual_value_entry=manual_value_entry,
                             manual_value_status=manual_value_status, manual_set_button=manual_set_button,
                             manual_clear_button=manual_clear_button, output_format=output_format,
                             output_format_box=output_format_box, output_file=export_variables[4],
                             output_file_entry=export_widgets[4], output_browse_button=output_browse_button)
    audit_button.configure(command=lambda: audit_action(application))
    load_columns_button.configure(command=lambda: load_columns_action(application))
    pairing_table.bind("<<TreeviewSelect>>", lambda event: pair_selection_action(application))
    apply_button.configure(command=lambda: apply_pair_action(application))
    reset_button.configure(command=lambda: reset_pair_action(application))
    export_widgets[0].bind("<<ComboboxSelected>>", lambda event: profile_selection_action(application))
    export_widgets[1].bind("<<ComboboxSelected>>", lambda event: path_mode_action(application))
    for box in mapping_boxes:
        box.bind("<<ComboboxSelected>>", lambda event: invalidate_audit_session(application))
    preview_button.configure(command=lambda: preview_export_action(application))
    manual_table.bind("<<TreeviewSelect>>", lambda event: manual_row_selection_action(application))
    manual_column_box.bind("<<ComboboxSelected>>", lambda event: manual_column_selection_action(application))
    manual_set_button.configure(command=lambda: set_manual_value_action(application))
    manual_clear_button.configure(command=lambda: clear_manual_value_action(application))
    output_format_box.bind("<<ComboboxSelected>>", lambda event: refresh_publication_controls(application))
    export_variables[4].trace_add("write", lambda *args: refresh_publication_controls(application))
    manual_value.trace_add("write", lambda *args: refresh_publication_controls(application))
    output_browse_button.configure(command=lambda: browse_output_file(application))
    export_button.configure(command=lambda: export_action(application))
    refresh_publication_controls(application)
    return application


def set_application_icon(root: Any) -> None:
    """Load the bundled PNG without making optional window decoration fatal."""
    import tkinter as tk
    from importlib.resources import as_file, files

    try:
        resource = files("fastq_sheet_audit").joinpath("assets", "app_icon.png")
        with as_file(resource) as path:
            icon = tk.PhotoImage(master=root, file=str(path))
        root.iconphoto(True, icon)
        root._app_icon = icon  # Keep the image alive for the root's lifetime.
    except Exception:
        # Icon/resource/Tk failures must not prevent the application launching.
        pass


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    set_application_icon(root)
    application = build_application(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
