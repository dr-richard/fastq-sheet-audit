from dataclasses import FrozenInstanceError
from itertools import product

import pytest

from fastq_sheet_audit.column_mapping import ColumnReference, ColumnRole, map_columns
from fastq_sheet_audit.sheet import SampleSheet, SheetRow


def sheet(*headers):
    return SampleSheet(tuple(headers), ())


@pytest.mark.parametrize("headers", list(product(
    ("sample", "sample_id", "sampleid"),
    ("r1", "fastq_1", "fastq1", "read1", "read_1"),
    ("r2", "fastq_2", "fastq2", "read2", "read_2"),
)))
def test_automatic_exact_aliases(headers):
    result = map_columns(sheet(*headers), require_complete=True)
    assert result.complete
    assert result.unresolved == result.ambiguous == ()
    for index, role in enumerate(ColumnRole):
        mapping = result.for_role(role)
        assert mapping.automatic == mapping.selected == ColumnReference(index, headers[index])
        assert not mapping.explicit


@pytest.mark.parametrize("headers", [
    ("SAMPLE_ID", "Read1", "FASTQ2"),
    (" sample ", "\tread_1 ", " r2\t"),
])
def test_case_and_surrounding_whitespace(headers):
    result = map_columns(sheet(*headers))
    assert [mapping.selected.index for mapping in result.roles] == [0, 1, 2]
    assert [mapping.selected.header for mapping in result.roles] == list(headers)


def test_unknown_headers_are_unresolved_data():
    result = map_columns(sheet("subject", "forward", "reverse"))
    assert result.unresolved == tuple(ColumnRole)
    assert result.ambiguous == ()
    assert not result.complete


@pytest.mark.parametrize("role, headers", [
    (ColumnRole.SAMPLE, ("sample", "sample_id", "r1")),
    (ColumnRole.R1, ("r1", "fastq_1", "sample")),
    (ColumnRole.R2, ("r2", "read2", "sample", "r1")),
])
def test_multiple_aliases_are_ambiguous(role, headers):
    result = map_columns(sheet(*headers))
    mapping = result.for_role(role)
    assert mapping.candidates == (ColumnReference(0, headers[0]), ColumnReference(1, headers[1]))
    assert mapping.automatic is mapping.selected is None
    assert mapping.ambiguous
    assert result.ambiguous == (mapping,)
    assert role in result.unresolved


def test_explicit_override_resolves_ambiguity_and_retains_candidates():
    imported = sheet("sample", "sample_id", "r1", "fastq_1")
    result = map_columns(imported, {ColumnRole.SAMPLE: 1, ColumnRole.R1: 3}, require_complete=True)
    assert result.ambiguous == ()
    assert result.unresolved == (ColumnRole.R2,)
    for role, index in [(ColumnRole.SAMPLE, 1), (ColumnRole.R1, 3)]:
        mapping = result.for_role(role)
        assert mapping.selected.index == index
        assert mapping.explicit
        assert mapping.automatic is None
        assert len(mapping.candidates) == 2


def test_override_can_select_unknown_metadata_column():
    result = map_columns(sheet("subject", "files", "note"),
                         {ColumnRole.SAMPLE: 0, ColumnRole.R1: 1}, require_complete=True)
    assert result.complete
    assert result.for_role(ColumnRole.SAMPLE).candidates == ()


@pytest.mark.parametrize("index", [-1, 2, 100, True, "0", 0.0])
def test_invalid_column_index(index):
    with pytest.raises(ValueError, match="invalid column index"):
        map_columns(sheet("sample", "r1"), {ColumnRole.SAMPLE: index})


def test_same_column_cannot_fill_two_roles():
    with pytest.raises(ValueError, match="multiple roles"):
        map_columns(sheet("a", "b"), {ColumnRole.SAMPLE: 0, ColumnRole.R1: 0})


def test_override_cannot_reuse_an_automatically_selected_column():
    with pytest.raises(ValueError, match="multiple roles"):
        map_columns(sheet("sample", "r1"), {ColumnRole.R2: 1})


def test_punctuation_is_not_normalized():
    result = map_columns(sheet("sample-id", "read-1", "fastq.2", "sample id"))
    assert result.unresolved == tuple(ColumnRole)


def test_r2_optional():
    result = map_columns(sheet("sample", "r1"), require_complete=True)
    assert result.complete
    assert result.unresolved == (ColumnRole.R2,)


def test_r2_can_be_explicitly_unmapped():
    result = map_columns(sheet("sample", "r1", "r2"), {ColumnRole.R2: None}, require_complete=True)
    mapping = result.for_role(ColumnRole.R2)
    assert mapping.automatic == ColumnReference(2, "r2")
    assert mapping.selected is None
    assert mapping.explicit


@pytest.mark.parametrize("headers", [("sample",), ("r1",), ("sample", "sampleid", "r1")])
def test_complete_mapping_requires_sample_and_r1(headers):
    assert not map_columns(sheet(*headers)).complete
    with pytest.raises(ValueError, match="requires resolved roles"):
        map_columns(sheet(*headers), require_complete=True)


def test_column_identity_is_by_index_even_with_identical_headers():
    result = map_columns(sheet("sample", "sample", "r1"), {ColumnRole.SAMPLE: 1})
    assert result.for_role(ColumnRole.SAMPLE).candidates == (
        ColumnReference(0, "sample"), ColumnReference(1, "sample")
    )
    assert result.for_role(ColumnRole.SAMPLE).selected.index == 1


def test_original_sheet_and_override_dictionary_are_unchanged():
    imported = SampleSheet((" sample ", "r1", "note"),
                           (SheetRow(4, (" A-B ", "path.fastq", "1.00e-03")),))
    original_headers, original_rows = imported.headers, imported.rows
    overrides = {ColumnRole.SAMPLE: 0}
    result = map_columns(imported, overrides)
    assert imported.headers is original_headers
    assert imported.rows is original_rows
    assert imported.rows[0].cells == (" A-B ", "path.fastq", "1.00e-03")
    assert overrides == {ColumnRole.SAMPLE: 0}
    overrides[ColumnRole.SAMPLE] = 2
    assert result.for_role(ColumnRole.SAMPLE).selected.index == 0


def test_result_is_immutable():
    result = map_columns(sheet("sample", "r1"))
    with pytest.raises(FrozenInstanceError):
        result.roles = ()
    with pytest.raises(FrozenInstanceError):
        result.roles[0].selected = None
    with pytest.raises(FrozenInstanceError):
        result.roles[0].selected.index = 10


def test_unknown_override_role_rejected():
    with pytest.raises(ValueError, match="unknown column role"):
        map_columns(sheet("sample", "r1"), {"sample": 0})


def test_empty_sheet_mapping_is_unresolved():
    assert map_columns(sheet()).unresolved == tuple(ColumnRole)
