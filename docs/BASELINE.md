# LinkRisk — ML Baseline v0.1

## Status
Frozen validation baseline before relationship-feature development.

## Split
Chronological 70/15/15 split over 590,540 labelled IEEE-CIS transactions.

- Train: 413,378 rows
- Validation: 88,581 rows
- Test: 88,581 rows — sealed, not evaluated
- Train fraud prevalence: 3.5169%
- Validation fraud prevalence: 3.4341%

## Model
XGBoost transaction-only baseline using 63 frozen raw point-in-time features.

Excluded from the baseline:

- `C*` count/history features
- `D*` time/history features
- `V*` Vesta engineered features
- `TransactionID` as a predictor
- `TransactionDT` as a direct predictor

Class imbalance is handled with `scale_pos_weight = 27.434`.

## Operating point
The decision threshold is selected on validation to maximize recall while keeping the false-positive rate at or below 1%.

- Threshold: 0.849797
- Target FPR budget: 1.00%
- Observed FPR: 0.9960%

## Validation metrics

| Metric | Value |
|---|---:|
| Precision | 0.5072 |
| Recall | 0.2883 |
| PR-AUC | 0.3496 |
| False-positive rate | 0.9960% |
| True positives | 877 |
| False positives | 852 |
| True negatives | 84,687 |
| False negatives | 2,165 |

## Interpretation
The validation stream has 3.4341% fraud prevalence. Among transactions flagged by the baseline at the chosen operating point, 50.72% are fraud, giving a large enrichment over the raw stream while respecting the fixed false-positive budget.

This result is the frozen comparator for the graph-enhanced LinkRisk system. The final held-out test set remains untouched until the graph pipeline, confidence logic, fusion rule, and operating policy are frozen.
