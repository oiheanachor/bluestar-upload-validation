"""
validate_items.py

Validates the frozen Item Sheet against BlueStar PRE and POST snapshots.

Validation rules:

1. Match using:
       New Item Number
       New Variant Id
       Revision
       Minor Revision

2. Resolve multiple POST candidates progressively using:
       Status
       New Item Name
       AX Template
       ItemType
       Variant Type

3. Classify processing results:
       PASS_CREATED: Created during upload
       PASS_MODIFIED: Modified during upload
       PASS_PRESENT_UNCHANGED: Exists but not changed by upload
       FAIL_MISSING: No matching item found
       FAIL_MULTIPLE_MATCHES: Multiple unresolvable candidates
       FAIL_WRONG_VARIANT: Exists under different variant

4. Validate:
       Item exists after upload
       Status is allowed
       Name is populated
       AX Template is populated and valid
       Existing BOM ItemType remains BOM
       Created/changed/modified audit evidence matches uploader and upload window

5. Returns:
       item_results_df: One result row per Item Sheet row
       item_summary_df: Reconciliation summary with row counts

No files are written by this module.
The returned DataFrames will later be used by the report writer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from mapping import (
    ITEM_TYPE_MAP,
    VARIANT_TYPE_MAP,
    STATUS_MAP,
    VALID_STATUSES,
    VALID_AX_TEMPLATES,
)


# =============================================================================
# REQUIRED COLUMNS
# =============================================================================

ITEM_SHEET_REQUIRED_COLUMNS = [
    "New Item Number",
    "New Variant Id",
    "Revision",
    "Minor Revision",
    "Status",
    "New Item Name",
    "AX Template",
    "ItemType",
    "Variant Type",
]

SNAPSHOT_REQUIRED_COLUMNS = [
    "New Item Number",
    "New Variant Id",
    "Revision",
    "Minor Revision",
    "New Item Name",
    "Status",
    "AX Template",
    "ItemType",
    "Variant Type",
    "BlueStar Object RecId",
]


# =============================================================================
# NORMALIZATION
# =============================================================================

def normalize_text(value: Any) -> str:
    """
    Normalize general text for comparison.

    Comparison is:
        - null-safe
        - whitespace-trimmed
        - case-insensitive
    """

    if value is None or pd.isna(value):
        return ""

    return str(value).strip().casefold()


def normalize_identifier(value: Any) -> str:
    """
    Normalize identifiers while preserving their meaningful characters.

    Examples:
        00123  -> 00123
        33A    -> 33A
        61.2   -> 61.2
        NULL   -> empty string

    Integer-like floating values produced by Excel are normalized:
        1.0 -> 1
        0.0 -> 0
    """

    if value is None or pd.isna(value):
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def normalize_status(value: Any) -> str:
    """
    Normalize lifecycle statuses using STATUS_MAP.

    Examples:
        Pre-Production -> preproduction
        PreProduction  -> preproduction
        PhaseOut       -> phaseout
    """

    if value is None or pd.isna(value):
        return ""

    text_value = str(value).strip()

    if not text_value:
        return ""

    normalized_status_map = {
        str(key).strip().casefold(): str(mapped).strip().casefold()
        for key, mapped in STATUS_MAP.items()
    }

    canonical_value = normalized_status_map.get(
        text_value.casefold(),
        text_value
    )

    return canonical_value.casefold()


def normalize_item_type(value: Any) -> int | None:
    """
    Normalize ItemType to numeric ID.

    Handles:
        "Item" -> 0
        "BOM" -> 1
        "Formula" -> 2
        "item" (lowercase) -> 0
        "1" (string) -> 1
        "1.0" (float string) -> 1
        NULL/NaN -> None
    """
    if value is None or pd.isna(value):
        return None

    text = str(value).strip().casefold()

    if not text:
        return None

    # Try direct lookup (handles case-insensitive text)
    for key, numeric_id in ITEM_TYPE_MAP.items():
        if key.casefold() == text:
            return numeric_id

    # Try numeric conversion (handles "1", "1.0", etc.)
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def normalize_variant_type(value: Any) -> int | None:
    """
    Normalize VariantType to numeric ID.

    Handles:
        "Item" -> 0
        "Color" -> 1
        "Size" -> 2
        "item" (lowercase) -> 0
        "1" (string) -> 1
        "1.0" (float string) -> 1
        NULL/NaN -> None
    """
    if value is None or pd.isna(value):
        return None

    text = str(value).strip().casefold()

    if not text:
        return None

    # Try direct lookup (handles case-insensitive text)
    for key, numeric_id in VARIANT_TYPE_MAP.items():
        if key.casefold() == text:
            return numeric_id

    # Try numeric conversion (handles "1", "1.0", etc.)
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def normalize_datetime(value: Any) -> pd.Timestamp:
    """
    Convert a value to a UTC-aware pandas Timestamp.

    Invalid or blank values return NaT.
    """

    if value is None or pd.isna(value):
        return pd.NaT

    return pd.to_datetime(
        value,
        errors="coerce",
        utc=True
    )


# =============================================================================
# DATAFRAME CHECKS
# =============================================================================

def validate_required_columns(
    dataframe: pd.DataFrame,
    required_columns: list[str],
    dataset_name: str
) -> None:
    """
    Confirm that all required columns are present.
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


def prepare_item_sheet(
    item_sheet_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Prepare and validate the Item Sheet.
    """

    validate_required_columns(
        item_sheet_df,
        ITEM_SHEET_REQUIRED_COLUMNS,
        "Item Sheet"
    )

    prepared = item_sheet_df.copy()

    prepared.insert(
        0,
        "Source Row Number",
        range(2, len(prepared) + 2)
    )

    prepared["_item_number_key"] = (
        prepared["New Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_variant_id_key"] = (
        prepared["New Variant Id"]
        .apply(normalize_identifier)
    )

    prepared["_revision_key"] = (
        prepared["Revision"]
        .apply(normalize_identifier)
    )

    prepared["_minor_revision_key"] = (
        prepared["Minor Revision"]
        .apply(normalize_identifier)
    )

    prepared["_expected_status"] = (
        prepared["Status"]
        .apply(normalize_status)
    )

    prepared["_expected_name"] = (
        prepared["New Item Name"]
        .apply(normalize_text)
    )

    prepared["_expected_ax_template"] = (
        prepared["AX Template"]
        .apply(normalize_text)
    )

    prepared["_expected_item_type"] = (
        prepared["ItemType"]
        .apply(normalize_item_type)
    )

    prepared["_expected_variant_type"] = (
        prepared["Variant Type"]
        .apply(normalize_variant_type)
    )

    if prepared["_item_number_key"].eq("").any():
        invalid_rows = prepared.loc[
            prepared["_item_number_key"].eq(""),
            "Source Row Number"
        ].tolist()

        raise ValueError(
            "Item Sheet contains blank New Item Number values "
            f"at Excel rows: {invalid_rows}"
        )

    duplicate_mask = prepared.duplicated(
        subset=[
            "_item_number_key",
            "_variant_id_key",
            "_revision_key",
            "_minor_revision_key",
        ],
        keep=False
    )

    if duplicate_mask.any():
        duplicate_rows = prepared.loc[
            duplicate_mask,
            [
                "Source Row Number",
                "New Item Number",
                "New Variant Id",
                "Revision",
                "Minor Revision",
            ]
        ]

        raise ValueError(
            "Item Sheet contains duplicate revision-level keys:\n"
            f"{duplicate_rows.to_string(index=False)}"
        )

    return prepared


def prepare_snapshot(
    snapshot_df: pd.DataFrame,
    snapshot_name: str
) -> pd.DataFrame:
    """
    Prepare a PRE or POST snapshot for matching.
    """

    if snapshot_df.empty:
        return snapshot_df.copy()

    validate_required_columns(
        snapshot_df,
        SNAPSHOT_REQUIRED_COLUMNS,
        snapshot_name
    )

    prepared = snapshot_df.copy()

    prepared["_item_number_key"] = (
        prepared["New Item Number"]
        .apply(normalize_identifier)
    )

    prepared["_variant_id_key"] = (
        prepared["New Variant Id"]
        .apply(normalize_identifier)
    )

    prepared["_revision_key"] = (
        prepared["Revision"]
        .apply(normalize_identifier)
    )

    prepared["_minor_revision_key"] = (
        prepared["Minor Revision"]
        .apply(normalize_identifier)
    )

    prepared["_actual_status"] = (
        prepared["Status"]
        .apply(normalize_status)
    )

    prepared["_actual_name"] = (
        prepared["New Item Name"]
        .apply(normalize_text)
    )

    prepared["_actual_ax_template"] = (
        prepared["AX Template"]
        .apply(normalize_text)
    )

    prepared["_actual_item_type"] = pd.to_numeric(
        prepared["ItemType"],
        errors="coerce"
    )

    prepared["_actual_variant_type"] = pd.to_numeric(
        prepared["Variant Type"],
        errors="coerce"
    )

    return prepared


# =============================================================================
# CANDIDATE MATCHING
# =============================================================================

def find_revision_candidates(
    item_row: pd.Series,
    snapshot_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Find all BlueStar candidates matching the Item Sheet revision-level key.
    """

    if snapshot_df.empty:
        return pd.DataFrame()

    matching_mask = (
        snapshot_df["_item_number_key"].eq(
            item_row["_item_number_key"]
        )
        & snapshot_df["_variant_id_key"].eq(
            item_row["_variant_id_key"]
        )
        & snapshot_df["_revision_key"].eq(
            item_row["_revision_key"]
        )
        & snapshot_df["_minor_revision_key"].eq(
            item_row["_minor_revision_key"]
        )
    )

    return snapshot_df.loc[matching_mask].copy()


def find_wrong_variant_candidates(
    item_row: pd.Series,
    snapshot_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Find BlueStar candidates with same Item Number and Revision
    but different Variant ID.
    """

    if snapshot_df.empty:
        return pd.DataFrame()

    matching_mask = (
        snapshot_df["_item_number_key"].eq(
            item_row["_item_number_key"]
        )
        & ~snapshot_df["_variant_id_key"].eq(
            item_row["_variant_id_key"]
        )
        & snapshot_df["_revision_key"].eq(
            item_row["_revision_key"]
        )
        & snapshot_df["_minor_revision_key"].eq(
            item_row["_minor_revision_key"]
        )
    )

    return snapshot_df.loc[matching_mask].copy()


def resolve_post_candidates(
    item_row: pd.Series,
    candidates: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    """
    Resolve multiple POST candidates progressively.

    Resolution order:
        1. Status
        2. New Item Name
        3. AX Template
        4. ItemType
        5. Variant Type

    A discriminator is applied only when:
        - multiple candidates remain
        - the Item Sheet expected value is populated
        - at least one candidate matches the expected value
    """

    remaining = candidates.copy()
    resolution_steps = []

    discriminator_fields = [
        (
            "Status",
            "_expected_status",
            "_actual_status"
        ),
        (
            "New Item Name",
            "_expected_name",
            "_actual_name"
        ),
        (
            "AX Template",
            "_expected_ax_template",
            "_actual_ax_template"
        ),
        (
            "ItemType",
            "_expected_item_type",
            "_actual_item_type"
        ),
        (
            "Variant Type",
            "_expected_variant_type",
            "_actual_variant_type"
        ),
    ]

    for (
        field_name,
        expected_column,
        actual_column
    ) in discriminator_fields:

        if len(remaining) <= 1:
            break

        expected_value = (
            item_row[expected_column]
            if expected_column in item_row.index
            else None
        )

        if expected_value is None or expected_value == "":
            continue

        matching_candidates = remaining.loc[
            remaining[actual_column].eq(expected_value)
        ]

        if not matching_candidates.empty:
            remaining = matching_candidates
            resolution_steps.append(field_name)

    return remaining, resolution_steps


# =============================================================================
# AUDIT ATTRIBUTION
# =============================================================================

def get_audit_classification(
    pre_exists: bool,
    post_row: pd.Series | None,
    uploader: str,
    upload_start: pd.Timestamp,
    upload_end: pd.Timestamp
) -> tuple[str, str]:
    """
    Classify whether an item was CREATED, MODIFIED, or PRESENT_UNCHANGED.

    Returns:
        (classification, evidence)

    Precedence:
        1. If no PRE and creation attributed to uploader: PASS_CREATED
        2. If PRE exists and modification attributed to uploader: PASS_MODIFIED
        3. If PRE exists, POST exists, but no attribution: PASS_PRESENT_UNCHANGED
        4. If no PRE, POST exists, but no creation attribution: NO_UPLOAD_ATTRIBUTION
    """

    if post_row is None:
        return "UNKNOWN", ""

    uploader_key = normalize_text(uploader)

    # Check for creation events
    creation_events = []
    for user_col, datetime_col in [
        ("System Created By", "System Created DateTime"),
        ("Created by", "Created date"),
    ]:
        if user_col not in post_row.index or datetime_col not in post_row.index:
            continue

        row_user = normalize_text(post_row.get(user_col, ""))
        row_datetime = normalize_datetime(post_row.get(datetime_col))

        if (row_user == uploader_key and
            not pd.isna(row_datetime) and
            upload_start <= row_datetime <= upload_end):
            creation_events.append("System Created" if "System" in user_col else "Created")

    # Check for modification events
    modification_events = []
    for user_col, datetime_col in [
        ("System Modified By", "System Modified DateTime"),
        ("Changed by", "Changed date"),
    ]:
        if user_col not in post_row.index or datetime_col not in post_row.index:
            continue

        row_user = normalize_text(post_row.get(user_col, ""))
        row_datetime = normalize_datetime(post_row.get(datetime_col))

        if (row_user == uploader_key and
            not pd.isna(row_datetime) and
            upload_start <= row_datetime <= upload_end):
            modification_events.append("System Modified" if "System" in user_col else "Changed")

    evidence = "; ".join(creation_events + modification_events)

    # Apply precedence rules
    if not pre_exists:
        if creation_events or modification_events:
            return "PASS_CREATED", evidence
        else:
            return "NO_UPLOAD_ATTRIBUTION", evidence

    if pre_exists:
        if modification_events:
            return "PASS_MODIFIED", evidence
        else:
            return "PASS_PRESENT_UNCHANGED", evidence

    return "UNKNOWN", evidence


# =============================================================================
# SAFE CONVERSIONS
# =============================================================================

def safe_int(value: Any) -> int | None:
    """
    Safely convert a value to int.
    Returns None if conversion fails.
    """
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


# =============================================================================
# FIELD VALIDATION
# =============================================================================

def is_allowed_status(value: Any) -> bool:
    """
    Validate lifecycle status against VALID_STATUSES.
    """

    normalized = normalize_status(value)
    valid_set = {
        normalize_status(v)
        for v in VALID_STATUSES
    }

    return normalized in valid_set


def is_valid_ax_template(value: Any) -> bool:
    """
    Validate the BlueStar AX template.
    """

    normalized = normalize_text(value)
    valid_set = {
        normalize_text(v)
        for v in VALID_AX_TEMPLATES
    }

    return normalized in valid_set


# =============================================================================
# MAIN VALIDATION
# =============================================================================

def validate_items(
    item_sheet_df: pd.DataFrame,
    pre_snapshot_df: pd.DataFrame,
    post_snapshot_df: pd.DataFrame,
    uploader: str,
    upload_start: str | datetime | pd.Timestamp,
    upload_end: str | datetime | pd.Timestamp | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Validate all Item Sheet rows.

    Parameters:
        item_sheet_df:
            Frozen Item Sheet.

        pre_snapshot_df:
            PRE item snapshot (may be empty for all-new uploads).

        post_snapshot_df:
            POST item snapshot.

        uploader:
            BlueStar uploader name as recorded in audit fields.

        upload_start:
            Upload start datetime.

        upload_end:
            Upload end boundary. If omitted, the latest
            Snapshot Captured UTC value from the POST snapshot is used.

    Returns:
        (item_results_df, item_summary_df)
    """

    if not uploader or not str(uploader).strip():
        raise ValueError(
            "Uploader must be provided."
        )

    upload_start_utc = normalize_datetime(upload_start)

    if pd.isna(upload_start_utc):
        raise ValueError(
            f"Invalid upload_start value: {upload_start}"
        )

    prepared_items = prepare_item_sheet(
        item_sheet_df
    )

    prepared_pre = prepare_snapshot(
        pre_snapshot_df,
        "PRE Item Snapshot"
    )

    prepared_post = prepare_snapshot(
        post_snapshot_df,
        "POST Item Snapshot"
    )

    if upload_end is None:
        if "Snapshot Captured UTC" not in prepared_post.columns:
            raise ValueError(
                "upload_end was not provided and the POST snapshot "
                "does not contain Snapshot Captured UTC."
            )

        post_capture_times = pd.to_datetime(
            prepared_post["Snapshot Captured UTC"],
            errors="coerce",
            utc=True
        ).dropna()

        if post_capture_times.empty:
            raise ValueError(
                "POST snapshot contains no valid Snapshot Captured UTC."
            )

        upload_end_utc = post_capture_times.max()

    else:
        upload_end_utc = normalize_datetime(upload_end)

    if pd.isna(upload_end_utc):
        raise ValueError(
            f"Invalid upload_end value: {upload_end}"
        )

    if upload_end_utc < upload_start_utc:
        raise ValueError(
            "upload_end cannot be earlier than upload_start."
        )

    results = []

    for _, item_row in prepared_items.iterrows():

        pre_candidates = find_revision_candidates(
            item_row,
            prepared_pre
        )

        post_candidates = find_revision_candidates(
            item_row,
            prepared_post
        )

        pre_exists = not pre_candidates.empty

        original_post_candidate_count = len(
            post_candidates
        )

        resolved_candidates, resolution_steps = (
            resolve_post_candidates(
                item_row,
                post_candidates
            )
        )

        resolved_candidate_count = len(
            resolved_candidates
        )

        selected_post_row = (
            resolved_candidates.iloc[0]
            if resolved_candidate_count == 1
            else None
        )

        expected_status_valid = is_allowed_status(
            item_row["Status"]
        )

        # Determine processing result
        processing_result = None
        failure_codes = []
        warning_codes = []

        if not expected_status_valid:
            failure_codes.append("FAIL_INVALID_UPLOAD_STATUS")

        if original_post_candidate_count == 0:
            # Check for wrong variant
            wrong_variant_candidates = find_wrong_variant_candidates(
                item_row,
                prepared_post
            )

            if not wrong_variant_candidates.empty:
                processing_result = "FAIL_WRONG_VARIANT"
                failure_codes.append("FAIL_WRONG_VARIANT")
            else:
                processing_result = "FAIL_MISSING"
                failure_codes.append("FAIL_MISSING_ITEM")

        elif resolved_candidate_count != 1:
            processing_result = "FAIL_MULTIPLE_CURRENT_CANDIDATES"
            failure_codes.append("FAIL_MULTIPLE_CURRENT_CANDIDATES")

        else:
            # Unique match found
            post_row = selected_post_row

            actual_status_valid = is_allowed_status(
                post_row["Status"]
            )

            if not actual_status_valid:
                failure_codes.append("BLOCK_INVALID_PRODUCTION_STATUS")

            status_match = (
                normalize_status(item_row["Status"]) ==
                normalize_status(post_row["Status"])
            )

            if (expected_status_valid and
                actual_status_valid and
                not status_match):
                warning_codes.append("WARN_STATUS_MISMATCH")

            name_populated = bool(
                normalize_text(post_row["New Item Name"])
            )

            if not name_populated:
                failure_codes.append("FAIL_NAME_BLANK")

            template_populated = bool(
                normalize_text(post_row["AX Template"])
            )

            if not template_populated:
                failure_codes.append("FAIL_AX_TEMPLATE_BLANK")

            elif not is_valid_ax_template(
                post_row["AX Template"]
            ):
                failure_codes.append("FAIL_AX_TEMPLATE_INVALID")

            pre_was_bom = False
            if not pre_candidates.empty:
                pre_item_type = safe_int(
                    pre_candidates["_actual_item_type"].iloc[0]
                )
                if pre_item_type == ITEM_TYPE_MAP["BOM"]:
                    pre_was_bom = True

            post_item_type = safe_int(post_row["_actual_item_type"])
            post_is_bom = post_item_type == ITEM_TYPE_MAP["BOM"]

            if pre_was_bom and not post_is_bom:
                failure_codes.append("BLOCK_ITEMTYPE_BOM_DOWNGRADED")

            # Validate ItemType and VariantType match
            expected_item_type = item_row["_expected_item_type"]
            expected_variant_type = item_row["_expected_variant_type"]

            if (expected_item_type is not None and
                post_item_type is not None and
                expected_item_type != post_item_type):
                failure_codes.append("FAIL_ITEMTYPE_MISMATCH")

            actual_variant_type = safe_int(
                post_row["_actual_variant_type"]
            )
            if (expected_variant_type is not None and
                actual_variant_type is not None and
                expected_variant_type != actual_variant_type):
                failure_codes.append("FAIL_VARIANTTYPE_MISMATCH")

            # Classify processing result
            audit_class, audit_evidence = get_audit_classification(
                pre_exists,
                post_row,
                uploader,
                upload_start_utc,
                upload_end_utc
            )

            # Fail if no upload attribution
            if audit_class == "NO_UPLOAD_ATTRIBUTION":
                failure_codes.append("FAIL_UPLOAD_ATTRIBUTION")

            if failure_codes:
                # Keep failure-based result
                if not processing_result:
                    processing_result = "FAIL"
            else:
                processing_result = audit_class

        overall_result = (
            "FAIL"
            if failure_codes
            else "PASS_WITH_WARNING"
            if warning_codes
            else "PASS"
        )

        result = {
            "Source Row Number": item_row["Source Row Number"],
            "New Item Number": item_row["New Item Number"],
            "New Variant Id": item_row["New Variant Id"],
            "Revision": item_row["Revision"],
            "Minor Revision": item_row["Minor Revision"],
            "Expected AX Template": item_row["AX Template"],
            "Actual AX Template": (
                selected_post_row["AX Template"]
                if selected_post_row is not None
                else None
            ),
            "Expected ItemType": item_row["ItemType"],
            "Actual ItemType": (
                selected_post_row["ItemType"]
                if selected_post_row is not None
                else None
            ),
            "Expected Variant Type": item_row["Variant Type"],
            "Actual Variant Type": (
                selected_post_row["Variant Type"]
                if selected_post_row is not None
                else None
            ),
            "BlueStar Object RecId": (
                selected_post_row["BlueStar Object RecId"]
                if selected_post_row is not None
                else None
            ),
            "Candidate Count": original_post_candidate_count,
            "Resolved Candidate Count": resolved_candidate_count,
            "Resolution Steps": "; ".join(resolution_steps),
            "Audit Evidence": (
                audit_evidence
                if selected_post_row is not None
                else ""
            ),
            "Processing Result": processing_result or "UNKNOWN",
            "Overall Result": overall_result,
            "Failure Codes": "; ".join(failure_codes),
            "Warning Codes": "; ".join(warning_codes),
        }

        results.append(result)

    results_df = pd.DataFrame(results)

    # Build summary with reconciliation control totals
    matched_count = len(
        results_df[
            ~results_df["Processing Result"].isin(
                [
                    "FAIL_MISSING",
                    "FAIL_WRONG_VARIANT",
                    "FAIL_MULTIPLE_CURRENT_CANDIDATES"
                ]
            )
        ]
    )

    summary_data = {
        "Metric": [
            "Expected Rows",
            "Matched Rows",
            "Created Rows",
            "Modified Rows",
            "Present Unchanged Rows",
            "Missing Rows",
            "Duplicate Match Rows",
            "Wrong Variant Rows",
            "Release Ready Items",
            "Release Blocked Items",
        ],
        "Count": [
            len(results_df),
            matched_count,
            len(results_df[results_df["Processing Result"] == "PASS_CREATED"]),
            len(results_df[results_df["Processing Result"] == "PASS_MODIFIED"]),
            len(results_df[results_df["Processing Result"] == "PASS_PRESENT_UNCHANGED"]),
            len(results_df[results_df["Processing Result"] == "FAIL_MISSING"]),
            len(results_df[results_df["Processing Result"] == "FAIL_MULTIPLE_CURRENT_CANDIDATES"]),
            len(results_df[results_df["Processing Result"] == "FAIL_WRONG_VARIANT"]),
            len(
                results_df[
                    ~results_df["Failure Codes"]
                    .str.contains(
                        (
                            "FAIL_NAME_BLANK|"
                            "FAIL_AX_TEMPLATE_BLANK|"
                            "FAIL_AX_TEMPLATE_INVALID|"
                            "FAIL_INVALID_UPLOAD_STATUS|"
                            "BLOCK_INVALID_PRODUCTION_STATUS|"
                            "BLOCK_ITEMTYPE_BOM_DOWNGRADED"
                        ),
                        na=False
                    )
                ]
            ),

            len(
                results_df[
                    results_df["Failure Codes"]
                    .str.contains(
                        (
                            "FAIL_NAME_BLANK|"
                            "FAIL_AX_TEMPLATE_BLANK|"
                            "FAIL_AX_TEMPLATE_INVALID|"
                            "FAIL_INVALID_UPLOAD_STATUS|"
                            "BLOCK_INVALID_PRODUCTION_STATUS|"
                            "BLOCK_ITEMTYPE_BOM_DOWNGRADED"
                        ),
                        na=False
                    )
                ]
            ),
        ],
    }

    summary_df = pd.DataFrame(summary_data)

    return results_df, summary_df
