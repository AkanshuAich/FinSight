"""Paths, versions and tunable thresholds. Every analysis records the versions below."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("FINSIGHT_DATA_DIR", ROOT / "data"))
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "finsight.duckdb"
KEYS_PATH = DATA_DIR / "dev_keys.json"  # dev only; production keys come from a KMS
SAMPLE_DIR = ROOT / "sample_data"

PIPELINE_VERSION = "p1"
RULES_VERSION = "r2"  # r2: food & dining, client payments, cheque-clearing and cash-machine credits, company payers
WEIGHTS_VERSION = "w0"
QUESTION_BANK_VERSION = "q1"

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".json"}

# Tier 3 decision policy
AUTO_MIN_P = 0.90
AUTO_MIN_MARGIN = 0.30
REVIEW_MIN_P = 0.60
KNN_DISAGREE_SIM = 0.60

# Detectors and flags (amounts in paise)
TRANSFER_MAX_DAYS = 1
REVERSAL_MAX_DAYS = 30
LOW_BALANCE_PAISE = 5_000_00
LARGE_CASH_PAISE = 2_00_000_00
ROUND_FIGURE_MIN_PAISE = 50_000_00
PRE_APPLICATION_DAYS = 30
UNEXPLAINED_CREDIT_PAISE = 10_000_00
