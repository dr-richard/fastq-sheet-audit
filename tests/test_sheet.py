from dataclasses import FrozenInstanceError

import pytest

from fastq_sheet_audit.sheet import SampleSheet, SheetRow, load_sheet


def write_sheet(tmp_path, text, suffix=".csv", encoding="utf-8"):
    path = tmp_path / ("sheet" + suffix)
    path.write_bytes(text.encode(encoding))
    return path


@pytest.mark.parametrize("suffix, delimiter", [(".csv", ","), (".tsv", "\t")])
def test_csv_and_tsv_without_semantic_columns(tmp_path, suffix, delimiter):
    path = write_sheet(tmp_path, f"subject{delimiter}condition\nα{delimiter}treated\n", suffix)
    assert load_sheet(path) == SampleSheet(
        ("subject", "condition"), (SheetRow(2, ("α", "treated")),)
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_bom_and_line_endings(tmp_path, newline, encoding):
    path = write_sheet(tmp_path, f"id,note{newline}A,café{newline}", encoding=encoding)
    assert load_sheet(path) == SampleSheet(("id", "note"), (SheetRow(2, ("A", "café")),))


def test_quoted_comma_and_escaped_quotes(tmp_path):
    path = write_sheet(tmp_path, 'id,note\nA,"dose, high; ""replicate"""\n')
    assert load_sheet(path).rows == (SheetRow(2, ("A", 'dose, high; "replicate"')),)


def test_quoted_tsv_field(tmp_path):
    path = write_sheet(tmp_path, 'id\tnote\nA\t"one\ttwo"\n', ".tsv")
    assert load_sheet(path).rows[0].cells == ("A", "one\ttwo")


def test_all_columns_and_order_and_metadata_are_preserved(tmp_path):
    path = write_sheet(tmp_path, ' batch ,note,id,concentration,unknown\n'
                       ' 001 ," a,b ",A-B,1.00e-03,NA\n')
    assert load_sheet(path) == SampleSheet(
        (" batch ", "note", "id", "concentration", "unknown"),
        (SheetRow(2, (" 001 ", " a,b ", "A-B", "1.00e-03", "NA")),),
    )


def test_original_row_numbers_and_multiline_cells(tmp_path):
    path = write_sheet(tmp_path, 'id,note\r\n\r\nA,"first\r\nsecond"\r\n,\r\nB,last\r\n')
    assert load_sheet(path).rows == (
        SheetRow(3, ("A", "first\r\nsecond")), SheetRow(6, ("B", "last")),
    )


@pytest.mark.parametrize("header", ["id,id", " id ,id", "id, id ", "x,x,x"])
def test_duplicate_headers(tmp_path, header):
    path = write_sheet(tmp_path, header + "\n")
    with pytest.raises(ValueError, match="duplicate headers"):
        load_sheet(path)


def test_header_comparison_is_exact_after_trimming(tmp_path):
    path = write_sheet(tmp_path, "ID,id\nA,B\n")
    assert load_sheet(path).headers == ("ID", "id")


@pytest.mark.parametrize("row", ["A,B,C", ",,", "A,B,"])
def test_surplus_fields_are_rejected(tmp_path, row):
    path = write_sheet(tmp_path, "id,note\n" + row + "\n")
    with pytest.raises(ValueError, match="row 2: more fields"):
        load_sheet(path)


@pytest.mark.parametrize("row", ['A,"unterminated', 'A,"closed"junk', 'A,un"quoted', 'A,"x" "y"'])
@pytest.mark.parametrize("suffix, delimiter", [(".csv", ","), (".tsv", "\t")])
def test_malformed_quoting(tmp_path, row, suffix, delimiter):
    path = write_sheet(tmp_path, "id" + delimiter + "note\n" + row.replace(",", delimiter), suffix)
    with pytest.raises(ValueError, match="quot"):
        load_sheet(path)


@pytest.mark.parametrize("text", ["", "\n", ",\n", '"",""\n', "  , \n"])
def test_missing_header(tmp_path, text):
    path = write_sheet(tmp_path, text)
    with pytest.raises(ValueError, match="no header"):
        load_sheet(path)


def test_blank_rows_only_skip_empty_cells(tmp_path):
    path = write_sheet(tmp_path, 'id,note\n\n,\n"",""\n ,\nA,\n,B\n')
    assert load_sheet(path).rows == (
        SheetRow(5, (" ", "")), SheetRow(6, ("A", "")), SheetRow(7, ("", "B")),
    )


def test_short_row_gets_empty_trailing_cells(tmp_path):
    path = write_sheet(tmp_path, "a,b,c\nx\n")
    assert load_sheet(path).rows == (SheetRow(2, ("x", "", "")),)


def test_header_only_sheet(tmp_path):
    assert load_sheet(write_sheet(tmp_path, "id,note\n")) == SampleSheet(("id", "note"), ())


def test_model_is_immutable(tmp_path):
    sheet = load_sheet(write_sheet(tmp_path, "id\nA\n"))
    with pytest.raises(FrozenInstanceError):
        sheet.headers = ("changed",)
    with pytest.raises(FrozenInstanceError):
        sheet.rows[0].row_number = 10
    assert isinstance(sheet.rows, tuple)
    assert isinstance(sheet.rows[0].cells, tuple)
