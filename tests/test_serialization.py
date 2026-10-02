import csv
import io
from pathlib import Path

import pytest

from fastq_sheet_audit.serialization import SheetFormat, serialize_sheet
from fastq_sheet_audit.sheet import SampleSheet, SheetRow


def sheet(headers, *rows):
    return SampleSheet(tuple(headers), tuple(SheetRow(i, tuple(cells)) for i, cells in enumerate(rows, 2)))


@pytest.mark.parametrize("format, expected", [
    (SheetFormat.CSV, "sample,r1\nA,A.fastq\n"),
    (SheetFormat.TSV, "sample\tr1\nA\tA.fastq\n"),
])
def test_simple_formats_and_fixed_lf(format, expected):
    result = serialize_sheet(sheet(("sample", "r1"), ("A", "A.fastq")), format)
    assert result == expected
    assert "\r" not in result
    assert result.endswith("\n") and not result.endswith("\n\n")


@pytest.mark.parametrize("format, value, expected", [
    (SheetFormat.CSV, "a,b", 'x\n"a,b"\n'),
    (SheetFormat.TSV, "a\tb", 'x\n"a\tb"\n'),
    (SheetFormat.CSV, "a\tb", "x\na\tb\n"),
    (SheetFormat.TSV, "a,b", "x\na,b\n"),
    (SheetFormat.CSV, 'a"b', 'x\n"a""b"\n'),
    (SheetFormat.TSV, 'a"b', 'x\n"a""b"\n'),
    (SheetFormat.CSV, "first\nsecond", 'x\n"first\nsecond"\n'),
    (SheetFormat.TSV, "first\nsecond", 'x\n"first\nsecond"\n'),
    (SheetFormat.CSV, "first\r\nsecond", 'x\n"first\r\nsecond"\n'),
    (SheetFormat.TSV, "first\r\nsecond", 'x\n"first\r\nsecond"\n'),
])
def test_standard_quoting_and_embedded_line_endings(format, value, expected):
    assert serialize_sheet(sheet(("x",), (value,)), format) == expected


@pytest.mark.parametrize("format", list(SheetFormat))
def test_exact_unicode_spaces_signs_formula_text_and_paths(format):
    values = (" α β ", "é", "e\u0301", "001", "+7", "-3", "=SUM(A1:A2)",
              "@value", "  spaced  ", "D:\\Run 1\\A.fastq")
    headers = tuple(f"column{i}" for i in range(len(values)))
    candidate = sheet(headers, values)
    delimiter = "," if format is SheetFormat.CSV else "\t"
    text = serialize_sheet(candidate, format)
    assert text == delimiter.join(headers) + "\n" + delimiter.join(values) + "\n"
    assert list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)) == [list(headers), list(values)]


@pytest.mark.parametrize("format", list(SheetFormat))
def test_headers_are_preserved_and_quoted(format):
    delimiter = "," if format is SheetFormat.CSV else "\t"
    headers = (" sample ", f"a{delimiter}b", 'a"b', "α\nβ")
    text = serialize_sheet(sheet(headers), format)
    assert list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)) == [list(headers)]


@pytest.mark.parametrize("format, delimiter", [(SheetFormat.CSV, ","), (SheetFormat.TSV, "\t")])
def test_empty_cells_and_empty_data_rows(format, delimiter):
    candidate = sheet(("a", "b"), ("", ""), ("x", ""))
    assert serialize_sheet(candidate, format) == f"a{delimiter}b\n{delimiter}\nx{delimiter}\n"


def test_empty_single_cell_uses_standard_writer_quoting():
    assert serialize_sheet(sheet(("a",), ("",)), SheetFormat.CSV) == 'a\n""\n'


@pytest.mark.parametrize("format, expected", [(SheetFormat.CSV, "a,b\n"), (SheetFormat.TSV, "a\tb\n")])
def test_header_only(format, expected):
    assert serialize_sheet(sheet(("a", "b")), format) == expected


def test_row_order_is_not_sorted_by_original_number():
    candidate = SampleSheet(("x",), (SheetRow(9, ("B",)), SheetRow(3, ("A",))))
    assert serialize_sheet(candidate, SheetFormat.CSV) == "x\nB\nA\n"


@pytest.mark.parametrize("cells", [("a",), ("a", "b", "c")])
def test_malformed_row_width_rejected(cells):
    with pytest.raises(ValueError, match="row 2: cell count"):
        serialize_sheet(sheet(("a", "b"), cells), SheetFormat.CSV)


@pytest.mark.parametrize("format", ["csv", "tsv", None, 1, True])
def test_invalid_format_rejected(format):
    with pytest.raises(ValueError, match="SheetFormat"):
        serialize_sheet(sheet(("a",)), format)


def test_inputs_unchanged_and_repeated_output_identical():
    candidate = sheet((" α ", "b"), ("001", 'a,b"\r\nx'))
    original = SampleSheet(candidate.headers, candidate.rows)
    headers, rows = candidate.headers, candidate.rows
    text = serialize_sheet(candidate, SheetFormat.CSV)
    assert serialize_sheet(candidate, SheetFormat.CSV) == text
    assert candidate == original
    assert candidate.headers is headers
    assert candidate.rows is rows


def test_no_external_access(monkeypatch):
    candidate = sheet(("sample", "r1"), ("A", "path"))

    def fail(*args, **kwargs):
        pytest.fail("serializer accessed external state")

    for method in ("open", "stat", "resolve", "exists"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    monkeypatch.setattr("os.getenv", fail)
    monkeypatch.setattr("locale.getpreferredencoding", fail)
    monkeypatch.setattr("platform.system", fail)
    assert serialize_sheet(candidate, SheetFormat.CSV) == "sample,r1\nA,path\n"
