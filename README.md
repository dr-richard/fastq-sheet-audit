# fastq-sheet-audit

<p align="center">
  <img src="src/fastq_sheet_audit/assets/app_icon.png"
       alt="fastq-sheet-audit icon"
       width="128">
</p>

A local, offline FASTQ ↔ sample-sheet preflight tool with a command-line audit,
a native desktop GUI, and explicit, validated sample-sheet export.

This README describes **fastq-sheet-audit v0.2.0**. The historical v0.1
prototype is preserved in Git under the `v0.1.0` tag.

## Why this exists

A sequencing workflow can fail before analysis begins because a sheet points to
missing files, mixes lanes or chunks, assigns the same FASTQ twice, or leaves
files unaccounted for. fastq-sheet-audit makes those discrepancies visible
before a downstream pipeline runs. It separates discovered evidence, automatic
interpretation, and explicit human decisions.

## Capabilities and design

- Lossless CSV/TSV import, deterministic column mapping, and recursive FASTQ inventory.
- Structural filename parsing, exact mate identities, and explicit read-layout checks.
- Findings for missing/reused files, role/sample/pair disagreements, and unlisted files.
- Case-portability diagnostics and GUI pairing adjudication without destroying evidence.
- Declarative export profiles, manual metadata editing, path previews, and CSV/TSV exports.
- Structured JSON audit reports for machine consumers.

The application is fully local/offline: **no telemetry, cloud/API dependency,
or AI/LLM dependency**. It uses filename structure and filesystem metadata;
FASTQ sequence contents are never opened or read. Interpretation is deterministic,
with no fuzzy matching or biological inference from filenames. Ambiguity stays
visible until an explicit decision is made.

FASTQs and input sample sheets are never renamed, moved, deleted, repaired, or
modified. Auditing leaves inputs untouched; explicit report/export actions can
create output files. Publication protects the input sheet, raw discovered FASTQs,
and referenced FASTQ paths, including references outside the scan root and
missing referenced destinations. Resolved aliases and existing symlink/hardlink
aliases are checked too.

Outputs use a temporary file in the destination directory, UTF-8 validation,
flush/fsync, and atomic replacement. Overwrite is conservative: CLI reports
require `--overwrite-report` to replace an ordinary file; GUI exports currently
refuse existing destinations. Protection remains active even with report overwrite.
No-overwrite publication reserves the destination exclusively before replacement.
An empty reservation can briefly be visible. Python's portable APIs do not offer
an atomic conditional replace, so hostile concurrent directory/path changes or
replacement of that reservation cannot be fully guarded against. This is
best-effort race safety, not a guarantee against concurrent filesystem mutation.

## Installation

Python 3.10 or newer is required. Install the released package from
[PyPI](https://pypi.org/project/fastq-sheet-audit/) using one of these methods.

Preferred CLI application installation with pipx:

```bash
pipx install fastq-sheet-audit
```

Standard pip installation:

```bash
python -m pip install fastq-sheet-audit
```

uv tool installation:

```bash
uv tool install fastq-sheet-audit
```

Verify the installation:

```bash
fastq-sheet-audit --version
```

For development or installation from a source checkout:

```bash
python -m pip install .
```

The GUI uses standard-library tkinter/ttk and needs an available Tk installation
and desktop display. Some Python distributions provide Tk separately. CLI use
does not require opening the GUI. Dependency installation may use the network;
audits and exports do not.

## CLI quick start

Input sheets may be UTF-8 CSV or TSV, including a UTF-8 BOM, quoted fields,
LF, and CRLF. Headers, column order, cell text, and physical row numbers are
preserved. Duplicate headers after surrounding-whitespace trimming, surplus
fields, malformed quoting, and missing headers are rejected. Short rows receive
empty trailing cells; only entirely empty rows are skipped.

Example `samples.csv`:

```csv
sample,r1,r2
A,A_S1_L001_R1_001.fastq.gz,A_S1_L001_R2_001.fastq.gz
A,A_S1_L002_R1_001.fastq.gz,A_S1_L002_R2_001.fastq.gz
```

```bash
fastq-sheet-audit check samples.csv --fastq-dir ./fastq
fastq-sheet-audit check samples.csv --fastq-dir ./fastq --read-mode paired --json audit.json
```

Relative FASTQ references resolve against `--fastq-dir`, including subdirectories,
not against the sheet's directory. Absolute references remain absolute. Path
cell text is used without trimming, variable expansion, or rewriting.
Discovery recognizes `.fastq.gz`, `.fq.gz`, `.fastq`, and `.fq`, case-insensitively.
Directory symlinks are not traversed recursively; eligible file symlinks may be
inventoried.

The CLI prints a deterministic summary and ordered findings. Available options:

| Option | Meaning |
| --- | --- |
| `--read-mode {auto,paired,single}` | Requested layout; default `auto` |
| `--sample-column N` | Explicit SAMPLE column, **1-based** |
| `--r1-column N` | Explicit R1 column, **1-based** |
| `--r2-column N` | Explicit R2 column, **1-based** |
| `--no-r2-column` | Explicitly leave R2 unmapped |
| `--json PATH` | Write a structured JSON audit report |
| `--overwrite-report` | Opt in to replacement of an ordinary JSON report file |

## Column mapping

Automatic mapping compares headers using surrounding-whitespace trimming and
Unicode casefold only. The deterministic aliases are:

| Role | Aliases |
| --- | --- |
| SAMPLE | `sample`, `sample_id`, `sampleid` |
| R1 | `r1`, `fastq_1`, `fastq1`, `read1`, `read_1` |
| R2 | `r2`, `fastq_2`, `fastq2`, `read2`, `read_2` |

SAMPLE and R1 are required; R2 is optional. Multiple candidates for any role
are refused unless explicitly resolved, including an ambiguous optional R2.
Errors list physical column numbers and exact headers. Overrides can select
non-alias headers; omitted overrides retain automatic mapping. One physical
column cannot fill multiple roles. R2 selection and unmapping are mutually
exclusive.

For a sheet with `specimen,forward,reverse`:

```bash
fastq-sheet-audit check samples.csv --fastq-dir ./fastq --sample-column 1 --r1-column 2 --r2-column 3
```

The GUI's **Load columns** action offers indexed choices, **Automatic**, and
**Unassigned**. Leaving SAMPLE or R1 unassigned prevents auditing. Unknown
metadata columns survive import; profile exports contain the selected profile's
columns rather than automatically copying arbitrary source metadata.

## Read modes, pairing, and findings

| Mode | Behavior |
| --- | --- |
| `auto` | Complete biological pairs classify as paired; R1-only groups classify as single. Mixed, orphaned, ambiguous, or empty biological evidence is unresolved with a warning. |
| `paired` | Every pairable R1/R2 needs its exact mate. Missing mates and duplicate-role ambiguity are errors. |
| `single` | R1 needs no mate; biological R2 presence is reported explicitly as an error. |

Index reads, Undetermined files, and unparsed names remain visible and are
excluded from biological layout inference. The parser recognizes common forms
such as `A_R1.fastq.gz`, `A_1.fastq`, `A_S1_L001_R1_001.fastq.gz`, and
`A_I1_001.fastq.gz`; it does not claim exhaustive naming support.

Mate identity includes sample, sample number, lane, chunk, read style, suffix,
and relative parent directory. **Only sample and suffix use Unicode casefold.**
Lane/sample-number/chunk differences and R-style versus bare `1/2` remain
significant. Directory identity preserves exact spelling through a
platform-independent representation: `Run/A_R1.fastq` and `run/A_R2.fastq`
are separate identities. Files are never paired by list position or proximity.

Repeated sample IDs are allowed when rows use distinct FASTQ evidence, as in the
two-lane example. Actual file reuse, including filesystem aliases, is an error
(`FASTQ_REUSED`). Sample-versus-filename comparison trims surrounding sheet
sample whitespace and uses Unicode casefold only: `A-B` and `AB` remain distinct.
Original text is retained.

An omitted optional R2 is **not** automatically assigned. If an exact R2 exists
on disk but is absent from the sheet, it remains `UNLISTED_FASTQ` evidence.
Unknown/unparsed filenames are retained, not guessed. Filename role disagreements,
structural pair mismatches, and missing references are reported. Case-only
relative-path collisions are warnings; this is a case-portability check, not a
complete set of Windows filename rules.

## GUI quick start and adjudication

```bash
fastq-sheet-audit-gui
```

Choose a FASTQ directory and sheet, load/resolve columns if needed, select a
read mode, and press **Audit**. Opening the GUI does not scan inputs automatically.
Summary, Findings, FASTQ Inventory, and Pairing / Adjudication tabs expose the
current evidence.

Select a pair row to choose R1/R2 candidates explicitly, leave a role
**Unassigned**, or **Reset automatic**. **Confirmed** records human confirmation;
it does not resolve ambiguity or override errors. Applying a decision revalidates
the workflow. All original candidates remain in the evidence even after a
selection or unassignment. Unresolved automatic choices remain unresolved.

Read-layout checks use effective adjudicated reads, while reconciliation and
case-collision checks retain raw inventory. Decisions cannot suppress unrelated
findings. The tool does not edit the source sheet to repair discrepancies;
correct it externally and rerun Audit when necessary. Changed inputs require a
new audit, and changed export options require a fresh preview.

## Export profiles and manual metadata

GUI export requires a clean workflow, followed by a valid profile preview.
Choose a profile and path mode, set any needed manual fields per source row,
then press **Preview export**. Choose CSV or TSV and a destination explicitly
before pressing **Export**. Format is independent of filename extension.
The CLI audits and publishes JSON reports; it does not export sample sheets.

Export uses exact source sample text and effective adjudicated R1/R2 records,
not the original sheet's FASTQ path cells after adjudication. Profile columns
declare their source roles. Columns with no source role are manual:
no metadata is inferred and no descriptive profile defaults are automatically
inserted. **Set** supplies exact text, including an explicit empty string;
**Clear** makes the value absent. Unapplied editor text must be applied or
cleared before preview/export.

Validation distinguishes a required column from a required cell. String allowed
values are matched exactly without trimming or casefolding. Integer values use
an optional sign and ASCII decimal digits; text such as `01` remains unchanged
in output. Whitespace, Unicode, punctuation, and formula-like text are preserved;
CSV/TSV export is not a spreadsheet-sanitization step.

Bundled profiles are local declarative contracts, not a guarantee that every
pipeline option or future release is supported:

| Profile ID | Contract / manual fields |
| --- | --- |
| `generic` | `sample,r1`; optional `r2`. No pipeline compatibility claim. |
| `nfcore-rnaseq-3.27.0` | `sample,fastq_1,fastq_2,strandedness`. Strandedness requires an explicit exact value: `forward`, `reverse`, `unstranded`, or `auto`; no automatic default. |
| `nfcore-methylseq-4.2.0` | `sample,fastq_1,fastq_2,genome`. Genome is manual and may be empty. |
| `nfcore-smrnaseq-2.4.1` | `sample,fastq_1`; optional `fastq_2`. Profile notes say downstream small-RNA processing primarily uses R1; this tool does not silently discard R2. |
| `nfcore-viralrecon-3.0.0-illumina` | Illumina-only: `sample,fastq_1,fastq_2`. |
| `nfcore-viralrecon-3.0.0-nanopore` | Nanopore-only **barcode mapping**, `sample,barcode`; barcode is a manual integer. Metadata/editor are available, but FASTQ audit sessions cannot preview or publish this profile. Nanopore FASTQs are supplied separately by the pipeline's directory layout. |

All five FASTQ-samplesheet profiles support single-end input. For rnaseq,
methylseq, and viralrecon Illumina, `fastq_2` is a required **column** but may
contain empty cells. Generic and smrnaseq omit their optional R2 column when no
row supplies an effective R2. Methylseq's `genome` column is required but its
value is optional. Viralrecon's downstream sample-name rewriting is not
reproduced here: sample IDs are not silently renamed or normalized.

## Export path modes

| GUI mode | Rendering |
| --- | --- |
| Local absolute | Original local absolute inventory path |
| Relative to FASTQ root | Inventory relative path in local/platform form |
| Rebased root | Relative components joined to an explicit target root |

Rebasing requires an explicit **POSIX** or **Windows** style and an absolute
root in that style. It uses pure path transformations without accessing the
target filesystem. Spaces and Unicode remain intact; unsafe relative components
are rejected rather than resolved away.

## JSON reports and exit codes

```bash
fastq-sheet-audit check samples.csv --fastq-dir ./fastq --json audit.json
fastq-sheet-audit check samples.csv --fastq-dir ./fastq --json audit.json --overwrite-report
```

JSON reports use `schema_version: 1`, independently of the package version.
They preserve structured inventory, reconciliation findings and assignments,
read-mode diagnostics and evidence, case collisions, and pair candidates,
decisions, effective/unresolved records, and confirmation. Pair keys remain
structured, absent values stay null, and Unicode remains literal. Ordering is
deterministic. A report can be written even when the audit has findings;
a publication failure instead returns exit 2.

| CLI exit | Meaning |
| --- | --- |
| `0` | Audit completed with no findings |
| `1` | Audit completed with findings, including warnings or errors |
| `2` | Expected invalid input, filesystem, or report-publication failure; argparse also uses 2 for invalid command usage |

Unexpected programmer errors are not converted into ordinary audit failures.

## Scope and development

This is a filename/path/sample-sheet preflight tool. It does not inspect read
contents, compare read counts, validate checksums, demultiplex, repair FASTQs,
run pipelines, infer biological metadata, or provide clinical validation.
Profile exports cover only the bundled declarative fields. CLI human pairing
adjudication and barcode-workflow export are outside the current scope.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Tests are headless; they do not launch Tk. CI covers Ubuntu Python 3.10–3.14,
representative Python 3.12 jobs on Windows/macOS, and isolated sdist/wheel,
entry-point, and profile-resource validation. See [CHANGELOG.md](CHANGELOG.md)
for the v0.2.0 changes and historical 0.1.0 entry, and
[SECURITY.md](SECURITY.md) for security reporting.
