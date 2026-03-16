"""
SecureGate – PDF Redaction Engine (Zero-Disk, Irreversible, CUDA-Accelerated)

Fixes the "output identical to input" bug by:
  1. Using **word-position mapping** instead of fragile page.search_for().
  2. For scanned pages: directly mapping EasyOCR bounding boxes to PDF
     coordinates for redaction (search_for can't find text in images).
  3. Calling apply_redactions(images=PDF_REDACT_IMAGE_PIXELS) so underlying
     image pixels are physically blanked.
  4. ALWAYS saving the redacted PDF (even when LOCKED) so Review-&-Unlock
     can serve it later.

GPU: Initialises EasyOCR with device='cuda' when NVIDIA RTX 3050 is detected.
RAM: Everything stays in io.BytesIO – zero disk writes.
"""

import io
import re
import time
import logging
from typing import List, Dict, Tuple, Optional

import fitz  # PyMuPDF

# ── CUDA detection ──────────────────────────────────────
try:
    import torch
    CUDA_AVAILABLE = torch.cuda.is_available()
    GPU_NAME = torch.cuda.get_device_name(0) if CUDA_AVAILABLE else None
except ImportError:
    CUDA_AVAILABLE = False
    GPU_NAME = None

from backend.config import settings, get_safety_threshold
from backend.audit import (
    DetectionEntry,
    AuditRecord,
    safe_snippet,
    build_audit_record,
)
from backend.phi_detector import get_phi_engine
from backend.biobert_engine import get_biobert_engine

logger = logging.getLogger("securegate.redactor")

if CUDA_AVAILABLE:
    logger.info("CUDA detected: %s – GPU-accelerated OCR enabled ✓", GPU_NAME)
else:
    logger.info("CUDA not available – OCR will run on CPU")


# ── Lazy-loaded EasyOCR reader (with CUDA) ──────────────
_ocr_reader = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en"], gpu=CUDA_AVAILABLE)
        logger.info("EasyOCR initialised (gpu=%s) ✓", CUDA_AVAILABLE)
    return _ocr_reader


# ── Constants ───────────────────────────────────────────
_OCR_DPI = 300
_AGE_NUM_RE = re.compile(r"\d+")

# PDF_REDACT_IMAGE_PIXELS blanks image pixels under redaction areas.
# Critical for scanned PDFs where "text" lives inside images.
_REDACT_IMAGE_MODE = getattr(fitz, "PDF_REDACT_IMAGE_PIXELS", 2)


def _aggregate_age_text(original: str) -> str:
    """Replace any age number > 89 with '90+' in the text."""
    def _replace(m):
        val = int(m.group())
        return "90+" if val > settings.AGE_AGGREGATION_THRESHOLD else m.group()
    return _AGE_NUM_RE.sub(_replace, original)


# ─── Word-position data structure ───────────────────────

class _WordSpan:
    """A word with its character span in the concatenated page text
    and its bounding rectangle in PDF coordinates."""
    __slots__ = ("text", "start", "end", "rect")

    def __init__(self, text: str, start: int, end: int, rect: fitz.Rect):
        self.text = text
        self.start = start
        self.end = end
        self.rect = rect


# ─── Core redaction pipeline ────────────────────────────

def redact_pdf(
    pdf_bytes: bytes,
    filename: str = "document.pdf",
    engine_mode: str = "standard",
) -> Tuple[bytes, AuditRecord, List[Dict]]:
    """
    Process a PDF entirely in-memory.

    Parameters
    ----------
    engine_mode : str
        "standard"       – Presidio + OpenBioNER ensemble (default)
        "custom_biobert" – Fine-tuned BioBERT model

    Returns
    -------
    (redacted_pdf_bytes, audit_record, phi_metadata)
        - **Always** returns redacted bytes.  Redactions are physically applied
          regardless of confidence.  The confidence gate only controls whether
          the download is automatically allowed (UNLOCKED vs LOCKED).
        - phi_metadata: structured list of dicts for the JSON export endpoint.
    """
    t0 = time.perf_counter()

    # ── Select engine ──────────────────────────────
    if engine_mode == "custom_biobert":
        biobert = get_biobert_engine()
        if not biobert.is_available:
            raise RuntimeError(
                "Custom BioBERT model not found.  Run "
                "`python -m backend.prepare_dataset` then "
                "`python -m backend.train_biobert` first."
            )
        biobert.load()
        detect_fn = biobert.detect
        engine_label = "custom_biobert"
    else:
        engine = get_phi_engine()
        detect_fn = engine.detect
        engine_label = "standard"

    all_detections: List[DetectionEntry] = []
    phi_metadata: List[Dict] = []
    ocr_used = False

    # Open PDF from memory (zero-disk)
    src_stream = io.BytesIO(pdf_bytes)
    doc = fitz.open(stream=src_stream, filetype="pdf")
    page_count = len(doc)

    logger.info(
        "Processing '%s' (%d pages) [CUDA=%s]",
        filename, page_count, CUDA_AVAILABLE,
    )

    for page_num in range(page_count):
        page = doc[page_num]

        # ── Extract text with word-level bounding boxes ─
        text, word_spans = _extract_page_words(page)
        is_ocr = False

        # If native text is too sparse → OCR fallback
        if len(text.strip()) < 20:
            logger.info(
                "Page %d: sparse text (%d chars), falling back to OCR",
                page_num + 1, len(text.strip()),
            )
            ocr_used = True
            is_ocr = True
            text, word_spans = _ocr_page_with_positions(page)

        if not text.strip():
            logger.info("Page %d: no extractable text, skipping", page_num + 1)
            continue

        # ── Detect PHI ──────────────────────────────────
        detections = detect_fn(text)
        logger.info(
            "Page %d: %d entities detected (engine=%s)", page_num + 1, len(detections), engine_label,
        )

        # ── Redact each entity ──────────────────────────
        for det in detections:
            action = det["action"]
            entity_text = det["text"]

            # Map entity span → PDF rectangles via word positions
            entity_rects = _find_entity_rects(det, word_spans)

            # Build union bounding box for metadata
            bbox = None
            if entity_rects:
                union = entity_rects[0]
                for r in entity_rects[1:]:
                    union = union | r
                bbox = [
                    round(union.x0, 2), round(union.y0, 2),
                    round(union.x1, 2), round(union.y1, 2),
                ]

            # Audit trail entry
            entry = DetectionEntry(
                entity_type=det["entity_type"],
                text_snippet=safe_snippet(entity_text),
                original_text=entity_text,
                start=det["start"],
                end=det["end"],
                score=det["score"],
                detected_by=det["detected_by"],
                action=action,
                page_number=page_num + 1,
                bounding_box=bbox,
            )
            all_detections.append(entry)

            # Structured PHI metadata for JSON export
            phi_metadata.append({
                "entity_type": det["entity_type"],
                "original_text": entity_text,
                "confidence_score": round(det["score"], 4),
                "page_number": page_num + 1,
                "bounding_box": bbox,
                "action": action,
                "detected_by": det["detected_by"],
            })

            # ── Physical redaction annotation ───────────
            if action == "MASKED":
                _apply_mask(page, det, entity_rects)

            elif action == "AGE_AGGREGATED":
                _apply_age_aggregation(page, entity_text, entity_rects)

        # ── Irreversible redaction ──────────────────────
        # images=PDF_REDACT_IMAGE_PIXELS physically blanks image pixels
        # under every redaction annotation.  This is the critical call
        # that ensures text AND image content are destroyed.
        page.apply_redactions(images=_REDACT_IMAGE_MODE)

    # ── Confidence gate ─────────────────────────────────
    masked_scores = [d.score for d in all_detections if d.action == "MASKED"]
    mean_conf = (
        sum(masked_scores) / len(masked_scores) if masked_scores else 1.0
    )
    threshold = get_safety_threshold()
    safety_status = "UNLOCKED" if mean_conf >= threshold else "LOCKED"

    elapsed_ms = (time.perf_counter() - t0) * 1000

    audit = build_audit_record(
        document_name=filename,
        detections=all_detections,
        mean_confidence=mean_conf,
        safety_status=safety_status,
        processing_time_ms=elapsed_ms,
        pages_processed=page_count,
        ocr_used=ocr_used,
    )

    # ── Always serialize redacted PDF to RAM ────────────
    # Redactions are physically applied regardless of confidence.
    # The gate only controls automatic download.  Storing always
    # ensures Review-&-Unlock can serve the file.
    out_buf = io.BytesIO()
    doc.save(out_buf, garbage=4, deflate=True, clean=True)
    doc.close()
    result_bytes = out_buf.getvalue()

    logger.info(
        "Redaction complete: %s → %d bytes (%s, confidence=%.4f, gpu=%s, engine=%s)",
        filename, len(result_bytes), safety_status, mean_conf, CUDA_AVAILABLE, engine_label,
    )
    return result_bytes, audit, phi_metadata


# ─── Text extraction (native) ──────────────────────────

def _extract_page_words(page: fitz.Page) -> Tuple[str, List[_WordSpan]]:
    """
    Extract text from a native-text PDF page using word-level positions.

    Uses ``page.get_text("words")`` which returns each word with its
    bounding box.  The full text is reconstructed by joining words with
    spaces and each word's character offset is tracked for entity mapping.
    """
    raw_words = page.get_text("words")
    # Each entry: (x0, y0, x1, y1, "word", block_no, line_no, word_no)

    spans: List[_WordSpan] = []
    parts: List[str] = []
    offset = 0

    for w in raw_words:
        word_text = w[4]
        spans.append(_WordSpan(
            text=word_text,
            start=offset,
            end=offset + len(word_text),
            rect=fitz.Rect(w[0], w[1], w[2], w[3]),
        ))
        parts.append(word_text)
        offset += len(word_text) + 1  # +1 for the joining space

    full_text = " ".join(parts)
    return full_text, spans


# ─── Text extraction (OCR with CUDA) ───────────────────

def _ocr_page_with_positions(page: fitz.Page) -> Tuple[str, List[_WordSpan]]:
    """
    Render page at 300 DPI, run EasyOCR (CUDA if available), and return
    text with word-level bounding boxes mapped to PDF coordinates.

    This solves the core bug: instead of calling ``page.search_for()``
    (which searches the nonexistent text layer of a scanned page), we
    directly use the OCR bounding boxes for redaction placement.
    """
    try:
        reader = _get_ocr_reader()
        pix = page.get_pixmap(dpi=_OCR_DPI)
        img_bytes = pix.tobytes("png")

        results = reader.readtext(img_bytes)

        # Scale factors: pixel coords → PDF points
        scale_x = page.rect.width / pix.width
        scale_y = page.rect.height / pix.height

        spans: List[_WordSpan] = []
        parts: List[str] = []
        offset = 0

        for bbox, text, _conf in results:
            # bbox = [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            full_rect = fitz.Rect(
                min(xs) * scale_x, min(ys) * scale_y,
                max(xs) * scale_x, max(ys) * scale_y,
            )

            # EasyOCR may return multi-word chunks; split into individual
            # words and distribute the bounding box proportionally.
            sub_words = text.split()
            if len(sub_words) <= 1:
                spans.append(_WordSpan(
                    text=text,
                    start=offset,
                    end=offset + len(text),
                    rect=full_rect,
                ))
                parts.append(text)
                offset += len(text) + 1
            else:
                total_chars = max(sum(len(w) for w in sub_words), 1)
                x_cursor = full_rect.x0
                for sw in sub_words:
                    frac = len(sw) / total_chars
                    sw_width = (full_rect.x1 - full_rect.x0) * frac
                    sw_rect = fitz.Rect(
                        x_cursor, full_rect.y0,
                        x_cursor + sw_width, full_rect.y1,
                    )
                    spans.append(_WordSpan(
                        text=sw,
                        start=offset,
                        end=offset + len(sw),
                        rect=sw_rect,
                    ))
                    parts.append(sw)
                    offset += len(sw) + 1
                    x_cursor += sw_width

        full_text = " ".join(parts)
        logger.info(
            "OCR extracted %d words (%d chars) [GPU=%s]",
            len(spans), len(full_text), CUDA_AVAILABLE,
        )
        return full_text, spans

    except Exception as e:
        logger.error("OCR failed: %s", e)
        return "", []


# ─── Entity → PDF rect mapping ─────────────────────────

def _find_entity_rects(
    det: Dict,
    word_spans: List[_WordSpan],
) -> List[fitz.Rect]:
    """
    Find PDF rectangles for a detected entity by matching the entity's
    character span (start..end) against the word-position map.
    """
    entity_start = det["start"]
    entity_end = det["end"]

    rects: List[fitz.Rect] = []
    for ws in word_spans:
        if ws.end > entity_start and ws.start < entity_end:
            rects.append(ws.rect)

    return rects


# ─── Physical redaction helpers ─────────────────────────

def _apply_mask(
    page: fitz.Page,
    det: Dict,
    entity_rects: List[fitz.Rect],
) -> None:
    """
    Add black-box redaction annotations for a MASKED entity.

    Primary path: use the computed rects from the word-position map.
    Fallback: use page.search_for() (text-layer search) as a last resort.
    """
    entity_text = det["text"]
    entity_type = det["entity_type"]

    if entity_rects:
        for rect in entity_rects:
            page.add_redact_annot(
                rect,
                text=f"[{entity_type}]",
                fontsize=settings.REDACT_FONT_SIZE,
                fill=settings.REDACT_FILL_COLOR,
                text_color=settings.REDACT_TEXT_COLOR,
            )
        logger.debug(
            "Redact (word-map, %d rects): '%s' → [%s]",
            len(entity_rects), entity_text[:20], entity_type,
        )
    else:
        # Fallback: search_for (works for native-text PDFs)
        quads = page.search_for(entity_text, quads=True)
        if not quads:
            for word in entity_text.split():
                if len(word) > 2:
                    quads.extend(page.search_for(word, quads=True))
        for quad in quads:
            page.add_redact_annot(
                quad,
                text=f"[{entity_type}]",
                fontsize=settings.REDACT_FONT_SIZE,
                fill=settings.REDACT_FILL_COLOR,
                text_color=settings.REDACT_TEXT_COLOR,
            )
        if quads:
            logger.debug(
                "Redact (search_for, %d quads): '%s' → [%s]",
                len(quads), entity_text[:20], entity_type,
            )
        else:
            logger.warning(
                "Could not locate '%s' (%s) on page – no redaction applied",
                entity_text[:30], entity_type,
            )


def _apply_age_aggregation(
    page: fitz.Page,
    entity_text: str,
    entity_rects: List[fitz.Rect],
) -> None:
    """Replace age > 89 with '90+' label."""
    replacement = _aggregate_age_text(entity_text)

    if entity_rects:
        for rect in entity_rects:
            page.add_redact_annot(
                rect,
                text=replacement,
                fontsize=settings.REDACT_FONT_SIZE,
                fill=(1, 1, 1),
                text_color=(0, 0, 0),
            )
    else:
        quads = page.search_for(entity_text, quads=True)
        for quad in quads:
            page.add_redact_annot(
                quad,
                text=replacement,
                fontsize=settings.REDACT_FONT_SIZE,
                fill=(1, 1, 1),
                text_color=(0, 0, 0),
            )
