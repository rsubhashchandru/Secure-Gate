# SecureGate – PHI De-Identification Engine

> A production-grade PHI de-identification system built for **Cognitva.ai** to safely access government healthcare datasets.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Next.js 15 Frontend                      │
│  Upload Zone → Processing Status → Results Panel → Audit Trail  │
│            Tailwind CSS + shadcn/ui design system                │
└──────────────────────────┬──────────────────────────────────────┘
                           │  REST API (JSON + PDF stream)
┌──────────────────────────▼──────────────────────────────────────┐
│                     FastAPI Backend (Python)                     │
│                                                                  │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │ PHI Detector  │  │   Redactor      │  │    Audit Trail       │ │
│  │ ─ Presidio    │→│ ─ PyMuPDF       │→│ ─ Per-entity log     │ │
│  │ ─ OpenBioNER  │  │ ─ apply_redact  │  │ ─ Model attribution │ │
│  │ ─ Ensemble    │  │ ─ EasyOCR (OCR) │  │ ─ Confidence gate   │ │
│  └──────────────┘  └────────────────┘  └──────────────────────┘ │
│                                                                  │
│  Zero-Disk Policy │ io.BytesIO only │ No temp files              │
└──────────────────────────────────────────────────────────────────┘
```

## Core Security Guarantees

| # | Constraint | Implementation |
|---|-----------|---------------|
| 1 | **Zero-Disk Policy** | All processing via `io.BytesIO`; no `tempfile` or disk writes |
| 2 | **Irreversible Redaction** | `fitz.Page.apply_redactions()` physically erases text/images |
| 3 | **Medical Awareness** | Ensemble: Presidio (PII) + OpenBioNER gazetteers (clinical terms) |
| 4 | **Safe Harbor** | 16/18 HIPAA identifiers masked; Gender & Age kept (ages >89 → 90+) |
| 5 | **Confidence Gate** | Mean confidence < 0.98 → LOCKED status; download disabled |

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+

### Backend

```bash
cd SecureGate
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Start the API server
python run.py
```

The API runs at **http://localhost:8000** with docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI runs at **http://localhost:3000** and proxies API calls to the backend.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/deidentify` | Upload PDF → detect + redact PHI → return audit JSON |
| `GET`  | `/api/download/{audit_id}` | Download redacted PDF (only if UNLOCKED) |
| `GET`  | `/api/audit/{audit_id}` | Full anonymization audit trail |
| `GET`  | `/api/audits` | List all processing history |
| `GET`  | `/api/health` | Health check |

## Project Structure

```
SecureGate/
├── backend/
│   ├── __init__.py
│   ├── config.py          # Central settings (Pydantic)
│   ├── phi_detector.py    # Ensemble PHI detection engine
│   ├── redactor.py        # Zero-disk PDF redaction
│   ├── audit.py           # Structured audit trail
│   └── main.py            # FastAPI application
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx
│   │   │   └── globals.css
│   │   ├── components/
│   │   │   ├── header.tsx
│   │   │   ├── upload-zone.tsx
│   │   │   ├── processing-status.tsx
│   │   │   ├── results-panel.tsx
│   │   │   ├── audit-trail.tsx
│   │   │   └── dashboard-history.tsx
│   │   └── lib/
│   │       └── utils.ts
│   ├── package.json
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── next.config.js
├── requirements.txt
├── run.py
└── README.md
```

## HIPAA Safe Harbor – 16 Masked Identifiers

1. Names (PERSON)
2. Dates (DATE_TIME)
3. Phone numbers
4. Email addresses
5. SSNs
6. Geographic data (LOCATION)
7. IP addresses
8. URLs
9. Driver license numbers
10. Medical record numbers
11. Nationality / Religion
12. Account numbers (IBAN)
13. Credit card numbers
14. Passport numbers
15. Bank account numbers
16. Device identifiers

**Kept**: Gender, Age (with >89 → 90+ aggregation)

---

Built with security-first engineering by **Cognitva.ai**.
