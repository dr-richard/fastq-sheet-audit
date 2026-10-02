"""Parse FASTQ filename structure without inferring biological meaning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ReadRole(Enum):
    R1 = "R1"
    R2 = "R2"
    I1 = "I1"
    I2 = "I2"


@dataclass(frozen=True)
class ParsedFastqName:
    sample: str
    sample_number: int | None
    lane: int | None
    read_role: ReadRole
    chunk: int | None
    suffix: str
    read_style: str


_FASTQ_NAME_RE = re.compile(
    r"(?P<sample>[^/\\\r\n]+?)"
    r"(?:_S(?P<sample_number>[0-9]+))?"
    r"(?:_L(?P<lane>[0-9]{3}))?"
    r"_(?P<read>[RI]?[12])"
    r"(?:_(?P<chunk>[0-9]{3}))?"
    r"(?P<suffix>\.(?:fastq|fq)(?:\.gz)?)",
    re.IGNORECASE,
)


def parse_fastq_name(name: str) -> ParsedFastqName | None:
    """Parse a filename, returning None for unsupported structure or suffix.

    Sample punctuation and suffix spelling are preserved. Numeric components
    become integers; absent components remain None. Read styles are "R", "I",
    and "bare" (for 1/2 tokens), independent of the token's letter case.
    """
    match = _FASTQ_NAME_RE.fullmatch(name)
    if match is None:
        return None

    read = match.group("read").upper()
    read_style = read[0] if read[0] in "RI" else "bare"
    read_role = ReadRole(read if read_style != "bare" else "R" + read)

    def number(component: str) -> int | None:
        value = match.group(component)
        return int(value) if value is not None else None

    return ParsedFastqName(
        sample=match.group("sample"),
        sample_number=number("sample_number"),
        lane=number("lane"),
        read_role=read_role,
        chunk=number("chunk"),
        suffix=match.group("suffix"),
        read_style=read_style,
    )
