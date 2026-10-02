from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path

from . import __version__
from .core import AuditResult, audit, validate_report_paths, write_json, write_tsv


def _write_reports(result: AuditResult, sheet: Path, fastq_dir: Path,
                   json_path: Path | None, tsv_path: Path | None) -> None:
    reports = []
    if json_path is not None:
        reports.append((json_path, write_json, result))
    if tsv_path is not None:
        reports.append((tsv_path, write_tsv, result.findings))
    if not reports:
        return
    destinations = validate_report_paths(sheet, fastq_dir, [r[0] for r in reports])
    staged: list[tuple[Path, Path]] = []
    try:
        for destination, (_, writer, payload) in zip(destinations, reports):
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".fastq-sheet-audit-", delete=False
            ) as temporary:
                temp_path = Path(temporary.name)
            staged.append((temp_path, destination))
            writer(payload, temp_path)
        # Both serializations have succeeded before either destination changes.
        for temp_path, destination in staged:
            temp_path.replace(destination)
    finally:
        for temp_path, _ in staged:
            temp_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fastq-sheet-audit", description="Reconcile a sample sheet with FASTQ files on disk.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="run read-only reconciliation checks")
    check.add_argument("sheet", type=Path, help="CSV/TSV with columns sample,r1[,r2]")
    check.add_argument("--fastq-dir", type=Path, required=True, help="root directory containing FASTQ files")
    check.add_argument("--json", dest="json_path", type=Path, help="write machine-readable JSON report")
    check.add_argument("--tsv", dest="tsv_path", type=Path, help="write findings as TSV")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = audit(args.sheet, args.fastq_dir)
        _write_reports(result, args.sheet, args.fastq_dir, args.json_path, args.tsv_path)
    except (OSError, ValueError, csv.Error, RuntimeError) as exc:
        print(f"fastq-sheet-audit: error: {exc}", file=sys.stderr)
        return 2

    errors = sum(f.severity == "ERROR" for f in result.findings)
    warnings = sum(f.severity == "WARNING" for f in result.findings)
    print(f"Samples: {result.records} | FASTQs on disk: {result.fastq_files} | Errors: {errors} | Warnings: {warnings}")
    for f in result.findings:
        location = ""
        if f.sample:
            location += f" sample={f.sample}"
        if f.path:
            location += f" path={f.path}"
        print(f"{f.severity} {f.code}:{location} — {f.message}")

    if not result.findings:
        print("OK: sample sheet and FASTQ directory are coherent.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
