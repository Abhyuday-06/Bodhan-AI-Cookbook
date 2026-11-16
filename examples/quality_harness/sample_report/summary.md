# Bodhan Quality Evaluation Summary

**Generated at:** 2026-11-16 12:45:16 UTC  
**Dataset:** `data/demo.jsonl` | **Target Languages:** `hi,ta,bn`

## Executive Overview

| Metric | Value | Target | Status |
|---|---|---|---|
| **Evaluated Items** | 120 | — | Complete |
| **Clean Items** | 92 (76.7%) | — | — |
| **Flagged Defect Items** | 28 (23.3%) | — | Audited |
| **Total Detected Defects** | 28 | — | — |
| **Detection Recall** | 60.0% | >= 80% | **NEEDS REVIEW** |
| **False Alarm Rate** | 0.0% | <= 10% | **PASS** |
| **Localization Overlap** | 100.0% | >= 70% | **PASS** |
| **Category Accuracy** | 100.0% | >= 70% | **PASS** |


## Language Breakdown

| Language | Items | Clean | Flagged | Defect Rate | Top Error Category |
|---|---|---|---|---|---|
| **bn** | 40 | 30 | 10 | 25.0% | `number` |
| **hi** | 40 | 31 | 9 | 22.5% | `number` |
| **ta** | 40 | 31 | 9 | 22.5% | `number` |


## Error Category Distribution

| Error Category | Occurrences | Share | Primary Detection Mechanism |
|---|---|---|---|
| `number` | 12 | 42.9% | Indic Numeral Normalization Check (Deterministic) |
| `format` | 9 | 32.1% | Markdown & LaTeX Delimiter Integrity Check (Deterministic) |
| `wrong_language` | 6 | 21.4% | Script Unicode Range Validator (Deterministic) |
| `entity` | 1 | 3.6% | Named Entity Heuristic Check (Deterministic) |


## Top Critical Failures

### 1. Item `hi-025` (hi) — Score: 5.0/10
- **Source:** *"Global trade reached a volume of  trillion in the year 2022."*
- **Translation:** *"वर्ष 2022 में वैश्विक व्यापार 32 ट this section is completely untranslated English ्रिलियन डॉलर के स्तर पर पहुंच गया।"*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 35:82]): Untranslated English passage left in output: 'this section is completely untranslated English...'

### 2. Item `hi-035` (hi) — Score: 5.0/10
- **Source:** *"Microprocessors execute millions of arithmetic instructions per second."*
- **Translation:** *"माइक्रोप्रोसेसर प्रति सेकंड लाखों अंकग this section is completely untranslated English णितीय निर्देशों को निष्पादित करते हैं।"*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 39:86]): Untranslated English passage left in output: 'this section is completely untranslated English...'

### 3. Item `ta-025` (ta) — Score: 5.0/10
- **Source:** *"Global trade reached a volume of  trillion in the year 2022."*
- **Translation:** *"2022 ஆம் ஆண்டில் உலகளாவிய வர்த் this section is completely untranslated English தகம்  டிரில்லியன் அளவை எட்டியது."*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 32:79]): Untranslated English passage left in output: 'this section is completely untranslated English...'

### 4. Item `ta-035` (ta) — Score: 5.0/10
- **Source:** *"Microprocessors execute millions of arithmetic instructions per second."*
- **Translation:** *"நுண்செயலிகள் வினாடிக்கு மில்லியன் கணக்கான  this section is completely untranslated English கணக்கீட்டு வழிமுறைகளைச் செயல்படுத்துகின்றன."*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 43:90]): Untranslated English passage left in output: 'this section is completely untranslated English...'

### 5. Item `bn-025` (bn) — Score: 5.0/10
- **Source:** *"Global trade reached a volume of  trillion in the year 2022."*
- **Translation:** *"2022 সালে বিশ্ব বাণিজ্য   this section is completely untranslated English ট্রিলিয়ন পরিমাপে পৌঁছেছে।"*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 26:73]): Untranslated English passage left in output: 'this section is completely untranslated English...'

## Model Cost & Resource Utilization

- **Total Spend:** ₹0.0000 (Budget: ₹50.00)
- **Budget Remaining:** ₹50.0000
- **API Operations:** 0


## Audit Targets & Known Limitations

- **Noisy Checkers Disambiguation:** Round-trip translation and transcription introduce lexical divergence. Semantic overlap thresholds ensure only true structural omissions or severe distortions trigger flags, while acceptable synonym paraphrasing is tolerated.
- **Script Normalization:** Full Unicode NFC and Indic numeral translation (e.g. '२५' -> '25') prevents false alarms on script numeral variations.
- **Cost Protection:** Audio synthesis is constrained to items flagged for audio validation or explicit generation requests, ensuring runs remain well under the ₹50 budget.