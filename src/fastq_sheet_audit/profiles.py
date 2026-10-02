"""Strict, offline loading of declarative JSON export profiles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from typing import Literal


@dataclass(frozen=True)
class ProfileColumn:
    name: str
    required_column: bool
    required_value: bool
    value_type: Literal["string", "integer"]
    allowed_values: tuple[str, ...] | tuple[int, ...] | None = None
    default_value: str | int | None = None


@dataclass(frozen=True)
class Profile:
    profile_id: str
    display_name: str
    pipeline: str | None
    verified_version: str | None
    verified_date: str | None
    source_reference: str
    columns: tuple[ProfileColumn, ...]
    input_kind: Literal["fastq_samplesheet", "barcode_mapping"]
    single_end_supported: bool | None
    notes: str


_PROFILE_FIELDS = {
    "profile_id", "display_name", "pipeline", "verified_version", "verified_date",
    "source_reference", "columns", "input_kind", "single_end_supported", "notes",
}
_COLUMN_REQUIRED = {"name", "required_column", "required_value", "value_type"}
_COLUMN_FIELDS = _COLUMN_REQUIRED | {"allowed_values", "default_value"}
_PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9_-]+)*")


def _fields(value: object, required: set[str], allowed: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing:
        raise ValueError(f"{label} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{label} unknown fields: {', '.join(sorted(unknown))}")


def _string(value: object, label: str, *, nullable: bool = False, empty: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{label} must be {'a string or null' if nullable else 'a string'}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_profile(text: str) -> Profile:
    """Validate profile JSON without executing or interpreting embedded code.

    All profile metadata keys must exist; pipeline/version/date may be null
    when compatibility is not claimed. Column names and values remain exact.
    Optional allowed_values/default_value fields default to None.
    """
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as error:
        raise ValueError("malformed profile JSON") from error
    _fields(data, _PROFILE_FIELDS, _PROFILE_FIELDS, "profile")
    for name in ("profile_id", "display_name", "source_reference"):
        _string(data[name], name)
    if _PROFILE_ID.fullmatch(data["profile_id"]) is None:
        raise ValueError("invalid profile_id")
    for name in ("pipeline", "verified_version", "verified_date"):
        _string(data[name], name, nullable=True)
    if data["verified_date"] is not None:
        try:
            parsed_date = date.fromisoformat(data["verified_date"])
        except ValueError as error:
            raise ValueError("verified_date must be YYYY-MM-DD or null") from error
        if parsed_date.isoformat() != data["verified_date"]:
            raise ValueError("verified_date must be YYYY-MM-DD or null")
    _string(data["notes"], "notes", empty=True)
    input_kind = data["input_kind"]
    if not isinstance(input_kind, str) or input_kind not in ("fastq_samplesheet", "barcode_mapping"):
        raise ValueError("input_kind must be 'fastq_samplesheet' or 'barcode_mapping'")
    if input_kind == "fastq_samplesheet":
        if type(data["single_end_supported"]) is not bool:
            raise ValueError("fastq_samplesheet single_end_supported must be a boolean")
    elif data["single_end_supported"] is not None:
        raise ValueError("barcode_mapping single_end_supported must be null")
    if not isinstance(data["columns"], list) or not data["columns"]:
        raise ValueError("columns must be a nonempty array")

    columns: list[ProfileColumn] = []
    names: set[str] = set()
    for column in data["columns"]:
        _fields(column, _COLUMN_REQUIRED, _COLUMN_FIELDS, "column")
        _string(column["name"], "column name")
        if column["name"] in names:
            raise ValueError(f"duplicate column name: {column['name']}")
        names.add(column["name"])
        for flag in ("required_column", "required_value"):
            if type(column[flag]) is not bool:
                raise ValueError(f"{column['name']}: {flag} must be a boolean")
        value_type = column["value_type"]
        if not isinstance(value_type, str) or value_type not in ("string", "integer"):
            raise ValueError(f"{column['name']}: value_type must be 'string' or 'integer'")
        expected_type = str if value_type == "string" else int
        allowed = column.get("allowed_values")
        if allowed is not None and (
            not isinstance(allowed, list) or any(type(value) is not expected_type for value in allowed)
        ):
            raise ValueError(f"{column['name']}: allowed_values must be a {value_type} array or null")
        default = column.get("default_value")
        if default is not None and type(default) is not expected_type:
            raise ValueError(f"{column['name']}: default_value must be {value_type} or null")
        if allowed is not None and default is not None and default not in allowed:
            raise ValueError(f"{column['name']}: default_value is not in allowed_values")
        columns.append(ProfileColumn(
            column["name"], column["required_column"], column["required_value"],
            value_type,
            tuple(allowed) if allowed is not None else None, default,
        ))
    return Profile(
        data["profile_id"], data["display_name"], data["pipeline"],
        data["verified_version"], data["verified_date"], data["source_reference"],
        tuple(columns), input_kind, data["single_end_supported"], data["notes"],
    )


def list_profile_ids() -> tuple[str, ...]:
    """List bundled JSON profile IDs in lexical order, entirely offline."""
    return tuple(sorted(
        resource.name[:-5] for resource in files("fastq_sheet_audit.profile_data").iterdir()
        if resource.is_file() and resource.name.endswith(".json")
        and _PROFILE_ID.fullmatch(resource.name[:-5]) is not None
    ))


def load_profile(profile_id: str) -> Profile:
    """Load only a bundled profile ID; never treat an ID as a filesystem path."""
    if not isinstance(profile_id, str) or profile_id not in list_profile_ids():
        raise ValueError(f"unknown profile ID: {profile_id!r}")
    resource = files("fastq_sheet_audit.profile_data").joinpath(profile_id + ".json")
    try:
        text = resource.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("profile must be UTF-8 JSON") from error
    profile = parse_profile(text)
    if profile.profile_id != profile_id:
        raise ValueError("profile_id does not match bundled resource name")
    return profile
