from pathlib import Path
from dataclasses import FrozenInstanceError, replace

import pytest

from fastq_sheet_audit import gui_controller as controller
from fastq_sheet_audit.column_mapping import map_columns
from fastq_sheet_audit.inventory import scan_fastqs
from fastq_sheet_audit.presentation import present_workflow
from fastq_sheet_audit.read_mode import ReadMode
from fastq_sheet_audit.sheet import load_sheet
from fastq_sheet_audit.workflow import build_workflow_snapshot


def test_output_format_exact_choices():
    from fastq_sheet_audit.serialization import SheetFormat
    assert controller.OUTPUT_FORMAT_CHOICES == (("CSV", SheetFormat.CSV), ("TSV", SheetFormat.TSV))
    for label, format in controller.OUTPUT_FORMAT_CHOICES:
        assert controller.output_format_from_label(label) is format
    for label in ("csv", "tsv", "Csv", "", "JSON", None):
        with pytest.raises(ValueError):
            controller.output_format_from_label(label)


@pytest.mark.parametrize("destination", ["", None, 1, Path("output.csv")])
def test_publication_destination_validation(tmp_path, monkeypatch, destination):
    session = session_fixture(tmp_path)
    def fail(*args, **kwargs):
        pytest.fail("invalid inputs reached planning or writer")
    monkeypatch.setattr(controller, "plan_session_export", fail)
    monkeypatch.setattr(controller, "write_sheet_atomic", fail)
    with pytest.raises(ValueError, match="destination"):
        controller.write_session_export(session, "generic", "Local absolute", destination, "CSV")


@pytest.mark.parametrize("overwrite", [0, 1, None, "true"])
def test_publication_requires_boolean_overwrite(tmp_path, overwrite):
    with pytest.raises(ValueError, match="overwrite"):
        controller.write_session_export(session_fixture(tmp_path), "generic", "Local absolute",
                                        str(tmp_path / "out.csv"), "CSV", overwrite=overwrite)


def test_publication_exact_fresh_planning_and_writer_delegation(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from fastq_sheet_audit.column_mapping import ColumnRole
    from fastq_sheet_audit.serialization import SheetFormat
    session = session_fixture(tmp_path)
    extra = tmp_path / "reference-only.fastq"
    assignments = session.snapshot.reconciliation.assignments
    session = replace(session, snapshot=replace(session.snapshot, reconciliation=replace(
        session.snapshot.reconciliation, assignments=assignments + (replace(assignments[0], path=extra, role=ColumnRole.R2),))))
    fresh = controller.plan_session_export(session, "nfcore-rnaseq-3.27.0", "Relative to FASTQ root",
                                          explicit_values={2: {"strandedness": "reverse"}})
    calls = []
    def plan(*args, **kwargs):
        calls.append("plan")
        return fresh
    def write(*args, **kwargs):
        assert calls == ["plan"] and fresh.plan.result.validation.ok
        calls.append("write")
        return tmp_path / "writer-returned.csv"
    planner, writer = Mock(side_effect=plan), Mock(side_effect=write)
    monkeypatch.setattr(controller, "plan_session_export", planner)
    monkeypatch.setattr(controller, "write_sheet_atomic", writer)
    manual = {2: {"strandedness": "reverse"}}
    result = controller.write_session_export(session, "exact-profile", "exact-path", " output.tsv ", "CSV",
        target_root=" exact root ", target_style_label="Windows", explicit_values=manual, overwrite=True)
    planner.assert_called_once_with(session, "exact-profile", "exact-path", target_root=" exact root ",
                                    target_style_label="Windows", explicit_values=manual)
    assert planner.call_args.kwargs["explicit_values"] is manual
    protected = (session.sample_sheet_path, *(r.path for r in session.inventory),
                 *(a.path for a in session.snapshot.reconciliation.assignments))
    writer.assert_called_once_with(fresh.plan.result.sheet, Path(" output.tsv "), SheetFormat.CSV,
                                   protected_paths=protected, overwrite=True)
    assert writer.call_args.args[0] is fresh.plan.result.sheet
    assert result.plan is fresh and result.destination == tmp_path / "writer-returned.csv"
    assert result.format is SheetFormat.CSV
    with pytest.raises(FrozenInstanceError):
        result.destination = Path("changed")


@pytest.mark.parametrize("format,delimiter", [("CSV", ","), ("TSV", "\t")])
def test_real_publication_exact_bytes_explicit_format_and_absolute_return(tmp_path, monkeypatch, format, delimiter):
    session = session_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = controller.write_session_export(session, "generic", "Relative to FASTQ root", "output.tsv", format)
    assert result.destination == tmp_path / "output.tsv"
    assert result.destination.read_bytes() == (
        delimiter.join(("sample", "r1", "r2")) + "\n" +
        delimiter.join(("A", "A_R1.fastq", "A_R2.fastq")) + "\n").encode()


@pytest.mark.parametrize("mode,options,prefix", [
    ("Local absolute", {}, None),
    ("Rebased root", {"target_root": "/data/项目", "target_style_label": "POSIX"}, "/data/项目/"),
    ("Rebased root", {"target_root": "D:\\项目", "target_style_label": "Windows"}, "D:\\项目\\"),
])
def test_real_publication_path_modes(tmp_path, mode, options, prefix):
    session = session_fixture(tmp_path)
    result = controller.write_session_export(session, "generic", mode, str(tmp_path / "out.csv"), "CSV", **options)
    expected = str(session.fastq_root / "A_R1.fastq") if prefix is None else prefix + "A_R1.fastq"
    assert result.plan.plan.result.sheet.rows[0].cells[1] == expected
    assert expected in result.destination.read_text()


@pytest.mark.parametrize("value", [" α =SUM(A1) ", "001", "+7", "@value", ""])
def test_real_publication_exact_manual_text_and_no_reload_network(tmp_path, monkeypatch, value):
    session = session_fixture(tmp_path)
    before = replace(session)
    manual = {2: {"genome": value}}
    def fail(*args, **kwargs):
        pytest.fail("publication reloaded/scanned/rebuilt or accessed network/FASTQ contents")
    for name in ("load_sheet", "scan_fastqs", "build_workflow_snapshot"):
        monkeypatch.setattr(controller, name, fail)
    monkeypatch.setattr("socket.socket", fail)
    original_open = Path.open
    def guarded_open(path, mode="r", *args, **kwargs):
        if path in tuple(record.path for record in session.inventory):
            fail()
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    result = controller.write_session_export(session, "nfcore-methylseq-4.2.0", "Relative to FASTQ root",
                                             str(tmp_path / "out.csv"), "CSV", explicit_values=manual)
    import csv
    assert list(csv.reader(result.destination.read_text().splitlines()))[1][-1] == value
    assert manual == {2: {"genome": value}} and session == before


@pytest.mark.parametrize("manual", [None, {2: {"strandedness": "Reverse"}}, {2: {"strandedness": ""}}])
def test_invalid_profile_plan_never_reaches_writer(tmp_path, monkeypatch, manual):
    session = session_fixture(tmp_path)
    destination = tmp_path / "out.csv"
    destination.write_bytes(b"original")
    def fail(*args, **kwargs):
        pytest.fail("invalid plan reached writer")
    monkeypatch.setattr(controller, "write_sheet_atomic", fail)
    with pytest.raises(ValueError, match="export plan has profile validation findings"):
        controller.write_session_export(session, "nfcore-rnaseq-3.27.0", "Relative to FASTQ root",
            str(destination), "CSV", explicit_values=manual, overwrite=True)
    assert destination.read_bytes() == b"original"


def test_valid_rnaseq_publication_and_planner_safety_gates(tmp_path, monkeypatch):
    session = session_fixture(tmp_path)
    result = controller.write_session_export(session, "nfcore-rnaseq-3.27.0", "Relative to FASTQ root",
        str(tmp_path / "rnaseq.csv"), "CSV", explicit_values={2: {"strandedness": "reverse"}})
    assert result.destination.read_text().endswith(",reverse\n")
    def fail(*args, **kwargs):
        pytest.fail("rejected workflow/profile reached writer")
    monkeypatch.setattr(controller, "write_sheet_atomic", fail)
    with pytest.raises(ValueError, match="barcode_mapping"):
        controller.write_session_export(session, "nfcore-viralrecon-3.0.0-nanopore", "Local absolute",
                                         str(tmp_path / "barcode.csv"), "CSV")
    unready = controller.apply_pair_adjudication(session, 0, "Unassigned", "Automatic", False)
    with pytest.raises(ValueError, match="not ready"):
        controller.write_session_export(unready, "generic", "Local absolute", str(tmp_path / "bad.csv"), "CSV")


def test_publication_effective_adjudicated_read_and_all_raw_paths_protected(tmp_path):
    session = session_fixture(tmp_path, ambiguous=True)
    original = session.fastq_root / session.sheet.rows[0].cells[1]
    resolution = session.snapshot.pair_resolutions[0]
    index = next(i for i, record in enumerate(resolution.group.r1) if record.path != original)
    choice = controller.pair_adjudication_views(session)[0].r1_choices[index].display
    session = controller.apply_pair_adjudication(session, 0, choice, "Automatic", False)
    result = controller.write_session_export(session, "generic", "Local absolute", str(tmp_path / "out.csv"), "CSV")
    assert str(session.snapshot.pair_resolutions[0].effective_r1.path) in result.destination.read_text()
    for protected in (session.sample_sheet_path, *(record.path for record in session.inventory)):
        before = protected.read_bytes()
        with pytest.raises(ValueError, match="protected"):
            controller.write_session_export(session, "generic", "Local absolute", str(protected), "CSV", overwrite=True)
        assert protected.read_bytes() == before


def test_assignment_only_path_is_protected(tmp_path):
    from fastq_sheet_audit.column_mapping import ColumnRole
    session = session_fixture(tmp_path)
    extra = tmp_path / "referenced.fastq"
    extra.write_bytes(b"protected")
    reconciliation = session.snapshot.reconciliation
    assignment = replace(reconciliation.assignments[0], path=extra, role=ColumnRole.R2)
    session = replace(session, snapshot=replace(session.snapshot, reconciliation=replace(
        reconciliation, assignments=reconciliation.assignments + (replace(assignment, row_number=999),))))
    with pytest.raises(ValueError, match="protected"):
        controller.write_session_export(session, "generic", "Relative to FASTQ root", str(extra), "CSV", overwrite=True)
    assert extra.read_bytes() == b"protected"


def test_publication_overwrite_and_unexpected_writer_error(tmp_path, monkeypatch):
    session = session_fixture(tmp_path)
    destination = tmp_path / "out.csv"
    destination.write_bytes(b"previous")
    with pytest.raises(FileExistsError):
        controller.write_session_export(session, "generic", "Relative to FASTQ root", str(destination), "CSV")
    assert destination.read_bytes() == b"previous"
    controller.write_session_export(session, "generic", "Relative to FASTQ root", str(destination), "CSV", overwrite=True)
    assert destination.read_text().startswith("sample,r1,r2\n")
    def fail(*args, **kwargs):
        raise RuntimeError("writer bug")
    monkeypatch.setattr(controller, "write_sheet_atomic", fail)
    with pytest.raises(RuntimeError, match="writer bug"):
        controller.write_session_export(session, "generic", "Relative to FASTQ root", str(destination), "CSV")


@pytest.mark.parametrize("profile_id, names", [
    ("generic", ()), ("nfcore-rnaseq-3.27.0", ("strandedness",)),
    ("nfcore-methylseq-4.2.0", ("genome",)), ("nfcore-smrnaseq-2.4.1", ()),
    ("nfcore-viralrecon-3.0.0-illumina", ()),
    ("nfcore-viralrecon-3.0.0-nanopore", ("barcode",)),
])
def test_manual_metadata_profiles_and_exact_source_rows(tmp_path, profile_id, names):
    from fastq_sheet_audit.sheet import SampleSheet, SheetRow
    from fastq_sheet_audit.column_mapping import ColumnRole
    session = session_fixture(tmp_path)
    sheet = SampleSheet(("r1", "Exact sample"), (
        SheetRow(19, ("first", "  α Café  ")),
        SheetRow(4, ("second", "=SUM(A1)")),
        SheetRow(8, ("third", "+01")),
    ))
    session = replace(session, sheet=sheet, mapping=map_columns(sheet, {ColumnRole.SAMPLE: 1}))
    before = replace(session)
    view = controller.manual_metadata_view(session, profile_id)
    assert tuple(column.name for column in view.columns) == names
    assert view.profile_view == next(p for p in controller.export_profile_views() if p.profile_id == profile_id)
    assert view.rows == (
        controller.ManualMetadataRowView(19, "  α Café  "),
        controller.ManualMetadataRowView(4, "=SUM(A1)"),
        controller.ManualMetadataRowView(8, "+01"),
    )
    assert isinstance(view.columns, tuple) and isinstance(view.rows, tuple)
    assert controller.manual_metadata_view(session, profile_id) == view
    assert session == before
    with pytest.raises(FrozenInstanceError):
        view.rows = ()
    with pytest.raises(FrozenInstanceError):
        view.rows[0].sample = "changed"
    with pytest.raises(FrozenInstanceError):
        view.profile_view.notes = "changed"


@pytest.mark.parametrize("problem", [
    "missing", "wrong_header", "case_header", "negative_index", "large_index", "bool_index",
    "short_row", "surplus_row", "duplicate_rows", "bool_row", "string_row", "float_row",
])
def test_manual_metadata_rejects_inconsistent_state(tmp_path, problem):
    from fastq_sheet_audit.column_mapping import ColumnRole
    from fastq_sheet_audit.sheet import SheetRow
    session = session_fixture(tmp_path)
    sample = session.mapping.for_role(ColumnRole.SAMPLE)
    if problem in {"missing", "wrong_header", "case_header", "negative_index", "large_index", "bool_index"}:
        selected = sample.selected
        if problem == "missing":
            selected = None
        elif problem in {"wrong_header", "case_header"}:
            selected = replace(selected, header="stale" if problem == "wrong_header" else "SAMPLE")
        else:
            selected = replace(selected, index={"negative_index": -1, "large_index": 99, "bool_index": False}[problem])
        mapping = replace(session.mapping, roles=tuple(
            replace(role, selected=selected) if role.role is ColumnRole.SAMPLE else role
            for role in session.mapping.roles))
        session = replace(session, mapping=mapping)
    else:
        row = session.sheet.rows[0]
        if problem == "duplicate_rows":
            rows = (row, row)
        elif problem in {"short_row", "surplus_row"}:
            rows = (replace(row, cells=row.cells[:-1] if problem == "short_row" else row.cells + ("extra",)),)
        else:
            rows = (SheetRow({"bool_row": True, "string_row": "2", "float_row": 2.0}[problem], row.cells),)
        session = replace(session, sheet=replace(session.sheet, rows=rows))
    with pytest.raises(ValueError):
        controller.manual_metadata_view(session, "generic")


def test_manual_metadata_only_loads_bundled_profile_and_preserves_session(tmp_path, monkeypatch):
    session = session_fixture(tmp_path)
    before = replace(session)
    original_open = Path.open
    def fail(*args, **kwargs):
        pytest.fail("manual metadata accessed audit inputs, planning, network, or writes")
    def resource_open(path, mode="r", *args, **kwargs):
        assert path.parent.name == "profile_data" and path.suffix == ".json"
        assert mode == "r"
        return original_open(path, mode, *args, **kwargs)
    for name in ("load_sheet", "scan_fastqs", "build_export_plan", "plan_session_export"):
        monkeypatch.setattr(controller, name, fail)
    monkeypatch.setattr(Path, "open", resource_open)
    for name in ("write_text", "write_bytes", "rename", "unlink", "mkdir"):
        monkeypatch.setattr(Path, name, fail)
    monkeypatch.setattr("socket.socket", fail)
    view = controller.manual_metadata_view(session, "nfcore-viralrecon-3.0.0-nanopore")
    assert view.profile_view.input_kind == "barcode_mapping"
    assert view.columns[0].name == "barcode"
    assert session == before


def inputs(tmp_path, paired=True):
    root = tmp_path / "fastqs"
    root.mkdir()
    (root / "A_R1.fastq").write_bytes(b"not read")
    if paired:
        (root / "A_R2.fastq").write_bytes(b"not read")
    sheet = tmp_path / "sheet.csv"
    sheet.write_text("sample,r1,r2\nA,A_R1.fastq," + ("A_R2.fastq" if paired else "") + "\n")
    return root, sheet


@pytest.mark.parametrize("paired, label", [(True, "Paired"), (False, "Single"), (True, "Auto")])
def test_audit_matches_existing_workflow_presentation(tmp_path, paired, label):
    root, path = inputs(tmp_path, paired)
    sheet = load_sheet(path)
    expected = present_workflow(build_workflow_snapshot(
        sheet, map_columns(sheet), scan_fastqs(root), root, read_mode=controller.read_mode_from_label(label),
    ))
    view = controller.audit_inputs(str(root), str(path), label)
    assert view == expected
    assert view.summary.ready_for_export


@pytest.mark.parametrize("label, mode", [("Auto", ReadMode.AUTO), ("Paired", ReadMode.PAIRED), ("Single", ReadMode.SINGLE)])
def test_mode_mapping(label, mode):
    assert controller.read_mode_from_label(label) is mode


@pytest.mark.parametrize("which", ["empty_root", "empty_sheet", "missing_root", "missing_sheet", "malformed"])
def test_input_errors(tmp_path, which):
    root, sheet = inputs(tmp_path)
    if which == "malformed":
        sheet.write_text('sample,r1\nA,"unterminated')
    directory = "" if which == "empty_root" else str(root / "missing") if which == "missing_root" else str(root)
    source = "" if which == "empty_sheet" else str(sheet.parent / "missing.csv") if which == "missing_sheet" else str(sheet)
    with pytest.raises(ValueError):
        controller.audit_inputs(directory, source, "Auto")


@pytest.mark.parametrize("headers", ["sample,sample_id,r1", "sample,r1,read1", "sample", "r1", "sample,r1,r2,read2"])
def test_mapping_refuses_before_scan_and_reconciliation(tmp_path, monkeypatch, headers):
    root, path = inputs(tmp_path)
    path.write_text(headers + "\n")
    def fail(*args, **kwargs):
        pytest.fail("audit continued past unresolved mapping")
    monkeypatch.setattr(controller, "scan_fastqs", fail)
    monkeypatch.setattr(controller, "build_workflow_snapshot", fail)
    with pytest.raises(ValueError, match="mapping"):
        controller.audit_inputs(str(root), str(path), "Auto")


def test_no_network_writes_or_fastq_reads(tmp_path, monkeypatch):
    root, path = inputs(tmp_path)
    before = {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    original_open = Path.open
    def guarded_open(self, mode="r", *args, **kwargs):
        assert self == path, "FASTQ contents were accessed"
        assert mode == "r", "file write attempted"
        return original_open(self, mode, *args, **kwargs)
    def fail(*args, **kwargs):
        pytest.fail("network or user-file write attempted")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded_open)
        for method in ("write_bytes", "write_text", "rename", "unlink", "mkdir"):
            patch.setattr(Path, method, fail)
        patch.setattr("socket.socket", fail)
        assert controller.audit_inputs(str(root), str(path), "Auto").summary.ready_for_export
    assert {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()} == before


def test_unexpected_controller_errors_are_not_swallowed(tmp_path, monkeypatch):
    root, path = inputs(tmp_path)
    def fail(*args):
        raise RuntimeError("programmer error")
    monkeypatch.setattr(controller, "load_sheet", fail)
    with pytest.raises(RuntimeError, match="programmer error"):
        controller.audit_inputs(str(root), str(path), "Auto")


def test_inspection_preserves_indexes_headers_and_ambiguity(tmp_path):
    from fastq_sheet_audit.column_mapping import ColumnRole
    path = tmp_path / "sheet.csv"
    path.write_text("sample,Sample,sample_id,fastq_1,metadata\n")
    view = controller.inspect_sheet_mapping(str(path))
    assert [(choice.index, choice.header, choice.display) for choice in view.choices] == [
        (0, "sample", "[0] sample"), (1, "Sample", "[1] Sample"),
        (2, "sample_id", "[2] sample_id"), (3, "fastq_1", "[3] fastq_1"), (4, "metadata", "[4] metadata"),
    ]
    roles = {item.role: item for item in view.roles}
    assert roles[ColumnRole.SAMPLE].candidates == (0, 1, 2)
    assert roles[ColumnRole.SAMPLE].ambiguous
    assert roles[ColumnRole.SAMPLE].selected is None
    assert roles[ColumnRole.R1].automatic == roles[ColumnRole.R1].selected == 3
    assert roles[ColumnRole.R2].selected is None
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        view.choices[0].index = 9


def test_inspection_never_scans_reconciles_writes_or_networks(tmp_path, monkeypatch):
    path = tmp_path / "sheet.csv"
    path.write_text("sample,r1\n")
    def fail(*args, **kwargs):
        pytest.fail("mapping inspection accessed forbidden operation")
    monkeypatch.setattr(controller, "scan_fastqs", fail)
    monkeypatch.setattr(controller, "build_workflow_snapshot", fail)
    monkeypatch.setattr("socket.socket", fail)
    monkeypatch.setattr(Path, "write_text", fail)
    monkeypatch.setattr(Path, "write_bytes", fail)
    assert controller.inspect_sheet_mapping(str(path)).roles[0].automatic == 0


@pytest.mark.parametrize("source", ["", "missing.csv", "."])
def test_inspection_invalid_paths(tmp_path, monkeypatch, source):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        controller.inspect_sheet_mapping(source)


def test_selection_conversion_and_explicit_audit(tmp_path):
    from fastq_sheet_audit.column_mapping import ColumnRole
    root, path = inputs(tmp_path)
    path.write_text("sample,sampleid,r1,r2\nA,A,A_R1.fastq,A_R2.fastq\n")
    view = controller.inspect_sheet_mapping(str(path))
    overrides = controller.mapping_overrides(view, {
        ColumnRole.SAMPLE: "[1] sampleid", ColumnRole.R1: "Automatic", ColumnRole.R2: "Unassigned",
    })
    assert overrides == {ColumnRole.SAMPLE: 1, ColumnRole.R2: None}
    # Explicit unassigned R2 is valid mapping, though the unlisted discovered mate remains visible.
    result = controller.audit_inputs(str(root), str(path), "Auto", overrides)
    assert any(row.code == "UNLISTED_FASTQ" for row in result.findings)
    assert controller.audit_inputs(str(root), str(path), "Auto", {ColumnRole.SAMPLE: 1}).summary.ready_for_export
    with pytest.raises(ValueError, match="Ambiguous"):
        controller.audit_inputs(str(root), str(path), "Auto",
                                controller.mapping_overrides(view, {ColumnRole.SAMPLE: "Automatic"}))


@pytest.mark.parametrize("role", ["SAMPLE", "R1"])
def test_required_role_explicit_unassigned_refused(tmp_path, role):
    from fastq_sheet_audit.column_mapping import ColumnRole
    root, path = inputs(tmp_path)
    with pytest.raises(ValueError, match="requires SAMPLE and R1"):
        controller.audit_inputs(str(root), str(path), "Auto", {ColumnRole[role]: None})


def test_same_column_reuse_rejected_by_existing_mapper(tmp_path):
    from fastq_sheet_audit.column_mapping import ColumnRole
    root, path = inputs(tmp_path)
    with pytest.raises(ValueError, match="multiple roles"):
        controller.audit_inputs(str(root), str(path), "Auto", {ColumnRole.SAMPLE: 0, ColumnRole.R1: 0})


def test_unknown_display_choice_rejected(tmp_path):
    from fastq_sheet_audit.column_mapping import ColumnRole
    _, path = inputs(tmp_path)
    view = controller.inspect_sheet_mapping(str(path))
    with pytest.raises(ValueError, match="unknown column choice"):
        controller.mapping_overrides(view, {ColumnRole.SAMPLE: "sample"})


def session_fixture(tmp_path, mode="Auto", ambiguous=False):
    root, path = inputs(tmp_path)
    if ambiguous:
        from dataclasses import replace
        original_scan = controller.scan_fastqs
        records = original_scan(root)
        alias = root.parent / "alias.fastq"
        try:
            alias.symlink_to(records[0].path)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlinks unsupported: {error}")
        records.append(replace(records[0], path=alias))
        sheet = load_sheet(path)
        mapping = map_columns(sheet)
        snapshot = build_workflow_snapshot(sheet, mapping, records, root,
                                           read_mode=controller.read_mode_from_label(mode))
        return controller.AuditSession(sheet, mapping, snapshot.inventory, root,
                                       controller.read_mode_from_label(mode), (), snapshot, present_workflow(snapshot), path.absolute())
    return controller.audit_session(str(root), str(path), mode)


def test_session_matches_compatibility_wrapper_and_has_no_explicit_decisions(tmp_path):
    root, path = inputs(tmp_path)
    session = controller.audit_session(str(root), str(path), "Auto")
    assert session.view == controller.audit_inputs(str(root), str(path), "Auto")
    assert session.decisions == ()
    assert session.inventory is session.snapshot.inventory
    assert session.fastq_root.is_absolute()


def test_ambiguous_candidates_automatic_and_select(tmp_path):
    session = session_fixture(tmp_path, ambiguous=True)
    view, = controller.pair_adjudication_views(session)
    assert view.pair_index == 0
    assert len(view.r1_choices) == 2
    assert [choice.index for choice in view.r1_choices] == [0, 1]
    assert view.r1_choices[1].display == "[1] A_R1.fastq"
    assert view.r1_selection == view.r2_selection == "Automatic"
    assert not view.resolved
    automatic = controller.apply_pair_adjudication(session, 0, "Automatic", "Automatic", True)
    assert automatic.snapshot.has_unresolved_pairs
    assert not automatic.view.summary.ready_for_export
    selected = controller.apply_pair_adjudication(session, 0, view.r1_choices[1].display, "Automatic", False)
    assert selected.snapshot.pair_resolutions[0].resolved
    assert selected.view.summary.ready_for_export
    assert len(selected.snapshot.pair_resolutions[0].group.r1) == 2
    assert selected.inventory is session.inventory
    updated, = controller.pair_adjudication_views(selected)
    assert updated.r1_selection == view.r1_choices[1].display
    assert not updated.confirmed


@pytest.mark.parametrize("mode", ["Auto", "Paired"])
def test_r2_unassigned_revalidates_layout(tmp_path, mode):
    session = session_fixture(tmp_path, mode)
    updated = controller.apply_pair_adjudication(session, 0, "Automatic", "Unassigned", True)
    resolution = updated.snapshot.pair_resolutions[0]
    assert resolution.effective_r2 is None
    assert resolution.unresolved_r2 == ()
    assert len(resolution.group.r2) == 1
    assert controller.pair_adjudication_views(updated)[0].r2_selection == "Unassigned"
    assert updated.decisions[0].confirmed
    if mode == "Auto":
        assert updated.snapshot.read_mode.layout.value == "single"
        assert updated.view.summary.ready_for_export
    else:
        assert updated.snapshot.read_mode.diagnostics[0].code == "MISSING_R2"
        assert not updated.view.summary.ready_for_export


def test_confirmed_r1_unassigned_is_not_resolved(tmp_path):
    session = session_fixture(tmp_path, ambiguous=True)
    updated = controller.apply_pair_adjudication(session, 0, "Unassigned", "Automatic", True)
    resolution = updated.snapshot.pair_resolutions[0]
    assert resolution.confirmed
    assert resolution.unresolved_r1 == ()
    assert len(resolution.group.r1) == 2
    assert not resolution.resolved
    assert not updated.view.summary.ready_for_export


def test_independent_decisions_replacement_and_reset(tmp_path):
    root, path = inputs(tmp_path)
    (root / "B_R1.fastq").touch()
    path.write_text("sample,r1,r2\nA,A_R1.fastq,A_R2.fastq\nB,B_R1.fastq,\n")
    original = controller.audit_session(str(root), str(path), "Auto")
    views = controller.pair_adjudication_views(original)
    assert [view.pair_index for view in views] == [0, 1]
    assert [view.key.sample for view in views] == ["a", "b"]
    first = controller.apply_pair_adjudication(original, 0, "Automatic", "Unassigned", True)
    second = controller.apply_pair_adjudication(first, 1, views[1].r1_choices[0].display, "Automatic", True)
    assert len(second.decisions) == 2
    replaced = controller.apply_pair_adjudication(second, 0, "Automatic", "Automatic", True)
    assert len(replaced.decisions) == 2
    assert replaced.decisions[1] is second.decisions[1]
    reset = controller.apply_pair_adjudication(replaced, 0, "Automatic", "Automatic", False)
    assert reset.decisions == (second.decisions[1],)
    assert controller.pair_adjudication_views(reset)[0].r2_selection == "Automatic"
    assert original.decisions == ()
    assert controller.pair_adjudication_views(original) == views


@pytest.mark.parametrize("index", [-1, 1, 100, True, False, 0.0, "0", None])
def test_invalid_pair_index_rejected(tmp_path, index):
    session = session_fixture(tmp_path)
    with pytest.raises(ValueError, match="pair index"):
        controller.apply_pair_adjudication(session, index, "Automatic", "Automatic", False)


@pytest.mark.parametrize("confirmed", [0, 1, None, "true"])
def test_confirmation_requires_bool(tmp_path, confirmed):
    session = session_fixture(tmp_path)
    with pytest.raises(ValueError, match="boolean"):
        controller.apply_pair_adjudication(session, 0, "Automatic", "Automatic", confirmed)


@pytest.mark.parametrize("r1, r2", [("[0] missing.fastq", "Automatic"), ("Automatic", "[0] A_R1.fastq"),
                                  ("A_R1.fastq", "Automatic")])
def test_unknown_or_wrong_role_display_rejected(tmp_path, r1, r2):
    session = session_fixture(tmp_path)
    with pytest.raises(ValueError, match="unknown candidate display"):
        controller.apply_pair_adjudication(session, 0, r1, r2, False)


def test_session_immutability_and_no_reloading_scanning_reads_writes_or_network(tmp_path, monkeypatch):
    from dataclasses import FrozenInstanceError
    session = session_fixture(tmp_path)
    views = controller.pair_adjudication_views(session)
    def fail(*args, **kwargs):
        pytest.fail("adjudication reloaded/scanned/read/wrote/accessed network")
    monkeypatch.setattr(controller, "load_sheet", fail)
    monkeypatch.setattr(controller, "scan_fastqs", fail)
    for method in ("open", "read_bytes", "read_text", "write_bytes", "write_text", "rename", "unlink"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    updated = controller.apply_pair_adjudication(session, 0, views[0].r1_choices[0].display, "Automatic", True)
    assert updated is not session
    assert updated.sheet is session.sheet
    assert updated.mapping is session.mapping
    assert updated.inventory is session.inventory
    assert session.decisions == ()
    assert controller.pair_adjudication_views(session) == views
    assert controller.apply_pair_adjudication(session, 0, views[0].r1_choices[0].display, "Automatic", True) == updated
    for obj, field, value in [(session, "decisions", ()), (views[0], "confirmed", True),
                              (views[0].r1_choices[0], "index", 8)]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)


def test_adjudication_keeps_raw_collisions_and_reconciliation_findings(tmp_path):
    root, path = inputs(tmp_path)
    (root / "a_R1.fastq").touch()
    if (root / "a_R1.fastq").samefile(root / "A_R1.fastq"):
        pytest.skip("filesystem cannot represent distinct case-only filenames")
    session = controller.audit_session(str(root), str(path), "Auto")
    choice = controller.pair_adjudication_views(session)[0].r1_choices[0].display
    updated = controller.apply_pair_adjudication(session, 0, choice, "Automatic", True)
    assert updated.snapshot.reconciliation == session.snapshot.reconciliation
    assert updated.snapshot.case_collisions == session.snapshot.case_collisions
    assert updated.snapshot.case_collisions
    assert updated.snapshot.reconciliation.findings
    assert not updated.view.summary.ready_for_export


def test_session_retains_exact_absolute_sheet_path(tmp_path, monkeypatch):
    root, path = inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    session = controller.audit_session("fastqs", "sheet.csv", "Auto")
    assert session.sample_sheet_path == path
    assert session.sample_sheet_path.is_absolute()
    assert session.fastq_root == root
    assert session.view == controller.audit_inputs("fastqs", "sheet.csv", "Auto")


def test_export_profile_views_exact_metadata_and_manual_fields():
    from fastq_sheet_audit.profiles import list_profile_ids, load_profile
    views = controller.export_profile_views()
    assert tuple(view.profile_id for view in views) == list_profile_ids()
    assert controller.export_profile_views() == views
    manual = {
        "generic": (), "nfcore-rnaseq-3.27.0": ("strandedness",),
        "nfcore-methylseq-4.2.0": ("genome",), "nfcore-smrnaseq-2.4.1": (),
        "nfcore-viralrecon-3.0.0-illumina": (), "nfcore-viralrecon-3.0.0-nanopore": ("barcode",),
    }
    for view in views:
        profile = load_profile(view.profile_id)
        assert (view.display_name, view.input_kind, view.notes) == (profile.display_name, profile.input_kind, profile.notes)
        assert tuple(column.name for column in controller.manual_profile_columns(view)) == manual[view.profile_id]
        assert [(column.name, column.source_role, column.allowed_values) for column in view.columns] == [
            (column.name, column.source_role, column.allowed_values) for column in profile.columns
        ]
    nanopore = views[-1]
    assert nanopore.input_kind == "barcode_mapping"
    assert nanopore.columns[0].source_role == "sample"
    assert nanopore.columns[1].source_role is None


def test_exact_export_option_mappings():
    from fastq_sheet_audit.pathmap import ExportMode, TargetStyle
    assert controller.PATH_MODE_CHOICES == (
        ("Local absolute", ExportMode.LOCAL_ABSOLUTE),
        ("Relative to FASTQ root", ExportMode.RELATIVE_TO_ROOT),
        ("Rebased root", ExportMode.REBASED_ROOT),
    )
    for label, mode in controller.PATH_MODE_CHOICES:
        assert controller.path_mode_from_label(label) is mode
    for label, style in (("POSIX", TargetStyle.POSIX), ("Windows", TargetStyle.WINDOWS)):
        assert controller.target_style_from_label(label) is style
    for label in ("", "windows", "Relative", "auto"):
        with pytest.raises(ValueError):
            controller.path_mode_from_label(label)
        with pytest.raises(ValueError):
            controller.target_style_from_label(label)


@pytest.mark.parametrize("label, options, expected", [
    ("Relative to FASTQ root", {}, "A_R1.fastq"),
    ("Local absolute", {}, None),
    ("Rebased root", {"target_root": "/data/项目", "target_style_label": "POSIX"}, "/data/项目/A_R1.fastq"),
    ("Rebased root", {"target_root": "D:\\项目", "target_style_label": "Windows"}, "D:\\项目\\A_R1.fastq"),
])
def test_session_export_path_options(tmp_path, label, options, expected):
    session = session_fixture(tmp_path)
    result = controller.plan_session_export(session, "generic", label, **options)
    assert result.plan.result.validation.ok
    assert result.plan.rows[0].values["r1"] == (expected or str(session.fastq_root / "A_R1.fastq"))
    assert result.profile_view.profile_id == "generic"


@pytest.mark.parametrize("label, options", [
    ("Rebased root", {}), ("Rebased root", {"target_root": "/data"}),
    ("Rebased root", {"target_style_label": "POSIX"}),
    ("Local absolute", {"target_root": "/data"}),
    ("Relative to FASTQ root", {"target_style_label": "Windows"}),
])
def test_session_export_rejects_invalid_target_options(tmp_path, label, options):
    session = session_fixture(tmp_path)
    with pytest.raises(ValueError):
        controller.plan_session_export(session, "generic", label, **options)


@pytest.mark.parametrize("manual, code", [(None, "EMPTY_REQUIRED_VALUE"),
    ({2: {"strandedness": "reverse"}}, None), ({2: {"strandedness": "Reverse"}}, "VALUE_NOT_ALLOWED")])
def test_session_export_returns_manual_validation_findings(tmp_path, manual, code):
    session = session_fixture(tmp_path)
    result = controller.plan_session_export(session, "nfcore-rnaseq-3.27.0", "Relative to FASTQ root", explicit_values=manual)
    if code is None:
        assert result.plan.result.validation.ok
    else:
        assert result.plan.result.validation.findings[0].code == code


def test_barcode_and_nonready_planning_rejected(tmp_path):
    session = session_fixture(tmp_path)
    with pytest.raises(ValueError, match="barcode_mapping"):
        controller.plan_session_export(session, "nfcore-viralrecon-3.0.0-nanopore", "Local absolute")
    updated = controller.apply_pair_adjudication(session, 0, "Unassigned", "Automatic", False)
    with pytest.raises(ValueError, match="workflow is not ready"):
        controller.plan_session_export(updated, "generic", "Local absolute")


def test_planning_uses_effective_read_not_original_sheet_path(tmp_path):
    session = session_fixture(tmp_path, ambiguous=True)
    view = controller.pair_adjudication_views(session)[0]
    original_path = session.fastq_root / session.sheet.rows[0].cells[1]
    alternate_index = next(index for index, record in enumerate(session.snapshot.pair_resolutions[0].group.r1)
                           if record.path != original_path)
    updated = controller.apply_pair_adjudication(session, 0, view.r1_choices[alternate_index].display, "Automatic", False)
    effective = updated.snapshot.pair_resolutions[0].effective_r1
    result = controller.plan_session_export(updated, "generic", "Local absolute")
    assert result.plan.rows[0].values["r1"] == str(effective.path)
    assert result.plan.rows[0].values["r1"] != str(updated.fastq_root / updated.sheet.rows[0].cells[1])


def test_planning_no_reload_scan_writes_network_and_inputs_unchanged(tmp_path, monkeypatch):
    from dataclasses import FrozenInstanceError
    session = session_fixture(tmp_path)
    before = session.view
    manual = {2: {"strandedness": "reverse"}}
    original_open = Path.open
    def guarded_open(self, mode="r", *args, **kwargs):
        assert self.suffix == ".json" and "profile_data" in self.parts
        assert mode == "r"
        return original_open(self, mode, *args, **kwargs)
    def fail(*args, **kwargs):
        pytest.fail("planning accessed forbidden side effect")
    monkeypatch.setattr(controller, "load_sheet", fail)
    monkeypatch.setattr(controller, "scan_fastqs", fail)
    monkeypatch.setattr(Path, "open", guarded_open)
    for method in ("write_text", "write_bytes", "rename", "unlink"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("socket.socket", fail)
    result = controller.plan_session_export(session, "nfcore-rnaseq-3.27.0", "Relative to FASTQ root", explicit_values=manual)
    assert result.plan.result.validation.ok
    assert session.view is before
    assert session.decisions == ()
    assert manual == {2: {"strandedness": "reverse"}}
    for obj, field, value in [(result, "plan", None), (result.profile_view, "notes", "changed"),
                              (result.profile_view.columns[0], "source_role", None), (session, "sample_sheet_path", None)]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
