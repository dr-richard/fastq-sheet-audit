import json
from dataclasses import FrozenInstanceError
from importlib.resources import files

import pytest

from fastq_sheet_audit.profiles import list_profile_ids, load_profile, parse_profile


def generic_data():
    return json.loads(files("fastq_sheet_audit.profile_data").joinpath("generic.json").read_text())


def test_load_generic():
    profile = load_profile("generic")
    assert profile.profile_id == "generic"
    assert profile.display_name
    assert profile.pipeline is profile.verified_version is profile.verified_date is None
    assert profile.source_reference
    assert profile.notes
    assert profile.single_end_supported
    assert [column.name for column in profile.columns] == ["sample", "r1", "r2"]
    assert [(column.required_column, column.required_value) for column in profile.columns] == [
        (True, True), (True, True), (False, False),
    ]


def test_required_column_and_value_are_independent():
    data = generic_data()
    data["columns"][2]["required_column"] = True
    profile = parse_profile(json.dumps(data))
    assert profile.columns[2].required_column
    assert not profile.columns[2].required_value


def test_structures_are_immutable():
    profile = load_profile("generic")
    with pytest.raises(FrozenInstanceError):
        profile.profile_id = "other"
    with pytest.raises(FrozenInstanceError):
        profile.columns[0].required_value = False
    assert isinstance(profile.columns, tuple)


def test_duplicate_columns_rejected():
    data = generic_data()
    data["columns"].append(dict(data["columns"][0]))
    with pytest.raises(ValueError, match="duplicate column"):
        parse_profile(json.dumps(data))


def test_allowed_values_and_default_are_preserved_immutably():
    data = generic_data()
    data["columns"][0].update(allowed_values=["A", "B"], default_value="A")
    profile = parse_profile(json.dumps(data))
    assert profile.columns[0].allowed_values == ("A", "B")
    assert profile.columns[0].default_value == "A"


def test_invalid_default_allowed_combination():
    data = generic_data()
    data["columns"][0].update(allowed_values=["A"], default_value="B")
    with pytest.raises(ValueError, match="not in allowed_values"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("field", list(generic_data()))
def test_missing_required_metadata(field):
    data = generic_data()
    del data[field]
    with pytest.raises(ValueError, match="missing fields"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("column_level", [False, True])
def test_unknown_fields_rejected(column_level):
    data = generic_data()
    target = data["columns"][0] if column_level else data
    target["executable"] = "print('never run')"
    with pytest.raises(ValueError, match="unknown fields"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("text", ["{", "", "not JSON", '{"x": 1,}', "[]", "null"])
def test_malformed_json_or_structure(text):
    with pytest.raises(ValueError):
        parse_profile(text)


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match="duplicate JSON field"):
        parse_profile('{"profile_id":"generic","profile_id":"other"}')


@pytest.mark.parametrize("flag", ["required_column", "required_value"])
@pytest.mark.parametrize("value", [1, "true", None])
def test_required_flags_are_strict_booleans(flag, value):
    data = generic_data()
    data["columns"][0][flag] = value
    with pytest.raises(ValueError, match="boolean"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("field, value", [
    ("single_end_supported", 1), ("display_name", ""), ("notes", []),
    ("pipeline", {}), ("verified_version", 2), ("verified_date", "2026-02-30"),
    ("columns", {}), ("columns", []), ("columns", ["sample"]),
])
def test_invalid_profile_types(field, value):
    data = generic_data()
    data[field] = value
    with pytest.raises(ValueError):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("field, value", [
    ("name", 1), ("allowed_values", "A"), ("allowed_values", [1]), ("default_value", []),
])
def test_invalid_column_types(field, value):
    data = generic_data()
    data["columns"][0][field] = value
    with pytest.raises(ValueError):
        parse_profile(json.dumps(data))


def test_deterministic_listing():
    assert list_profile_ids() == ("generic",)
    assert list_profile_ids() == list_profile_ids()


@pytest.mark.parametrize("profile_id", ["unknown", "../generic", "/tmp/generic", "GENERIC", None])
def test_unknown_id_rejected(profile_id):
    with pytest.raises(ValueError, match="unknown profile ID"):
        load_profile(profile_id)


def test_offline_loading(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("profile loading attempted network access")

    monkeypatch.setattr("socket.socket", fail)
    assert load_profile("generic").profile_id == "generic"
