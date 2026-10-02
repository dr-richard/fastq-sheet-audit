from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

FASTQ_SUFFIXES = (".fastq", ".fastq.gz", ".fq", ".fq.gz")

# Conservative support for common Illumina/generic paired-read names.
FASTQ_NAME_RE = re.compile(
    r"^(?P<sample>.+?)"
    r"(?P<index>_S\d+)?"
    r"(?P<lane>_L\d{3})?"
    r"_(?P<read>R?[12])"
    r"(?P<chunk>_\d{3})?"
    r"(?P<suffix>\.(?:fastq|fq)(?:\.gz)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Record:
    row: int
    sample: str
    r1: str
    r2: str | None


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    sample: str = ""
    path: str = ""


@dataclass
class AuditResult:
    sheet: str
    fastq_dir: str
    records: int
    fastq_files: int
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_json_obj(self) -> dict:
        return {
            "sheet": self.sheet,
            "fastq_dir": self.fastq_dir,
            "records": self.records,
            "fastq_files": self.fastq_files,
            "ok": self.ok,
            "findings": [asdict(f) for f in self.findings],
        }


def is_fastq(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(s) for s in FASTQ_SUFFIXES)


def parse_fastq_name(path: Path) -> tuple[str, int] | None:
    m = FASTQ_NAME_RE.match(path.name)
    if not m:
        return None
    read = m.group("read").upper().removeprefix("R")
    return m.group("sample"), int(read)


def _delimiter(path: Path, text: str) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    if path.suffix.lower() == ".csv":
        return ","
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",\t").delimiter
    except csv.Error:
        return "\t"


def read_sheet(path: Path) -> list[Record]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(
        io.StringIO(text, newline=""), delimiter=_delimiter(path, text), strict=True
    )
    if reader.fieldnames is None:
        raise ValueError("sample sheet has no header")

    normalized = [f.strip() for f in reader.fieldnames]
    if len(normalized) != len(set(normalized)):
        raise ValueError("sample sheet has duplicate headers after trimming whitespace")
    fields = {f.strip(): f for f in reader.fieldnames}
    missing = [name for name in ("sample", "r1") if name not in fields]
    if missing:
        raise ValueError("sample sheet missing required column(s): " + ", ".join(missing))

    records: list[Record] = []
    for row_number, raw in enumerate(reader, start=2):
        if None in raw:
            raise ValueError(f"row {row_number}: more fields than the header")
        sample = (raw.get(fields["sample"]) or "").strip()
        r1 = (raw.get(fields["r1"]) or "").strip()
        r2 = (raw.get(fields.get("r2", "")) or "").strip() if "r2" in fields else ""
        if not sample and not r1 and not r2:
            continue
        if not sample:
            raise ValueError(f"row {row_number}: empty sample")
        if not r1:
            raise ValueError(f"row {row_number}: empty r1")
        records.append(Record(row_number, sample, r1, r2 or None))
    return records


def resolve_fastq(value: str, fastq_dir: Path) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else fastq_dir / p


def scan_fastqs(fastq_dir: Path) -> set[Path]:
    return {p.resolve() for p in fastq_dir.rglob("*") if p.is_file() and is_fastq(p)}


def _norm_id(value: str) -> str:
    return value.casefold()


def _pair_key(path: Path) -> str | None:
    match = FASTQ_NAME_RE.fullmatch(path.name)
    if match is None:
        return None
    start, end = match.span("read")
    # Preserve every naming component, including the read-token style.
    return (path.name[:start] + match.group("read")[:-1] + "?" + path.name[end:]).casefold()


def _expected_mate(path: Path) -> Path | None:
    match = FASTQ_NAME_RE.fullmatch(path.name)
    if match is None:
        return None
    start, end = match.span("read")
    role = match.group("read")
    mate_role = role[:-1] + ("2" if role[-1] == "1" else "1")
    return path.with_name(path.name[:start] + mate_role + path.name[end:])


def _same_path(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    return left.exists() and right.exists() and left.samefile(right)


def validate_report_paths(sheet: Path, fastq_dir: Path, outputs: Iterable[Path]) -> list[Path]:
    """Validate all destinations before creating any report temporary files."""
    protected = {sheet.resolve()} | scan_fastqs(fastq_dir)
    for record in read_sheet(sheet):
        protected.add(resolve_fastq(record.r1, fastq_dir).resolve())
        if record.r2:
            protected.add(resolve_fastq(record.r2, fastq_dir).resolve())

    checked: list[Path] = []
    for output in outputs:
        if any(_same_path(output, source) for source in protected):
            raise ValueError(f"report destination overlaps an input: {output}")
        if any(_same_path(output, previous) for previous in checked):
            raise ValueError(f"report destinations overlap: {output}")
        destination = output.resolve()
        if not destination.parent.is_dir():
            raise ValueError(f"report parent directory does not exist: {output.parent}")
        if destination.exists() and not destination.is_file():
            raise ValueError(f"report destination is not a regular file: {output}")
        checked.append(destination)
    return checked


def _add(findings: list[Finding], severity: str, code: str, message: str, *, sample: str = "", path: Path | str = "") -> None:
    findings.append(Finding(severity, code, message, sample, str(path)))


def audit(sheet: Path, fastq_dir: Path) -> AuditResult:
    if not sheet.is_file():
        raise ValueError(f"sample sheet not found: {sheet}")
    if not fastq_dir.is_dir():
        raise ValueError(f"FASTQ directory not found: {fastq_dir}")

    records = read_sheet(sheet)
    disk_fastqs = scan_fastqs(fastq_dir)
    findings: list[Finding] = []

    seen_samples: dict[str, int] = {}
    assigned: dict[Path, tuple[str, str]] = {}
    referenced: set[Path] = set()
    explained_unlisted: set[Path] = set()

    for rec in records:
        key = rec.sample.casefold()
        if key in seen_samples:
            _add(
                findings,
                "ERROR",
                "DUPLICATE_SAMPLE",
                f"sample ID is repeated (rows {seen_samples[key]} and {rec.row})",
                sample=rec.sample,
            )
        else:
            seen_samples[key] = rec.row

        pair: list[tuple[str, Path]] = [("R1", resolve_fastq(rec.r1, fastq_dir))]
        if rec.r2:
            pair.append(("R2", resolve_fastq(rec.r2, fastq_dir)))

        parsed: dict[str, tuple[str, int] | None] = {}
        for role, p in pair:
            rp = p.resolve()
            referenced.add(rp)
            if not p.is_file():
                _add(findings, "ERROR", "MISSING_FILE", f"{role} file does not exist", sample=rec.sample, path=p)
                continue
            if not is_fastq(p):
                _add(findings, "ERROR", "NOT_FASTQ", f"{role} path does not look like FASTQ", sample=rec.sample, path=p)
            previous = assigned.get(rp)
            if previous:
                _add(
                    findings,
                    "ERROR",
                    "FASTQ_REUSED",
                    f"file already assigned to sample {previous[0]} as {previous[1]}",
                    sample=rec.sample,
                    path=p,
                )
            else:
                assigned[rp] = (rec.sample, role)
            parsed[role] = parse_fastq_name(p)

            parsed_name = parsed[role]
            if parsed_name:
                inferred_sample, inferred_read = parsed_name
                expected_read = 1 if role == "R1" else 2
                if inferred_read != expected_read:
                    _add(
                        findings,
                        "ERROR",
                        "READ_ROLE_MISMATCH",
                        f"sheet assigns this file as {role}, filename looks like R{inferred_read}",
                        sample=rec.sample,
                        path=p,
                    )
                if _norm_id(inferred_sample) != _norm_id(rec.sample):
                    _add(
                        findings,
                        "WARNING",
                        "SAMPLE_NAME_MISMATCH",
                        f"filename suggests sample '{inferred_sample}', sheet says '{rec.sample}'",
                        sample=rec.sample,
                        path=p,
                    )

        if rec.r2 and parsed.get("R1") and parsed.get("R2"):
            r1_path = resolve_fastq(rec.r1, fastq_dir)
            r2_path = resolve_fastq(rec.r2, fastq_dir)
            if _pair_key(r1_path) != _pair_key(r2_path):
                _add(
                    findings,
                    "ERROR",
                    "PAIR_NAME_MISMATCH",
                    "R1/R2 filenames disagree beyond the read-role digit",
                    sample=rec.sample,
                )

        # If sheet claims single-end but a clear mate exists beside R1, flag it.
        if not rec.r2:
            r1_path = resolve_fastq(rec.r1, fastq_dir)
            parsed_r1 = parse_fastq_name(r1_path)
            if parsed_r1 and parsed_r1[1] == 1:
                mate = _expected_mate(r1_path)
                if mate is not None and mate.is_file():
                    explained_unlisted.add(mate.resolve())
                    _add(
                        findings,
                        "WARNING",
                        "UNLISTED_MATE",
                        "sheet has no r2, but a matching R2 file exists on disk",
                        sample=rec.sample,
                        path=mate,
                    )

    for extra in sorted(disk_fastqs - referenced - explained_unlisted):
        _add(findings, "WARNING", "UNLISTED_FASTQ", "FASTQ exists on disk but is absent from the sample sheet", path=extra)

    findings.sort(key=lambda f: (0 if f.severity == "ERROR" else 1, f.code, f.sample, f.path))
    return AuditResult(str(sheet), str(fastq_dir), len(records), len(disk_fastqs), findings)


def write_json(result: AuditResult, path: Path) -> None:
    path.write_text(json.dumps(result.to_json_obj(), indent=2) + "\n", encoding="utf-8")


def write_tsv(findings: Iterable[Finding], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(["severity", "code", "sample", "path", "message"])
        for f in findings:
            writer.writerow([f.severity, f.code, f.sample, f.path, f.message])
