# Security

fastq-sheet-audit runs locally/offline. Audits and exports require no network,
telemetry, cloud/API service, or AI/LLM dependency. Installing the software and
its development dependencies may require network access.

FASTQ contents are never opened or read. Input FASTQs and sample sheets are
never renamed, moved, deleted, repaired, or modified. The tool reads sample-sheet
text and filesystem metadata to audit filename/path evidence.

Explicit user-selected output files can be created. Publication protects the
input sheet, discovered FASTQs, and referenced FASTQ paths, including missing
references and resolvable aliases. CLI report overwrite is opt-in; GUI exports
currently refuse existing destinations. Overwrite never disables input protection.

Publication uses same-directory temporary files, flush/fsync, and atomic replace,
with exclusive destination reservation for no-overwrite mode. Python's portable
APIs cannot guarantee atomic conditional replacement or protection against
hostile concurrent filesystem mutation; a reservation can briefly be visible
and paths can change between checks. Coordinate concurrent writers externally.

Please report security issues privately through GitHub private vulnerability
reporting when available, rather than posting sensitive data in a public issue.
