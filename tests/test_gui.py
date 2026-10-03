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
    assert gui.read_mode_value(label) == value


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
    assert imports <= {"__future__", "dataclasses", "typing", "tkinter"}
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
