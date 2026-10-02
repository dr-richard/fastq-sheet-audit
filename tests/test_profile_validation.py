from dataclasses import FrozenInstanceError, replace

import pytest

from fastq_sheet_audit.profile_validation import ProfileFinding, validate_profile_sheet
from fastq_sheet_audit.profiles import ProfileColumn, load_profile
from fastq_sheet_audit.sheet import SampleSheet, SheetRow


def candidate(headers, *rows):
    return SampleSheet(tuple(headers), tuple(SheetRow(i, tuple(row)) for i, row in enumerate(rows, 2)))


def single_column_profile(column):
    return replace(load_profile("generic"), columns=(column,))


def test_clean_generic_candidate():
    sheet = candidate(("sample", "r1", "r2"), ("A", "A_R1.fastq", "A_R2.fastq"))
    result = validate_profile_sheet(sheet, load_profile("generic"))
    assert result.profile_id == "generic"
    assert result.findings == ()
    assert result.ok is True


def test_missing_required_column_matches_exactly():
    sheet = candidate((" Sample ", "r1"), ("A", "A.fastq"))
    result = validate_profile_sheet(sheet, load_profile("generic"))
    assert result.findings == (ProfileFinding(
        "MISSING_REQUIRED_COLUMN", "required column 'sample' is missing", None, "sample", None,
    ),)
    assert result.ok is False


def test_missing_optional_column():
    sheet = candidate(("sample", "r1"), ("A", "A.fastq"))
    assert validate_profile_sheet(sheet, load_profile("generic")).ok


def test_empty_required_value_does_not_apply_default():
    column = ProfileColumn("sample", True, True, "string", default_value="replacement")
    sheet = candidate(("sample",), ("",))
    result = validate_profile_sheet(sheet, single_column_profile(column))
    finding, = result.findings
    assert finding.code == "EMPTY_REQUIRED_VALUE"
    assert finding.row_number == 2
    assert finding.column == "sample"
    assert finding.value == ""
    assert sheet.rows[0].cells == ("",)


@pytest.mark.parametrize("value_type, allowed", [("string", ("A",)), ("integer", (1,))])
def test_empty_optional_value_skips_type_and_allowed_checks(value_type, allowed):
    profile = single_column_profile(ProfileColumn("x", True, False, value_type, allowed))
    assert validate_profile_sheet(candidate(("x",), ("",)), profile).ok


def test_whitespace_is_not_empty_or_normalized():
    profile = single_column_profile(ProfileColumn("x", True, True, "string"))
    sheet = candidate(("x",), ("   ",))
    assert validate_profile_sheet(sheet, profile).ok
    restricted = replace(profile, columns=(replace(profile.columns[0], allowed_values=("A",)),))
    result = validate_profile_sheet(sheet, restricted)
    assert result.findings[0].code == "VALUE_NOT_ALLOWED"
    assert result.findings[0].value == "   "


@pytest.mark.parametrize("value, valid", [("forward", True), ("auto", True), ("Forward", False),
                                          (" auto", False), ("", False)])
def test_rnaseq_strandedness_contract(value, valid):
    sheet = candidate(("sample", "fastq_1", "fastq_2", "strandedness"), ("A", "anything", "", value))
    result = validate_profile_sheet(sheet, load_profile("nfcore-rnaseq-3.27.0"))
    assert result.ok is valid
    if not valid:
        assert result.findings[0].column == "strandedness"
        assert result.findings[0].code == ("EMPTY_REQUIRED_VALUE" if value == "" else "VALUE_NOT_ALLOWED")


@pytest.mark.parametrize("value", ["0", "01", "42", "+7", "-3"])
def test_valid_integer_lexical_forms(value):
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    sheet = candidate(("sample", "barcode"), ("A-B", value))
    assert validate_profile_sheet(sheet, profile).ok
    assert sheet.rows[0].cells == ("A-B", value)


@pytest.mark.parametrize("value", ["1.0", "1e2", " 1", "1 ", "True", "１", "+", "-", "1\n", "1_0"])
def test_invalid_integer_lexical_forms(value):
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    result = validate_profile_sheet(candidate(("sample", "barcode"), ("A", value)), profile)
    finding, = result.findings
    assert finding.code == "INVALID_INTEGER"
    assert finding.column == "barcode"
    assert finding.value == value
    assert not result.ok


@pytest.mark.parametrize("value, valid", [("01", True), ("+1", True), ("-3", True), ("2", False)])
def test_integer_allowed_values_after_parsing(value, valid):
    profile = single_column_profile(ProfileColumn("barcode", True, True, "integer", (1, -3)))
    result = validate_profile_sheet(candidate(("barcode",), (value,)), profile)
    assert result.ok is valid
    if not valid:
        assert result.findings[0].code == "VALUE_NOT_ALLOWED"
        assert result.findings[0].value == value


def test_duplicate_profile_column_does_not_choose_or_validate_one():
    sheet = candidate(("sample", "sample", "r1"), ("", "A", "path"))
    result = validate_profile_sheet(sheet, load_profile("generic"))
    finding, = result.findings
    assert finding.code == "DUPLICATE_PROFILE_COLUMN"
    assert finding.column == "sample"
    assert finding.row_number is finding.value is None


def test_unrelated_extra_and_duplicate_columns_are_ignored_and_preserved():
    sheet = candidate(("note", "sample", "r1", "note"), ("1.00e-03", "A", "path", " α "))
    assert validate_profile_sheet(sheet, load_profile("generic")).ok
    assert sheet.headers == ("note", "sample", "r1", "note")
    assert sheet.rows[0].cells == ("1.00e-03", "A", "path", " α ")


def test_deterministic_column_then_sheet_row_order():
    sheet = SampleSheet(("r1", "sample"), (SheetRow(9, ("", "")), SheetRow(3, ("", ""))))
    profile = load_profile("nfcore-rnaseq-3.27.0")
    result = validate_profile_sheet(sheet, profile)
    assert [(finding.column, finding.row_number, finding.code) for finding in result.findings] == [
        ("sample", 9, "EMPTY_REQUIRED_VALUE"), ("sample", 3, "EMPTY_REQUIRED_VALUE"),
        ("fastq_1", None, "MISSING_REQUIRED_COLUMN"),
        ("fastq_2", None, "MISSING_REQUIRED_COLUMN"),
        ("strandedness", None, "MISSING_REQUIRED_COLUMN"),
    ]
    assert validate_profile_sheet(sheet, profile) == result


def test_result_and_findings_are_immutable():
    result = validate_profile_sheet(candidate(()), load_profile("generic"))
    with pytest.raises(FrozenInstanceError):
        result.findings = ()
    with pytest.raises(FrozenInstanceError):
        result.findings[0].value = "changed"
    assert isinstance(result.findings, tuple)


def test_inputs_remain_unchanged():
    sheet = candidate(("sample", "barcode"), (" A-B ", "01"))
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    headers, rows, columns = sheet.headers, sheet.rows, profile.columns
    assert validate_profile_sheet(sheet, profile).ok
    assert sheet.headers is headers
    assert sheet.rows is rows
    assert profile.columns is columns
    assert sheet.rows[0].cells == (" A-B ", "01")


def test_no_hidden_path_or_sample_name_rules():
    sheet = candidate(("sample", "r1"), (" A-B / α ", "not a FASTQ path"))
    assert validate_profile_sheet(sheet, load_profile("generic")).ok


def test_optional_column_when_present_still_requires_its_value():
    profile = single_column_profile(ProfileColumn("x", False, True, "string"))
    assert validate_profile_sheet(candidate(()), profile).ok
    assert validate_profile_sheet(candidate(("x",), ("",)), profile).findings[0].code == "EMPTY_REQUIRED_VALUE"


def test_malformed_manual_row_width_rejected():
    sheet = SampleSheet(("sample", "r1"), (SheetRow(2, ("A",)),))
    with pytest.raises(ValueError, match="cell count"):
        validate_profile_sheet(sheet, load_profile("generic"))
