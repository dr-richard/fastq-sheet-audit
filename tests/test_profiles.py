import json
from dataclasses import FrozenInstanceError
from importlib.resources import files

import pytest

from fastq_sheet_audit.profiles import list_profile_ids, load_profile, parse_profile


FASTQ_PROFILE_IDS = (
    "generic", "nfcore-methylseq-4.2.0", "nfcore-rnaseq-3.27.0", "nfcore-smrnaseq-2.4.1",
    "nfcore-viralrecon-3.0.0-illumina",
)


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
    assert list_profile_ids() == (
        "generic", "nfcore-methylseq-4.2.0", "nfcore-rnaseq-3.27.0", "nfcore-smrnaseq-2.4.1",
        "nfcore-viralrecon-3.0.0-illumina",
        "nfcore-viralrecon-3.0.0-nanopore",
    )
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
    assert load_profile("nfcore-rnaseq-3.27.0").profile_id == "nfcore-rnaseq-3.27.0"
    assert load_profile("nfcore-methylseq-4.2.0").profile_id == "nfcore-methylseq-4.2.0"
    assert load_profile("nfcore-smrnaseq-2.4.1").profile_id == "nfcore-smrnaseq-2.4.1"
    assert load_profile("nfcore-viralrecon-3.0.0-illumina").profile_id == "nfcore-viralrecon-3.0.0-illumina"
    assert load_profile("nfcore-viralrecon-3.0.0-nanopore").profile_id == "nfcore-viralrecon-3.0.0-nanopore"


def test_load_nfcore_viralrecon_illumina_metadata():
    profile = load_profile("nfcore-viralrecon-3.0.0-illumina")
    assert profile.profile_id == "nfcore-viralrecon-3.0.0-illumina"
    assert profile.display_name == "nf-core/viralrecon 3.0.0 — Illumina"
    assert profile.pipeline == "nf-core/viralrecon"
    assert profile.verified_version == "3.0.0"
    assert profile.verified_date == "2026-10-03"
    assert profile.source_reference == (
        "Official nf-core/viralrecon 3.0.0 usage documentation: "
        "https://nf-co.re/viralrecon/3.0.0/docs/usage/; official tagged input schema: "
        "https://github.com/nf-core/viralrecon/blob/3.0.0/assets/schema_input.json"
    )
    assert profile.single_end_supported is True


def test_nfcore_viralrecon_illumina_column_contract():
    profile = load_profile("nfcore-viralrecon-3.0.0-illumina")
    assert [column.name for column in profile.columns] == ["sample", "fastq_1", "fastq_2"]
    assert [(column.required_column, column.required_value) for column in profile.columns] == [
        (True, True), (True, True), (True, False),
    ]
    assert all(column.default_value is None for column in profile.columns)
    assert all(column.allowed_values is None for column in profile.columns)
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-viralrecon-3.0.0-illumina.json"
    ).read_text())
    assert all("default_value" not in column and "allowed_values" not in column
               for column in data["columns"])


def test_nfcore_viralrecon_notes_explain_scope_and_preserve_sample_ids():
    profile = load_profile("nfcore-viralrecon-3.0.0-illumina")
    assert profile.notes == (
        "Illumina-only samplesheet profile; no Nanopore compatibility is claimed. "
        "The fastq_2 column is required but its values may be empty for single-end Illumina data. "
        "Viralrecon documentation says dashes and spaces in sample names are converted to "
        "underscores downstream; fastq-sheet-audit itself does not silently rename or normalize "
        "sample IDs. No biological metadata is inferred or defaulted."
    )


def test_smrnaseq_profile_remains_unchanged():
    expected = {
        "profile_id": "nfcore-smrnaseq-2.4.1",
        "display_name": "nf-core/smrnaseq 2.4.1",
        "pipeline": "nf-core/smrnaseq",
        "verified_version": "2.4.1",
        "verified_date": "2026-10-03",
        "source_reference": (
            "Official nf-core/smrnaseq 2.4.1 usage documentation: "
            "https://nf-co.re/smrnaseq/2.4.1/docs/usage/; official tagged input schema: "
            "https://github.com/nf-core/smrnaseq/blob/2.4.1/assets/schema_input.json"
        ),
        "columns": [
            {"name": "sample", "source_role": "sample", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_1", "source_role": "r1", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_2", "source_role": "r2", "value_type": "string", "required_column": False, "required_value": False},
        ],
        "input_kind": "fastq_samplesheet",
        "single_end_supported": True,
        "notes": (
            "Pipeline documentation says R2 may be supplied, but downstream small-RNA processing "
            "primarily uses R1. This profile is declarative metadata only; fastq-sheet-audit "
            "does not silently discard R2. No biological metadata is inferred or defaulted."
        ),
    }
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-smrnaseq-2.4.1.json"
    ).read_text())
    assert data == expected
    assert load_profile("nfcore-smrnaseq-2.4.1") == parse_profile(json.dumps(expected))


def test_load_nfcore_smrnaseq_metadata():
    profile = load_profile("nfcore-smrnaseq-2.4.1")
    assert profile.profile_id == "nfcore-smrnaseq-2.4.1"
    assert profile.display_name == "nf-core/smrnaseq 2.4.1"
    assert profile.pipeline == "nf-core/smrnaseq"
    assert profile.verified_version == "2.4.1"
    assert profile.verified_date == "2026-10-03"
    assert profile.source_reference == (
        "Official nf-core/smrnaseq 2.4.1 usage documentation: "
        "https://nf-co.re/smrnaseq/2.4.1/docs/usage/; official tagged input schema: "
        "https://github.com/nf-core/smrnaseq/blob/2.4.1/assets/schema_input.json"
    )
    assert profile.single_end_supported is True
    assert profile.notes == (
        "Pipeline documentation says R2 may be supplied, but downstream small-RNA processing "
        "primarily uses R1. This profile is declarative metadata only; fastq-sheet-audit "
        "does not silently discard R2. No biological metadata is inferred or defaulted."
    )


def test_nfcore_smrnaseq_core_column_contract():
    profile = load_profile("nfcore-smrnaseq-2.4.1")
    assert [column.name for column in profile.columns] == ["sample", "fastq_1", "fastq_2"]
    assert [(column.required_column, column.required_value) for column in profile.columns] == [
        (True, True), (True, True), (False, False),
    ]
    assert all(column.default_value is None for column in profile.columns)
    assert all(column.allowed_values is None for column in profile.columns)
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-smrnaseq-2.4.1.json"
    ).read_text())
    assert all("default_value" not in column and "allowed_values" not in column
               for column in data["columns"])


def test_methylseq_profile_remains_unchanged():
    expected = {
        "profile_id": "nfcore-methylseq-4.2.0",
        "display_name": "nf-core/methylseq 4.2.0",
        "pipeline": "nf-core/methylseq",
        "verified_version": "4.2.0",
        "verified_date": "2026-10-03",
        "source_reference": (
            "Official nf-core/methylseq 4.2.0 usage documentation: "
            "https://nf-co.re/methylseq/4.2.0/docs/usage/; official tagged input schema: "
            "https://github.com/nf-core/methylseq/blob/4.2.0/assets/schema_input.json"
        ),
        "columns": [
            {"name": "sample", "source_role": "sample", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_1", "source_role": "r1", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_2", "source_role": "r2", "value_type": "string", "required_column": True, "required_value": False},
            {"name": "genome", "source_role": None, "value_type": "string", "required_column": True, "required_value": False},
        ],
        "input_kind": "fastq_samplesheet",
        "single_end_supported": True,
        "notes": "Core portable samplesheet contract only. The fastq_2 and genome columns are required but their values may be empty. No genome or biological metadata is inferred or defaulted.",
    }
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-methylseq-4.2.0.json"
    ).read_text())
    assert data == expected
    assert load_profile("nfcore-methylseq-4.2.0") == parse_profile(json.dumps(expected))


def test_load_nfcore_methylseq_metadata():
    profile = load_profile("nfcore-methylseq-4.2.0")
    assert profile.profile_id == "nfcore-methylseq-4.2.0"
    assert profile.display_name == "nf-core/methylseq 4.2.0"
    assert profile.pipeline == "nf-core/methylseq"
    assert profile.verified_version == "4.2.0"
    assert profile.verified_date == "2026-10-03"
    assert profile.source_reference == (
        "Official nf-core/methylseq 4.2.0 usage documentation: "
        "https://nf-co.re/methylseq/4.2.0/docs/usage/; official tagged input schema: "
        "https://github.com/nf-core/methylseq/blob/4.2.0/assets/schema_input.json"
    )
    assert profile.single_end_supported is True


def test_nfcore_methylseq_core_column_contract():
    profile = load_profile("nfcore-methylseq-4.2.0")
    assert [column.name for column in profile.columns] == [
        "sample", "fastq_1", "fastq_2", "genome",
    ]
    assert [(column.required_column, column.required_value) for column in profile.columns] == [
        (True, True), (True, True), (True, False), (True, False),
    ]
    assert all(column.default_value is None for column in profile.columns)
    assert all(column.allowed_values is None for column in profile.columns)
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-methylseq-4.2.0.json"
    ).read_text())
    assert all("default_value" not in column and "allowed_values" not in column
               for column in data["columns"])


def test_rnaseq_profile_remains_unchanged():
    expected = {
        "profile_id": "nfcore-rnaseq-3.27.0",
        "display_name": "nf-core/rnaseq 3.27.0",
        "pipeline": "nf-core/rnaseq",
        "verified_version": "3.27.0",
        "verified_date": "2026-10-03",
        "source_reference": (
            "Official nf-core/rnaseq 3.27.0 usage documentation: "
            "https://nf-co.re/rnaseq/3.27.0/docs/usage/; official tagged input schema: "
            "https://github.com/nf-core/rnaseq/blob/3.27.0/assets/schema_input.json"
        ),
        "columns": [
            {"name": "sample", "source_role": "sample", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_1", "source_role": "r1", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_2", "source_role": "r2", "value_type": "string", "required_column": True, "required_value": False},
            {"name": "strandedness", "source_role": None, "value_type": "string", "required_column": True, "required_value": True,
             "allowed_values": ["forward", "reverse", "unstranded", "auto"], "default_value": None},
        ],
        "input_kind": "fastq_samplesheet",
        "single_end_supported": True,
        "notes": "Core portable samplesheet contract only. The fastq_2 column is required but may have empty values for single-end data. Strandedness must be supplied explicitly; no biological metadata is inferred or defaulted.",
    }
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-rnaseq-3.27.0.json"
    ).read_text())
    assert data == expected
    assert load_profile("nfcore-rnaseq-3.27.0") == parse_profile(json.dumps(expected))


def test_load_nfcore_rnaseq_metadata():
    profile = load_profile("nfcore-rnaseq-3.27.0")
    assert profile.profile_id == "nfcore-rnaseq-3.27.0"
    assert profile.display_name == "nf-core/rnaseq 3.27.0"
    assert profile.pipeline == "nf-core/rnaseq"
    assert profile.verified_version == "3.27.0"
    assert profile.verified_date == "2026-10-03"
    assert profile.source_reference == (
        "Official nf-core/rnaseq 3.27.0 usage documentation: "
        "https://nf-co.re/rnaseq/3.27.0/docs/usage/; official tagged input schema: "
        "https://github.com/nf-core/rnaseq/blob/3.27.0/assets/schema_input.json"
    )
    assert profile.single_end_supported is True


def test_nfcore_rnaseq_core_column_contract():
    profile = load_profile("nfcore-rnaseq-3.27.0")
    assert [column.name for column in profile.columns] == [
        "sample", "fastq_1", "fastq_2", "strandedness",
    ]
    assert [(column.required_column, column.required_value) for column in profile.columns] == [
        (True, True), (True, True), (True, False), (True, True),
    ]
    assert profile.columns[3].allowed_values == ("forward", "reverse", "unstranded", "auto")
    assert profile.columns[3].default_value is None
    assert all(column.default_value is None for column in profile.columns)
    assert all(column.allowed_values is None for column in profile.columns[:3])
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-rnaseq-3.27.0.json"
    ).read_text())
    assert data["columns"][3]["default_value"] is None


def test_generic_profile_remains_unchanged():
    expected = {
        "profile_id": "generic",
        "display_name": "Generic FASTQ sheet",
        "pipeline": None,
        "verified_version": None,
        "verified_date": None,
        "source_reference": "fastq-sheet-audit generic export specification",
        "columns": [
            {"name": "sample", "source_role": "sample", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "r1", "source_role": "r1", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "r2", "source_role": "r2", "value_type": "string", "required_column": False, "required_value": False},
        ],
        "input_kind": "fastq_samplesheet",
        "single_end_supported": True,
        "notes": "Conservative generic export; no pipeline compatibility claim. R2 may be omitted or empty for single-end data.",
    }
    assert generic_data() == expected
    assert load_profile("generic") == parse_profile(json.dumps(expected))


@pytest.mark.parametrize("profile_id", ["../generic", "generic/1.0", "generic\\1.0", "generic..1", "generic."])
def test_dotted_profile_id_validation_rejects_unsafe_ids(profile_id):
    data = generic_data()
    data["profile_id"] = profile_id
    with pytest.raises(ValueError, match="invalid profile_id"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("profile_id", FASTQ_PROFILE_IDS)
def test_every_bundled_column_declares_string_type(profile_id):
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        profile_id + ".json"
    ).read_text())
    assert all(column["value_type"] == "string" for column in data["columns"])
    assert all(column.value_type == "string" for column in load_profile(profile_id).columns)


@pytest.mark.parametrize("value_type, allowed, default", [
    ("string", ["A", "B"], "A"),
    ("string", ["", " α "], ""),
    ("integer", [0, 1, -2], 0),
    ("integer", [1, 2], 2),
    ("integer", None, None),
    ("integer", None, -3),
])
def test_typed_values_load_immutably(value_type, allowed, default):
    data = generic_data()
    data["columns"][0].update(value_type=value_type, allowed_values=allowed, default_value=default)
    column = parse_profile(json.dumps(data)).columns[0]
    assert column.value_type == value_type
    assert column.allowed_values == (tuple(allowed) if allowed is not None else None)
    assert column.default_value == default
    assert type(column.default_value) is type(default)
    with pytest.raises(FrozenInstanceError):
        column.value_type = "integer"


@pytest.mark.parametrize("value_type, field, value", [
    ("string", "allowed_values", [1]),
    ("string", "allowed_values", [True]),
    ("string", "default_value", 1),
    ("string", "default_value", False),
    ("integer", "allowed_values", [True]),
    ("integer", "allowed_values", [1, False]),
    ("integer", "allowed_values", [1.0]),
    ("integer", "allowed_values", ["1"]),
    ("integer", "allowed_values", "1"),
    ("integer", "default_value", True),
    ("integer", "default_value", False),
    ("integer", "default_value", 1.0),
    ("integer", "default_value", "1"),
])
def test_wrong_typed_values_rejected(value_type, field, value):
    data = generic_data()
    data["columns"][0].update(value_type=value_type)
    data["columns"][0][field] = value
    with pytest.raises(ValueError, match=field):
        parse_profile(json.dumps(data))


def test_integer_default_must_be_allowed():
    data = generic_data()
    data["columns"][0].update(value_type="integer", allowed_values=[1, 2], default_value=3)
    with pytest.raises(ValueError, match="not in allowed_values"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("value_type", ["float", "STRING", "", None, True, 1, [], {}])
def test_unknown_or_nonstring_value_type_rejected(value_type):
    data = generic_data()
    data["columns"][0]["value_type"] = value_type
    with pytest.raises(ValueError, match="value_type"):
        parse_profile(json.dumps(data))


def test_missing_value_type_rejected():
    data = generic_data()
    del data["columns"][0]["value_type"]
    with pytest.raises(ValueError, match="missing fields: value_type"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("profile_id", FASTQ_PROFILE_IDS)
def test_bundled_input_kind_and_single_end_support(profile_id):
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        profile_id + ".json"
    ).read_text())
    assert data["input_kind"] == "fastq_samplesheet"
    assert data["single_end_supported"] is True
    profile = load_profile(profile_id)
    assert profile.input_kind == "fastq_samplesheet"
    assert profile.single_end_supported is True
    with pytest.raises(FrozenInstanceError):
        profile.input_kind = "barcode_mapping"


def test_barcode_mapping_accepts_null_single_end_support():
    data = generic_data()
    data.update(input_kind="barcode_mapping", single_end_supported=None)
    data["columns"] = [
        {"name": "sample", "source_role": "sample", "required_column": True, "required_value": True, "value_type": "string"},
        {"name": "barcode", "source_role": None, "required_column": True, "required_value": True, "value_type": "integer"},
    ]
    profile = parse_profile(json.dumps(data))
    assert profile.input_kind == "barcode_mapping"
    assert profile.single_end_supported is None
    assert [column.name for column in profile.columns] == ["sample", "barcode"]


@pytest.mark.parametrize("value", [True, False, 0, 1, "true", "null", [], {}])
def test_barcode_mapping_rejects_nonnull_single_end_support(value):
    data = generic_data()
    data.update(input_kind="barcode_mapping", single_end_supported=value)
    with pytest.raises(ValueError, match="single_end_supported must be null"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_fastq_samplesheet_rejects_nonboolean_single_end_support(value):
    data = generic_data()
    data["single_end_supported"] = value
    with pytest.raises(ValueError, match="single_end_supported must be a boolean"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("value", [True, False])
def test_fastq_samplesheet_accepts_both_boolean_values(value):
    data = generic_data()
    data["single_end_supported"] = value
    profile = parse_profile(json.dumps(data))
    assert profile.single_end_supported is value


@pytest.mark.parametrize("value", ["unknown", "FASTQ_SAMPLESHEET", "", None, True, 1, [], {}])
def test_unknown_or_nonstring_input_kind_rejected(value):
    data = generic_data()
    data["input_kind"] = value
    with pytest.raises(ValueError, match="input_kind"):
        parse_profile(json.dumps(data))


def test_missing_input_kind_rejected():
    data = generic_data()
    del data["input_kind"]
    with pytest.raises(ValueError, match="missing fields: input_kind"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("profile_id, roles", [
    ("generic", ("sample", "r1", "r2")),
    ("nfcore-rnaseq-3.27.0", ("sample", "r1", "r2", None)),
    ("nfcore-methylseq-4.2.0", ("sample", "r1", "r2", None)),
    ("nfcore-smrnaseq-2.4.1", ("sample", "r1", "r2")),
    ("nfcore-viralrecon-3.0.0-illumina", ("sample", "r1", "r2")),
    ("nfcore-viralrecon-3.0.0-nanopore", ("sample", None)),
])
def test_bundled_source_roles_exact(profile_id, roles):
    profile = load_profile(profile_id)
    assert tuple(column.source_role for column in profile.columns) == roles
    text = files("fastq_sheet_audit.profile_data").joinpath(profile_id + ".json").read_text()
    data = json.loads(text)
    assert tuple(column["source_role"] for column in data["columns"]) == roles
    assert parse_profile(text) == load_profile(profile_id) == profile
    with pytest.raises(FrozenInstanceError):
        profile.columns[0].source_role = "r1"


def test_missing_source_role_rejected():
    data = generic_data()
    del data["columns"][0]["source_role"]
    with pytest.raises(ValueError, match="missing fields: source_role"):
        parse_profile(json.dumps(data))


@pytest.mark.parametrize("role", ["R1", "Sample", " r1", "r1 ", "fastq_1", "", True, 1, [], {}])
def test_invalid_source_role_rejected(role):
    data = generic_data()
    data["columns"][0]["source_role"] = role
    with pytest.raises(ValueError, match="source_role"):
        parse_profile(json.dumps(data))


def test_duplicate_source_role_rejected_for_distinct_column_names():
    data = generic_data()
    data["columns"][1]["source_role"] = "sample"
    with pytest.raises(ValueError, match="duplicate source_role: sample"):
        parse_profile(json.dumps(data))


def test_multiple_null_roles_allowed_without_name_inference():
    data = generic_data()
    for column in data["columns"]:
        column["source_role"] = None
    profile = parse_profile(json.dumps(data))
    assert all(column.source_role is None for column in profile.columns)
    assert [column.name for column in profile.columns] == ["sample", "r1", "r2"]


def test_roles_are_declarative_and_not_required_globally():
    data = generic_data()
    data["columns"] = [{"name": "custom_path", "source_role": "r2", "value_type": "string",
                        "required_column": True, "required_value": False}]
    profile = parse_profile(json.dumps(data))
    assert profile.columns[0].source_role == "r2"
    assert profile.columns[0].name == "custom_path"


def test_load_nfcore_viralrecon_nanopore_metadata():
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    assert profile.profile_id == "nfcore-viralrecon-3.0.0-nanopore"
    assert profile.display_name == "nf-core/viralrecon 3.0.0 — Nanopore"
    assert profile.pipeline == "nf-core/viralrecon"
    assert profile.verified_version == "3.0.0"
    assert profile.verified_date == "2026-10-03"
    assert profile.source_reference == (
        "Official nf-core/viralrecon 3.0.0 usage documentation: "
        "https://nf-co.re/viralrecon/3.0.0/docs/usage/; official tagged input schema: "
        "https://github.com/nf-core/viralrecon/blob/3.0.0/assets/schema_input.json"
    )
    assert profile.input_kind == "barcode_mapping"
    assert profile.single_end_supported is None


def test_nfcore_viralrecon_nanopore_column_contract():
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    assert [column.name for column in profile.columns] == ["sample", "barcode"]
    assert [column.value_type for column in profile.columns] == ["string", "integer"]
    assert all(column.required_column and column.required_value for column in profile.columns)
    assert all(column.default_value is None for column in profile.columns)
    assert all(column.allowed_values is None for column in profile.columns)
    assert not {"fastq_1", "fastq_2"}.intersection(column.name for column in profile.columns)
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-viralrecon-3.0.0-nanopore.json"
    ).read_text())
    assert all("default_value" not in column and "allowed_values" not in column
               for column in data["columns"])


def test_nfcore_viralrecon_nanopore_notes():
    profile = load_profile("nfcore-viralrecon-3.0.0-nanopore")
    assert profile.notes == (
        "Nanopore-only barcode mapping sheet, not a FASTQ samplesheet. Nanopore FASTQs are "
        "supplied separately through viralrecon's Nanopore FASTQ directory layout. "
        "Barcode must be an integer. Viralrecon documentation says dashes and spaces in "
        "sample names are converted to underscores downstream; fastq-sheet-audit itself "
        "does not silently rename or normalize sample IDs. No biological metadata is inferred or defaulted."
    )


def test_viralrecon_illumina_profile_remains_unchanged():
    expected = {
        "profile_id": "nfcore-viralrecon-3.0.0-illumina",
        "display_name": "nf-core/viralrecon 3.0.0 — Illumina",
        "pipeline": "nf-core/viralrecon",
        "verified_version": "3.0.0",
        "verified_date": "2026-10-03",
        "source_reference": (
            "Official nf-core/viralrecon 3.0.0 usage documentation: "
            "https://nf-co.re/viralrecon/3.0.0/docs/usage/; official tagged input schema: "
            "https://github.com/nf-core/viralrecon/blob/3.0.0/assets/schema_input.json"
        ),
        "columns": [
            {"name": "sample", "source_role": "sample", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_1", "source_role": "r1", "value_type": "string", "required_column": True, "required_value": True},
            {"name": "fastq_2", "source_role": "r2", "value_type": "string", "required_column": True, "required_value": False},
        ],
        "input_kind": "fastq_samplesheet",
        "single_end_supported": True,
        "notes": (
            "Illumina-only samplesheet profile; no Nanopore compatibility is claimed. "
            "The fastq_2 column is required but its values may be empty for single-end Illumina data. "
            "Viralrecon documentation says dashes and spaces in sample names are converted to "
            "underscores downstream; fastq-sheet-audit itself does not silently rename or normalize "
            "sample IDs. No biological metadata is inferred or defaulted."
        ),
    }
    data = json.loads(files("fastq_sheet_audit.profile_data").joinpath(
        "nfcore-viralrecon-3.0.0-illumina.json"
    ).read_text())
    assert data == expected
    assert load_profile("nfcore-viralrecon-3.0.0-illumina") == parse_profile(json.dumps(expected))
