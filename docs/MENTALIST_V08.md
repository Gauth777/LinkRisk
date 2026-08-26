# Mentalist v0.8 — Evidence-Gated Investigator

## Why v0.8 exists

v0.7 failed as a global baseline replacement, but its validation diagnostics showed a monotonic pattern: Jane hurt zero-clue traffic and improved recall in every clue-bearing segment, with the largest gains under corroborated evidence.

v0.8 changes **deployment architecture, not the learned model**.

The frozen baseline remains authoritative for all hard REVIEW decisions. Jane is evaluated only as a proactive VERIFY/rescue investigator for transactions that:

1. are **not already REVIEWed by the baseline**; and
2. have **at least two independent proactive clue families** active.

No confirmed-fraud memory is used. The held-out test remains sealed.

## Why two clue families

This follows the pre-existing Mentalist corroboration philosophy:

- one suspicious family creates suspicion;
- two or more independent families create a case worth investigating;
- clue count itself never declares fraud.

Jane's model score ranks the corroborated candidate set. The clue threshold is therefore an eligibility/safety gate, not a hand-written fraud score.

## Capacity-based evaluation

The experiment evaluates fixed proactive VERIFY budgets of:

- 0.25% of validation traffic;
- 0.50%;
- 1.00%; and
- 2.00%.

For each budget, the highest Jane-scored eligible transactions are routed to VERIFY. The score cutoff is selected from capacity only; validation fraud labels are not used to choose it.

The frozen baseline REVIEW tier is unchanged.

## Predeclared usefulness gate

At the **1.00% proactive VERIFY budget**, v0.8 is useful enough to continue if both are true:

1. the Jane VERIFY tier has at least **2.0x fraud-rate enrichment** over overall validation prevalence; and
2. it recovers at least **+1.5 percentage points of absolute fraud recall** from transactions the frozen baseline did not REVIEW.

This is a product-investigator gate, not a claim that v0.7 became a better global classifier.

If it passes, the next experiment may retrain a specialist specifically on evidence-bearing cases and later combine proactive Jane evidence with the separate v0.5 trusted-fraud-memory channel under the existing total intervention budget.

If it fails, v0.8 is rejected and the stable v0.5 branch remains the fallback.

## Run

```powershell
python scripts/evaluate_mentalist_investigator_v8.py
```
