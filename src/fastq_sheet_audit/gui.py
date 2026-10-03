"""Native read-only audit GUI; export and adjudication are not connected.

Manual smoke command: python -m fastq_sheet_audit.gui
"""

from __future__ import annotations

from dataclasses import dataclass
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


def browse_fastq_directory(variable: Any, *, parent: Any = None) -> None:
    from tkinter import filedialog

    selected = filedialog.askdirectory(parent=parent, title="Choose FASTQ directory")
    if selected:
        variable.set(selected)


def browse_sample_sheet(variable: Any, *, parent: Any = None) -> None:
    from tkinter import filedialog

    selected = filedialog.askopenfilename(
        parent=parent, title="Choose sample sheet",
        filetypes=(("CSV sheets", "*.csv"), ("TSV sheets", "*.tsv")),
    )
    if selected:
        variable.set(selected)


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
    for row in view.pairs:
        application.pairing_table.insert("", "end", values=cells((
            row.key_text, row.r1_candidate_count, row.r2_candidate_count, row.effective_r1,
            row.effective_r2, row.unresolved_r1_count, row.unresolved_r2_count, row.confirmed, row.resolved,
        )))


def audit_action(application: ApplicationWindow) -> None:
    from .gui_controller import audit_inputs

    clear_audit_view(application)
    application.status.set("Auditing…")
    try:
        view = audit_inputs(application.fastq_directory.get(), application.sample_sheet.get(),
                            application.read_mode.get())
    except (OSError, ValueError) as error:
        application.status.set(f"Audit failed: {error}")
        return
    render_workflow(application, view)
    application.status.set(
        f"Audit complete: {view.summary.inventory_count} FASTQs, "
        f"{view.summary.error_count} errors, {view.summary.warning_count} warnings."
    )


def build_application(root: Any) -> ApplicationWindow:
    """Construct widgets on an existing root without scanning or loading data."""
    import tkinter as tk
    from tkinter import ttk

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
        browse = browse_fastq_directory if row == 0 else browse_sample_sheet
        ttk.Button(inputs, text="Browse", command=lambda action=browse, value=variable:
                   action(value, parent=root)).grid(row=row, column=2, padx=(8, 0), pady=4)
    ttk.Label(inputs, text="Read mode").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Combobox(inputs, textvariable=read_mode, state="readonly",
                 values=tuple(label for label, _ in READ_MODE_CHOICES)).grid(row=2, column=1, sticky="w")
    audit_button = ttk.Button(inputs, text="Audit")
    audit_button.grid(row=2, column=2, padx=(8, 0))

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
    for column, label in enumerate(("Select R1", "Select R2", "Unassign", "Confirm")):
        ttk.Button(controls, text=label, state="disabled").grid(row=0, column=column, padx=(0, 8))

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
                             audit_button, export_button)
    audit_button.configure(command=lambda: audit_action(application))
    return application


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    application = build_application(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
