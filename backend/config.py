"""
SecureGate – Central Configuration
All tunables live here. No PHI is stored on disk.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── API ──────────────────────────────────────────────
    APP_NAME: str = "SecureGate PHI De-Identification Engine"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # ── Presidio ─────────────────────────────────────────
    PRESIDIO_LANGUAGE: str = "en"
    PRESIDIO_SCORE_THRESHOLD: float = 0.35

    # ── Confidence Gate ──────────────────────────────────
    SAFETY_THRESHOLD: float = 0.98

    # ── Safe Harbor – 18 HIPAA identifiers ───────────────
    # We KEEP: Gender, Age (aggregate >89 → 90+)
    # We MASK the remaining 16:
    HIPAA_MASK_ENTITIES: List[str] = [
        "PERSON",            # 1  Names
        "DATE_TIME",         # 2  Dates (except year)
        "PHONE_NUMBER",      # 3  Telephone numbers
        "EMAIL_ADDRESS",     # 4  Email addresses
        "US_SSN",            # 5  Social Security numbers
        "LOCATION",          # 6  Geographic data
        "IP_ADDRESS",        # 7  IP addresses
        "URL",               # 8  Web URLs
        "US_DRIVER_LICENSE", # 9  Driver license numbers
        "MEDICAL_LICENSE",   # 10 Medical record numbers
        "NRP",               # 11 Nationality / religion
        "IBAN_CODE",         # 12 Account numbers
        "CREDIT_CARD",       # 13 Credit-card numbers
        "US_PASSPORT",       # 14 Passport numbers
        "US_BANK_NUMBER",    # 15 Bank account numbers
        "DEVICE_ID",         # 16 Device identifiers
    ]

    # ── Entities to always KEEP (never redact) ───────────
    KEEP_ENTITIES: List[str] = [
        "DIAGNOSIS",
        "MEDICATION",
        "PROCEDURE",
        "MEDICAL_CONDITION",
        "GENDER",
        "AGE",
    ]

    # ── Redaction appearance ─────────────────────────────
    REDACT_FILL_COLOR: tuple = (0, 0, 0)  # black
    REDACT_TEXT_COLOR: tuple = (1, 1, 1)   # white label
    REDACT_FONT_SIZE: float = 8.0

    # ── Age aggregation ──────────────────────────────────
    AGE_AGGREGATION_THRESHOLD: int = 89

    # ── Logging ──────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    class Config:
        env_prefix = "SG_"


settings = Settings()

# ── Runtime-adjustable threshold ─────────────────────────
# The admin UI can lower the safety gate for testing.
# Stored outside the frozen Settings model.
_runtime_threshold: float = settings.SAFETY_THRESHOLD


def get_safety_threshold() -> float:
    return _runtime_threshold


def set_safety_threshold(value: float) -> float:
    global _runtime_threshold
    _runtime_threshold = max(0.0, min(1.0, value))
    return _runtime_threshold
