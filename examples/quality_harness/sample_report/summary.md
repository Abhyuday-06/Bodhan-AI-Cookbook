# Bodhan Quality Evaluation Summary

**Generated at:** 2026-11-21 03:59:59 UTC
**Dataset:** `data/demo.jsonl` | **Target Languages:** `hi,ta,bn`

## Executive Overview

| Metric | Value | Target | Status |
|---|---|---|---|
| **Evaluated Items** | 120 | — | Complete |
| **Clean Items** | 59 (49.2%) | — | — |
| **Items With Unavailable Checks** | 0 | 0 | Complete |
| **Flagged Defect Items** | 61 (50.8%) | — | Audited |
| **Total Detected Defects** | 102 | — | — |
| **Detection Recall** | 96.5% | >= 80% | **PASS** |
| **False Alarm Rate** | 0.0% | <= 10% | **PASS** |
| **Localization Overlap** | 79.3% | >= 70% | **PASS** |
| **Category Accuracy** | 96.5% | >= 70% | **PASS** |


## Language Breakdown

| Language | Items | Clean | Flagged | Defect Rate | Top Error Category |
|---|---|---|---|---|---|
| **bn** | 40 | 17 | 23 | 57.5% | `mistranslation` |
| **hi** | 40 | 22 | 18 | 45.0% | `format` |
| **ta** | 40 | 20 | 20 | 50.0% | `format` |


## Error Category Distribution

| Error Category | Occurrences | Share | Primary Detection Mechanism |
|---|---|---|---|
| `format` | 21 | 20.6% | Markdown & LaTeX Delimiter Integrity Check (Deterministic) |
| `number` | 19 | 18.6% | Indic Numeral Normalization Check (Deterministic) |
| `mistranslation` | 17 | 16.7% | chrF++ reference / Back-translation + LLM Judge |
| `addition` | 17 | 16.7% | Back-translation + LLM Judge |
| `wrong_language` | 16 | 15.7% | Script Unicode Range Validator (Deterministic) |
| `omission` | 11 | 10.8% | Back-translation + LLM Judge |
| `entity` | 1 | 1.0% | Named Entity Heuristic Check (Deterministic) |


## Top Critical Failures

### 1. Item `hi-025` (hi) — Score: 0.0/10
- **Source:** *"Global trade reached a volume of  trillion in the year 2022."*
- **Translation:** *"वर्ष 2022 में वैश्विक व्यापार 32 ट this section is completely untranslated English ्रिलियन डॉलर के स्तर पर पहुंच गया।"*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 35:82]): Untranslated English passage left in output: 'this section is completely untranslated English...'
  - **[wrong_language]** (CRITICAL [chars 23:63]): this section is completely untranslated English
  - **[number]** (MAJOR [chars 19:21]): 32

### 2. Item `hi-035` (hi) — Score: 0.0/10
- **Source:** *"Microprocessors execute millions of arithmetic instructions per second."*
- **Translation:** *"माइक्रोप्रोसेसर प्रति सेकंड लाखों अंकग this section is completely untranslated English णितीय निर्देशों को निष्पादित करते हैं।"*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 39:86]): Untranslated English passage left in output: 'this section is completely untranslated English...'
  - **[wrong_language]** (CRITICAL [chars 35:78]): this section is completely untranslated English
  - **[mistranslation]** (MAJOR [chars 30:85]): लाखों अंकग this section is completely untranslated English णितीय

### 3. Item `ta-025` (ta) — Score: 0.0/10
- **Source:** *"Global trade reached a volume of  trillion in the year 2022."*
- **Translation:** *"2022 ஆம் ஆண்டில் உலகளாவிய வர்த் this section is completely untranslated English தகம்  டிரில்லியன் அளவை எட்டியது."*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 32:79]): Untranslated English passage left in output: 'this section is completely untranslated English...'
  - **[wrong_language]** (CRITICAL [chars 33:75]): this section is completely untranslated English
  - **[omission]** (MAJOR [chars 33:75]): The numerical value for the trillion amount is missing.

### 4. Item `bn-025` (bn) — Score: 0.0/10
- **Source:** *"Global trade reached a volume of  trillion in the year 2022."*
- **Translation:** *"2022 সালে বিশ্ব বাণিজ্য   this section is completely untranslated English ট্রিলিয়ন পরিমাপে পৌঁছেছে।"*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 26:73]): Untranslated English passage left in output: 'this section is completely untranslated English...'
  - **[wrong_language]** (CRITICAL [chars 24:63]): this section is completely untranslated English
  - **[omission]** (MAJOR): trillion

### 5. Item `ta-035` (ta) — Score: 0.0/10
- **Source:** *"Microprocessors execute millions of arithmetic instructions per second."*
- **Translation:** *"நுண்செயலிகள் வினாடிக்கு மில்லியன் கணக்கான  this section is completely untranslated English கணக்கீட்டு வழிமுறைகளைச் செயல்படுத்துகின்றன."*
- **Flags:**
  - **[wrong_language]** (CRITICAL [chars 43:90]): Untranslated English passage left in output: 'this section is completely untranslated English...'
  - **[wrong_language]** (CRITICAL [chars 27:67]): this section is completely untranslated English

## Model Cost & Resource Utilization

- **Total Spend:** ₹0.0005 (Budget: ₹4.00)
- **Budget Remaining:** ₹3.9995
- **API Operations:** 2
- **Expenditure by Model:**
  - `indic-translate`: ₹0.0005


## Audit Targets & Known Limitations

- **Noisy Checkers Disambiguation:** Round-trip translation and transcription introduce lexical divergence. Semantic overlap thresholds ensure only true structural omissions or severe distortions trigger flags, while acceptable synonym paraphrasing is tolerated.
- **Script Normalization:** Full Unicode NFC and Indic numeral translation (e.g. '२५' -> '25') prevents false alarms on script numeral variations.
- **Cost Protection:** Audio synthesis is constrained to items flagged for audio validation or explicit generation requests, ensuring runs remain well under the ₹50 budget.
