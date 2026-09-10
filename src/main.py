"""
main.py

Command-line entry point for the BlueStar Item and BOM validation workflow.

Examples:
    python main.py pre --environment UAT1 \
        --item-file "input/Item Sheet.xlsx" \
        --bom-file "input/BOM Sheet.xlsx"

    python main.py post --environment UAT1 \
        --item-file "input/Item Sheet.xlsx" \
        --bom-file "input/BOM Sheet.xlsx"

    python main.py validate --environment UAT1 \
        --item-file "input/Item Sheet.xlsx" \
        --bom-file "input/BOM Sheet.xlsx" \
        --uploader "Dineshkumar" \
        --upload-start "2026-09-10 08:30:00+00:00" \
        --upload-end "2026-09-10 11:00:00+00:00"
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

from capture_snapshot import capture_snapshot
from config import get_schema
from fabric import load_bom_dataset, load_item_dataset
from report_writer import write_validation_report
from validate_boms import validate_boms
from validate_items import validate_items


OUTPUT_FOLDER = Path("output")
OUTPUT_FOLDER.mkdir(exist_ok=True)


def clean_column_names(dataframe: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    """Trim surrounding whitespace from Excel column names and reject duplicates."""
    prepared = dataframe.copy()
    prepared.columns = [str(column).strip() for column in prepared.columns]

    duplicated = prepared.columns[prepared.columns.duplicated()].tolist()
    if duplicated:
        raise ValueError(
            f"{dataset_name} contains duplicate column names after trimming: "
            f"{', '.join(duplicated)}"
        )

    return prepared


def read_excel_sheet(file_path: str, sheet_name: str | int, dataset_name: str) -> pd.DataFrame:
    """Read one Excel worksheet and return a DataFrame with clean column names."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"{dataset_name} file not found: {path}")

    try:
        dataframe = pd.read_excel(
            path,
            sheet_name=sheet_name,
            engine="openpyxl",
            dtype=object,
        )
    except ValueError as exc:
        raise ValueError(
            f"Unable to read worksheet '{sheet_name}' from {path}: {exc}"
        ) from exc

    if not isinstance(dataframe, pd.DataFrame):
        raise ValueError(f"{dataset_name} did not resolve to one worksheet.")

    return clean_column_names(dataframe, dataset_name)


def load_input_files(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the frozen Item and BOM worksheets."""
    item_sheet_df = read_excel_sheet(
        args.item_file,
        args.item_sheet,
        "Item Sheet",
    )
    bom_sheet_df = read_excel_sheet(
        args.bom_file,
        args.bom_sheet,
        "BOM Sheet",
    )
    return item_sheet_df, bom_sheet_df


def capture(args: argparse.Namespace, snapshot_type: str) -> None:
    """Query Fabric and save a scoped PRE or POST snapshot."""
    item_sheet_df, bom_sheet_df = load_input_files(args)

    print(f"Environment: {args.environment.upper()} ({get_schema(args.environment)})")
    item_dataset_df = load_item_dataset(args.environment)
    bom_dataset_df = load_bom_dataset(args.environment)

    item_snapshot_df, bom_snapshot_df = capture_snapshot(
        item_sheet_df=item_sheet_df,
        bom_sheet_df=bom_sheet_df,
        item_dataset_df=item_dataset_df,
        bom_dataset_df=bom_dataset_df,
        snapshot_type=snapshot_type,
    )

    print(f"Item snapshot rows: {len(item_snapshot_df):,}")
    print(f"BOM snapshot rows: {len(bom_snapshot_df):,}")


def read_parquet_snapshot(file_name: str, label: str) -> pd.DataFrame:
    """Load a snapshot file, retaining an empty snapshot if it was saved empty."""
    path = OUTPUT_FOLDER / file_name
    if not path.is_file():
        raise FileNotFoundError(
            f"{label} not found: {path}. Capture PRE and POST snapshots first."
        )
    return pd.read_parquet(path)


def run_validation(args: argparse.Namespace) -> None:
    """Validate saved PRE and POST snapshots and create the Excel report."""
    if not args.uploader:
        raise ValueError("--uploader is required for validate mode.")
    if not args.upload_start:
        raise ValueError("--upload-start is required for validate mode.")

    item_sheet_df, bom_sheet_df = load_input_files(args)

    item_pre_df = read_parquet_snapshot(
        "item_snapshot_pre.parquet", "PRE Item snapshot"
    )
    item_post_df = read_parquet_snapshot(
        "item_snapshot_post.parquet", "POST Item snapshot"
    )
    bom_pre_df = read_parquet_snapshot(
        "bom_snapshot_pre.parquet", "PRE BOM snapshot"
    )
    bom_post_df = read_parquet_snapshot(
        "bom_snapshot_post.parquet", "POST BOM snapshot"
    )
    print("STARTING ITEM VALIDATION")
    item_results_df, item_summary_df = validate_items(
        item_sheet_df=item_sheet_df,
        pre_snapshot_df=item_pre_df,
        post_snapshot_df=item_post_df,
        uploader=args.uploader,
        upload_start=args.upload_start,
        upload_end=args.upload_end,
    )
    print("ITEM VALIDATION COMPLETE")
    print("STARTING BOM VALIDATION")
    bom_results_df, protected_bom_results_df, bom_summary_df = validate_boms(
        item_sheet_df=item_sheet_df,
        bom_sheet_df=bom_sheet_df,
        pre_snapshot_df=bom_pre_df,
        post_snapshot_df=bom_post_df,
        uploader=args.uploader,
        upload_start=args.upload_start,
        upload_end=args.upload_end,
    )
    print("BOM VALIDATION COMPLETE")

    print("STARTING REPORT WRITER")
    report_path = write_validation_report(
        item_summary_df=item_summary_df,
        item_results_df=item_results_df,
        bom_summary_df=bom_summary_df,
        bom_results_df=bom_results_df,
        protected_bom_results_df=protected_bom_results_df,
        environment=args.environment.upper(),
        uploader=args.uploader,
        upload_start=args.upload_start,
        upload_end=args.upload_end,
        output_path=args.report,
    )

    print(f"Validation report saved: {report_path}")


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description="BlueStar Item and BOM upload validation"
    )
    parser.add_argument(
        "mode",
        choices=("pre", "post", "validate"),
        help="Capture PRE, capture POST, or validate saved snapshots.",
    )
    parser.add_argument("--environment", required=True)
    parser.add_argument("--item-file", required=True)
    parser.add_argument("--bom-file", required=True)
    parser.add_argument(
        "--item-sheet",
        default=0,
        help="Item worksheet name. Defaults to the first worksheet.",
    )
    parser.add_argument(
        "--bom-sheet",
        default=0,
        help="BOM worksheet name. Defaults to the first worksheet.",
    )
    parser.add_argument("--uploader")
    parser.add_argument("--upload-start")
    parser.add_argument("--upload-end")
    parser.add_argument(
        "--report",
        default=str(OUTPUT_FOLDER / "ValidationReport.xlsx"),
    )
    return parser


def main() -> int:
    """Run the requested workflow stage."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        get_schema(args.environment)

        if args.mode == "pre":
            capture(args, "PRE")
        elif args.mode == "post":
            capture(args, "POST")
        else:
            run_validation(args)

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
