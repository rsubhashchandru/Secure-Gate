"""
SecureGate – FastAPI Application
Production-grade API for PHI de-identification.
Serves redacted PDFs + structured PHI JSON metadata.
"""

import io
import json
import logging
import uuid
import asyncio
from functools import partial
from typing import Dict, List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel

from backend.config import settings, get_safety_threshold, set_safety_threshold
from backend.redactor import redact_pdf, CUDA_AVAILABLE, GPU_NAME
from backend.audit import AuditRecord
from backend.biobert_engine import get_biobert_engine

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("securegate.api")

# ── FastAPI app ──────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store for audit trails & redacted PDFs ─────
# (In production, swap for Redis or a database.)
_audit_store: Dict[str, AuditRecord] = {}
_pdf_store: Dict[str, bytes] = {}
_phi_metadata_store: Dict[str, List[Dict]] = {}


# ── Health-check ─────────────────────────────────────────

@app.get("/api/health")
async def health():
    biobert = get_biobert_engine()
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "cuda_available": CUDA_AVAILABLE,
        "gpu_name": GPU_NAME,
        "custom_model_available": biobert.is_available,
    }


# ── Upload & process ────────────────────────────────────

@app.post("/api/deidentify")
async def deidentify(file: UploadFile = File(...), engine: str = "standard"):
    """
    Upload a PDF → detect PHI → irreversibly redact → return audit JSON.

    Query parameter `engine`:
      - "standard"       → Presidio + OpenBioNER ensemble (default)
      - "custom_biobert" → Fine-tuned BioBERT model

    If confidence < threshold the response carries status=LOCKED and no
    download will be possible.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    if engine not in ("standard", "custom_biobert"):
        raise HTTPException(status_code=400, detail="engine must be 'standard' or 'custom_biobert'.")

    # Validate custom model availability
    if engine == "custom_biobert":
        biobert = get_biobert_engine()
        if not biobert.is_available:
            raise HTTPException(
                status_code=400,
                detail="Custom BioBERT model not trained yet. Run training pipeline first.",
            )

    # Read entirely into memory (zero-disk policy)
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    logger.info("Received '%s' (%d bytes)", file.filename, len(pdf_bytes))

    try:
        # Run CPU/GPU-bound redaction in a thread pool so the async
        # event loop is not blocked (prevents proxy timeouts).
        loop = asyncio.get_event_loop()
        redacted_bytes, audit, phi_metadata = await loop.run_in_executor(
            None, partial(redact_pdf, pdf_bytes, filename=file.filename, engine_mode=engine)
        )
    except Exception as e:
        logger.exception("Processing failed for '%s'", file.filename)
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

    # Always store results — redaction is physically applied regardless
    # of confidence.  The gate only controls auto-download.
    _audit_store[audit.audit_id] = audit
    _pdf_store[audit.audit_id] = redacted_bytes
    _phi_metadata_store[audit.audit_id] = phi_metadata

    return JSONResponse(content={
        "audit_id": audit.audit_id,
        "document_name": audit.document_name,
        "status": audit.safety_status,
        "ensemble_mean_confidence": audit.ensemble_mean_confidence,
        "total_entities_detected": audit.total_entities_detected,
        "total_entities_masked": audit.total_entities_masked,
        "total_entities_kept": audit.total_entities_kept,
        "pages_processed": audit.pages_processed,
        "ocr_used": audit.ocr_used,
        "processing_time_ms": audit.processing_time_ms,
        "gpu_accelerated": CUDA_AVAILABLE,
        "engine_used": engine,
        "message": (
            "Document de-identified successfully. Ready for download."
            if audit.safety_status == "UNLOCKED"
            else "Confidence below safety threshold. Download is LOCKED. Manual review required."
        ),
    })


# ── Download redacted PDF ───────────────────────────────

@app.get("/api/download/{audit_id}")
async def download(audit_id: str):
    """Stream the in-memory redacted PDF. Only works if status is UNLOCKED."""
    audit = _audit_store.get(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit ID not found.")

    if audit.safety_status != "UNLOCKED":
        raise HTTPException(
            status_code=403,
            detail="Download LOCKED – confidence below safety threshold.",
        )

    pdf_data = _pdf_store.get(audit_id)
    if pdf_data is None:
        raise HTTPException(status_code=404, detail="Redacted PDF not available.")

    safe_name = f"redacted_{audit.document_name}"
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )


# ── Full audit trail ───────────────────────────────────

@app.get("/api/audit/{audit_id}")
async def get_audit(audit_id: str):
    """Return the full anonymization audit trail for a processed document."""
    audit = _audit_store.get(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit ID not found.")
    return audit.model_dump()


# ── PHI metadata JSON ──────────────────────────────────

@app.get("/api/phi-metadata/{audit_id}")
async def get_phi_metadata(audit_id: str):
    """
    Return structured PHI JSON metadata for a processed document.
    Contains: entity_type, original_text, confidence_score,
    page_number, bounding_box for every detection.
    """
    audit = _audit_store.get(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit ID not found.")

    metadata = _phi_metadata_store.get(audit_id, [])
    return {
        "audit_id": audit_id,
        "document_name": audit.document_name,
        "timestamp": audit.timestamp,
        "safety_status": audit.safety_status,
        "ensemble_mean_confidence": audit.ensemble_mean_confidence,
        "gpu_accelerated": CUDA_AVAILABLE,
        "detections": metadata,
    }


@app.get("/api/phi-metadata/{audit_id}/download")
async def download_phi_metadata(audit_id: str):
    """Download PHI metadata as a JSON file."""
    audit = _audit_store.get(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit ID not found.")

    metadata = _phi_metadata_store.get(audit_id, [])
    payload = {
        "audit_id": audit_id,
        "document_name": audit.document_name,
        "timestamp": audit.timestamp,
        "safety_status": audit.safety_status,
        "ensemble_mean_confidence": audit.ensemble_mean_confidence,
        "total_entities_detected": audit.total_entities_detected,
        "total_entities_masked": audit.total_entities_masked,
        "total_entities_kept": audit.total_entities_kept,
        "pages_processed": audit.pages_processed,
        "ocr_used": audit.ocr_used,
        "gpu_accelerated": CUDA_AVAILABLE,
        "detections": metadata,
    }
    json_bytes = json.dumps(payload, indent=2).encode("utf-8")
    safe_name = f"phi_metadata_{audit.document_name.replace('.pdf', '')}.json"

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )


# ── List all audits (dashboard) ─────────────────────────

@app.get("/api/audits")
async def list_audits():
    """Return summary of all processed documents."""
    summaries = []
    for aid, audit in _audit_store.items():
        summaries.append({
            "audit_id": aid,
            "document_name": audit.document_name,
            "status": audit.safety_status,
            "ensemble_mean_confidence": audit.ensemble_mean_confidence,
            "total_entities_detected": audit.total_entities_detected,
            "total_entities_masked": audit.total_entities_masked,
            "processing_time_ms": audit.processing_time_ms,
            "timestamp": audit.timestamp,
        })
    return summaries


# ── Manual Review & Unlock ──────────────────────────────

@app.post("/api/review/{audit_id}")
async def review_unlock(audit_id: str):
    """
    Human-in-the-loop: manually unlock a LOCKED document after review.
    This marks the audit as REVIEWED_UNLOCKED so the download becomes available.
    """
    audit = _audit_store.get(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit ID not found.")
    if audit.safety_status == "UNLOCKED":
        return {"message": "Document is already UNLOCKED.", "status": audit.safety_status}

    # Mark as reviewed and unlocked
    audit.safety_status = "UNLOCKED"
    logger.info(
        "Manual review UNLOCK: audit_id=%s, doc=%s",
        audit_id, audit.document_name,
    )
    return {
        "audit_id": audit_id,
        "status": "UNLOCKED",
        "message": "Document manually unlocked after human review.",
    }


# ── Admin: Safety Threshold ─────────────────────────────

class ThresholdUpdate(BaseModel):
    threshold: float


@app.get("/api/settings/threshold")
async def get_threshold():
    """Return the current safety threshold."""
    return {"threshold": get_safety_threshold()}


@app.patch("/api/settings/threshold")
async def update_threshold(body: ThresholdUpdate):
    """
    Adjust the safety threshold at runtime (admin tool for testing).
    Range: 0.0 – 1.0.
    """
    new_val = set_safety_threshold(body.threshold)
    logger.info("Safety threshold updated to %.4f", new_val)
    return {"threshold": new_val, "message": f"Threshold set to {new_val:.4f}"}


# ── Custom Model Status & Report ────────────────────────

@app.get("/api/model/status")
async def model_status():
    """Return status of both detection engines."""
    biobert = get_biobert_engine()
    report = biobert.get_training_report() if biobert.is_available else None

    return {
        "standard_engine": {
            "available": True,
            "name": "Presidio + OpenBioNER Ensemble",
            "description": "Rule-based + spaCy NER with Indian Optimization Layer",
        },
        "custom_engine": {
            "available": biobert.is_available,
            "name": "Cognitva Custom BioBERT",
            "description": "Fine-tuned dmis-lab/biobert-v1.1 on Indian medical reports",
            "loaded": biobert._loaded,
            "training_report": {
                "eval_f1": report.get("eval_metrics", {}).get("eval_f1", 0) if report else 0,
                "eval_precision": report.get("eval_metrics", {}).get("eval_precision", 0) if report else 0,
                "eval_recall": report.get("eval_metrics", {}).get("eval_recall", 0) if report else 0,
                "train_sentences": report.get("train_sentences", 0) if report else 0,
                "eval_sentences": report.get("eval_sentences", 0) if report else 0,
                "epochs": report.get("epochs", 0) if report else 0,
                "base_model": report.get("base_model", "N/A") if report else "N/A",
            } if report else None,
        },
        "cuda_available": CUDA_AVAILABLE,
        "gpu_name": GPU_NAME,
    }
