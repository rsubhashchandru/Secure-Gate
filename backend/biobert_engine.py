"""
SecureGate – Phase 3: Custom BioBERT PHI Detection Engine
==========================================================
Inference engine that loads the fine-tuned BioBERT model and runs
token-classification NER for PHI detection in Indian medical reports.

Designed for dual-engine architecture:
  • Standard   = Presidio + OpenBioNER ensemble (phi_detector.py)
  • Custom     = This BioBERT-based engine (biobert_engine.py)

Both engines produce the same output format:
  List[Dict] with keys: entity_type, start, end, score, text, detected_by, action

Zero-disk: model is loaded once at startup; all inference is in-memory.
GPU-first: fp16 inference on CUDA when available.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForTokenClassification

from backend.config import settings

logger = logging.getLogger("securegate.biobert_engine")

# ── Paths ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "backend" / "custom_phi_model"

# ── Device ───────────────────────────────────────────────
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ── BIO label → SecureGate entity_type mapping ───────────
BIO_TO_ENTITY: Dict[str, str] = {
    "Name":         "PERSON",
    "DoctorName":   "PERSON",
    "Age":          "AGE",
    "Phone":        "PHONE_NUMBER",
    "Email":        "EMAIL_ADDRESS",
    "Address":      "LOCATION",
    "HospitalID":   "DEVICE_ID",
    "Date":         "DATE_TIME",
    "Organization": "ORGANIZATION",
    "Other":        "DEVICE_ID",
}

# Medical terms that should always be KEPT (same as phi_detector)
KEEP_ENTITY_TYPES = {
    "MEDICAL_CONDITION", "DIAGNOSIS", "MEDICATION", "PROCEDURE", "GENDER", "AGE",
}

# Chunk overlap for long texts (in tokens)
MAX_LENGTH = 256
STRIDE = 64


class BioBERTEngine:
    """
    Custom fine-tuned BioBERT NER engine for Indian PHI detection.

    Produces output in the same format as PHIDetectionEngine.detect()
    so the redactor can work with either engine transparently.
    """

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._label2id: Dict[str, int] = {}
        self._id2label: Dict[int, str] = {}
        self._loaded = False

    @property
    def is_available(self) -> bool:
        """Check if the custom model exists on disk."""
        return (MODEL_DIR / "config.json").exists() and (MODEL_DIR / "label_map.json").exists()

    def load(self) -> bool:
        """Load the fine-tuned model into memory. Returns True on success."""
        if self._loaded:
            return True

        if not self.is_available:
            logger.warning("Custom BioBERT model not found at %s", MODEL_DIR)
            return False

        try:
            logger.info("Loading custom BioBERT model from %s …", MODEL_DIR)

            # Load label map
            with open(MODEL_DIR / "label_map.json", "r") as f:
                maps = json.load(f)
            self._label2id = maps["label2id"]
            self._id2label = {int(k): v for k, v in maps["id2label"].items()}

            # Load tokenizer & model
            self._tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
            self._model = AutoModelForTokenClassification.from_pretrained(str(MODEL_DIR))

            # Move to GPU with fp16 if available
            self._model.to(DEVICE)
            if DEVICE == "cuda":
                self._model.half()  # fp16 inference

            self._model.eval()
            self._loaded = True

            params = sum(p.numel() for p in self._model.parameters())
            logger.info(
                "BioBERT loaded: %s params, device=%s, fp16=%s ✓",
                f"{params:,}", DEVICE, DEVICE == "cuda",
            )
            return True

        except Exception as e:
            logger.error("Failed to load BioBERT model: %s", e)
            self._loaded = False
            return False

    def detect(self, text: str) -> List[Dict]:
        """
        Run BioBERT NER on text.

        Returns a list of dicts matching PHIDetectionEngine.detect() output:
            entity_type, start, end, score, text, detected_by, action
        """
        if not self._loaded:
            if not self.load():
                return []

        if not text or not text.strip():
            return []

        # Tokenize with word-level alignment
        tokens_info = self._tokenize_with_offsets(text)
        if not tokens_info:
            return []

        # Run model inference
        predictions = self._predict(tokens_info)

        # Convert BIO predictions to entity spans
        entities = self._bio_to_entities(predictions, text)

        # Classify actions
        for entity in entities:
            entity["action"] = self._classify_action(entity, text)

        return entities

    def _tokenize_with_offsets(self, text: str) -> List[Dict]:
        """
        Tokenize text and track word-level character offsets.
        Uses sliding window for long texts.
        """
        # Simple whitespace tokenization for word-level alignment
        words = []
        word_offsets = []
        for m in re.finditer(r"\S+", text):
            words.append(m.group())
            word_offsets.append((m.start(), m.end()))

        if not words:
            return []

        return [{"words": words, "offsets": word_offsets}]

    @torch.no_grad()
    def _predict(self, tokens_info: List[Dict]) -> List[Dict]:
        """Run model inference on tokenized chunks."""
        results = []

        for chunk in tokens_info:
            words = chunk["words"]
            offsets = chunk["offsets"]

            # Tokenize for model
            encoding = self._tokenizer(
                words,
                is_split_into_words=True,
                truncation=True,
                max_length=MAX_LENGTH,
                padding=True,
                return_tensors="pt",
            ).to(DEVICE)

            # Inference
            if DEVICE == "cuda":
                with torch.cuda.amp.autocast():
                    outputs = self._model(**encoding)
            else:
                outputs = self._model(**encoding)

            logits = outputs.logits[0]  # (seq_len, num_labels)
            probs = torch.softmax(logits.float(), dim=-1)
            pred_ids = torch.argmax(probs, dim=-1).cpu().numpy()
            pred_scores = probs.max(dim=-1).values.cpu().numpy()

            # Map sub-token predictions back to words
            word_ids = encoding.word_ids(batch_index=0)
            word_preds = {}

            for idx, word_id in enumerate(word_ids):
                if word_id is None:
                    continue
                if word_id not in word_preds:
                    word_preds[word_id] = {
                        "label_id": pred_ids[idx],
                        "label": self._id2label.get(int(pred_ids[idx]), "O"),
                        "score": float(pred_scores[idx]),
                    }

            # Build result for this chunk
            for word_idx, word in enumerate(words):
                pred = word_preds.get(word_idx, {"label": "O", "score": 1.0, "label_id": 0})
                results.append({
                    "word": word,
                    "char_start": offsets[word_idx][0],
                    "char_end": offsets[word_idx][1],
                    "label": pred["label"],
                    "score": pred["score"],
                })

        return results

    def _bio_to_entities(self, predictions: List[Dict], text: str) -> List[Dict]:
        """Convert BIO-tagged word predictions into entity spans."""
        entities: List[Dict] = []
        current_entity: Optional[Dict] = None

        for pred in predictions:
            label = pred["label"]

            if label.startswith("B-"):
                # Finalize previous entity
                if current_entity:
                    entities.append(current_entity)

                bio_stem = label[2:]
                entity_type = BIO_TO_ENTITY.get(bio_stem, "DEVICE_ID")

                current_entity = {
                    "entity_type": entity_type,
                    "bio_label": bio_stem,
                    "start": pred["char_start"],
                    "end": pred["char_end"],
                    "score": pred["score"],
                    "text": pred["word"],
                    "detected_by": "custom_biobert",
                    "word_scores": [pred["score"]],
                }

            elif label.startswith("I-") and current_entity:
                bio_stem = label[2:]
                if bio_stem == current_entity["bio_label"]:
                    # Extend current entity
                    current_entity["end"] = pred["char_end"]
                    current_entity["text"] = text[current_entity["start"]:pred["char_end"]]
                    current_entity["word_scores"].append(pred["score"])
                else:
                    # Different I- tag → finalize and start new
                    entities.append(current_entity)
                    entity_type = BIO_TO_ENTITY.get(bio_stem, "DEVICE_ID")
                    current_entity = {
                        "entity_type": entity_type,
                        "bio_label": bio_stem,
                        "start": pred["char_start"],
                        "end": pred["char_end"],
                        "score": pred["score"],
                        "text": pred["word"],
                        "detected_by": "custom_biobert",
                        "word_scores": [pred["score"]],
                    }
            else:
                # O label → finalize current entity
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None

        # Finalize last entity
        if current_entity:
            entities.append(current_entity)

        # Compute mean confidence per entity
        for entity in entities:
            scores = entity.pop("word_scores", [])
            entity.pop("bio_label", None)
            if scores:
                entity["score"] = round(float(np.mean(scores)), 4)

        return entities

    def _classify_action(self, entity: Dict, text: str) -> str:
        """Decide MASK / KEEP / AGE_AGGREGATED (same logic as phi_detector)."""
        etype = entity["entity_type"]

        if etype in settings.KEEP_ENTITIES:
            if etype == "AGE":
                numbers = re.findall(r"\d+", entity.get("text", ""))
                for n in numbers:
                    if int(n) > settings.AGE_AGGREGATION_THRESHOLD:
                        return "AGE_AGGREGATED"
                return "KEPT"
            return "KEPT"

        if etype in settings.HIPAA_MASK_ENTITIES:
            return "MASKED"

        return "MASKED"

    def get_training_report(self) -> Optional[Dict]:
        """Load and return the training report if available."""
        report_path = MODEL_DIR / "training_report.json"
        if report_path.exists():
            with open(report_path, "r") as f:
                return json.load(f)
        return None


# ── Module-level singleton ────────────────────────────────
_biobert_engine: Optional[BioBERTEngine] = None


def get_biobert_engine() -> BioBERTEngine:
    """Get or create the singleton BioBERT engine."""
    global _biobert_engine
    if _biobert_engine is None:
        _biobert_engine = BioBERTEngine()
    return _biobert_engine
