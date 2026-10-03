"""Local/offline v0.2 sample-sheet and FASTQ preflight command-line front end."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from . import __version__
from .column_mapping import ColumnRole, map_columns
from .inventory import scan_fastqs
from .presentation import present_workflow
from .read_mode import ReadMode
from .report_io import write_workflow_report_json
from .reporting import build_workflow_report
from .sheet import load_sheet
from .workflow import build_workflow_snapshot


def _positive_column_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("column number must be a positive 1-based integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("column number must be a positive 1-based integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fastq-sheet-audit", description="Local/offline FASTQ ↔ sample-sheet preflight and audit.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="audit sample-sheet references and discovered FASTQ filenames")
    check.add_argument("sheet", type=Path, help="CSV/TSV sample sheet with unambiguous SAMPLE and R1 columns")
    check.add_argument("--fastq-dir", type=Path, required=True, help="FASTQ scan root directory")
    check.add_argument("--read-mode", choices=tuple(mode.value for mode in ReadMode), default="auto")
    check.add_argument("--sample-column", type=_positive_column_number, metavar="N",
                       help="explicit SAMPLE column number (1-based)")
    check.add_argument("--r1-column", type=_positive_column_number, metavar="N",
                       help="explicit R1 column number (1-based)")
    r2 = check.add_mutually_exclusive_group()
    r2.add_argument("--r2-column", type=_positive_column_number, metavar="N",
                    help="explicit R2 column number (1-based)")
    r2.add_argument("--no-r2-column", action="store_true", help="explicitly leave R2 unmapped")
    check.add_argument("--json", dest="json_path", type=Path, help="publish a structured v0.2 JSON report")
    check.add_argument("--overwrite-report", action="store_true",
                       help="allow replacing an ordinary JSON report file; input paths remain protected")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.sheet.is_file():
            raise ValueError(f"Sample sheet does not exist or is not a regular file: {args.sheet}")
        if not args.fastq_dir.is_dir():
            raise ValueError(f"FASTQ root does not exist or is not a directory: {args.fastq_dir}")
        sheet = load_sheet(args.sheet)
        overrides = {}
        for role, number in ((ColumnRole.SAMPLE, args.sample_column),
                             (ColumnRole.R1, args.r1_column), (ColumnRole.R2, args.r2_column)):
            if number is not None:
                overrides[role] = number - 1
        if args.no_r2_column:
            overrides[ColumnRole.R2] = None
        mapping = map_columns(sheet, overrides if overrides else None)
        if mapping.ambiguous:
            roles = ", ".join(item.role.name for item in mapping.ambiguous)
            candidates = "; ".join(
                f"{item.role.name} candidates: " + ", ".join(
                    f"{column.index + 1}:{column.header!r}" for column in item.candidates)
                for item in mapping.ambiguous)
            raise ValueError(f"Ambiguous column mapping: {roles}. Explicit mapping is required. {candidates}")
        if not mapping.complete:
            missing = ", ".join(role.name for role in (ColumnRole.SAMPLE, ColumnRole.R1)
                                if mapping.for_role(role).selected is None)
            columns = ", ".join(f"{index + 1}:{header!r}" for index, header in enumerate(sheet.headers))
            raise ValueError(f"Column mapping requires SAMPLE and R1 mappings. Missing required roles: {missing}. "
                             f"Available columns: {columns}")
        fastq_root = args.fastq_dir.absolute()
        inventory = scan_fastqs(fastq_root)
        snapshot = build_workflow_snapshot(sheet, mapping, inventory, fastq_root,
                                           read_mode=ReadMode(args.read_mode))
        view = present_workflow(snapshot)
        if args.json_path is not None:
            report = build_workflow_report(snapshot)
            protected_paths = (
                args.sheet,
                *(record.path for record in snapshot.inventory),
                *(assignment.path for assignment in snapshot.reconciliation.assignments),
            )
            write_workflow_report_json(report, args.json_path, protected_paths=protected_paths,
                                        overwrite=args.overwrite_report)
    except (OSError, ValueError, csv.Error) as error:
        message = " ".join(str(error).splitlines())
        print(f"fastq-sheet-audit: error: {message}", file=sys.stderr)
        return 2

    summary = view.summary
    print(f"Inventory: {summary.inventory_count} | Errors: {summary.error_count} | "
          f"Warnings: {summary.warning_count} | Unresolved pairs: {summary.unresolved_pair_count} | "
          f"Read layout: {snapshot.read_mode.layout.value} | "
          f"Ready for export: {'yes' if summary.ready_for_export else 'no'}")
    for finding in view.findings:
        location = ""
        if finding.row_number is not None:
            location += f" row={finding.row_number}"
        if finding.sample is not None:
            location += f" sample={finding.sample!r}"
        if finding.path is not None:
            location += f" path={finding.path!r}"
        print(f"{finding.severity} {finding.source} {finding.code}:{location} — {finding.message}")
    return 1 if snapshot.has_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
