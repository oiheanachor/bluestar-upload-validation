"""
BlueStar Validation - Mapping Definitions

Purpose:
    Convert Item Sheet text values into the values stored in BlueStar.

    These mappings are used during validation only.

    Do NOT hardcode any mappings elsewhere in the solution.
"""


# =============================================================================
# ITEM TYPE
# =============================================================================

ITEM_TYPE_MAP = {
    "Item": 0,
    "BOM": 1,
    "Formula": 2
}


# =============================================================================
# VARIANT TYPE
# =============================================================================

VARIANT_TYPE_MAP = {
    "No variant": 0,
    "Bluestar variant": 1,
    "CAD variant": 2,
    "Cad file variant": 6,
    "Ignore cad variants": 7
}


# =============================================================================
# MASTER VARIANT
# =============================================================================

MASTER_VARIANT_MAP = {
    "No": 0,
    "Yes": 1
}


# =============================================================================
# PHANTOM
# =============================================================================

PHANTOM_MAP = {
    "No": 0,
    "Yes": 1
}


# =============================================================================
# eCON MASTER
# =============================================================================

ECON_MASTER_MAP = {
    "No": 0,
    "Yes": 1
}


# =============================================================================
# MASTER CONFIGURATION
# =============================================================================

MASTER_CONFIGURATION_MAP = {
    "No": 0,
    "Yes": 1
}


# =============================================================================
# MANUAL WEIGHT
# =============================================================================

MANUAL_WEIGHT_MAP = {
    "No": 0,
    "Yes": 1
}


# =============================================================================
# STATUS NORMALIZATION
# =============================================================================

STATUS_MAP = {

    # Valid statuses

    "Approved": "Approved",

    "PreProduction": "PreProduction",
    "Pre-Production": "PreProduction",

    "Obsolete": "Obsolete",

    "Phaseout": "Phaseout",
    "PhaseOut": "Phaseout",

    # Invalid statuses

    "Design": "Design",

    "Checked": "DesignEnd",
    "DesignEnd": "DesignEnd",

    "Revised": "Revised",

    "Prototype": "Prototype",

    "Onhold": "Onhold",

    "concept": "concept",

    "notused": "notused",

    "Sparepartonly": "Sparepartonly"
}


# =============================================================================
# VALID STATUSES
# =============================================================================

VALID_STATUSES = {
    "Approved",
    "PreProduction",
    "Obsolete",
    "Phaseout"
}


# =============================================================================
# VALID AX TEMPLATES
# =============================================================================

VALID_AX_TEMPLATES = {
    "BatchTrackConfigProd",
    "BatchTrackConfigPur",
    "BatchTrackingPur",
    "BatchTrackingProd"
    "ConsigTrackPur",
    "NoTrackConfigPhan",
    "NoTrackConfigProd",
    "NoTrackConfigPur",
    "NoTrackingProd",
    "NoTrackingPur",
    "NoTrackPhan",
    "PriceAdders",
    "SerTrackConfigProd",
    "SerTrackConfigPur",
    "SerTrackProd",
    "SerTrackPur",
    "ServiceNoTrackConfig",
    "ServiceNoTrackPur"
}


def clean_text(value):
    """
    Standard normalization used before comparisons.
    """

    if value is None:
        return ""

    return str(value).strip()


def normalize_status(value):
    """
    Normalize status values.
    """

    value = clean_text(value)

    return STATUS_MAP.get(value, value)


def is_valid_status(value):
    """
    Returns True if status is allowed.
    """

    return normalize_status(value) in VALID_STATUSES


def is_valid_ax_template(value):
    """
    Returns True if AX template is approved.
    """

    value = clean_text(value)

    return value in VALID_AX_TEMPLATES
