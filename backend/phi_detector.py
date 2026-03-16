"""
SecureGate – PHI Detection Engine (Ensemble + Indian Optimization Layer)
Combines Microsoft Presidio with a medical-NER model to
distinguish clinical terms (KEEP) from identifiers (MASK).

Indian Optimization Layer:
  • 50 common Indian surnames deny-list (0.85 base score)
  • Aadhaar / PAN card regex patterns
  • Kinship Context Enhancer (S/O, D/O, W/O, C/O, Dr.)
  • Medical Shield Priority – BioNER MEDICAL_CONDITION overrides lower PHI
"""

import logging
import re
from typing import List, Dict, Tuple

from presidio_analyzer import (
    AnalyzerEngine,
    PatternRecognizer,
    Pattern,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpEngineProvider

from backend.config import settings

logger = logging.getLogger("securegate.phi_detector")

# ─── Medical term lists (lightweight OpenBioNER-v2 stand-in) ─────────
# In production, replace with a transformer model (e.g. HuggingFace
# d4data/biomedical-ner-all). For air-gapped deployments we ship curated
# gazetteers that cover ICD-10 diagnoses, RxNorm drugs, and CPT codes.

_DIAGNOSES: set = {
    "diabetes", "hypertension", "asthma", "copd", "pneumonia",
    "tuberculosis", "malaria", "hiv", "hepatitis", "cancer",
    "leukemia", "anemia", "epilepsy", "migraine", "arthritis",
    "osteoporosis", "alzheimer", "parkinson", "stroke", "sepsis",
    "bronchitis", "influenza", "dengue", "cholera", "typhoid",
    "cirrhosis", "pancreatitis", "meningitis", "encephalitis",
    "lymphoma", "melanoma", "sarcoma", "fibromyalgia", "lupus",
    "psoriasis", "eczema", "gout", "obesity", "hypothyroidism",
    "hyperthyroidism", "chronic kidney disease", "heart failure",
    "atrial fibrillation", "deep vein thrombosis", "pulmonary embolism",
    "type 1 diabetes", "type 2 diabetes", "gestational diabetes",
    "diabetic retinopathy", "diabetic neuropathy", "coronary artery disease",
    "myocardial infarction", "cerebrovascular accident", "rheumatoid arthritis",
    "multiple sclerosis", "amyotrophic lateral sclerosis",
}

_MEDICATIONS: set = {
    "metformin", "insulin", "lisinopril", "amlodipine", "atorvastatin",
    "omeprazole", "amoxicillin", "azithromycin", "ibuprofen", "aspirin",
    "paracetamol", "acetaminophen", "warfarin", "heparin", "clopidogrel",
    "prednisone", "dexamethasone", "salbutamol", "albuterol", "fluticasone",
    "ciprofloxacin", "doxycycline", "levothyroxine", "metoprolol",
    "losartan", "hydrochlorothiazide", "furosemide", "gabapentin",
    "sertraline", "fluoxetine", "escitalopram", "diazepam", "lorazepam",
    "morphine", "fentanyl", "tramadol", "codeine", "naproxen",
    "pantoprazole", "ranitidine", "metoclopramide", "ondansetron",
    "simvastatin", "rosuvastatin", "empagliflozin", "sitagliptin",
}

_PROCEDURES: set = {
    "mri", "ct scan", "x-ray", "ultrasound", "echocardiogram",
    "colonoscopy", "endoscopy", "biopsy", "surgery", "dialysis",
    "chemotherapy", "radiotherapy", "blood transfusion", "intubation",
    "ventilation", "catheterization", "angioplasty", "bypass",
    "transplant", "amputation", "appendectomy", "cholecystectomy",
    "hysterectomy", "mastectomy", "vasectomy", "c-section",
    "cesarean section", "laparoscopy", "arthroscopy", "bronchoscopy",
    "mammography", "electrocardiogram", "ekg", "ecg", "eeg",
    "lumbar puncture", "bone marrow biopsy", "pap smear",
    "blood test", "urine test", "covid test", "pcr test",
}

_GENDER_TERMS: set = {
    "male", "female", "man", "woman", "boy", "girl",
    "transgender", "non-binary", "nonbinary", "intersex",
    "m", "f",  # single-letter codes in structured records
}

# Age pattern: matches "age 45", "aged 72", "45 years old", "67 yo", "Age: 92"
_AGE_PATTERN = re.compile(
    r"""
    (?:age[d]?\s*[:=]?\s*(\d{1,3}))     |   # age 45 / aged 72 / Age: 92
    (?:(\d{1,3})\s*(?:years?\s*old|yo|y/o|yrs))  # 45 years old / 67 yo
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ─── Indian Optimization Layer ───────────────────────────────────────

# 50 common Indian surnames (deny-list for name detection)
_INDIAN_SURNAMES: set = {
    "sharma", "singh", "rao", "reddy", "patel", "kumar", "gupta", "joshi",
    "mehta", "shah", "verma", "mishra", "pandey", "trivedi", "iyer",
    "nair", "menon", "pillai", "mukherjee", "chatterjee", "banerjee",
    "dasgupta", "bose", "sen", "ghosh", "das", "dey", "roy", "chakraborty",
    "srinivasan", "krishnamurthy", "subramaniam", "venkatesh", "rajan",
    "sundaram", "naidu", "choudhury", "tiwari", "dubey", "yadav",
    "thakur", "saxena", "agarwal", "jain", "kaur", "chopra", "malhotra",
    "kapoor", "bhat", "hegde", "kulkarni",
}

# Kinship / honorific prefixes that strongly indicate a PERSON nearby
_KINSHIP_KEYWORDS = re.compile(
    r"\b(S/O|D/O|W/O|C/O|s/o|d/o|w/o|c/o|"
    r"Son\s+of|Daughter\s+of|Wife\s+of|Care\s+of|"
    r"Dr\.|Dr\b|Smt\.|Shri\.|Shri\b|Sri\.|Sri\b|Mr\.|Mrs\.|Ms\.)\b",
    re.IGNORECASE,
)

# Aadhaar: 12 digits with optional spaces/dashes
_AADHAAR_PATTERN = r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"

# PAN: AAAAA9999A (5 letters, 4 digits, 1 letter)
_PAN_PATTERN = r"\b[A-Z]{5}\d{4}[A-Z]\b"

# Indian phone: +91 / 0 prefix, 10 digits
_INDIAN_PHONE_PATTERN = r"(?:\+91[\s-]?|0)\d{10}\b"

# Indian PIN code (6 digits, first digit 1-9)
_INDIAN_PIN_PATTERN = r"\b[1-9]\d{5}\b"

# Medical facility keywords (KEEP, not MASK)
_MEDICAL_FACILITY_TERMS: set = {
    "hospital", "clinic", "medical center", "medical centre",
    "health center", "health centre", "nursing home", "dispensary",
    "polyclinic", "icu", "ot", "opd", "emergency", "pharmacy",
    "laboratory", "lab", "radiology", "pathology", "department",
    "ward", "casualty", "maternity", "pediatric", "orthopaedic",
    "orthopedic", "cardiology", "neurology", "oncology", "dermatology",
    "ophthalmology", "ent", "gynecology", "urology",
}


# ─── Custom Presidio Recognisers ────────────────────────────────────

class MedicalTermRecognizer(PatternRecognizer):
    """Flags medical terms so they are KEPT, not redacted."""

    MEDICAL_TERMS = _DIAGNOSES | _MEDICATIONS | _PROCEDURES

    def __init__(self, **kwargs):
        patterns = [
            Pattern(
                name="medical_term",
                regex=r"\b(" + "|".join(
                    re.escape(t) for t in sorted(self.MEDICAL_TERMS, key=len, reverse=True)
                ) + r")\b",
                score=0.95,
            )
        ]
        super().__init__(
            supported_entity="MEDICAL_CONDITION",
            name="medical_term_recognizer",
            supported_language="en",
            patterns=patterns,
            context=["diagnosis", "condition", "disease", "medication",
                      "drug", "prescription", "procedure", "treatment"],
        )


class GenderRecognizer(PatternRecognizer):
    """Detects gender references so we can KEEP them."""

    def __init__(self, **kwargs):
        patterns = [
            Pattern(
                name="gender_term",
                regex=r"\b(" + "|".join(re.escape(g) for g in _GENDER_TERMS) + r")\b",
                score=0.90,
            )
        ]
        super().__init__(
            supported_entity="GENDER",
            name="gender_recognizer",
            supported_language="en",
            patterns=patterns,
            context=["gender", "sex"],
        )


class AgeRecognizer(PatternRecognizer):
    """Detects age mentions – kept but aggregated if > 89."""

    def __init__(self, **kwargs):
        patterns = [
            Pattern(name="age_expr", regex=_AGE_PATTERN.pattern, score=0.90),
        ]
        super().__init__(
            supported_entity="AGE",
            name="age_recognizer",
            supported_language="en",
            patterns=patterns,
            context=["age", "years old", "yo"],
        )


class DeviceIdRecognizer(PatternRecognizer):
    """Detects medical device serial numbers / UDI patterns."""

    def __init__(self, **kwargs):
        patterns = [
            Pattern(
                name="device_udi",
                regex=r"\b\d{2}\-\d{5,}\b",
                score=0.60,
            ),
            Pattern(
                name="device_serial",
                regex=r"\b[A-Z]{2,3}\-?\d{6,}\b",
                score=0.55,
            ),
        ]
        super().__init__(
            supported_entity="DEVICE_ID",
            name="device_id_recognizer",
            supported_language="en",
            patterns=patterns,
            context=["device", "serial", "UDI", "implant"],
        )


class MedicalLicenseRecognizer(PatternRecognizer):
    """Detects medical record / license numbers."""

    def __init__(self, **kwargs):
        patterns = [
            Pattern(
                name="mrn",
                regex=r"\b(?:MRN|MR#|Medical Record)\s*[:#]?\s*\d{5,}\b",
                score=0.80,
            ),
            Pattern(
                name="npi",
                regex=r"\b(?:NPI)\s*[:#]?\s*\d{10}\b",
                score=0.85,
            ),
        ]
        super().__init__(
            supported_entity="MEDICAL_LICENSE",
            supported_language="en",
            patterns=patterns,
            context=["record", "license", "NPI", "MRN"],
        )


class CustomIndianRecognizer(PatternRecognizer):
    """
    Indian Optimization Layer recognizer:
      • 50 common Indian surnames as a deny-list (base score 0.85)
      • Aadhaar number detection (12-digit pattern)
      • PAN card detection (AAAAA9999A)
      • Indian phone numbers (+91 / 0-prefix)
    """

    def __init__(self, **kwargs):
        # Build surname pattern
        surname_regex = r"\b(" + "|".join(
            re.escape(s) for s in sorted(_INDIAN_SURNAMES, key=len, reverse=True)
        ) + r")\b"

        patterns = [
            Pattern(name="indian_surname", regex=surname_regex, score=0.85),
            Pattern(name="aadhaar", regex=_AADHAAR_PATTERN, score=0.90),
            Pattern(name="pan_card", regex=_PAN_PATTERN, score=0.90),
            Pattern(name="indian_phone", regex=_INDIAN_PHONE_PATTERN, score=0.80),
        ]
        super().__init__(
            supported_entity="PERSON",
            supported_language="en",
            patterns=patterns,
            context=["name", "patient", "s/o", "d/o", "w/o", "c/o",
                      "son of", "daughter of", "wife of", "shri", "smt"],
        )


class MedicalFacilityRecognizer(PatternRecognizer):
    """Recognizes medical facility terms so they are KEPT (not masked as LOCATION)."""

    def __init__(self, **kwargs):
        facility_regex = r"\b(" + "|".join(
            re.escape(t) for t in sorted(_MEDICAL_FACILITY_TERMS, key=len, reverse=True)
        ) + r")\b"
        patterns = [
            Pattern(name="medical_facility", regex=facility_regex, score=0.93),
        ]
        super().__init__(
            supported_entity="MEDICAL_CONDITION",
            supported_language="en",
            patterns=patterns,
            context=["hospital", "clinic", "medical", "health", "department"],
        )


class BroadSsnRecognizer(PatternRecognizer):
    """
    Catches ALL SSN-formatted numbers (XXX-XX-XXXX) regardless of SSA area
    validation.  Presidio's built-in UsSsnRecognizer rejects certain area
    numbers (e.g. 000, 666, 900-999) which is appropriate for financial
    systems but too permissive for PHI de-identification where ANY
    SSN-patterned number must be redacted.
    """

    def __init__(self, **kwargs):
        patterns = [
            Pattern(
                name="ssn_broad",
                regex=r"\b\d{3}[- ]\d{2}[- ]\d{4}\b",
                score=0.75,
            ),
        ]
        super().__init__(
            supported_entity="US_SSN",
            supported_language="en",
            patterns=patterns,
            context=["ssn", "social", "security", "ss#", "ss #"],
        )


# ─── Ensemble Engine ────────────────────────────────────────────────

class PHIDetectionEngine:
    """
    Ensemble PHI detector with Indian Optimization Layer:
      • Microsoft Presidio  – general PII / PHI recognition
      • Medical NER layer   – gazetteer + pattern recognisers for clinical terms
      • Indian recognizer   – surnames, Aadhaar, PAN, kinship context
      • Kinship Enhancer    – boosts PERSON confidence near S/O, D/O, Dr., etc.
      • Medical Shield      – BioNER MEDICAL_CONDITION overrides lower PHI flags
    Returns unified, deduplicated results with source attribution.
    """

    KINSHIP_BOOST = 0.15          # confidence boost for kinship-adjacent PERSON
    KINSHIP_WORD_WINDOW = 5       # words to look around for kinship keywords

    def __init__(self):
        logger.info("Initialising PHI Detection Engine (Indian Opt Layer) …")

        # Presidio NLP backend (spaCy)
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        )
        nlp_engine = provider.create_engine()

        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=["en"],
        )

        # Register custom recognisers
        self._analyzer.registry.add_recognizer(MedicalTermRecognizer())
        self._analyzer.registry.add_recognizer(GenderRecognizer())
        self._analyzer.registry.add_recognizer(AgeRecognizer())
        self._analyzer.registry.add_recognizer(DeviceIdRecognizer())
        self._analyzer.registry.add_recognizer(MedicalLicenseRecognizer())
        self._analyzer.registry.add_recognizer(CustomIndianRecognizer())
        self._analyzer.registry.add_recognizer(MedicalFacilityRecognizer())
        self._analyzer.registry.add_recognizer(BroadSsnRecognizer())

        logger.info("PHI Detection Engine ready (with Indian Opt Layer) ✓")

    # ──────────────────────────────────────────────────────

    def detect(self, text: str) -> List[Dict]:
        """
        Run ensemble detection on `text`.
        Returns a list of dicts with keys:
            entity_type, start, end, score, text, detected_by, action
        """
        if not text or not text.strip():
            return []

        # Run Presidio (includes all custom recognisers)
        raw_results: List[RecognizerResult] = self._analyzer.analyze(
            text=text,
            language=settings.PRESIDIO_LANGUAGE,
            score_threshold=settings.PRESIDIO_SCORE_THRESHOLD,
        )

        # Run supplementary medical NER pass (regex-based second sweep)
        bio_results = self._bio_ner_pass(text)

        # Merge & deduplicate
        merged = self._merge_results(raw_results, bio_results, text)

        # ── Kinship Context Enhancer ────────────────────
        merged = self._apply_kinship_boost(merged, text)

        # ── Medical Shield Priority ─────────────────────
        merged = self._apply_medical_shield(merged)

        # Classify action (MASK / KEEP / AGE_AGGREGATED)
        for entry in merged:
            entry["action"] = self._classify_action(entry, text)

        return merged

    # ──────────────────────────────────────────────────────

    def _apply_kinship_boost(self, detections: List[Dict], text: str) -> List[Dict]:
        """
        Kinship Context Enhancer:
        If S/O, D/O, W/O, C/O, Dr., Shri, Smt is within KINSHIP_WORD_WINDOW
        words of a detected PERSON, boost that entity's confidence by 0.15.
        """
        kinship_matches = list(_KINSHIP_KEYWORDS.finditer(text))
        if not kinship_matches:
            return detections

        # Build word-index mapping: char offset → word index
        words = text.split()
        word_starts = []
        pos = 0
        for w in words:
            idx = text.find(w, pos)
            word_starts.append(idx)
            pos = idx + len(w)

        def _char_to_word_idx(char_pos: int) -> int:
            for i, ws in enumerate(word_starts):
                if ws > char_pos:
                    return max(0, i - 1)
            return len(word_starts) - 1

        kinship_word_indices = [_char_to_word_idx(m.start()) for m in kinship_matches]

        for det in detections:
            if det["entity_type"] == "PERSON":
                det_word_idx = _char_to_word_idx(det["start"])
                for kw_idx in kinship_word_indices:
                    if abs(det_word_idx - kw_idx) <= self.KINSHIP_WORD_WINDOW:
                        old_score = det["score"]
                        det["score"] = min(1.0, det["score"] + self.KINSHIP_BOOST)
                        det["detected_by"] = "ensemble"
                        logger.debug(
                            "Kinship boost: '%s' %.3f → %.3f",
                            det["text"], old_score, det["score"],
                        )
                        break  # one boost per entity

        return detections

    # ──────────────────────────────────────────────────────

    def _apply_medical_shield(self, detections: List[Dict]) -> List[Dict]:
        """
        Medical Shield Priority:
        If OpenBioNER flags a span as MEDICAL_CONDITION / DIAGNOSIS / MEDICATION /
        PROCEDURE, it overrides any lower-confidence PHI flag on the same span.
        This ensures medical context is preserved.
        """
        medical_types = {"MEDICAL_CONDITION", "DIAGNOSIS", "MEDICATION", "PROCEDURE"}
        medical_spans = [
            d for d in detections if d["entity_type"] in medical_types
        ]

        if not medical_spans:
            return detections

        shielded: List[Dict] = []
        for det in detections:
            is_overridden = False
            if det["entity_type"] not in medical_types:
                for med in medical_spans:
                    # Check if the PHI detection overlaps with a medical span
                    if (det["start"] < med["end"] and det["end"] > med["start"]):
                        # Medical shield: medical entity wins
                        logger.debug(
                            "Medical shield: '%s' (%s, %.3f) overrides '%s' (%s, %.3f)",
                            med["text"], med["entity_type"], med["score"],
                            det["text"], det["entity_type"], det["score"],
                        )
                        is_overridden = True
                        break
            if not is_overridden:
                shielded.append(det)

        # Re-add medical spans that might have been merged out
        existing_starts = {(d["start"], d["end"]) for d in shielded}
        for med in medical_spans:
            if (med["start"], med["end"]) not in existing_starts:
                shielded.append(med)

        return shielded

    # ──────────────────────────────────────────────────────

    def _bio_ner_pass(self, text: str) -> List[Dict]:
        """Supplementary medical-term sweep (OpenBioNER-v2 stand-in)."""
        results = []
        text_lower = text.lower()

        def _find_whole_word(haystack: str, needle: str) -> List[int]:
            """Find all whole-word occurrences of needle in haystack."""
            positions = []
            start = 0
            while True:
                idx = haystack.find(needle, start)
                if idx == -1:
                    break
                # Check word boundaries
                before_ok = (idx == 0 or not haystack[idx - 1].isalnum())
                end_pos = idx + len(needle)
                after_ok = (end_pos >= len(haystack) or not haystack[end_pos].isalnum())
                if before_ok and after_ok:
                    positions.append(idx)
                start = idx + 1
            return positions

        # Diagnoses
        for term in _DIAGNOSES:
            for idx in _find_whole_word(text_lower, term):
                results.append({
                    "entity_type": "DIAGNOSIS",
                    "start": idx,
                    "end": idx + len(term),
                    "score": 0.92,
                    "text": text[idx:idx + len(term)],
                    "detected_by": "openbioner",
                })

        # Medications
        for term in _MEDICATIONS:
            for idx in _find_whole_word(text_lower, term):
                results.append({
                    "entity_type": "MEDICATION",
                    "start": idx,
                    "end": idx + len(term),
                    "score": 0.90,
                    "text": text[idx:idx + len(term)],
                    "detected_by": "openbioner",
                })

        # Procedures
        for term in _PROCEDURES:
            for idx in _find_whole_word(text_lower, term):
                results.append({
                    "entity_type": "PROCEDURE",
                    "start": idx,
                    "end": idx + len(term),
                    "score": 0.88,
                    "text": text[idx:idx + len(term)],
                    "detected_by": "openbioner",
                })

        # Medical facility terms
        for term in _MEDICAL_FACILITY_TERMS:
            for idx in _find_whole_word(text_lower, term):
                results.append({
                    "entity_type": "MEDICAL_CONDITION",
                    "start": idx,
                    "end": idx + len(term),
                    "score": 0.93,
                    "text": text[idx:idx + len(term)],
                    "detected_by": "openbioner",
                })

        return results

    # ──────────────────────────────────────────────────────

    def _merge_results(
        self,
        presidio: List[RecognizerResult],
        bio: List[Dict],
        text: str,
    ) -> List[Dict]:
        """Merge Presidio + BioNER results; deduplicate overlapping spans."""

        combined: List[Dict] = []

        for r in presidio:
            # ── Trim entity spans at newline boundaries ──
            # spaCy NER sometimes extends spans across lines (e.g.
            # "Veerabhadra Rao\nDOB" as a single PERSON).  Trim to
            # the first line so the entity makes sense.
            raw_text = text[r.start : r.end]
            if "\n" in raw_text:
                first_line = raw_text.split("\n")[0].rstrip()
                if first_line:
                    combined.append({
                        "entity_type": r.entity_type,
                        "start": r.start,
                        "end": r.start + len(first_line),
                        "score": r.score,
                        "text": first_line,
                        "detected_by": "presidio",
                    })
                    continue
            combined.append({
                "entity_type": r.entity_type,
                "start": r.start,
                "end": r.end,
                "score": r.score,
                "text": raw_text,
                "detected_by": "presidio",
            })

        for b in bio:
            combined.append(b)

        # Sort by start position, then by score descending
        combined.sort(key=lambda x: (x["start"], -x["score"]))

        # Remove overlaps – keep highest-score span, prefer medical entities.
        # When same entity_type and one span contains the other, prefer the
        # LONGER span (better coverage) and boost its score.
        medical_types = {"MEDICAL_CONDITION", "DIAGNOSIS", "MEDICATION", "PROCEDURE"}
        deduplicated: List[Dict] = []
        for entry in combined:
            overlaps = False
            for i, existing in enumerate(deduplicated):
                if entry["start"] < existing["end"] and entry["end"] > existing["start"]:
                    overlaps = True
                    # Medical Shield: medical entity always wins over non-medical
                    entry_is_medical = entry["entity_type"] in medical_types
                    existing_is_medical = existing["entity_type"] in medical_types

                    if entry_is_medical and not existing_is_medical:
                        deduplicated[i] = entry
                    elif not entry_is_medical and existing_is_medical:
                        pass  # keep existing medical
                    else:
                        # Same-type containment: prefer longer span
                        entry_len = entry["end"] - entry["start"]
                        existing_len = existing["end"] - existing["start"]
                        same_type = entry["entity_type"] == existing["entity_type"]

                        if same_type and entry_len > existing_len:
                            # Longer span wins; boost score to max of both
                            entry["score"] = max(entry["score"], existing["score"])
                            deduplicated[i] = entry
                        elif same_type and existing_len > entry_len:
                            # Existing is longer, boost its score
                            existing["score"] = max(entry["score"], existing["score"])
                        elif entry["score"] > existing["score"]:
                            deduplicated[i] = entry

                    # Mark ensemble if from different sources
                    if entry["detected_by"] != existing.get("detected_by"):
                        deduplicated[i]["detected_by"] = "ensemble"
                    break
            if not overlaps:
                deduplicated.append(entry)

        return deduplicated

    # ──────────────────────────────────────────────────────

    def _classify_action(self, entry: Dict, full_text: str) -> str:
        """Decide MASK / KEEP / AGE_AGGREGATED for each detection."""

        etype = entry["entity_type"]

        # Clinical entities → KEEP
        if etype in settings.KEEP_ENTITIES:
            if etype == "AGE":
                return self._handle_age(entry, full_text)
            return "KEPT"

        # HIPAA-listed entities → MASK
        if etype in settings.HIPAA_MASK_ENTITIES:
            return "MASKED"

        # Default: MASK anything Presidio flags that isn't in KEEP
        return "MASKED"

    # ──────────────────────────────────────────────────────

    @staticmethod
    def _handle_age(entry: Dict, full_text: str) -> str:
        """If age > 89, aggregate to 90+.  Otherwise KEEP as-is."""
        snippet = entry.get("text", "")
        numbers = re.findall(r"\d+", snippet)
        for n in numbers:
            if int(n) > settings.AGE_AGGREGATION_THRESHOLD:
                return "AGE_AGGREGATED"
        return "KEPT"


# ─── Module-level singleton ─────────────────────────────────────────
_engine: PHIDetectionEngine | None = None


def get_phi_engine() -> PHIDetectionEngine:
    global _engine
    if _engine is None:
        _engine = PHIDetectionEngine()
    return _engine
