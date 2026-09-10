"""
validate_boms.py

Validates the frozen BOM Sheet against BlueStar PRE and POST snapshots.

BOM Sheet matching:

    Primary key:
        Parent Item Number
        Child Item Number
        Position

    Secondary discriminator:
        Quantity

Validation covers:

    - Every expected BOM line exists after upload
    - Parent-level line counts reconcile
    - Quantity matches
    - Duplicate or ambiguous BlueStar matches are reported
    - Unexpected lines under uploaded parents are reported
    - New lines have uploader/time attribution
    - Existing unchanged lines are identified
    - Protected BOM structures remain unchanged

Returns:

    bom_results_df
        One result row per BOM Sheet row.

    protected_bom_results_df
        One result row per protected BOM parent.

    bom_summary_df
        Reconciliation control totals.

No files are written by this module.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from mapping import ITEM_TYPE_MAP


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_QUANTITY_TOLERANCE = Decimal("0.000001")


BOM_SHEET_REQUIRED_COLUMNS = [
    "Parent Item Number",
    "Child Item Number",
    "Position",
    "Quantity",
]


SNAPSHOT_REQUIRED_COLUMNS = [
    "Parent Item Number",
    "Child Item Number",
    "Position",
    "Quantity",
    "BlueStar BOM RecId",
    "Created By",
    "Modified By",
    "Upload Tracking DateTime",
]


# Accepted minor header variations from manually maintained Excel files.
COLUMN_ALIASES = {
    "parentitemnumber": "Parent Item Number",
    "parentitem": "Parent Item Number",
    "bomid": "Parent Item Number",

    "childitemnumber": "Child Item Number",
    "childitem": "Child Item Number",
    "itemid": "Child Item Number",

    "position": "Position",

    "quantity": "Quantity",
    "bomqty": "Quantity",

    "newitemnumber": "New Item Number",
    "itemtype": "ItemType",
}


# =============================================================================
# NORMALIZATION
# =============================================================================

def column_key(value: Any) -> str:
    """
    Create a comparison key for Excel column names.

    Ignores:
        - Case
        - Spaces
        - Underscores
        - Hyphens
        - Other punctuation
    """

    if value is None:
        return ""

    return "".join(
        character
        for character in str(value).strip().casefold()
        if character.isalnum()
    )


def standardize_columns(
    dataframe: pd.DataFrame,
    dataset_name: str
) -> pd.DataFrame:
    """
    Standardize known Excel column-name variations.

    Raises an error if two original columns resolve to the same
    canonical column name.
    """

    prepared = dataframe.copy()
    rename_map = {}
    resolved_names = {}

    for original_column in prepared.columns:
        key = column_key(original_column)
        canonical_column = COLUMN_ALIASES.get(
            key,
            str(original_column).strip()
        )

        if (
            canonical_column in resolved_names
            and resolved_names[canonical_column] != original_column
        ):
            raise ValueError(
                f"{dataset_name} contains multiple columns that resolve to "
                f"'{canonical_column}': "
                f"'{resolved_names[canonical_column]}' and "
                f"'{original_column}'."
            )

        resolved_names[canonical_column] = original_column
        rename_map[original_column] = canonical_column

    return prepared.rename(columns=rename_map)

def normalize_position(value: Any) -> str:
    if value is None or pd.isna(value):
        return "0"

    text = str(value).strip()

    if not text:
        return "0"

    try:
        numeric_value = Decimal(text)

        if numeric_value == numeric_value.to_integral_value():
            return str(int(numeric_value))

        return format(
            numeric_value.normalize(),
            "f"
        ).rstrip("0").rstrip(".")

    except InvalidOperation:
        return text.casefold()
def normalize_identifier(value: Any) -> str:
    """
    Normalize Parent and Child item identifiers for matching.

    Position is not split, reformatted or converted to numeric.

    Examples:
        33A  -> 33A
        61.2 -> 61.2
        BB   -> BB
        1.0 from Excel -> 1

    Only surrounding whitespace is removed.
    """

    if value is None or pd.isna(value):
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def normalize_quantity(value: Any) -> Decimal | None:
    """
    Convert Quantity to Decimal for reliable numeric comparison.

    Returns None for blank or invalid values.
    """

    if value is None or pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def quantities_match(
    expected: Decimal | None,
    actual: Decimal | None,
    tolerance: Decimal
) -> bool:
    """
    Compare quantities using the configured numeric tolerance.
    """

    if expected is None or actual is None:
        return expected is None and actual is None

    return abs(expected - actual) <= tolerance


def normalize_datetime(value: Any) -> pd.Timestamp:
    """
    Convert a value to a UTC-aware timestamp.
    """

    if value is None or pd.isna(value):
        return pd.NaT

    return pd.to_datetime(
        value,
        errors="coerce",
        utc=True
    )


def normalize_user(value: Any) -> str:
    """
    Normalize uploader names for comparison.
    """

    if value is None or pd.isna(value):
        return ""

    return str(value).strip().casefold()


def normalize_item_type(value: Any) -> int | None:
    """
    Normalize ItemType to its BlueStar numeric value.

    Supports:
        Item / 0
        BOM / 1
        Formula / 2
    """

    if value is None or pd.isna(value):
        return None

    text = str(value).strip().casefold()

    if not text:
        return None

    for mapping_text, mapping_value in ITEM_TYPE_MAP.items():
        if str(mapping_text).strip().casefold() == text:
            return mapping_value

    try:
        numeric_value = Decimal(text)

        if numeric_value == numeric_value.to_integral_value():
            return int(numeric_value)

    except InvalidOperation:
        pass

    return None


# =============================================================================
# DATAFRAME VALIDATION
# =============================================================================

def validate_required_columns(
    dataframe: pd.DataFrame,
    required_columns: list[str],
    dataset_name: str
) -> None:
    """
    Ensure required columns are present.
    """

    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise ValueError(
            f"{dataset_name} is missing required columns: "
            f"{', '.join(missing_columns)}"
        )


def prepare_bom_sheet(
    bom_sheet_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Standardize and validate the BOM Sheet.
    """

    prepared = standardize_columns(
        bom_sheet_df,
        "BOM Sheet"
    )

    validate_required_columns(
        prepared,
        BOM_SHEET_REQUIRED_COLUMNS,
        "BOM Sheet"
    )

    prepared = prepared.copy()

    if "Source Row Number" in prepared.columns:
        raise ValueError(
            "BOM Sheet already contains a 'Source Row Number' column."
        )

    prepared.insert(
        0,
        "Source Row Number",
        range(2, len(prepared) + 2)
    )

    prepared["_parent_key"] = (
        prepared["Parent Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_child_key"] = (
        prepared["Child Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_position_key"] = (
        prepared["Position"]
        .apply(normalize_position)
    )

    prepared["_expected_quantity"] = (
        prepared["Quantity"]
        .apply(normalize_quantity)
    )

    blank_key_mask = (
        prepared["_parent_key"].eq("")
        | prepared["_child_key"].eq("")
    )

    if blank_key_mask.any():
        invalid_rows = prepared.loc[
            blank_key_mask,
            [
                "Source Row Number",
                "Parent Item Number",
                "Child Item Number",
                "Position",
            ]
        ]

        raise ValueError(
            f"BOM Sheet contains {len(invalid_rows):,} rows with a blank "
            "Parent Item Number or Child Item Number.\n\n"
            "First 20 examples:\n"
            f"{invalid_rows.head(20).to_string(index=False)}"
        )

    invalid_quantity_mask = (
        prepared["_expected_quantity"].isna()
    )
    
    if invalid_quantity_mask.any():
        invalid_rows = prepared.loc[
            invalid_quantity_mask,
            [
                "Source Row Number",
                "Parent Item Number",
                "Child Item Number",
                "Position",
                "Quantity",
            ]
        ]

        raise ValueError(
            f"BOM Sheet contains {len(invalid_rows):,} rows with a blank "
            "or invalid Quantity.\n\n"
            "First 20 examples:\n"
            f"{invalid_rows.head(20).to_string(index=False)}"
        )
    
    duplicate_key_mask = prepared.duplicated(
        subset=[
            "_parent_key",
            "_child_key",
            "_position_key",
        ],
        keep=False
    )
    
    if duplicate_key_mask.any():
        duplicate_rows = prepared.loc[
            duplicate_key_mask,
            [
                "Source Row Number",
                "Parent Item Number",
                "Child Item Number",
                "Position",
                "Quantity",
            ]
        ]

        raise ValueError(
            f"BOM Sheet contains {len(duplicate_rows):,} duplicate "
            "Parent + Child + Position combinations.\n\n"
            "First 20 examples:\n"
            f"{duplicate_rows.head(20).to_string(index=False)}"
        )

    return prepared


def prepare_snapshot(
    snapshot_df: pd.DataFrame,
    snapshot_name: str
) -> pd.DataFrame:
    """
    Prepare a PRE or POST BOM snapshot.
    """

    if snapshot_df.empty:
        return snapshot_df.copy()

    validate_required_columns(
        snapshot_df,
        SNAPSHOT_REQUIRED_COLUMNS,
        snapshot_name
    )

    prepared = snapshot_df.copy()

    prepared["_parent_key"] = (
        prepared["Parent Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_child_key"] = (
        prepared["Child Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_position_key"] = (
        prepared["Position"]
        .apply(normalize_position)
    )

    prepared["_actual_quantity"] = (
        prepared["Quantity"]
        .apply(normalize_quantity)
    )

    return prepared


def prepare_item_sheet_for_protection(
    item_sheet_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Prepare the Item Sheet fields required to determine protected BOMs.
    """

    prepared = standardize_columns(
        item_sheet_df,
        "Item Sheet"
    )

    validate_required_columns(
        prepared,
        [
            "New Item Number",
            "ItemType",
        ],
        "Item Sheet"
    )

    prepared = prepared.copy()

    prepared["_item_number_key"] = (
        prepared["New Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_item_type_key"] = (
        prepared["ItemType"]
        .apply(normalize_item_type)
    )

    return prepared


# =============================================================================
# SCOPE
# =============================================================================

def get_uploaded_parent_keys(
    prepared_bom_sheet: pd.DataFrame
) -> set[str]:
    """
    Return uploaded BOM parent keys.
    """

    return set(
        prepared_bom_sheet["_parent_key"]
        .dropna()
        .tolist()
    )


def get_protected_parent_keys(
    prepared_item_sheet: pd.DataFrame,
    uploaded_parent_keys: set[str]
) -> set[str]:
    """
    Protected BOMs are Item Sheet rows where:

        ItemType = BOM

    and:

        New Item Number is not a parent in the BOM Sheet.
    """

    bom_type_value = ITEM_TYPE_MAP["BOM"]

    return set(
        prepared_item_sheet.loc[
            prepared_item_sheet["_item_type_key"].eq(
                bom_type_value
            )
            & ~prepared_item_sheet["_item_number_key"].isin(
                uploaded_parent_keys
            ),
            "_item_number_key"
        ]
        .dropna()
        .tolist()
    )


# =============================================================================
# MATCHING
# =============================================================================

def find_line_candidates(
    bom_row: pd.Series,
    snapshot_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Find candidates using Parent, Child and Position.
    """

    if snapshot_df.empty:
        return snapshot_df.copy()

    matching_mask = (
        snapshot_df["_parent_key"].eq(
            bom_row["_parent_key"]
        )
        & snapshot_df["_child_key"].eq(
            bom_row["_child_key"]
        )
        & snapshot_df["_position_key"].eq(
            bom_row["_position_key"]
        )
    )

    return snapshot_df.loc[matching_mask].copy()


def resolve_quantity_candidates(
    candidates: pd.DataFrame,
    expected_quantity: Decimal,
    tolerance: Decimal
) -> pd.DataFrame:
    """
    Resolve multiple candidates using Quantity.
    """

    if candidates.empty:
        return candidates.copy()

    matching_mask = candidates[
        "_actual_quantity"
    ].apply(
        lambda actual_quantity: quantities_match(
            expected_quantity,
            actual_quantity,
            tolerance
        )
    )

    return candidates.loc[matching_mask].copy()


def resolve_snapshot_line(
    bom_row: pd.Series,
    snapshot_df: pd.DataFrame,
    tolerance: Decimal
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return:

        primary_candidates
        quantity_candidates
    """

    primary_candidates = find_line_candidates(
        bom_row,
        snapshot_df
    )

    quantity_candidates = resolve_quantity_candidates(
        primary_candidates,
        bom_row["_expected_quantity"],
        tolerance
    )

    return primary_candidates, quantity_candidates


# =============================================================================
# AUDIT ATTRIBUTION
# =============================================================================
def line_has_upload_attribution(
    post_row: pd.Series,
    uploader: str,
) -> tuple[bool, str]:

    uploader_key = normalize_user(uploader)
    evidence = []

    if normalize_user(post_row.get("Created By")) == uploader_key:
        evidence.append("Created By matched")

    if normalize_user(post_row.get("Modified By")) == uploader_key:
        evidence.append("Modified By matched")

    return bool(evidence), "; ".join(evidence)

# =============================================================================
# PROTECTED BOM COMPARISON
# =============================================================================

def structure_counter(
    parent_rows: pd.DataFrame
) -> Counter:
    """
    Return a multiset of BOM lines.

    Quantity is included so duplicate physical lines and quantity changes
    are not hidden.
    """

    if parent_rows.empty:
        return Counter()

    return Counter(
        (
            row["_child_key"],
            row["_position_key"],
            row["_actual_quantity"],
        )
        for _, row in parent_rows.iterrows()
    )


def base_key_counter(
    parent_rows: pd.DataFrame
) -> Counter:
    """
    Return a multiset that excludes Quantity.

    Used to distinguish quantity changes from added or removed lines.
    """

    if parent_rows.empty:
        return Counter()

    return Counter(
        (
            row["_child_key"],
            row["_position_key"],
        )
        for _, row in parent_rows.iterrows()
    )


def validate_protected_boms(
    protected_parent_keys: set[str],
    pre_snapshot: pd.DataFrame,
    post_snapshot: pd.DataFrame
) -> pd.DataFrame:
    """
    Compare protected BOM structures between PRE and POST snapshots.
    """

    results = []

    for parent_key in sorted(protected_parent_keys):

        pre_rows = (
            pre_snapshot.loc[
                pre_snapshot["_parent_key"].eq(
                    parent_key
                )
            ].copy()
            if not pre_snapshot.empty
            else pd.DataFrame()
        )

        post_rows = (
            post_snapshot.loc[
                post_snapshot["_parent_key"].eq(
                    parent_key
                )
            ].copy()
            if not post_snapshot.empty
            else pd.DataFrame()
        )

        pre_structure = structure_counter(
            pre_rows
        )

        post_structure = structure_counter(
            post_rows
        )

        pre_base_keys = base_key_counter(
            pre_rows
        )

        post_base_keys = base_key_counter(
            post_rows
        )

        failure_codes = []

        if pre_structure != post_structure:

            if pre_rows.empty and not post_rows.empty:
                failure_codes.append(
                    "BLOCK_PROTECTED_BOM_LINE_ADDED"
                )

            elif not pre_rows.empty and post_rows.empty:
                failure_codes.append(
                    "BLOCK_PROTECTED_BOM_EMPTIED"
                )

            else:
                removed_base_keys = (
                    pre_base_keys - post_base_keys
                )

                added_base_keys = (
                    post_base_keys - pre_base_keys
                )

                if removed_base_keys:
                    failure_codes.append(
                        "BLOCK_PROTECTED_BOM_LINE_REMOVED"
                    )

                if added_base_keys:
                    failure_codes.append(
                        "BLOCK_PROTECTED_BOM_LINE_ADDED"
                    )

                common_base_keys = (
                    set(pre_base_keys)
                    & set(post_base_keys)
                )

                quantity_changed = False

                for child_key, position_key in common_base_keys:
                    pre_quantities = sorted(
                        str(value)
                        for value in pre_rows.loc[
                            pre_rows["_child_key"].eq(child_key)
                            & pre_rows["_position_key"].eq(position_key),
                            "_actual_quantity"
                        ].tolist()
                    )

                    post_quantities = sorted(
                        str(value)
                        for value in post_rows.loc[
                            post_rows["_child_key"].eq(child_key)
                            & post_rows["_position_key"].eq(position_key),
                            "_actual_quantity"
                        ].tolist()
                    )

                    if pre_quantities != post_quantities:
                        quantity_changed = True
                        break

                if quantity_changed:
                    failure_codes.append(
                        "BLOCK_PROTECTED_BOM_LINE_CHANGED"
                    )

        results.append(
            {
                "Parent Item Number": parent_key,
                "PRE Line Count": len(pre_rows),
                "POST Line Count": len(post_rows),
                "Protected BOM Unchanged":
                    not failure_codes,
                "Failure Codes":
                    "; ".join(dict.fromkeys(failure_codes)),
                "Overall Result":
                    "FAIL" if failure_codes else "PASS",
            }
        )

    return pd.DataFrame(results)


# =============================================================================
# MAIN VALIDATION
# =============================================================================

def validate_boms(
    item_sheet_df: pd.DataFrame,
    bom_sheet_df: pd.DataFrame,
    pre_snapshot_df: pd.DataFrame,
    post_snapshot_df: pd.DataFrame,
    uploader: str,
    upload_start: str | datetime | pd.Timestamp,
    upload_end: str | datetime | pd.Timestamp | None = None,
    quantity_tolerance: Decimal | str | float = (
        DEFAULT_QUANTITY_TOLERANCE
    )
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame
]:
    """
    Validate BOM Sheet rows and protected BOM structures.

    Returns:

        bom_results_df
        protected_bom_results_df
        bom_summary_df
    """

    if not uploader or not str(uploader).strip():
        raise ValueError(
            "Uploader must be provided."
        )

    tolerance = normalize_quantity(
        quantity_tolerance
    )

    if tolerance is None or tolerance < 0:
        raise ValueError(
            "quantity_tolerance must be a valid non-negative number."
        )

    upload_start_utc = normalize_datetime(
        upload_start
    )

    if pd.isna(upload_start_utc):
        raise ValueError(
            f"Invalid upload_start value: {upload_start}"
        )

    prepared_bom_sheet = prepare_bom_sheet(
        bom_sheet_df
    )

    prepared_item_sheet = (
        prepare_item_sheet_for_protection(
            item_sheet_df
        )
    )

    prepared_pre = prepare_snapshot(
        pre_snapshot_df,
        "PRE BOM Snapshot"
    )

    prepared_post = prepare_snapshot(
        post_snapshot_df,
        "POST BOM Snapshot"
    )

    if upload_end is None:
        if (
            prepared_post.empty
            or "Snapshot Captured UTC"
            not in prepared_post.columns
        ):
            raise ValueError(
                "upload_end was not provided and the POST BOM snapshot "
                "does not contain usable Snapshot Captured UTC values."
            )

        capture_times = pd.to_datetime(
            prepared_post["Snapshot Captured UTC"],
            errors="coerce",
            utc=True
        ).dropna()

        if capture_times.empty:
            raise ValueError(
                "POST BOM snapshot contains no valid "
                "Snapshot Captured UTC values."
            )

        upload_end_utc = capture_times.max()

    else:
        upload_end_utc = normalize_datetime(
            upload_end
        )

    if pd.isna(upload_end_utc):
        raise ValueError(
            f"Invalid upload_end value: {upload_end}"
        )

    if upload_end_utc < upload_start_utc:
        raise ValueError(
            "upload_end cannot be earlier than upload_start."
        )

    uploaded_parent_keys = get_uploaded_parent_keys(
        prepared_bom_sheet
    )

    protected_parent_keys = get_protected_parent_keys(
        prepared_item_sheet,
        uploaded_parent_keys
    )

    # Parent counts
    # Existing parent: expected count comes from PRE.
    # New parent: expected count comes from the BOM Sheet.
    # Actual count always comes from POST.
    # -------------------------------------------------------------------------

    pre_parent_counts = (
        prepared_pre.loc[
            prepared_pre["_parent_key"].isin(
                uploaded_parent_keys
            )
        ]
        .groupby("_parent_key")
        .size()
        .to_dict()
        if not prepared_pre.empty
        else {}
    )

    bom_sheet_parent_counts = (
        prepared_bom_sheet
        .groupby("_parent_key")
        .size()
        .to_dict()
    )

    post_parent_counts = (
        prepared_post.loc[
            prepared_post["_parent_key"].isin(
                uploaded_parent_keys
            )
        ]
        .groupby("_parent_key")
        .size()
        .to_dict()
        if not prepared_post.empty
        else {}
    )

    expected_parent_counts = {}

    for parent_key in uploaded_parent_keys:

        pre_parent_count = pre_parent_counts.get(
            parent_key,
            0
        )

        if pre_parent_count > 0:

            expected_parent_counts[parent_key] = (
                pre_parent_count
            )

        else:

            expected_parent_counts[parent_key] = (
                bom_sheet_parent_counts.get(
                    parent_key,
                    0
                )
            )

    actual_parent_counts = post_parent_counts


    results = []

    for _, bom_row in prepared_bom_sheet.iterrows():

        pre_primary, pre_quantity = (
            resolve_snapshot_line(
                bom_row,
                prepared_pre,
                tolerance
            )
        )

        post_primary, post_quantity = (
            resolve_snapshot_line(
                bom_row,
                prepared_post,
                tolerance
            )
        )

        primary_count = len(post_primary)
        quantity_match_count = len(
            post_quantity
        )

        failure_codes = []
        warning_codes = []

        selected_post_row = None

        if primary_count == 0:
            processing_result = (
                "FAIL_MISSING_BOM_LINE"
            )
            failure_codes.append(
                "FAIL_MISSING_BOM_LINE"
            )

        elif quantity_match_count == 0:
            processing_result = (
                "FAIL_QUANTITY_MISMATCH"
            )
            failure_codes.append(
                "FAIL_QUANTITY_MISMATCH"
            )

        elif quantity_match_count > 1:
            processing_result = (
                "FAIL_MULTIPLE_BOM_CANDIDATES"
            )
            failure_codes.append(
                "FAIL_MULTIPLE_BOM_CANDIDATES"
            )

        else:
            selected_post_row = (
                post_quantity.iloc[0]
            )

            pre_exists = not pre_quantity.empty

            attribution_found, audit_evidence = (
                line_has_upload_attribution(
                    selected_post_row,
                    uploader
                )
            )
            
            if not pre_exists and attribution_found:

                processing_result = (
                    "PASS_CREATED"
                )

            elif pre_exists and attribution_found:

                processing_result = (
                    "PASS_MODIFIED"
                )

            elif pre_exists:

                processing_result = (
                    "PASS_PRESENT_UNCHANGED"
                )

            else:

                processing_result = (
                    "FAIL_UPLOAD_ATTRIBUTION"
                )

                failure_codes.append(
                    "FAIL_UPLOAD_ATTRIBUTION"
                )

        parent_key = bom_row["_parent_key"]

        pre_parent_count = (
            pre_parent_counts.get(
                parent_key,
                0
            )
        )

        bom_sheet_parent_count = (
            bom_sheet_parent_counts.get(
                parent_key,
                0
            )
        )

        post_parent_count = (
            post_parent_counts.get(
                parent_key,
                0
            )
        )

        parent_existed_in_pre = (
            pre_parent_count > 0
        )

        if parent_existed_in_pre:

            parent_count_rule = (
                "EXISTING_PARENT_PRE_EQUALS_POST"
            )

            expected_parent_count = (
                pre_parent_count
            )

        else:

            parent_count_rule = (
                "NEW_PARENT_BOM_SHEET_EQUALS_POST"
            )

            expected_parent_count = (
                bom_sheet_parent_count
            )

        actual_parent_count = (
            post_parent_count
        )

        parent_count_matches = (
            expected_parent_count
            == actual_parent_count
        )

        if not parent_count_matches:
            failure_codes.append(
                "FAIL_PARENT_COUNT_MISMATCH"
            )
        
        overall_result = (
            "FAIL"
            if failure_codes
            else "PASS_WITH_WARNING"
            if warning_codes
            else "PASS"
        )

        result = {
            "Source Row Number":
                bom_row["Source Row Number"],

            "Parent Item Number":
                bom_row["Parent Item Number"],

            "Child Item Number":
                bom_row["Child Item Number"],

            "Position":
                bom_row["Position"],

            "Expected Quantity":
                bom_row["Quantity"],

            "Actual Quantity":
                (
                    selected_post_row["Quantity"]
                    if selected_post_row is not None
                    else None
                ),

            "Expected Parent Key":
                bom_row["_parent_key"],

            "Expected Child Key":
                bom_row["_child_key"],

            "Expected Position Key":
                bom_row["_position_key"],

            "Actual Parent Key":
                (
                    selected_post_row["_parent_key"]
                    if selected_post_row is not None
                    else None
                ),

            "Actual Child Key":
                (
                    selected_post_row["_child_key"]
                    if selected_post_row is not None
                    else None
                ),

            "Actual Position Key":
                (
                    selected_post_row["_position_key"]
                    if selected_post_row is not None
                    else None
                ),

            "Primary Candidate Count":
                primary_count,

            "Quantity Match Count":
                quantity_match_count,

            "Parent Existed In PRE":
                parent_existed_in_pre,

            "PRE Parent Line Count":
                pre_parent_count,

            "BOM Sheet Parent Row Count":
                bom_sheet_parent_count,

            "POST Parent Line Count":
                post_parent_count,

            "Parent Count Rule":
                parent_count_rule,

            "Expected Parent Count":
                expected_parent_count,

            "Actual Parent Count":
                actual_parent_count,

            "Parent Count Matches":
                parent_count_matches,

            "Upload Attribution Found":
                (
                    attribution_found
                    if selected_post_row is not None
                    else False
                ),

            "Upload Attribution Evidence":
                (
                    audit_evidence
                    if selected_post_row is not None
                    else ""
                ),

            "BlueStar BOM RecId":
                (
                    selected_post_row[
                        "BlueStar BOM RecId"
                    ]
                    if selected_post_row is not None
                    else None
                ),

            "Processing Result":
                processing_result,

            "Failure Codes":
                "; ".join(
                    dict.fromkeys(failure_codes)
                ),

            "Warning Codes":
                "; ".join(
                    dict.fromkeys(warning_codes)
                ),

            "Overall Result":
                overall_result,
        }

        results.append(result)

    bom_results_df = pd.DataFrame(
        results
    )

    # -------------------------------------------------------------------------
    # Unexpected post-load lines
    # -------------------------------------------------------------------------

    expected_keys = set(
        zip(
            prepared_bom_sheet["_parent_key"],
            prepared_bom_sheet["_child_key"],
            prepared_bom_sheet["_position_key"],
        )
    )

    unexpected_rows = []

    if not prepared_post.empty:

        uploaded_parent_post_rows = prepared_post.loc[
            prepared_post["_parent_key"].isin(
                uploaded_parent_keys
            )
        ]

        for _, post_row in uploaded_parent_post_rows.iterrows():

            post_key = (
                post_row["_parent_key"],
                post_row["_child_key"],
                post_row["_position_key"],
            )

            if post_key in expected_keys:
                continue

            pre_matching_lines = prepared_pre.loc[
                prepared_pre["_parent_key"].eq(
                    post_row["_parent_key"]
                )
                & prepared_pre["_child_key"].eq(
                    post_row["_child_key"]
                )
                & prepared_pre["_position_key"].eq(
                    post_row["_position_key"]
                )
            ] if not prepared_pre.empty else pd.DataFrame()

            pre_line_exists = not pre_matching_lines.empty

            pre_line_unchanged = False

            if pre_line_exists:
                post_quantity = post_row["_actual_quantity"]

                pre_line_unchanged = pre_matching_lines[
                    "_actual_quantity"
                ].apply(
                    lambda pre_quantity: quantities_match(
                        pre_quantity,
                        post_quantity,
                        tolerance
                    )
                ).any()

            if pre_line_unchanged:
                continue

            attribution_found, audit_evidence = (
                line_has_upload_attribution(
                    post_row,
                    uploader
                )
            )

            unexpected_rows.append(
                {
                    "Source Row Number": None,

                    "Parent Item Number":
                        post_row["Parent Item Number"],

                    "Child Item Number":
                        post_row["Child Item Number"],

                    "Position":
                        post_row["Position"],

                    "Expected Quantity": None,

                    "Actual Quantity":
                        post_row["Quantity"],

                    "Expected Parent Key":
                        None,

                    "Expected Child Key":
                        None,

                    "Expected Position Key":
                        None,

                    "Actual Parent Key":
                        post_row["_parent_key"],

                    "Actual Child Key":
                        post_row["_child_key"],

                    "Actual Position Key":
                        post_row["_position_key"],

                    "Primary Candidate Count": None,

                    "Quantity Match Count": None,

                    "Parent Existed In PRE":
                        (
                            pre_parent_counts.get(
                                post_row["_parent_key"],
                                0
                            )
                            > 0
                        ),

                    "PRE Parent Line Count":
                        pre_parent_counts.get(
                            post_row["_parent_key"],
                            0
                        ),

                    "BOM Sheet Parent Row Count":
                        bom_sheet_parent_counts.get(
                            post_row["_parent_key"],
                            0
                        ),

                    "POST Parent Line Count":
                        post_parent_counts.get(
                            post_row["_parent_key"],
                            0
                        ),

                    "Parent Count Rule":
                        (
                            "EXISTING_PARENT_PRE_EQUALS_POST"
                            if pre_parent_counts.get(
                                post_row["_parent_key"],
                                0
                            ) > 0
                            else "NEW_PARENT_BOM_SHEET_EQUALS_POST"
                        ),

                    "Expected Parent Count":
                        expected_parent_counts.get(
                            post_row["_parent_key"],
                            0
                        ),

                    "Actual Parent Count":
                        post_parent_counts.get(
                            post_row["_parent_key"],
                            0
                        ),

                    "Parent Count Matches":
                        (
                            expected_parent_counts.get(
                                post_row["_parent_key"],
                                0
                            )
                            == post_parent_counts.get(
                                post_row["_parent_key"],
                                0
                            )
                        ),

                    "Upload Attribution Found":
                        attribution_found,

                    "Upload Attribution Evidence":
                        audit_evidence,

                    "BlueStar BOM RecId":
                        post_row["BlueStar BOM RecId"],

                    "Processing Result":
                        "FAIL_UNEXPECTED_BOM_LINE",

                    "Failure Codes":
                        "FAIL_UNEXPECTED_BOM_LINE",

                    "Warning Codes": "",

                    "Overall Result": "FAIL",
                }
            )


    if unexpected_rows:
        bom_results_df = pd.concat(
            [
                bom_results_df,
                pd.DataFrame(unexpected_rows),
            ],
            ignore_index=True
        )

    # -------------------------------------------------------------------------
    # Protected BOM validation
    # -------------------------------------------------------------------------

    protected_bom_results_df = (
        validate_protected_boms(
            protected_parent_keys,
            prepared_pre,
            prepared_post
        )
    )

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------

    matched_mask = ~bom_results_df[
        "Processing Result"
    ].isin(
        [
            "FAIL_MISSING_BOM_LINE",
            "FAIL_QUANTITY_MISMATCH",
            "FAIL_MULTIPLE_BOM_CANDIDATES",
            "FAIL_UNEXPECTED_BOM_LINE",
        ]
    )

    summary_data = {
        "Metric": [
            "Expected BOM Sheet Rows",
            "Matched Rows",
            "Created Rows",
            "Modified Rows",
            "Present Unchanged Rows",
            "Missing Rows",
            "Quantity Mismatch Rows",
            "Duplicate Match Rows",
            "Unexpected Rows",
            "Parents Expected",
            "Parent Structures Changed",
            "Unique BOM Parents With Errors",
            "Parents With Missing Lines",
            "Parents With Unexpected Lines",
            "Parents With Quantity Mismatches",
            "Parents With Duplicate Matches",
            "Protected BOMs Checked",
            "Protected BOM Failures",
            "Passed Result Rows",
            "Failed Result Rows",
        ],
        "Count": [
            len(prepared_bom_sheet),

            int(matched_mask.sum()),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq("PASS_CREATED").sum()
            ),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq("PASS_MODIFIED").sum()
            ),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq(
                    "PASS_PRESENT_UNCHANGED"
                ).sum()
            ),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq(
                    "FAIL_MISSING_BOM_LINE"
                ).sum()
            ),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq(
                    "FAIL_QUANTITY_MISMATCH"
                ).sum()
            ),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq(
                    "FAIL_MULTIPLE_BOM_CANDIDATES"
                ).sum()
            ),

            int(
                bom_results_df[
                    "Processing Result"
                ].eq(
                    "FAIL_UNEXPECTED_BOM_LINE"
                ).sum()
            ),

            len(uploaded_parent_keys),

            sum(
                expected_parent_counts.get(
                    parent_key,
                    0
                )
                != actual_parent_counts.get(
                    parent_key,
                    0
                )
                for parent_key
                in uploaded_parent_keys
            ),
            bom_results_df.loc[
                bom_results_df["Overall Result"].eq(
                    "FAIL"
                ),
                "Parent Item Number"
            ].nunique(),

            bom_results_df.loc[
                bom_results_df["Failure Codes"]
                .str.contains(
                    "FAIL_MISSING_BOM_LINE",
                    na=False
                ),
                "Parent Item Number"
            ].nunique(),

            bom_results_df.loc[
                bom_results_df["Failure Codes"]
                .str.contains(
                    "FAIL_UNEXPECTED_BOM_LINE",
                    na=False
                ),
                "Parent Item Number"
            ].nunique(),

            bom_results_df.loc[
                bom_results_df["Failure Codes"]
                .str.contains(
                    "FAIL_QUANTITY_MISMATCH",
                    na=False
                ),
                "Parent Item Number"
            ].nunique(),

            bom_results_df.loc[
                bom_results_df["Failure Codes"]
                .str.contains(
                    "FAIL_MULTIPLE_BOM_CANDIDATES",
                    na=False
                ),
                "Parent Item Number"
            ].nunique(),

            len(
                protected_bom_results_df
            ),

            int(
                protected_bom_results_df[
                    "Overall Result"
                ].eq("FAIL").sum()
            )
            if not protected_bom_results_df.empty
            else 0,

            int(
                bom_results_df[
                    "Overall Result"
                ].isin(
                    [
                        "PASS",
                        "PASS_WITH_WARNING",
                    ]
                ).sum()
            ),

            int(
                bom_results_df[
                    "Overall Result"
                ].eq("FAIL").sum()
            ),
        ],
    }

    bom_summary_df = pd.DataFrame(
        summary_data
    )

    return (
        bom_results_df,
        protected_bom_results_df,
        bom_summary_df,
    )