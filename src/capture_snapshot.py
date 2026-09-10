"""
capture_snapshot.py

Purpose:
    Create PRE and POST BlueStar validation snapshots.

Snapshot Scope:

    Items:
        New Item Number
        (ALL variants for each Item Number in scope)

    BOMs:
        Parent Item Number

    Protected BOMs:
        ItemType = BOM
        AND
        New Item Number NOT IN BOM Parent List

Outputs:

    output/item_snapshot_pre.parquet
    output/bom_snapshot_pre.parquet

    output/item_snapshot_post.parquet
    output/bom_snapshot_post.parquet

Note:
    Empty Item snapshots are allowed (all items may be new).
    Validation determines whether absence represents failure.
"""

from pathlib import Path
from mapping import ITEM_TYPE_MAP
from validate_boms import normalize_item_type
import pandas as pd


OUTPUT_FOLDER = Path("output")
OUTPUT_FOLDER.mkdir(exist_ok=True)


# =============================================================================
# HELPERS
# =============================================================================

def normalize_text(value) -> str:
    """
    Normalize text values for matching.

    Preserves:
        33A
        61.2
        85AA

    Removes:
        Leading spaces
        Trailing spaces
    """

    if pd.isna(value):
        return ""

    return str(value).strip()


def validate_required_columns(
    dataframe: pd.DataFrame,
    required_columns: list,
    dataset_name: str
) -> None:
    """
    Ensure required columns exist.
    """

    missing = [
        col
        for col in required_columns
        if col not in dataframe.columns
    ]

    if missing:
        raise ValueError(
            f"{dataset_name} missing required columns: "
            f"{', '.join(missing)}"
        )


# =============================================================================
# ITEM SCOPE
# =============================================================================

def build_item_scope(
    item_sheet_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Build unique Item validation scope.

    Scope includes ALL variants for each Item Number.

    Key:
        New Item Number only
    """

    validate_required_columns(
        item_sheet_df,
        ["New Item Number"],
        "Item Sheet"
    )

    scope = item_sheet_df[
        ["New Item Number"]
    ].copy()

    scope["New Item Number"] = (
        scope["New Item Number"]
        .apply(normalize_text)
    )

    scope = scope.drop_duplicates()

    return scope


# =============================================================================
# BOM SCOPE
# =============================================================================

def build_bom_scope(
    bom_sheet_df: pd.DataFrame
) -> list:
    """
    Build BOM Parent scope.
    """

    validate_required_columns(
        bom_sheet_df,
        ["Parent Item Number"],
        "BOM Sheet"
    )

    return (
        bom_sheet_df["Parent Item Number"]
        .apply(normalize_text)
        .drop_duplicates()
        .tolist()
    )


# =============================================================================
# PROTECTED BOMS
# =============================================================================

def build_protected_bom_scope(
    item_sheet_df: pd.DataFrame,
    bom_sheet_df: pd.DataFrame
) -> list:
    """
    Protected BOM definition:

        ItemType = BOM

    AND

        New Item Number
        not present in BOM Parent list
    """

    validate_required_columns(
        item_sheet_df,
        [
            "New Item Number",
            "ItemType"
        ],
        "Item Sheet"
    )

    validate_required_columns(
        bom_sheet_df,
        ["Parent Item Number"],
        "BOM Sheet"
    )

    bom_parents = set(
        bom_sheet_df["Parent Item Number"]
        .apply(normalize_text)
    )

    protected = item_sheet_df.copy()

    protected["New Item Number"] = (
        protected["New Item Number"]
        .apply(normalize_text)
    )

    protected["_item_type_key"] = (
        protected["ItemType"]
        .apply(normalize_item_type)
    )

    protected = protected[
        protected["_item_type_key"] == ITEM_TYPE_MAP["BOM"]
    ]

    protected = protected[
        ~protected["New Item Number"]
        .isin(bom_parents)
    ]

    return (
        protected["New Item Number"]
        .drop_duplicates()
        .tolist()
    )


# =============================================================================
# SAVE SNAPSHOTS
# =============================================================================

def save_snapshot(
    item_snapshot_df: pd.DataFrame,
    bom_snapshot_df: pd.DataFrame,
    snapshot_type: str
) -> None:
    """
    Save snapshot outputs.
    """

    snapshot_type = snapshot_type.upper()

    if snapshot_type not in {"PRE", "POST"}:
        raise ValueError(
            "snapshot_type must be PRE or POST"
        )

    item_file = (
        OUTPUT_FOLDER /
        f"item_snapshot_{snapshot_type.lower()}.parquet"
    )

    bom_file = (
        OUTPUT_FOLDER /
        f"bom_snapshot_{snapshot_type.lower()}.parquet"
    )

    item_snapshot_df.to_parquet(
        item_file,
        index=False
    )

    bom_snapshot_df.to_parquet(
        bom_file,
        index=False
    )

    print(f"Saved: {item_file}")
    print(f"Saved: {bom_file}")


# =============================================================================
# MAIN SNAPSHOT CAPTURE
# =============================================================================

def capture_snapshot(
    item_sheet_df: pd.DataFrame,
    bom_sheet_df: pd.DataFrame,
    item_dataset_df: pd.DataFrame,
    bom_dataset_df: pd.DataFrame,
    snapshot_type: str
):
    """
    Capture scoped validation snapshots.

    Parameters:

        item_sheet_df
            Uploaded Item Sheet

        bom_sheet_df
            Uploaded BOM Sheet

        item_dataset_df
            Output from item_dataset.sql

        bom_dataset_df
            Output from bom_dataset.sql

        snapshot_type
            PRE or POST
    """

    # ---------------------------------------------------------
    # Build scopes
    # ---------------------------------------------------------

    item_scope = build_item_scope(
        item_sheet_df
    )

    bom_scope = build_bom_scope(
        bom_sheet_df
    )

    protected_scope = build_protected_bom_scope(
        item_sheet_df,
        bom_sheet_df
    )

    # ---------------------------------------------------------
    # Normalize snapshot datasets
    # ---------------------------------------------------------

    item_dataset = item_dataset_df.copy()

    item_dataset["New Item Number"] = (
        item_dataset["New Item Number"]
        .apply(normalize_text)
    )

    item_dataset["New Variant Id"] = (
        item_dataset["New Variant Id"]
        .fillna("")
        .apply(normalize_text)
    )

    bom_dataset = bom_dataset_df.copy()

    bom_dataset["Parent Item Number"] = (
        bom_dataset["Parent Item Number"]
        .apply(normalize_text)
    )

    # ---------------------------------------------------------
    # Item Snapshot
    # ---------------------------------------------------------
    # Include ALL variants for each Item Number in scope.
    # This allows wrong-variant detection in validation.

    item_snapshot = item_dataset.merge(
        item_scope,
        on=["New Item Number"],
        how="inner"
    )

    # Empty Item snapshots are allowed (e.g., all items are new).

    # ---------------------------------------------------------
    # BOM Snapshot
    # ---------------------------------------------------------

    normal_boms = bom_dataset[
        bom_dataset["Parent Item Number"]
        .isin(bom_scope)
    ]

    protected_boms = bom_dataset[
        bom_dataset["Parent Item Number"]
        .isin(protected_scope)
    ]

    bom_snapshot = pd.concat(
        [
            normal_boms,
            protected_boms
        ],
        ignore_index=True
    )

    bom_snapshot = bom_snapshot.drop_duplicates()


    # ---------------------------------------------------------
    # Save
    # ---------------------------------------------------------

    save_snapshot(
        item_snapshot,
        bom_snapshot,
        snapshot_type
    )

    return (
        item_snapshot,
        bom_snapshot
    )