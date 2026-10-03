# Changelog

## 0.2.0

- Redesigned the deterministic domain pipeline around immutable workflow evidence.
- Added lossless CSV/TSV sample-sheet import and deterministic alias/explicit column mapping.
- Added recursive FASTQ inventory, structural filename parsing, and exact pairing identities,
  including platform-independent, case-sensitive relative directory spelling.
- Added explicit Auto/Paired/Single read modes and path case-collision diagnostics.
- Added human pairing selection, unassignment, reset, and confirmation with evidence-preserving revalidation.
- Added declarative bundled export profiles, exact manual metadata validation, and local/relative/rebased path rendering.
- Added a native tkinter/ttk GUI for auditing, adjudication, export previews, and explicit CSV/TSV publication.
- Added immutable machine reports and deterministic, schema-versioned JSON serialization.
- Added protected atomic UTF-8 publication with conservative overwrite behavior and documented race limitations.
- Replaced the CLI with the v0.2 pipeline, explicit 1-based column mapping, read modes, and JSON report publication.
- Added Windows/macOS CI, distribution-build validation, and installed entry-point/profile-resource checks.
- Retired the obsolete v0.1 engine and its tests; the prototype remains preserved in Git history/tag `v0.1.0`.

## 0.1.0

- Initial read-only sample-sheet / FASTQ reconciliation checks.
