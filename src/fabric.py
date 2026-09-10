"""
fabric.py

Purpose:
    Load SQL files and execute them against
    Microsoft Fabric SQL Endpoint.

Responsibilities:

    - Connect to Fabric
    - Load SQL files
    - Replace __SCHEMA__
    - Execute queries
    - Return Pandas DataFrames

No validation logic.
No snapshot logic.
"""

from pathlib import Path

import pandas as pd
import pyodbc

from config import get_schema


# =============================================================================
# FABRIC CONNECTION DETAILS
# =============================================================================

FABRIC_SERVER = (
    "put your server details here"
)

FABRIC_DATABASE = (
    "put your database details here"
)

FABRIC_USERNAME = (
    "firstname.lastname@rotork.com"
)

# =============================================================================
# CONNECTION
# =============================================================================

def get_connection():
    """
    Return Fabric SQL connection using ODBC Driver 17 and Azure AD authentication.
    
    Uses ActiveDirectoryInteractive which leverages Azure CLI cached credentials.
    """
    
    try:
        # Create connection string with ActiveDirectoryInteractive
        # This uses your Azure CLI login without needing to pass a token
        connection_string = (
            f"Driver={{ODBC Driver 17 for SQL Server}};"
            f"Server={FABRIC_SERVER};"
            f"Database={FABRIC_DATABASE};"
            f"Authentication=ActiveDirectoryInteractive;"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
        )
        
        # Connect with Azure AD interactive authentication
        conn = pyodbc.connect(connection_string)
        
        return conn
    
    except Exception as e:
        raise ConnectionError(
            f"Failed to connect to Fabric: {e}\n\n"
            f"Troubleshooting:\n"
            f"1. Verify you're logged in to Azure CLI: az account show\n"
            f"2. Ensure your Azure account has access to Fabric\n"
            f"3. Try logging in again: az login\n"
            f"4. Check your internet connection"
        )


def execute_query(
    sql_text: str
) -> pd.DataFrame:
    """
    Execute query against Fabric SQL Endpoint and return dataframe.
    """
    
    conn = get_connection()
    
    try:
        dataframe = pd.read_sql(
            sql_text,
            conn
        )
        return dataframe
    finally:
        conn.close()


# =============================================================================
# SQL FILES
# =============================================================================

def read_sql_file(
    sql_file_path: str
) -> str:
    """
    Read SQL file.
    """

    path = Path(sql_file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"SQL file not found: {path}"
        )

    return path.read_text(
        encoding="utf-8"
    )


def prepare_sql(
    sql_text: str,
    environment: str
) -> str:
    """
    Replace schema placeholder.
    """

    schema = get_schema(environment)

    return sql_text.replace(
        "__SCHEMA__",
        schema
    )


# =============================================================================
# EXECUTION
# =============================================================================

def execute_query(
    sql_text: str
) -> pd.DataFrame:
    """
    Execute query against Fabric SQL Endpoint and return dataframe.
    """
    
    conn = get_connection()
    
    try:
        dataframe = pd.read_sql(
            sql_text,
            conn
        )
        return dataframe
    finally:
        conn.close()


# =============================================================================
# GENERIC DATASET LOADER
# =============================================================================

def load_dataset(
    sql_file_path: str,
    environment: str
) -> pd.DataFrame:
    """
    Generic SQL loader.
    """

    sql_text = read_sql_file(
        sql_file_path
    )

    sql_text = prepare_sql(
        sql_text,
        environment
    )

    return execute_query(
        sql_text
    )


# =============================================================================
# ITEM DATASET
# =============================================================================

def load_item_dataset(
    environment: str
) -> pd.DataFrame:
    """
    Load item_dataset.sql
    """

    print(
        f"Loading Item Dataset ({environment})..."
    )

    return load_dataset(
        "sql/item_dataset.sql",
        environment
    )


# =============================================================================
# BOM DATASET
# =============================================================================

def load_bom_dataset(
    environment: str
) -> pd.DataFrame:
    """
    Load bom_dataset.sql
    """

    print(
        f"Loading BOM Dataset ({environment})..."
    )

    return load_dataset(
        "sql/bom_dataset.sql",
        environment
    )
