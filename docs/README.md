
# BlueStar Upload Validation

Python validation tooling for comparing BlueStar Item and BOM upload sheets against frozen PRE and POST snapshots.

## Purpose

The project verifies that a BlueStar upload produced the intended result:

- expected Items were created or modified;
- expected BOM lines exist with the correct Parent, Child, Position and Quantity;
- existing BOM structures were not unintentionally expanded, reduced or duplicated;
- newly created BOM structures contain the expected lines;
- uploaded records can be attributed to the intended uploader;
- protected BOMs were not changed;
- failures are written to a reviewable Excel report.

## Process

```text
Item/BOM upload workbook
        |
        v
Run PRE snapshot queries
        |
        v
Save item_snapshot_pre.parquet and bom_snapshot_pre.parquet
        |
        v
Perform BlueStar upload
        |
        v
Run POST snapshot queries
        |
        v
Save item_snapshot_post.parquet and bom_snapshot_post.parquet
        |
        v
Run validation
        |
        v
ValidationReport.xlsx
```

## Main files

```text
config.py                  Runtime configuration
mapping.py                 Item type and validation mappings
item_dataset.sql           Item snapshot query
bom_dataset.sql            BOM snapshot query
capture_snapshot.py        Executes snapshot queries and writes Parquet files
validate_items.py          Item validation logic
validate_boms.py           BOM and protected-BOM validation logic
main.py                    Orchestrates the end-to-end validation run
convert_snapshots.py       Converts Parquet snapshots to Excel for investigation
CODEBASE_GUIDE.md          Detailed codebase documentation
```

The exact repository may contain a subset of these files or use a different entry-point filename. Keep this list aligned with the committed code.

## Requirements

- Python 3.10 or later
- pandas
- pyarrow
- openpyxl
- database driver required by the snapshot scripts

Install project dependencies from the repository root:

```bash
python -m pip install pandas pyarrow openpyxl
```

If a `requirements.txt` file is supplied, use:

```bash
python -m pip install -r requirements.txt
```

## Running validation

1. Capture and freeze the PRE Item and BOM snapshots.
2. Complete the BlueStar upload.
3. Capture and freeze the POST Item and BOM snapshots.
4. Run the project entry point with the uploader and upload-window values required by the implementation.
5. Review `ValidationReport.xlsx`, starting with the summary sheets and then filtering the detailed result sheets by `Overall Result = FAIL`.

Do not overwrite the PRE snapshots after the upload. The PRE and POST files are the audit evidence for the validation run.

## Snapshot names

Expected default names:

```text
item_snapshot_pre.parquet
item_snapshot_post.parquet
bom_snapshot_pre.parquet
bom_snapshot_post.parquet
```

## Convert snapshots to Excel

Place the four Parquet files beside `convert_snapshots.py`, then run:

```bash
python convert_snapshots.py
```

The script creates one `.xlsx` file per snapshot. Excel has a worksheet row limit of 1,048,576, so oversized snapshots are split across numbered worksheets.

## Output handling

- Commit source code, SQL, Markdown documentation and dependency files to GitHub.
- Store generated validation reports and PRE/POST snapshot evidence in the controlled SharePoint results folder.
- Do not commit credentials, connection strings, tokens, generated reports, Parquet snapshots or Excel snapshot exports to GitHub.

Suggested `.gitignore` entries:

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
*.parquet
*.xlsx
!example_data/*.xlsx
```

## Further documentation

See [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) for validation rules, matching keys, report interpretation and troubleshooting guidance.
