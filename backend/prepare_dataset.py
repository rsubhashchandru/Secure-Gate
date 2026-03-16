"""
SecureGate – Phase 1: Data Preparation & Auto-Labeling Pipeline
===============================================================
1. OCR  : Extract text from 64 PDFs using EasyOCR (en + hi), CUDA-accelerated.
2. Label: Auto-label with existing Presidio+OpenBioNER ensemble ("silver standard").
3. BIO  : Convert to BIO format for BioBERT fine-tuning.
4. Shield: Force medical terms to O (Outside) to prevent accidental redaction.

Output  → data/processed/train.bio  (BIO-tagged, one token per line)
        → data/processed/labels.txt (label vocabulary)
        → data/processed/stats.json (dataset statistics)

Usage:
    python -m backend.prepare_dataset            # from project root
    python -m backend.prepare_dataset --limit 10 # process first N PDFs only
"""

import io
import os
import re
import json
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import fitz  # PyMuPDF

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("securegate.prepare_dataset")

# ── Paths ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw_pdf"
OUT_DIR = ROOT / "data" / "processed"

# ── CUDA ─────────────────────────────────────────────────
try:
    import torch
    CUDA = torch.cuda.is_available()
except ImportError:
    CUDA = False

# ── BIO label mapping ───────────────────────────────────
# Maps Presidio/ensemble entity_type → BIO label stem
ENTITY_TO_BIO: Dict[str, str] = {
    "PERSON":           "Name",
    "AGE":              "Age",
    "PHONE_NUMBER":     "Phone",
    "EMAIL_ADDRESS":    "Email",
    "LOCATION":         "Address",
    "DEVICE_ID":        "HospitalID",
    "MEDICAL_LICENSE":  "HospitalID",
    "DATE_TIME":        "Date",
    "US_SSN":           "HospitalID",
    "ORGANIZATION":     "Organization",
    "NRP":              "Organization",
    "URL":              "Other",
    "IP_ADDRESS":       "Other",
    "US_DRIVER_LICENSE":"HospitalID",
    "UK_NHS":           "HospitalID",
    "IBAN_CODE":        "HospitalID",
    "CREDIT_CARD":      "HospitalID",
    "US_PASSPORT":      "HospitalID",
    "US_BANK_NUMBER":   "HospitalID",
}

# Doctor-name heuristic context words
_DOCTOR_CONTEXT = re.compile(
    r"\b(Dr\.?|Doctor|Physician|Surgeon|Consultant|Attending|Referred\s+by|Reporting)\b",
    re.IGNORECASE,
)

# Entities classified as KEEP → force O label (Medical Preservation)
KEEP_ENTITY_TYPES = {
    "MEDICAL_CONDITION", "DIAGNOSIS", "MEDICATION", "PROCEDURE", "GENDER",
}

# All valid BIO labels
BIO_LABELS = [
    "O",
    "B-Name", "I-Name",
    "B-Age", "I-Age",
    "B-Phone", "I-Phone",
    "B-Email", "I-Email",
    "B-Address", "I-Address",
    "B-HospitalID", "I-HospitalID",
    "B-Date", "I-Date",
    "B-DoctorName", "I-DoctorName",
    "B-Organization", "I-Organization",
    "B-Other", "I-Other",
]


# ──────────────────────────────────────────────────────────
# OCR extraction
# ──────────────────────────────────────────────────────────

_ocr_reader = None

def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en", "hi"], gpu=CUDA)
        logger.info("EasyOCR initialised (en+hi, gpu=%s)", CUDA)
    return _ocr_reader


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF using native text layer + EasyOCR fallback."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning("Cannot open %s: %s", pdf_path.name, e)
        return ""
    pages_text: List[str] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        try:
            text = page.get_text("text").strip()
        except Exception:
            text = ""

        # Sparse native text → OCR fallback (use lower DPI to avoid OOM/hangs)
        if len(text) < 30:
            try:
                reader = _get_ocr_reader()
                pix = page.get_pixmap(dpi=150)  # lower DPI for stability
                img_bytes = pix.tobytes("png")
                results = reader.readtext(img_bytes, detail=1)
                text = " ".join(r[1] for r in results)
            except BaseException as e:
                logger.warning("OCR failed page %d of %s: %s", page_num + 1, pdf_path.name, e)

        if text.strip():
            pages_text.append(text.strip())

    doc.close()
    return "\n\n".join(pages_text)


# ──────────────────────────────────────────────────────────
# Auto-labeling with Presidio ensemble
# ──────────────────────────────────────────────────────────

def auto_label_text(text: str, engine) -> List[Dict]:
    """Run the existing Presidio+OpenBioNER ensemble and return detections."""
    return engine.detect(text)


def _is_doctor_context(text: str, start: int, window: int = 80) -> bool:
    """Check if a PERSON entity is near doctor-related context words."""
    left = max(0, start - window)
    context = text[left:start]
    return bool(_DOCTOR_CONTEXT.search(context))


# ──────────────────────────────────────────────────────────
# BIO conversion
# ──────────────────────────────────────────────────────────

def _simple_tokenize(text: str) -> List[Tuple[str, int, int]]:
    """
    Simple whitespace+punctuation tokenizer that tracks character offsets.
    Returns list of (token_text, char_start, char_end).
    """
    tokens = []
    for m in re.finditer(r"\S+", text):
        tokens.append((m.group(), m.start(), m.end()))
    return tokens


def convert_to_bio(
    text: str,
    detections: List[Dict],
) -> List[Tuple[str, str]]:
    """
    Convert text + entity detections to BIO-tagged token sequence.

    Medical Preservation: entities with type in KEEP_ENTITY_TYPES → O label.
    Doctor Name: PERSON entities near doctor context → DoctorName label.
    """
    tokens = _simple_tokenize(text)
    labels = ["O"] * len(tokens)

    # Sort detections by start offset for deterministic labeling
    sorted_dets = sorted(detections, key=lambda d: d["start"])

    for det in sorted_dets:
        etype = det["entity_type"]
        action = det.get("action", "MASKED")

        # Medical Preservation: medical entities → O
        if etype in KEEP_ENTITY_TYPES or action == "KEPT":
            continue

        # Map entity type to BIO stem
        bio_stem = ENTITY_TO_BIO.get(etype, "Other")

        # Doctor name heuristic
        if etype == "PERSON" and _is_doctor_context(text, det["start"]):
            bio_stem = "DoctorName"

        det_start = det["start"]
        det_end = det["end"]
        first_token = True

        for idx, (tok_text, tok_start, tok_end) in enumerate(tokens):
            # Check if token overlaps with the entity span
            if tok_end > det_start and tok_start < det_end:
                if first_token:
                    labels[idx] = f"B-{bio_stem}"
                    first_token = False
                else:
                    labels[idx] = f"I-{bio_stem}"

    return list(zip([t[0] for t in tokens], labels))


# ──────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SecureGate data preparation")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N PDFs (0=all)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Gather all PDFs
    pdf_files = sorted(RAW_DIR.glob("*.pdf"))
    if args.limit > 0:
        pdf_files = pdf_files[:args.limit]

    logger.info("Found %d PDFs in %s", len(pdf_files), RAW_DIR)

    # Lazy-load the Presidio engine
    from backend.phi_detector import get_phi_engine
    engine = get_phi_engine()

    all_bio_lines: List[str] = []
    stats = {
        "total_pdfs": len(pdf_files),
        "total_tokens": 0,
        "total_entities": 0,
        "label_counts": {},
        "per_file": [],
    }

    for i, pdf_path in enumerate(pdf_files):
        logger.info("[%d/%d] Processing: %s", i + 1, len(pdf_files), pdf_path.name)

        try:
            # Step 1: Extract text
            text = extract_text_from_pdf(pdf_path)
            if not text.strip():
                logger.warning("No text extracted from %s, skipping", pdf_path.name)
                continue

            # Step 2: Auto-label
            detections = auto_label_text(text, engine)

            # Step 3: Convert to BIO
            bio_tokens = convert_to_bio(text, detections)

            # Collect stats
            file_stats = {
                "filename": pdf_path.name,
                "chars": len(text),
                "tokens": len(bio_tokens),
                "entities": len([d for d in detections if d.get("action") == "MASKED"]),
            }
            stats["per_file"].append(file_stats)
            stats["total_tokens"] += len(bio_tokens)
            stats["total_entities"] += file_stats["entities"]

            for _, label in bio_tokens:
                stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1

            # Format: one token per line, blank line between chunks
            # Split long docs into ~150-token chunks so BioBERT (max 256 sub-tokens) sees all entities
            CHUNK_SIZE = 150
            for chunk_start in range(0, len(bio_tokens), CHUNK_SIZE):
                chunk = bio_tokens[chunk_start:chunk_start + CHUNK_SIZE]
                for token, label in chunk:
                    all_bio_lines.append(f"{token}\t{label}")
                all_bio_lines.append("")  # chunk separator

        except BaseException as e:
            logger.error("Failed on %s: %s", pdf_path.name, e)
            continue

    # ── Write outputs ────────────────────────────────────
    bio_path = OUT_DIR / "train.bio"
    with open(bio_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_bio_lines))
    logger.info("Wrote BIO file: %s (%d lines)", bio_path, len(all_bio_lines))

    labels_path = OUT_DIR / "labels.txt"
    with open(labels_path, "w", encoding="utf-8") as f:
        f.write("\n".join(BIO_LABELS))
    logger.info("Wrote labels: %s (%d labels)", labels_path, len(BIO_LABELS))

    stats_path = OUT_DIR / "stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    logger.info("Wrote stats: %s", stats_path)

    # Summary
    logger.info("=" * 60)
    logger.info("Dataset preparation complete!")
    logger.info("  PDFs processed : %d / %d", len(stats["per_file"]), len(pdf_files))
    logger.info("  Total tokens   : %d", stats["total_tokens"])
    logger.info("  Total entities : %d", stats["total_entities"])
    logger.info("  Label dist     : %s", json.dumps(stats["label_counts"], indent=2))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
