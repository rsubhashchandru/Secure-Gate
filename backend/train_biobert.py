"""
SecureGate – Phase 2: BioBERT Fine-Tuning for Indian PHI NER
=============================================================
Fine-tunes dmis-lab/biobert-v1.1 on the auto-labeled BIO dataset.

OOM-safe for NVIDIA RTX 3050 (6 GB VRAM):
  • per_device_train_batch_size = 4
  • gradient_accumulation_steps = 4  (effective batch = 16)
  • fp16 = True
  • max_length = 256

Usage:
    python -m backend.train_biobert                    # full training
    python -m backend.train_biobert --epochs 5         # custom epoch count
    python -m backend.train_biobert --eval_split 0.15  # 15% eval hold-out

Outputs → backend/custom_phi_model/
          ├── model files (pytorch_model.bin, config.json, …)
          ├── tokenizer files
          ├── label_map.json
          └── training_report.json
"""

import os
import json
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import numpy as np
import torch
from torch.utils.data import Dataset

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    TrainingArguments,
    Trainer,
    DataCollatorForTokenClassification,
    EarlyStoppingCallback,
)
from sklearn.metrics import classification_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("securegate.train_biobert")

# ── Paths ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "processed"
MODEL_OUT = ROOT / "backend" / "custom_phi_model"

# ── Constants ────────────────────────────────────────────
BASE_MODEL = "dmis-lab/biobert-v1.1"
MAX_LENGTH = 256
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ──────────────────────────────────────────────────────────
# Dataset
# ──────────────────────────────────────────────────────────

def load_bio_file(path: Path) -> List[List[Tuple[str, str]]]:
    """
    Load a BIO-tagged file.  Each sentence is a list of (token, label).
    Sentences are separated by blank lines.
    """
    sentences: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                if current:
                    sentences.append(current)
                    current = []
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                current.append((parts[0], parts[1]))

    if current:
        sentences.append(current)

    return sentences


def build_label_map(labels_path: Path) -> Tuple[Dict[str, int], Dict[int, str]]:
    """Build label↔id mappings from labels.txt."""
    with open(labels_path, "r", encoding="utf-8") as f:
        labels = [l.strip() for l in f if l.strip()]

    label2id = {label: idx for idx, label in enumerate(labels)}
    id2label = {idx: label for label, idx in label2id.items()}
    return label2id, id2label


class NERDataset(Dataset):
    """Token-classification dataset compatible with HuggingFace Trainer."""

    def __init__(
        self,
        sentences: List[List[Tuple[str, str]]],
        tokenizer,
        label2id: Dict[str, int],
        max_length: int = MAX_LENGTH,
    ):
        self.sentences = sentences
        self.tokenizer = tokenizer
        self.label2id = label2id
        self.max_length = max_length

    def __len__(self):
        return len(self.sentences)

    def __getitem__(self, idx):
        tokens = [t for t, _ in self.sentences[idx]]
        labels = [l for _, l in self.sentences[idx]]

        # Tokenize with word-level alignment
        encoding = self.tokenizer(
            tokens,
            is_split_into_words=True,
            truncation=True,
            max_length=self.max_length,
            padding=False,
            return_offsets_mapping=False,
        )

        word_ids = encoding.word_ids()
        label_ids = []
        prev_word_id = None

        for word_id in word_ids:
            if word_id is None:
                label_ids.append(-100)  # special tokens
            elif word_id != prev_word_id:
                # First sub-token of a word → use the word's label
                label_ids.append(self.label2id.get(labels[word_id], 0))
            else:
                # Subsequent sub-tokens → for I- continuation or -100
                orig_label = labels[word_id]
                if orig_label.startswith("B-"):
                    label_ids.append(self.label2id.get("I-" + orig_label[2:], 0))
                else:
                    label_ids.append(self.label2id.get(orig_label, 0))
            prev_word_id = word_id

        encoding["labels"] = label_ids
        return {k: torch.tensor(v) for k, v in encoding.items()}


# ──────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────

def compute_metrics(eval_pred, id2label: Dict[int, str]):
    """Compute token-level P/R/F1 ignoring -100 padding and O labels."""
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)

    true_labels = []
    pred_labels = []

    for i in range(labels.shape[0]):
        for j in range(labels.shape[1]):
            if labels[i][j] != -100:
                true_labels.append(id2label.get(labels[i][j], "O"))
                pred_labels.append(id2label.get(preds[i][j], "O"))

    # Filter out O for entity-level metrics
    entity_true = [l for l in true_labels if l != "O"]
    entity_pred = [pred_labels[i] for i, l in enumerate(true_labels) if l != "O"]

    if not entity_true:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0}

    report = classification_report(
        true_labels, pred_labels, output_dict=True, zero_division=0,
    )
    return {
        "precision": report["weighted avg"]["precision"],
        "recall": report["weighted avg"]["recall"],
        "f1": report["weighted avg"]["f1-score"],
        "accuracy": report.get("accuracy", 0.0),
    }


# ──────────────────────────────────────────────────────────
# Training
# ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BioBERT PHI NER training")
    parser.add_argument("--epochs", type=int, default=10, help="Training epochs")
    parser.add_argument("--lr", type=float, default=3e-5, help="Learning rate")
    parser.add_argument("--batch_size", type=int, default=4, help="Per-device batch size")
    parser.add_argument("--grad_accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--eval_split", type=float, default=0.15, help="Eval hold-out fraction")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    MODEL_OUT.mkdir(parents=True, exist_ok=True)

    logger.info("Device: %s", DEVICE)
    if DEVICE == "cuda":
        logger.info("GPU: %s (%.1f GB)", torch.cuda.get_device_name(0),
                     torch.cuda.get_device_properties(0).total_memory / 1e9)

    # ── Load data ──────────────────────────────────
    bio_path = DATA_DIR / "train.bio"
    labels_path = DATA_DIR / "labels.txt"

    if not bio_path.exists():
        logger.error("BIO file not found: %s\nRun `python -m backend.prepare_dataset` first.", bio_path)
        return

    sentences = load_bio_file(bio_path)
    label2id, id2label = build_label_map(labels_path)
    logger.info("Loaded %d sentences, %d label types", len(sentences), len(label2id))

    # ── Train/eval split ───────────────────────────
    np.random.seed(args.seed)
    indices = np.random.permutation(len(sentences))
    split_idx = int(len(sentences) * (1 - args.eval_split))
    train_sents = [sentences[i] for i in indices[:split_idx]]
    eval_sents = [sentences[i] for i in indices[split_idx:]]
    logger.info("Train: %d sentences | Eval: %d sentences", len(train_sents), len(eval_sents))

    # ── Tokenizer & model ──────────────────────────
    logger.info("Loading base model: %s", BASE_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForTokenClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(label2id),
        id2label=id2label,
        label2id=label2id,
    ).to(DEVICE)

    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info("Model parameters: %s (trainable: %s)",
                f"{sum(p.numel() for p in model.parameters()):,}",
                f"{trainable_params:,}")

    # ── Datasets ───────────────────────────────────
    train_dataset = NERDataset(train_sents, tokenizer, label2id)
    eval_dataset = NERDataset(eval_sents, tokenizer, label2id)
    data_collator = DataCollatorForTokenClassification(tokenizer)

    # ── Training arguments (OOM-safe for 6GB) ──────
    training_args = TrainingArguments(
        output_dir=str(MODEL_OUT / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size * 2,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        fp16=(DEVICE == "cuda"),
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        logging_dir=str(MODEL_OUT / "logs"),
        logging_steps=50,
        report_to="none",
        seed=args.seed,
        dataloader_num_workers=0,  # Windows compatibility
    )

    # ── Trainer ────────────────────────────────────
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
        processing_class=tokenizer,
        compute_metrics=lambda p: compute_metrics(p, id2label),
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )

    # ── Train ──────────────────────────────────────
    logger.info("Starting training…")
    train_result = trainer.train()
    logger.info("Training complete: %s", train_result.metrics)

    # ── Evaluate ───────────────────────────────────
    eval_metrics = trainer.evaluate()
    logger.info("Evaluation: %s", eval_metrics)

    # ── Full classification report ─────────────────
    preds_output = trainer.predict(eval_dataset)
    logits = preds_output.predictions
    label_ids = preds_output.label_ids
    preds = np.argmax(logits, axis=-1)

    true_flat, pred_flat = [], []
    for i in range(label_ids.shape[0]):
        for j in range(label_ids.shape[1]):
            if label_ids[i][j] != -100:
                true_flat.append(id2label.get(label_ids[i][j], "O"))
                pred_flat.append(id2label.get(preds[i][j], "O"))

    report_text = classification_report(true_flat, pred_flat, zero_division=0)
    report_dict = classification_report(true_flat, pred_flat, output_dict=True, zero_division=0)
    logger.info("\n%s", report_text)

    # ── Save model ─────────────────────────────────
    logger.info("Saving model to %s", MODEL_OUT)
    trainer.save_model(str(MODEL_OUT))
    tokenizer.save_pretrained(str(MODEL_OUT))

    # Save label map
    label_map_path = MODEL_OUT / "label_map.json"
    with open(label_map_path, "w") as f:
        json.dump({"label2id": label2id, "id2label": {str(k): v for k, v in id2label.items()}}, f, indent=2)

    # Save training report
    report_path = MODEL_OUT / "training_report.json"
    training_report = {
        "base_model": BASE_MODEL,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "grad_accumulation": args.grad_accum,
        "learning_rate": args.lr,
        "fp16": DEVICE == "cuda",
        "device": DEVICE,
        "gpu": torch.cuda.get_device_name(0) if DEVICE == "cuda" else "N/A",
        "train_sentences": len(train_sents),
        "eval_sentences": len(eval_sents),
        "total_labels": len(label2id),
        "train_metrics": train_result.metrics,
        "eval_metrics": eval_metrics,
        "classification_report": report_dict,
    }
    with open(report_path, "w") as f:
        json.dump(training_report, f, indent=2)

    logger.info("=" * 60)
    logger.info("Training pipeline complete!")
    logger.info("  Model saved to   : %s", MODEL_OUT)
    logger.info("  Eval F1          : %.4f", eval_metrics.get("eval_f1", 0))
    logger.info("  Eval Precision   : %.4f", eval_metrics.get("eval_precision", 0))
    logger.info("  Eval Recall      : %.4f", eval_metrics.get("eval_recall", 0))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
