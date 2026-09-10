# config.py

DATABASE = "put your database details here"

ENVIRONMENTS = {
    "PROD": "",
    "UAT1": "",
    "UAT2": "",
    "UAT3": "",
    "SIT1": "",
    "SIT2": "",
    "SIT3": ""
}

DEFAULT_ENVIRONMENT = "PROD"

SNAPSHOT_FOLDER = "snapshots"
INPUT_FOLDER = "input"
OUTPUT_FOLDER = "output"
SQL_FOLDER = "sql"

REFRESH_WAIT_HOURS = 2

def get_schema(environment: str) -> str:
    env = environment.upper()

    if env not in ENVIRONMENTS:
        raise ValueError(
            f"Unknown environment: {environment}"
        )

    return ENVIRONMENTS[env]
