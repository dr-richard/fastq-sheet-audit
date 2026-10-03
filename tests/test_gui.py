import ast
import builtins
import importlib
import inspect
import sys
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fastq_sheet_audit import gui


def test_import_does_not_import_tk_or_create_root_or_scan(monkeypatch):
    original = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"tkinter", "socket", "urllib", "requests"}:
            pytest.fail(f"GUI import accessed {name}")
        return original(name, *args, **kwargs)
    def fail(*args, **kwargs):
        pytest.fail("GUI import scanned filesystem")
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr("os.scandir", fail)
    importlib.reload(gui)


def test_deterministic_window_metadata():
    assert gui.APPLICATION_TITLE == "FASTQ Sheet Audit"
    assert gui.MINIMUM_SIZE == (900, 600)
    assert gui.TAB_NAMES == ("Summary", "Findings", "FASTQ Inventory", "Pairing / Adjudication", "Export")
    assert gui.INITIAL_STATUS == "Choose a FASTQ directory and sample sheet."
    assert tuple(label for _, label in gui.SUMMARY_FIELDS) == (
        "Inventory count", "Errors", "Warnings", "Unresolved pairs", "Ready for export",
    )


def test_table_definitions():
    assert tuple(column.key for column in gui.FINDING_COLUMNS) == (
        "source", "severity", "code", "message", "row", "sample", "path",
    )
    assert tuple(column.key for column in gui.INVENTORY_COLUMNS) == (
        "relative_path", "category", "sample", "read_role", "lane", "chunk",
    )
    assert tuple(column.key for column in gui.PAIR_COLUMNS) == (
        "key", "r1_candidate_count", "r2_candidate_count", "effective_r1", "effective_r2",
        "unresolved_r1_count", "unresolved_r2_count", "confirmed", "resolved",
    )
    for columns in (gui.FINDING_COLUMNS, gui.INVENTORY_COLUMNS, gui.PAIR_COLUMNS):
        assert isinstance(columns, tuple)
        assert all(column.width > 0 for column in columns)


@pytest.mark.parametrize("label, value", [("Auto", "auto"), ("Paired", "paired"), ("Single", "single")])
def test_read_mode_display_mapping(label, value):
    from fastq_sheet_audit.read_mode import ReadMode
    assert gui.read_mode_value(label) is ReadMode(value)


def test_unknown_read_mode_rejected():
    with pytest.raises(ValueError):
        gui.read_mode_value("AUTO")


def test_metadata_is_immutable():
    with pytest.raises(FrozenInstanceError):
        gui.FINDING_COLUMNS[0].label = "changed"


def test_entry_and_build_functions_exist():
    assert callable(gui.main)
    assert callable(gui.build_application)


def test_main_startup_boundary_without_display(monkeypatch):
    root = Mock()
    fake_tk = SimpleNamespace(Tk=Mock(return_value=root))
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    builder = Mock()
    monkeypatch.setattr(gui, "build_application", builder)
    assert gui.main() == 0
    fake_tk.Tk.assert_called_once_with()
    builder.assert_called_once_with(root)
    root.mainloop.assert_called_once_with()


def test_gui_contains_no_audit_or_network_implementation():
    source = inspect.getsource(gui)
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    assert imports <= {"__future__", "dataclasses", "typing", "tkinter", "gui_controller"}
    called_names = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called_names.intersection({
        "scan_fastqs", "reconcile", "group_pairs", "pair_key", "parse_fastq_name",
        "write_sheet_atomic", "build_workflow_snapshot", "open",
    })
    assert "re.compile" not in source
    assert "os.walk" not in source
    assert "samefile" not in source


class FakeVariable:
    def __init__(self, value="old"):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class FakeTable:
    def __init__(self, events):
        self.rows = [("old",)]
        self.events = events
    def get_children(self):
        return tuple(range(len(self.rows)))
    def delete(self, *children):
        self.events.append("clear")
        self.rows.clear()
    def insert(self, parent, index, *, values):
        self.events.append("insert")
        self.rows.append(values)


def fake_application():
    from fastq_sheet_audit.column_mapping import ColumnRole
    events = []
    return SimpleNamespace(
        findings_table=FakeTable(events), inventory_table=FakeTable(events), pairing_table=FakeTable(events),
        summary_values=tuple((key, FakeVariable()) for key, _ in gui.SUMMARY_FIELDS),
        export_button=Mock(), status=FakeVariable(), fastq_directory=FakeVariable("root"),
        sample_sheet=FakeVariable("sheet.csv"), read_mode=FakeVariable("Auto"), events=events,
        mapping_state={}, mapping_variables=tuple((role, FakeVariable("Automatic")) for role in ColumnRole),
        mapping_boxes=tuple(Mock() for _ in ColumnRole),
    )


def test_render_clears_tables_updates_summary_and_preserves_order():
    from fastq_sheet_audit.presentation import (
        FindingView, InventoryView, PairView, SummaryView, WorkflowView,
    )
    application = fake_application()
    view = WorkflowView(SummaryView(2, 1, 1, 0, False), (
        FindingView("reconciliation", "error", "E", "error", 8, "A", "path"),
        FindingView("read_mode", "warning", "W", "warning", None, None, None),
    ), (InventoryView("α/A.fastq", "read", "A", "R1", 0, None),), (
        PairView("key", 1, 0, "α/A.fastq", None, 0, 0, False, True),
    ))
    gui.render_workflow(application, view)
    assert application.events[:3] == ["clear"] * 3
    assert [row[2] for row in application.findings_table.rows] == ["E", "W"]
    assert application.findings_table.rows[1][-3:] == ("", "", "")
    assert application.inventory_table.rows == [("α/A.fastq", "read", "A", "R1", 0, "")]
    assert application.pairing_table.rows[0][3:5] == ("α/A.fastq", "")
    assert {key: variable.get() for key, variable in application.summary_values} == {
        "inventory_count": "2", "error_count": "1", "warning_count": "1",
        "unresolved_pair_count": "0", "ready_for_export": "Not ready",
    }
    application.export_button.configure.assert_called_with(state="disabled")
    gui.render_workflow(application, view)
    assert len(application.findings_table.rows) == 2


@pytest.mark.parametrize("browse, dialog", [
    (gui.browse_fastq_directory, "askdirectory"), (gui.browse_sample_sheet, "askopenfilename"),
])
@pytest.mark.parametrize("selection", ["", "/selected path"])
def test_browse_cancellation_and_selection_without_tk(monkeypatch, browse, dialog, selection):
    variable = FakeVariable("original")
    chooser = Mock(return_value=selection)
    dialogs = SimpleNamespace(**{dialog: chooser})
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(filedialog=dialogs))
    browse(variable, parent="fake root")
    assert variable.get() == (selection or "original")
    assert chooser.call_args.kwargs["parent"] == "fake root"
    if dialog == "askopenfilename":
        assert chooser.call_args.kwargs["filetypes"] == (("CSV sheets", "*.csv"), ("TSV sheets", "*.tsv"))


def test_audit_callback_localizes_expected_errors_and_clears_old_data(monkeypatch):
    from fastq_sheet_audit import gui_controller
    application = fake_application()
    def fail(*args, **kwargs):
        raise ValueError("Ambiguous mapping")
    monkeypatch.setattr(gui_controller, "audit_inputs", fail)
    gui.audit_action(application)
    assert application.status.get() == "Audit failed: Ambiguous mapping"
    assert application.findings_table.rows == []
    assert all(variable.get() == "—" for _, variable in application.summary_values)
    application.export_button.configure.assert_called_with(state="disabled")


def test_audit_callback_success_and_unexpected_error_boundary(monkeypatch):
    from fastq_sheet_audit import gui_controller
    from fastq_sheet_audit.presentation import SummaryView, WorkflowView
    application = fake_application()
    view = WorkflowView(SummaryView(2, 0, 0, 0, True), (), (), ())
    monkeypatch.setattr(gui_controller, "audit_inputs", Mock(return_value=view))
    gui.audit_action(application)
    assert application.status.get() == "Audit complete: 2 FASTQs, 0 errors, 0 warnings."
    assert dict(application.summary_values)["ready_for_export"].get() == "Ready"
    def fail(*args, **kwargs):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(gui_controller, "audit_inputs", fail)
    with pytest.raises(RuntimeError, match="unexpected"):
        gui.audit_action(application)


def test_load_columns_populates_index_choices_without_tk(tmp_path):
    from fastq_sheet_audit.column_mapping import ColumnRole
    path = tmp_path / "sheet.csv"
    path.write_text("sample,sample_id,read1\n")
    application = fake_application()
    application.sample_sheet.set(str(path))
    gui.load_columns_action(application)
    variables = dict(application.mapping_variables)
    assert variables[ColumnRole.SAMPLE].get() == "Automatic"
    assert variables[ColumnRole.R1].get() == "[2] read1"
    assert "SAMPLE" in application.status.get()
    assert application.mapping_state["path"] == str(path)
    for box in application.mapping_boxes:
        assert box.configure.call_args.kwargs == {
            "state": "readonly", "values": ("Automatic", "Unassigned", "[0] sample", "[1] sample_id", "[2] read1"),
        }


def test_stale_path_or_changed_columns_refuses_audit(tmp_path, monkeypatch):
    from fastq_sheet_audit import gui_controller
    path = tmp_path / "sheet.csv"
    path.write_text("sample,r1\n")
    application = fake_application()
    application.sample_sheet.set(str(path))
    gui.load_columns_action(application)
    audit = Mock()
    monkeypatch.setattr(gui_controller, "audit_inputs", audit)
    application.sample_sheet.set(str(tmp_path / "other.csv"))
    gui.audit_action(application)
    audit.assert_not_called()
    assert "Load columns again" in application.status.get()
    assert application.mapping_state == {}
    assert all(variable.get() == "Automatic" for _, variable in application.mapping_variables)
    application.sample_sheet.set(str(path))
    gui.load_columns_action(application)
    path.write_text("r1,sample\n")
    gui.audit_action(application)
    audit.assert_not_called()
    assert "columns changed" in application.status.get()


def test_browse_cancel_preserves_mapping_and_new_selection_clears_it(monkeypatch):
    application = fake_application()
    application.mapping_state.update(path="sheet.csv", view="loaded")
    chooser = Mock(return_value="")
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(filedialog=SimpleNamespace(askopenfilename=chooser)))
    callback = lambda: gui.clear_column_mapping(application)
    gui.browse_sample_sheet(application.sample_sheet, on_selected=callback)
    assert application.mapping_state == {"path": "sheet.csv", "view": "loaded"}
    assert application.sample_sheet.get() == "sheet.csv"
    chooser.return_value = "new.csv"
    gui.browse_sample_sheet(application.sample_sheet, on_selected=callback)
    assert application.sample_sheet.get() == "new.csv"
    assert application.mapping_state == {}


def test_audit_passes_exact_mapping_overrides(tmp_path, monkeypatch):
    from fastq_sheet_audit import gui_controller
    from fastq_sheet_audit.column_mapping import ColumnRole
    from fastq_sheet_audit.presentation import SummaryView, WorkflowView
    path = tmp_path / "sheet.csv"
    path.write_text("sample,sampleid,r1,r2\n")
    application = fake_application()
    application.sample_sheet.set(str(path))
    gui.load_columns_action(application)
    variables = dict(application.mapping_variables)
    variables[ColumnRole.SAMPLE].set("[1] sampleid")
    variables[ColumnRole.R1].set("Automatic")
    variables[ColumnRole.R2].set("Unassigned")
    audit = Mock(return_value=WorkflowView(SummaryView(0, 0, 0, 0, True), (), (), ()))
    monkeypatch.setattr(gui_controller, "audit_inputs", audit)
    gui.audit_action(application)
    assert audit.call_args.kwargs["overrides"] == {ColumnRole.SAMPLE: 1, ColumnRole.R2: None}
