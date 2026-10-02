# fastq-sheet-audit

Read-only preflight checks that reconcile a sequencing sample sheet with the FASTQ files actually present on disk.

It is designed to catch mundane input mistakes before they become confusing downstream pipeline failures: missing mates, duplicate sample IDs, reused files, filename/sample mismatches, and unlisted FASTQs.

## Install

```bash
python -m pip install .
```

## Usage

Input CSV/TSV columns: `sample`, `r1`, and optional `r2`.

Relative FASTQ paths are resolved against `--fastq-dir`, including any
subdirectories in the path. Absolute paths are used directly. Paths are
not resolved against the sample sheet's directory.

Minimal CSV example (`samples.csv`):

```csv
sample,r1,r2
A,A_S1_L001_R1_001.fastq.gz,A_S1_L001_R2_001.fastq.gz
```

For TSV, use the same columns and values separated by tabs. Header names
are case-sensitive; surrounding header and value whitespace is trimmed.
Duplicate headers after trimming, surplus row fields, and malformed quoted
fields are rejected.

```bash
fastq-sheet-audit check samples.tsv --fastq-dir ./fastq
fastq-sheet-audit check samples.tsv --fastq-dir ./fastq --json report.json --tsv findings.tsv
```

Exit codes:

- `0`: no findings
- `1`: inconsistencies or warnings found
- `2`: invalid input, CLI usage error, or report output failure

## v0.1 checks

- missing FASTQ paths
- duplicate sample IDs
- the same FASTQ assigned more than once
- R1/R2 role disagreement in common FASTQ filenames
- R1 and R2 filenames disagreeing in sample, sample index, lane, or chunk
- obvious sample-ID versus FASTQ filename disagreement
- FASTQs present on disk but absent from the sample sheet
- a clear R2 mate present on disk but omitted from the sheet

Recognized common names include `A_R1.fastq.gz`, `A_1.fastq`, and
`A_S1_L001_R1_001.fastq.gz`. Sample IDs are compared using Unicode case
folding only after sheet whitespace is trimmed. Punctuation is preserved:
`AB` and `A-B` are distinct IDs. No fuzzy matching is performed.

Pair comparisons preserve sample index (`S1`), lane (`L001`), chunk
(`001`), read-token style, and FASTQ suffix, ignoring letter case.
Changing the read-role digit from 1 to 2 is the only expected difference.
Read roles must match the sheet's columns. An omitted R2 mate is inferred
only when changing that digit in R1's filename yields an existing file
beside R1; unrelated lanes or chunks are not selected.

## Safety and privacy

`fastq-sheet-audit` is offline and read-only. It does not open FASTQ contents, rename files, move files, repair reads, or upload data.

Optional reports may replace existing report files. All destinations are
validated before any report is written. Destinations overlapping the
sample sheet, referenced FASTQs (including missing paths), discovered
FASTQs, or each other are rejected, including resolved path aliases,
symlinks, and existing hard links. Invalid destinations leave inputs and
reports unchanged.

Reports are serialized to temporary files in their destination directories.
Only after every requested report has serialized successfully is each
destination atomically replaced. Temporary files are cleaned up on failure,
and report-writing failures return exit code 2. The two replacements are
not a single transaction: a failure during the second replacement can leave
the first report updated. These checks assume paths are not concurrently
changed by another process.

## Scope

v0.1 intentionally does **not** validate read contents, compare read counts, verify checksums, demultiplex, repair FASTQs, or implement pipeline-specific sample-sheet schemas.
