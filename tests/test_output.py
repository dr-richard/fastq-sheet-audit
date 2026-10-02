from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastq_sheet_audit.output import OutputRow, build_profile_sheet
from fastq_sheet_audit.profile_validation import validate_profile_sheet
from fastq_sheet_audit.profiles import load_profile
from fastq_sheet_audit.sheet import SampleSheet, SheetRow


def test_generic_single_end_candidate():
    result = build_profile_sheet(load_profile("generic"), [OutputRow(2, {"sample": "A", "r1": "A.fastq"})])
    assert result.sheet == SampleSheet(("sample", "r1"), (SheetRow(2, ("A", "A.fastq")),))
    assert result.validation.ok


def test_generic_paired_candidate():
    result = build_profile_sheet(load_profile("generic"), [
        OutputRow(2, {"r2": "A_R2.fastq", "sample": "A", "r1": "A_R1.fastq"}),
    ])
    assert result.sheet.headers == ("sample", "r1", "r2")
    assert result.sheet.rows[0].cells == ("A", "A_R1.fastq", "A_R2.fastq")
    assert result.validation.ok


def test_required_headers_present_with_missing_cells():
    result = build_profile_sheet(load_profile("generic"), [OutputRow(4, {})])
    assert result.sheet.headers == ("sample", "r1")
    assert result.sheet.rows == (SheetRow(4, ("", "")),)
    assert [finding.code for finding in result.validation.findings] == ["EMPTY_REQUIRED_VALUE"] * 2


def test_empty_input_still_includes_required_headers_only():
    result = build_profile_sheet(load_profile("generic"), iter(()))
    assert result.sheet == SampleSheet(("sample", "r1"), ())
    assert result.validation.ok


def test_explicit_empty_optional_value_includes_header_and_missing_cells():
    result = build_profile_sheet(load_profile("generic"), [
        OutputRow(2, {"sample": "A", "r1": "a"}),
        OutputRow(3, {"sample": "B", "r1": "b", "r2": ""}),
    ])
    assert result.sheet.headers == ("sample", "r1", "r2")
    assert result.sheet.rows == (SheetRow(2, ("A", "a", "")), SheetRow(3, ("B", "b", "")))


def test_profile_controls_header_order():
    profile = load_profile("generic")
    profile = replace(profile, columns=tuple(reversed(profile.columns)))
    result = build_profile_sheet(profile, [OutputRow(2, {"sample": "A", "r1": "a", "r2": "b"})])
    assert result.sheet.headers == ("r2", "r1", "sample")
    assert result.sheet.rows[0].cells == ("b", "a", "A")


def test_supplied_row_order_and_numbers_preserved():
    rows = [OutputRow(9, {"sample": "B", "r1": "b"}), OutputRow(3, {"sample": "A", "r1": "a"})]
    result = build_profile_sheet(load_profile("generic"), iter(rows))
    assert result.sheet.rows == (SheetRow(9, ("B", "b")), SheetRow(3, ("A", "a")))


def test_duplicate_row_numbers_rejected():
    with pytest.raises(ValueError, match="duplicate row_number"):
        build_profile_sheet(load_profile("generic"), [OutputRow(2, {}), OutputRow(2, {})])


@pytest.mark.parametrize("number", [True, False, "2", 2.0, None])
def test_invalid_row_numbers_rejected(number):
    with pytest.raises(ValueError, match="row_number"):
        build_profile_sheet(load_profile("generic"), [OutputRow(number, {})])


@pytest.mark.parametrize("key", ["metadata", "Sample", " sample ", "fastq_1", 1])
def test_unknown_exact_keys_rejected(key):
    with pytest.raises(ValueError, match="unknown column key"):
        build_profile_sheet(load_profile("generic"), [OutputRow(2, {key: "x"})])


@pytest.mark.parametrize("value", [1, True, None, 1.0, [], b"A"])
def test_nonstring_values_rejected(value):
    with pytest.raises(ValueError, match="must be a string"):
        build_profile_sheet(load_profile("generic"), [OutputRow(2, {"sample": value})])


def test_text_is_preserved_without_normalization():
    values = {"sample": " α-A.B +01 ", "r1": " run 空间/file.fastq ", "r2": "+7"}
    result = build_profile_sheet(load_profile("generic"), [OutputRow(2, values)])
    assert result.sheet.rows[0].cells == tuple(values[name] for name in result.sheet.headers)
    assert result.validation.ok


def test_defaults_are_never_inserted_or_used_to_include_optional_columns():
    profile = load_profile("generic")
    profile = replace(profile, columns=tuple(replace(column, default_value="default") for column in profile.columns))
    result = build_profile_sheet(profile, [OutputRow(2, {"sample": ""})])
    assert result.sheet.headers == ("sample", "r1")
    assert result.sheet.rows[0].cells == ("", "")
    assert not result.validation.ok


def test_invalid_rnaseq_strandedness_validation_is_propagated():
    profile = load_profile("nfcore-rnaseq-3.27.0")
    result = build_profile_sheet(profile, [OutputRow(8, {
        "sample": "A", "fastq_1": "path", "strandedness": "Forward",
    })])
    assert result.sheet.headers == ("sample", "fastq_1", "fastq_2", "strandedness")
    assert result.validation == validate_profile_sheet(result.sheet, profile)
    finding, = result.validation.findings
    assert finding.code == "VALUE_NOT_ALLOWED"
    assert (finding.row_number, finding.column, finding.value) == (8, "strandedness", "Forward")


def test_nanopore_barcode_remains_textual_with_leading_zero():
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    result = build_profile_sheet(profile, [OutputRow(2, {"sample": "A-B", "barcode": "01"})])
    assert result.sheet.headers == ("sample", "barcode")
    assert result.sheet.rows[0].cells == ("A-B", "01")
    assert result.validation.ok


def test_output_rows_and_result_are_immutable_snapshots():
    values = {"sample": "A", "r1": "path"}
    row = OutputRow(2, values)
    values["sample"] = "changed"
    assert row.values["sample"] == "A"
    with pytest.raises(TypeError):
        row.values["sample"] = "changed"
    with pytest.raises(FrozenInstanceError):
        row.row_number = 3
    result = build_profile_sheet(load_profile("generic"), [row])
    with pytest.raises(FrozenInstanceError):
        result.sheet = SampleSheet((), ())


def test_inputs_unchanged_and_deterministic():
    profile = load_profile("generic")
    values = {"sample": " A-B ", "r1": "path"}
    rows = [OutputRow(2, values)]
    columns = profile.columns
    result = build_profile_sheet(profile, rows)
    assert build_profile_sheet(profile, rows) == result
    assert values == {"sample": " A-B ", "r1": "path"}
    assert dict(rows[0].values) == values
    assert profile.columns is columns
    assert len(rows) == 1


def test_no_filesystem_network_or_environment_access(monkeypatch):
    profile = load_profile("generic")
    rows = [OutputRow(2, {"sample": "A", "r1": "path"})]

    def fail(*args, **kwargs):
        pytest.fail("builder accessed external state")

    for method in ("open", "stat", "resolve", "exists"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    monkeypatch.setattr("os.getenv", fail)
    assert build_profile_sheet(profile, rows).validation.ok
