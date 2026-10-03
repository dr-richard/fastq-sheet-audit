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
        self.selected = ()
        self.identities = []
        self.options = {}
    def configure(self, **kwargs):
        self.options.update(kwargs)
    def heading(self, key, **kwargs):
        pass
    def column(self, key, **kwargs):
        pass
    def get_children(self):
        return tuple(range(len(self.rows)))
    def delete(self, *children):
        self.events.append("clear")
        self.rows.clear()
        self.identities.clear()
        self.selected = ()
    def insert(self, parent, index, *, values, iid=None):
        self.events.append("insert")
        self.rows.append(values)
        self.identities.append(iid)
    def selection(self):
        return self.selected
    def selection_set(self, identity):
        self.selected = (identity,)
    def see(self, identity):
        assert identity in self.identities


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
        session_state={}, r1_selection=FakeVariable("Automatic"), r2_selection=FakeVariable("Automatic"),
        confirmation=FakeVariable(False), r1_box=Mock(), r2_box=Mock(),
        confirmation_check=Mock(), apply_button=Mock(), reset_button=Mock(),
        profile=FakeVariable(""), profile_box=Mock(), path_mode=FakeVariable(""), path_mode_box=Mock(),
        target_style=FakeVariable(""), target_style_box=Mock(), target_root=FakeVariable(""),
        target_root_entry=Mock(), profile_notes=FakeVariable(""), manual_fields=FakeVariable(""),
        preview_button=Mock(), output_preview=FakeTable(events), validation_preview=FakeTable(events),
        export_state={},
    )


def export_application(*, ready=True):
    application = fake_application()
    session = SimpleNamespace(snapshot=SimpleNamespace(ready_for_export=ready))
    application.session_state.update(session=session, signature=gui.audit_input_signature(application))
    gui.refresh_export_controls(application)
    return application


@pytest.mark.parametrize("ready", [True, False])
def test_export_controls_profiles_and_initial_disable(ready):
    from fastq_sheet_audit.gui_controller import export_profile_views
    application = fake_application()
    gui.invalidate_audit_session(application)
    application.preview_button.configure.assert_called_with(state="disabled")
    application = export_application(ready=ready)
    application.profile_box.configure.assert_called_with(
        values=tuple(profile.profile_id for profile in export_profile_views()),
        state="readonly" if ready else "disabled")
    assert application.profile.get() == ""
    assert application.path_mode.get() == "Relative to FASTQ root"
    application.preview_button.configure.assert_called_with(state="normal" if ready else "disabled")
    application.export_button.configure.assert_called_with(state="disabled")


@pytest.mark.parametrize("profile_id,manual", [
    ("generic", "none"), ("nfcore-rnaseq-3.27.0", "strandedness"),
    ("nfcore-methylseq-4.2.0", "genome"), ("nfcore-viralrecon-3.0.0-nanopore", "barcode"),
])
def test_profile_notes_and_declarative_manual_summary(profile_id, manual):
    application = export_application()
    application.profile.set(profile_id)
    gui.profile_selection_action(application)
    profile = next(p for p in application.export_state["profiles"] if p.profile_id == profile_id)
    assert application.profile_notes.get() == profile.notes
    assert application.manual_fields.get() == f"Manual fields: {manual}"
    application.profile.set("unknown")
    gui.profile_selection_action(application)
    assert application.profile_notes.get() == application.manual_fields.get() == ""


def test_path_mode_controls_and_clearing():
    application = export_application()
    application.path_mode.set("Rebased root")
    gui.path_mode_action(application)
    application.target_root_entry.configure.assert_called_with(state="normal")
    application.target_style_box.configure.assert_called_with(state="readonly")
    assert application.target_style.get() == ""
    application.target_root.set("D:\\Unicode α")
    application.target_style.set("Windows")
    application.export_state["plan"] = object()
    for mode in ("Local absolute", "Relative to FASTQ root"):
        application.path_mode.set(mode)
        gui.path_mode_action(application)
        assert application.target_root.get() == application.target_style.get() == ""
        application.target_root_entry.configure.assert_called_with(state="disabled")
        application.target_style_box.configure.assert_called_with(state="disabled")
    assert "plan" not in application.export_state


def preview_plan(findings=(), headers=("sample", "r1")):
    from fastq_sheet_audit.sheet import SampleSheet, SheetRow
    from fastq_sheet_audit.profile_validation import ProfileValidationResult
    sheet = SampleSheet(headers, (SheetRow(7, (" α =value ", "01")), SheetRow(3, ("+2", "@path"))))
    return SimpleNamespace(plan=SimpleNamespace(result=SimpleNamespace(
        sheet=sheet, validation=ProfileValidationResult("generic", findings))))


@pytest.mark.parametrize("with_findings", [False, True])
def test_preview_exact_options_rendering_status_and_dynamic_columns(monkeypatch, with_findings):
    from fastq_sheet_audit import gui_controller
    from fastq_sheet_audit.profile_validation import ProfileFinding
    application = export_application()
    application.profile.set("generic")
    application.path_mode.set("Rebased root")
    application.target_root.set("D:\\ α ")
    application.target_style.set("Windows")
    findings = (ProfileFinding("EMPTY_REQUIRED_VALUE", "exact message", 7, "manual", ""),
                ProfileFinding("OTHER", "second", None, None, None)) if with_findings else ()
    plan = preview_plan(findings)
    planner = Mock(return_value=plan)
    monkeypatch.setattr(gui_controller, "plan_session_export", planner)
    gui.preview_export_action(application)
    session = application.session_state["session"]
    planner.assert_called_once_with(session, "generic", "Rebased root", target_root="D:\\ α ",
                                   target_style_label="Windows", explicit_values=None)
    assert application.export_state["plan"] is plan
    assert application.export_state["signature"] == (session, "generic", "Rebased root", "D:\\ α ", "Windows")
    assert application.output_preview.options["columns"] == ("sample", "r1")
    assert application.output_preview.rows == [(" α =value ", "01"), ("+2", "@path")]
    assert application.validation_preview.rows == ([
        ("EMPTY_REQUIRED_VALUE", 7, "manual", "", "exact message"), ("OTHER", "", "", "", "second")
    ] if with_findings else [])
    assert application.status.get() == ("Export preview has 2 profile validation finding(s)." if with_findings else
                                        "Export preview valid. File writing is not enabled yet.")
    planner.return_value = preview_plan(headers=("different", "headers"))
    gui.preview_export_action(application)
    assert application.output_preview.options["columns"] == ("different", "headers")
    assert len(application.output_preview.rows) == 2
    application.export_button.configure.assert_called_with(state="disabled")


@pytest.mark.parametrize("changed", ["fastq_directory", "sample_sheet", "read_mode", "mapping"])
def test_stale_inputs_refuse_export_preview(monkeypatch, changed):
    from fastq_sheet_audit import gui_controller
    application = export_application()
    application.profile.set("generic")
    if changed == "mapping":
        application.mapping_variables[0][1].set("Unassigned")
    else:
        getattr(application, changed).set("changed")
    planner = Mock()
    monkeypatch.setattr(gui_controller, "plan_session_export", planner)
    gui.preview_export_action(application)
    planner.assert_not_called()
    assert application.status.get() == "Export preview failed: Inputs changed. Run Audit again before planning export."


@pytest.mark.parametrize("error", [ValueError("barcode_mapping unsupported"), OSError("bad path"), RuntimeError("bug")])
def test_preview_failure_clears_plan_and_preserves_exception_boundary(monkeypatch, error):
    from fastq_sheet_audit import gui_controller
    application = export_application()
    application.profile.set("nfcore-viralrecon-3.0.0-nanopore")
    application.export_state["plan"] = object()
    monkeypatch.setattr(gui_controller, "plan_session_export", Mock(side_effect=error))
    if isinstance(error, RuntimeError):
        with pytest.raises(RuntimeError):
            gui.preview_export_action(application)
    else:
        gui.preview_export_action(application)
        assert application.status.get() == f"Export preview failed: {error}"
    assert "plan" not in application.export_state
    assert application.output_preview.rows == application.validation_preview.rows == []


def test_session_invalidation_clears_export_evidence():
    application = export_application()
    application.export_state.update(plan=object(), signature=object())
    gui.clear_column_mapping(application)
    assert application.export_state == {}
    assert application.output_preview.rows == application.validation_preview.rows == []
    application.preview_button.configure.assert_called_with(state="disabled")


@pytest.mark.parametrize("reset", [False, True])
@pytest.mark.parametrize("ready", [False, True])
def test_pair_action_invalidates_preview_and_refreshes_readiness(monkeypatch, reset, ready):
    from fastq_sheet_audit import gui_controller
    application = fake_application()
    attach_session(application, editor_session(), monkeypatch)
    gui.load_pair_editor(application, 0)
    application.export_state["plan"] = object()
    new = editor_session()
    new.snapshot.ready_for_export = ready
    monkeypatch.setattr(gui_controller, "apply_pair_adjudication", Mock(return_value=new))
    (gui.reset_pair_action if reset else gui.apply_pair_action)(application)
    assert "plan" not in application.export_state
    assert application.output_preview.rows == application.validation_preview.rows == []
    application.preview_button.configure.assert_called_with(state="normal" if ready else "disabled")
    application.export_button.configure.assert_called_with(state="disabled")


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
    monkeypatch.setattr(gui_controller, "audit_session", fail)
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
    monkeypatch.setattr(gui_controller, "audit_session", Mock(return_value=SimpleNamespace(
        view=view, snapshot=SimpleNamespace(ready_for_export=True))))
    gui.audit_action(application)
    assert application.status.get() == "Audit complete: 2 FASTQs, 0 errors, 0 warnings."
    assert dict(application.summary_values)["ready_for_export"].get() == "Ready"
    def fail(*args, **kwargs):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(gui_controller, "audit_session", fail)
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
    monkeypatch.setattr(gui_controller, "audit_session", audit)
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
    audit = Mock(return_value=SimpleNamespace(view=WorkflowView(SummaryView(0, 0, 0, 0, True), (), (), ()),
                                            snapshot=SimpleNamespace(ready_for_export=True)))
    monkeypatch.setattr(gui_controller, "audit_session", audit)
    gui.audit_action(application)
    assert audit.call_args.kwargs["overrides"] == {ColumnRole.SAMPLE: 1, ColumnRole.R2: None}


def editor_session(*, selected="Automatic", confirmed=False):
    from fastq_sheet_audit.presentation import PairView, SummaryView, WorkflowView
    from fastq_sheet_audit.gui_controller import PairAdjudicationView, PairCandidateChoice
    from fastq_sheet_audit.pairing import PairKey
    from pathlib import Path
    rows = (
        PairView("first", 2, 1, None, "A_R2.fastq", 2, 0, confirmed, False),
        PairView("second", 1, 0, "B_R1.fastq", None, 0, 0, False, True),
    )
    first_key = PairKey("A", None, None, None, "R", ".fastq", Path("."))
    second_key = PairKey("B", None, None, None, "R", ".fastq", Path("."))
    views = (
        PairAdjudicationView(0, first_key, (
            PairCandidateChoice(0, "A_R1.fastq", "[0] A_R1.fastq"),
            PairCandidateChoice(1, "other/A_R1.fastq", "[1] other/A_R1.fastq"),
        ), (PairCandidateChoice(0, "A_R2.fastq", "[0] A_R2.fastq"),), selected, "Automatic", confirmed, False),
        PairAdjudicationView(1, second_key, (
            PairCandidateChoice(0, "B_R1.fastq", "[0] B_R1.fastq"),
        ), (), "[0] B_R1.fastq", "Unassigned", False, True),
    )
    return SimpleNamespace(view=WorkflowView(SummaryView(4, 0, 1, 1, False), (), (), rows), editors=views,
                           snapshot=SimpleNamespace(ready_for_export=False))


def attach_session(application, session, monkeypatch):
    from fastq_sheet_audit import gui_controller
    monkeypatch.setattr(gui_controller, "pair_adjudication_views", lambda state: state.editors)
    application.session_state.update(session=session, signature=gui.audit_input_signature(application))
    gui.render_workflow(application, session.view)


def test_initial_editor_disabled_and_selection_loads_exact_choices(monkeypatch):
    application = fake_application()
    gui.disable_pair_editor(application)
    for control in (application.r1_box, application.r2_box, application.confirmation_check,
                    application.apply_button, application.reset_button):
        assert control.configure.call_args.kwargs["state"] == "disabled"
    session = editor_session()
    attach_session(application, session, monkeypatch)
    assert application.pairing_table.identities == ["pair:0", "pair:1"]
    assert application.pairing_table.selection() == ()
    application.pairing_table.selection_set("pair:0")
    gui.pair_selection_action(application)
    assert application.r1_box.configure.call_args.kwargs == {
        "state": "readonly", "values": ("Automatic", "Unassigned", "[0] A_R1.fastq", "[1] other/A_R1.fastq"),
    }
    assert application.r1_selection.get() == "Automatic"
    assert application.r2_selection.get() == "Automatic"
    assert application.confirmation.get() is False
    gui.load_pair_editor(application, 1)
    assert application.r1_selection.get() == "[0] B_R1.fastq"
    assert application.r2_selection.get() == "Unassigned"


@pytest.mark.parametrize("selection", [(), ("unknown",), ("pair:-1",), ("pair:99",), ("pair:00",), ("pair:0", "pair:1")])
def test_invalid_selection_disables_without_guessing(monkeypatch, selection):
    application = fake_application()
    attach_session(application, editor_session(), monkeypatch)
    gui.load_pair_editor(application, 0)
    application.pairing_table.selected = selection
    gui.pair_selection_action(application)
    assert "pair_index" not in application.session_state
    assert application.r1_selection.get() == "Automatic"
    application.apply_button.configure.assert_called_with(state="disabled")


def test_no_session_selection_disables_editor():
    application = fake_application()
    application.pairing_table.selection_set("pair:0")
    gui.pair_selection_action(application)
    assert "pair_index" not in application.session_state
    application.apply_button.configure.assert_called_with(state="disabled")


@pytest.mark.parametrize("reset", [False, True])
def test_apply_and_reset_use_controller_replace_session_rerender_and_reload(monkeypatch, reset):
    from fastq_sheet_audit import gui_controller
    application = fake_application()
    old = editor_session()
    new = editor_session(selected="Automatic" if reset else "[1] other/A_R1.fastq", confirmed=not reset)
    attach_session(application, old, monkeypatch)
    gui.load_pair_editor(application, 0)
    application.r1_selection.set("[1] other/A_R1.fastq")
    application.r2_selection.set("Unassigned")
    application.confirmation.set(True)
    apply = Mock(return_value=new)
    monkeypatch.setattr(gui_controller, "apply_pair_adjudication", apply)
    (gui.reset_pair_action if reset else gui.apply_pair_action)(application)
    apply.assert_called_once_with(old, 0, "Automatic" if reset else "[1] other/A_R1.fastq",
                                  "Automatic" if reset else "Unassigned", False if reset else True)
    assert application.session_state["session"] is new
    assert application.session_state["pair_index"] == 0
    assert application.pairing_table.selection() == ("pair:0",)
    assert application.r1_selection.get() == new.editors[0].r1_selection
    assert application.confirmation.get() is new.editors[0].confirmed
    assert len(application.pairing_table.rows) == 2
    assert application.status.get() == (
        "Pair decision reset to automatic. Workflow revalidated." if reset else
        "Pair decision applied. Workflow revalidated."
    )
    application.export_button.configure.assert_called_with(state="disabled")


@pytest.mark.parametrize("field", ["fastq_directory", "sample_sheet", "read_mode", "column", "mapping_state"])
@pytest.mark.parametrize("reset", [False, True])
def test_stale_inputs_refuse_controller_call(monkeypatch, field, reset):
    from fastq_sheet_audit import gui_controller
    application = fake_application()
    session = editor_session()
    attach_session(application, session, monkeypatch)
    gui.load_pair_editor(application, 0)
    if field == "column":
        application.mapping_variables[0][1].set("Unassigned")
    elif field == "mapping_state":
        application.mapping_state["path"] = "new.csv"
    else:
        getattr(application, field).set("changed")
    apply = Mock()
    monkeypatch.setattr(gui_controller, "apply_pair_adjudication", apply)
    (gui.reset_pair_action if reset else gui.apply_pair_action)(application)
    apply.assert_not_called()
    assert application.status.get() == "Inputs changed. Run Audit again before adjudicating."
    assert application.session_state["session"] is session


@pytest.mark.parametrize("sample", [False, True])
def test_browse_invalidation_only_after_selection(monkeypatch, sample):
    application = fake_application()
    session = editor_session()
    attach_session(application, session, monkeypatch)
    gui.load_pair_editor(application, 0)
    plan = object()
    application.export_state["plan"] = plan
    chooser = Mock(return_value="")
    dialogs = SimpleNamespace(askdirectory=chooser, askopenfilename=chooser)
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(filedialog=dialogs))
    browse = gui.browse_sample_sheet if sample else gui.browse_fastq_directory
    variable = application.sample_sheet if sample else application.fastq_directory
    callback = (lambda: gui.clear_column_mapping(application)) if sample else (lambda: gui.invalidate_audit_session(application))
    browse(variable, on_selected=callback)
    assert application.session_state["session"] is session
    assert application.export_state["plan"] is plan
    chooser.return_value = "new path"
    browse(variable, on_selected=callback)
    assert application.session_state == {}
    assert "plan" not in application.export_state
    application.apply_button.configure.assert_called_with(state="disabled")


def test_failed_audit_discards_session_and_success_starts_new_session(monkeypatch):
    from fastq_sheet_audit import gui_controller
    application = fake_application()
    old = editor_session()
    attach_session(application, old, monkeypatch)
    gui.load_pair_editor(application, 0)
    application.export_state["plan"] = object()
    monkeypatch.setattr(gui_controller, "audit_session", Mock(side_effect=ValueError("bad input")))
    gui.audit_action(application)
    assert application.session_state == {}
    assert "plan" not in application.export_state
    application.apply_button.configure.assert_called_with(state="disabled")
    new = editor_session()
    monkeypatch.setattr(gui_controller, "audit_session", Mock(return_value=new))
    application.export_state["plan"] = object()
    gui.audit_action(application)
    assert "plan" not in application.export_state
    assert application.session_state["session"] is new
    assert application.session_state["signature"] == gui.audit_input_signature(application)
    assert "pair_index" not in application.session_state
    assert application.pairing_table.selection() == ()
    assert len(application.pairing_table.rows) == 2
    application.export_button.configure.assert_called_with(state="disabled")


def test_unexpected_apply_error_propagates_and_has_no_reload_scan_or_network(monkeypatch):
    from fastq_sheet_audit import gui_controller
    application = fake_application()
    attach_session(application, editor_session(), monkeypatch)
    gui.load_pair_editor(application, 0)
    def forbidden(*args, **kwargs):
        pytest.fail("adjudication accessed files or network")
    monkeypatch.setattr(gui_controller, "load_sheet", forbidden)
    monkeypatch.setattr(gui_controller, "scan_fastqs", forbidden)
    monkeypatch.setattr(gui_controller, "inspect_sheet_mapping", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr(gui_controller, "apply_pair_adjudication", Mock(side_effect=RuntimeError("programmer error")))
    with pytest.raises(RuntimeError, match="programmer error"):
        gui.apply_pair_action(application)
