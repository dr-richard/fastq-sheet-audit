"""Native read-only audit and adjudication GUI; export is not connected.

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
    for row, label in enumerate(("Profile", "Path mode", "Target style", "Target root", "Output file")):
        ttk.Label(export_tab, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=8)
        widget = (ttk.Combobox(export_tab, state="disabled") if row < 3
                  else ttk.Entry(export_tab, state="disabled"))
        widget.grid(row=row, column=1, sticky="ew", pady=8)
    export_button = ttk.Button(export_tab, text="Export", state="disabled")
    export_button.grid(row=5, column=1, sticky="e", pady=8)
    ttk.Label(frame, textvariable=status, wraplength=850).grid(row=2, column=0, sticky="ew", pady=(10, 0))
    application = ApplicationWindow(root, fastq_directory, sample_sheet, read_mode, status, notebook,
                             findings_table, inventory_table, pairing_table, tuple(summary_values),
                             audit_button, export_button, tuple(mapping_variables), tuple(mapping_boxes),
                             load_columns_button, session_state={}, r1_selection=r1_selection,
                             r2_selection=r2_selection, confirmation=confirmation, r1_box=r1_box, r2_box=r2_box,
                             confirmation_check=confirmation_check, apply_button=apply_button, reset_button=reset_button)
    audit_button.configure(command=lambda: audit_action(application))
    load_columns_button.configure(command=lambda: load_columns_action(application))
    pairing_table.bind("<<TreeviewSelect>>", lambda event: pair_selection_action(application))
    apply_button.configure(command=lambda: apply_pair_action(application))
    reset_button.configure(command=lambda: reset_pair_action(application))
    return application


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    application = build_application(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
