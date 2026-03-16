"""
SecureGate – Anonymization Audit Trail
Structured, per-document log that records which model caught which PHI.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("securegate.audit")


# ── Audit Models ─────────────────────────────────────────

class DetectionEntry(BaseModel):
    """Single PHI detection event."""
    entity_type: str
    text_snippet: str = Field(
        description="First 4 chars + '***' so we can audit without leaking PHI"
    )
    original_text: str = Field(
        default="",
        description="Full original text (kept in RAM only, for JSON metadata export)",
    )
    start: int
    end: int
    score: float
    detected_by: str = Field(description="presidio | openbioner | ensemble")
    action: str = Field(description="MASKED | KEPT | AGE_AGGREGATED")
    page_number: int = Field(default=0, description="1-indexed page number")
    bounding_box: Optional[List[float]] = Field(
        default=None,
        description="[x0, y0, x1, y1] in PDF points",
    )


class AuditRecord(BaseModel):
    """Full audit trail for one document."""
    audit_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    document_name: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_entities_detected: int = 0
    total_entities_masked: int = 0
    total_entities_kept: int = 0
    ensemble_mean_confidence: float = 0.0
    safety_status: str = "PENDING"  # UNLOCKED | LOCKED
    detections: List[DetectionEntry] = []
    processing_time_ms: float = 0.0
    pages_processed: int = 0
    ocr_used: bool = False


# ── Helper ───────────────────────────────────────────────

def safe_snippet(text: str, max_prefix: int = 4) -> str:
    """Return a non-leaking snippet: first `max_prefix` chars + ***."""
    if len(text) <= max_prefix:
        return "*" * len(text)
    return text[:max_prefix] + "***"


def build_audit_record(
    document_name: str,
    detections: List[DetectionEntry],
    mean_confidence: float,
    safety_status: str,
    processing_time_ms: float,
    pages_processed: int,
    ocr_used: bool,
) -> AuditRecord:
    masked = [d for d in detections if d.action == "MASKED"]
    kept = [d for d in detections if d.action in ("KEPT", "AGE_AGGREGATED")]

    record = AuditRecord(
        document_name=document_name,
        total_entities_detected=len(detections),
        total_entities_masked=len(masked),
        total_entities_kept=len(kept),
        ensemble_mean_confidence=round(mean_confidence, 4),
        safety_status=safety_status,
        detections=detections,
        processing_time_ms=round(processing_time_ms, 2),
        pages_processed=pages_processed,
        ocr_used=ocr_used,
    )

    logger.info(
        "AUDIT | doc=%s | entities=%d | masked=%d | kept=%d | confidence=%.4f | status=%s",
        document_name,
        record.total_entities_detected,
        record.total_entities_masked,
        record.total_entities_kept,
        record.ensemble_mean_confidence,
        record.safety_status,
    )
    for d in detections:
        logger.debug(
            "  ├─ %s | '%s' | score=%.3f | by=%s | action=%s",
            d.entity_type, d.text_snippet, d.score, d.detected_by, d.action,
        )

    return record
