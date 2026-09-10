# BlueStar Upload Validation: Codebase Guide

## 1. Overview

This codebase validates BlueStar Item and BOM migration uploads by comparing the intended upload sheets with frozen database snapshots taken before and after the upload.

The design has three evidence layers:

1. **Upload intent**: the Item Sheet and BOM Sheet define what was intended.
2. **PRE state**: the PRE snapshots record the BlueStar state before loading.
3. **POST state**: the POST snapshots record the BlueStar state after loading.

The generated Excel report combines these layers so a reviewer can distinguish successful creation, successful modification, unchanged data and genuine validation failures.

## 2. End-to-end architecture

```text
                       +----------------------+
                       | BlueStar upload file |
                       | Item Sheet / BOM     |
                       +----------+-----------+
                                  |
              +-------------------+-------------------+
              |                                       |
              v                                       v
      +---------------+                       +---------------+
      | PRE SQL query |                       | POST SQL query|
      +-------+-------+                       +-------+-------+
              |                                       |
              v                                       v
  item_snapshot_pre.parquet              item_snapshot_post.parquet
  bom_snapshot_pre.parquet               bom_snapshot_post.parquet
              |                                       |
              +-------------------+-------------------+
                                  |
                                  v
                         +------------------+
                         | Python validators|
                         +--------+---------+
                                  |
                                  v
                       ValidationReport.xlsx
```

## 3. Repository components

### `config.py`

Central configuration for paths, connection details, upload parameters and report output. Secrets should not be hard-coded or committed. Prefer environment variables or an approved secret store.

### `mapping.py`

Contains canonical mappings used by validators, including Item Type mappings such as Item, BOM and Formula. Mapping changes affect validation results and should be reviewed as controlled logic changes.

### `item_dataset.sql`

Returns the Item population required for PRE and POST comparison. The dataset should expose stable identifiers, Item status, Item Type, AX Template, variant fields, audit users, business timestamps and record identifiers used for diagnostics.

### `bom_dataset.sql`

Returns BOM relationships required for PRE and POST comparison. At minimum, the validator expects:

```text
Parent Item Number
Child Item Number
Position
Quantity
BlueStar BOM RecId
Created By
Modified By
Upload Tracking DateTime
```

The SQL must use the same structural grain in PRE and POST. Duplicate database rows or inconsistent filters can produce false multiple-candidate and parent-count errors.

### `capture_snapshot.py`

Runs the snapshot queries and writes frozen Parquet files. PRE files must be captured before the upload and must not be regenerated afterwards. POST files must be captured after the upload and after the underlying reporting source contains the loaded records.

### `validate_items.py`

Validates Item Sheet rows against PRE and POST Item snapshots. Typical checks include:

- Item exists in POST;
- new versus existing classification based on PRE presence;
- upload attribution from creation or modification evidence;
- AX Template comparison;
- Item Type comparison;
- variant-field comparison;
- duplicate or ambiguous candidate detection.

Detailed report fields should expose both expected and actual values, selected record IDs, candidate counts and candidate-resolution evidence.

### `validate_boms.py`

Validates BOM Sheet rows and protected BOM structures.

#### Sheet preparation

The validator standardises accepted headers, adds `Source Row Number`, creates normalised matching keys and rejects invalid input rows.

#### Primary BOM key

```text
Parent Item Number + Child Item Number + Position
```

Quantity is a secondary discriminator. A row first resolves candidates on the primary key, then resolves the correct candidate using normalised Quantity.

#### Normalisation

- Parent and Child identifiers are trimmed.
- integer-like Excel values are normalised consistently;
- blank, null and backend zero Positions are treated as the same canonical Position where BlueStar stores upload blanks as zero;
- numeric Positions such as `500`, `500.0` and `500.000000` resolve to one value;
- alphanumeric Positions are compared case-insensitively;
- Quantity is compared as `Decimal` with a configured tolerance.

Excel date-formatted Position cells should be corrected at source or explicitly normalised. A Position displayed as a 1900 date can represent an Excel serial number rather than a true date.

#### Line-level outcomes

Typical processing results are:

```text
PASS_CREATED
PASS_MODIFIED
PASS_PRESENT_UNCHANGED
FAIL_MISSING_BOM_LINE
FAIL_QUANTITY_MISMATCH
FAIL_MULTIPLE_BOM_CANDIDATES
FAIL_UPLOAD_ATTRIBUTION
FAIL_UNEXPECTED_BOM_LINE
```

#### Unexpected POST lines

A POST line under an uploaded parent is not automatically unexpected. The validator should suppress a line that:

- is not in the BOM Sheet;
- existed in PRE with the same Parent, Child and Position;
- has an unchanged Quantity in POST.

A line is unexpected when it is absent from the intended upload and cannot be explained as an unchanged PRE line.

#### Parent-count rule

Parent counts are selected conditionally:

```text
Existing parent: expected count = PRE parent line count
New parent:      expected count = BOM Sheet parent row count
Actual count:    POST parent line count
```

This validates the intended behaviours:

- an existing BOM relationship may be recreated or modified, but the overall parent line count should not change;
- a new BOM parent should contain the number of direct lines supplied for that parent in the BOM Sheet.

The report should expose:

```text
Parent Existed In PRE
PRE Parent Line Count
BOM Sheet Parent Row Count
POST Parent Line Count
Parent Count Rule
Expected Parent Count
Actual Parent Count
Parent Count Matches
```

A parent-level count failure may appear on multiple detailed rows for investigation. The summary must therefore report both failed rows and unique affected parents.

#### Protected BOMs

Items classified as BOMs in the Item Sheet but absent as uploaded BOM Sheet parents are treated as protected structures. PRE and POST multisets are compared using Child, Position and Quantity so that added, removed and changed protected lines are not hidden.

## 4. Report interpretation

### Summary metrics

Recommended BOM summary metrics include:

```text
Expected BOM Sheet Rows
Matched Rows
Created Rows
Modified Rows
Present Unchanged Rows
Missing Rows
Quantity Mismatch Rows
Duplicate Match Rows
Unexpected Rows
Parents Expected
Parents With Count Mismatch
Unique BOM Parents With Errors
Parents With Missing Lines
Parents With Unexpected Lines
Parents With Quantity Mismatches
Parents With Duplicate Matches
Protected BOMs Checked
Protected BOM Failures
Passed Result Rows
Failed Result Rows
```

`Failed Result Rows` is the detailed workload. `Unique BOM Parents With Errors` is the affected-BOM count and should be used alongside row counts to avoid overstating a repeated parent-level failure.

### Investigation order

1. Filter the relevant detail sheet to `Overall Result = FAIL`.
2. Group by `Failure Codes`.
3. Review unique parents before reviewing every repeated row.
4. For missing lines, compare expected and actual normalised keys.
5. For quantity failures, compare expected and actual quantities.
6. For count failures, review PRE, BOM Sheet and POST parent counts together.
7. For Item field failures, inspect selected BlueStar and Engineering Object record IDs.
8. Confirm whether the issue is source formatting, query grain, candidate selection, business data or load execution.

## 5. Common failure patterns

### Blank Position versus backend zero

BlueStar may store a blank upload Position as `0`. Both inputs must normalise to the same key.

### Numeric formatting

Values such as `1` and `1.000000` should match after Decimal conversion.

### Excel date formatting in Position

Excel can display numeric Positions as dates. Correct the upload workbook formatting and preserve Positions as text where possible.

### False unexpected lines

A full POST parent structure may contain pre-existing lines not included in a targeted upload. Such lines are not unexpected when an identical line and quantity existed in PRE.

### Inflated error totals

One parent-count failure can be repeated across every result row for the parent. Report both detailed failed rows and unique failed parents.

### Audit timestamps

Backend business timestamps and data-platform sink timestamps can represent different events. Do not substitute ingestion timestamps for business-event timestamps without confirming their semantics. The current BOM attribution logic relies on normalised uploader fields rather than treating `createdonpartition` as the sole attribution gate.

## 6. Snapshot evidence and Excel conversion

Parquet is the primary technical snapshot format because it preserves tabular types efficiently. Excel copies are useful for manual investigation and SharePoint review.

Run:

```bash
python convert_snapshots.py
```

The converter:

- looks for the four standard snapshot filenames;
- creates one Excel workbook per Parquet file;
- writes data in chunks to respect Excel's 1,048,576-row worksheet limit;
- freezes headers and enables filters;
- keeps Parquet files unchanged.

Excel exports are review copies. The Parquet files remain the authoritative inputs used by the Python validators.

## 7. GitHub and SharePoint separation

### GitHub

Store:

- Python source;
- SQL queries;
- mappings and non-secret configuration templates;
- Markdown documentation;
- dependency files;
- tests and small synthetic examples.

Do not store:

- credentials or tokens;
- live connection strings;
- upload workbooks containing operational data;
- PRE/POST snapshots;
- generated validation reports;
- production or UAT data extracts.

### SharePoint results folder

Store run evidence together:

```text
<run-folder>/
    ValidationReport.xlsx
    item_snapshot_pre.parquet
    item_snapshot_post.parquet
    bom_snapshot_pre.parquet
    bom_snapshot_post.parquet
    item_snapshot_pre.xlsx
    item_snapshot_post.xlsx
    bom_snapshot_pre.xlsx
    bom_snapshot_post.xlsx
    upload-source-file.xlsx
    run-notes.md
```

Use an agreed naming convention that identifies environment and run, and restrict access according to the data's classification.

## 8. Change-control recommendations

- Keep validation-rule changes in small commits.
- Record why each rule changed and include a representative failure example.
- Re-run against the same frozen snapshots after logic-only changes.
- Add regression tests for every confirmed edge case.
- Keep query changes separate from validator changes where possible.
- Treat mapping changes as controlled business-rule changes.

Recommended regression cases include:

```text
blank Position vs backend 0
1 vs 1.000000 Quantity
alphanumeric Position case differences
Excel date-formatted Position
existing parent with a targeted line update
new parent with multiple lines
unchanged PRE line absent from targeted upload
truly unexpected POST line
multiple matching backend candidates
protected BOM line addition/removal/quantity change
```

## 9. Handover checklist

- [ ] Repository contains no secrets or result data.
- [ ] `README.md` matches the committed filenames and entry point.
- [ ] Dependencies are recorded.
- [ ] PRE and POST snapshots are frozen and identifiable.
- [ ] Validation report is stored with the snapshots used to generate it.
- [ ] Excel review copies are stored beside the Parquet evidence.
- [ ] Summary reports both failed rows and unique affected parents.
- [ ] Known limitations and unresolved failures are recorded in run notes.
- [ ] A reviewer can reproduce the validation from the committed code and controlled evidence files.
