# ML Challenge 2026: Business Entity Resolution

**Team Name:** BusyBugs  
**Team Members:** BusyBugs team  
**Submission Date:** 2026-09-26

## 1. Executive Summary

BusyBugs uses deterministic local normalization, country-aware blocking, and
conservative pair scoring. The implementation is batch-oriented and writes the
required outputs incrementally so memory does not scale with the full
candidate cross-product.

## 2. Methodology

### 2.1 Problem Analysis

The training data contains millions of records, missing addresses, legal-form
and street abbreviations, punctuation differences, transliteration variation,
and singleton Source 1 entities. Country is retained as a blocking dimension,
but is treated as an open string rather than a fixed category.

### 2.2 Solution Strategy

Names and addresses are normalized locally, exact and informative-token keys
are indexed, candidates are retrieved only within the same country, and pairs
are scored conservatively. Empty predictions are retained for entities with no
high-confidence candidate.

**Approach Type:** Blocking plus conservative pair scorer  
**Core Innovation:** DuckDB-backed, chunked inverted blocking with frequency
pruning of generic tokens and incremental output generation.

## 3. Candidate Generation (Blocking)

Candidates use country plus normalized name, normalized address, informative
name tokens, and informative address tokens. Exact keys are always retained;
token keys are retained only when their country/type/value frequency is below
the configured cap. Candidate retrieval is batch-based and duplicate pairs are
removed in SQL.

- **Blocking keys used:** country + exact normalized name/address and country +
  name/address tokens of length at least four.
- **Candidate pairs generated:** measured in `output/candidate_pairs.tsv`;
  bounded benchmarks produced approximately 56 candidates per Source 1 entity
  with a token cap of 100.
- **Recall protection:** exact keys are never pruned, and independent name and
  address blocking keys are unioned.

## 4. Matching Model

**Features used:**

- Name: RapidFuzz token-set ratio, character ratio, token overlap,
  containment, and exact normalized equality.
- Address: RapidFuzz token-set ratio, token overlap, containment, and exact
  normalized equality.
- Other: country equality and numeric-token agreement.

**Model type:** Conservative deterministic scorer in the packaged inference
entry point; the feature module and LightGBM prototype are included for
training and ablation.

**Threshold selection:** The training prototype supports validation macro F0.5
threshold selection and permits empty predictions. The packaged scorer uses a
high-precision threshold to avoid false merges.

## 5. Results & Error Analysis

- **F0.5 Score (macro):** No full test score is possible because test labels are
  withheld. Bounded validation diagnostics are recorded under `reports/`.
- **False positives:** Common business names combined with short or missing
  addresses.
- **False negatives:** Severe transliteration, abbreviated names, and records
  with both missing address and weak name overlap.

## 6. Conclusion

The solution separates high-recall blocking from precision-heavy scoring and
uses disk-backed, chunked processing for the challenge scale. The main
engineering lesson is that token-frequency pruning and bounded batches are
more important than adding model complexity before the candidate pipeline is
reliable.

## Appendix

### A. Code Artefacts

`code/business_entity_resolution/` contains normalization, features, the batch
inference entry point, README instructions, and dependency requirements. The
index builder is included with the working code and should be copied under
`src/` when creating the final standalone archive. The inference entry point is
`src/run_pipeline.py`.

### B. Additional Results

Bounded DuckDB measurements indexed 1,000,000 target rows in about 150 seconds
with a 100-token frequency cap. A 10,000-row Source 1 benchmark produced
514,509 candidate pairs, with mean 56.5, p95 147, and maximum 354 candidates.
These are engineering diagnostics, not leaderboard scores.
