# LinkRisk Engineering Decisions

## D001 — Scope
Detect coordinated payment abuse rather than build a general-purpose fraud platform.

## D002 — Baseline
Use a supervised transaction-level model to establish what can be detected without explicitly constructed relationship features.

## D003 — Baseline feature policy
IEEE-CIS contains feature families that already encode counts, history, time-to-prior-event signals, and entity relations. The initial baseline excludes `C*`, `D*`, and `V*` families. The baseline may use the same raw point-in-time transaction and identity attributes available to LinkRisk so that the graph model's incremental signal comes from historical cross-transaction relationships rather than richer raw inputs. The exact feature list will be frozen before final held-out evaluation.

## D004 — Graph approach
Use lightweight, interpretable graph-derived signals rather than a GNN.

## D005 — Graph confidence
Graph evidence is not trusted unconditionally. A graph-confidence value describes how much usable relationship evidence exists for a transaction.

## D006 — Fusion
Graph influence is confidence-gated. Missing or weak relationship evidence moves the final score toward the transaction-only ML score.

## D007 — Missing graph data
Missing graph evidence must never crash the scoring path or silently imply low risk. Fallback is explicitly recorded as ML-dominant / ML-only scoring.

## D008 — LLM usage
LLM is not part of the fraud decision. Deterministic evidence explanations are MVP.

## D009 — Evaluation
Use chronological train/validation/test split. Final held-out test is not used for tuning.

## D010 — Claims
Do not claim graph fraud detection itself is novel. Buildathon differentiation is confidence-aware, interpretable, gracefully-degrading graph augmentation with honest evaluation.

## D011 — Dataset suitability
IEEE-CIS is approved for the MVP. It contains 590,540 labelled transactions with 3.50% fraud prevalence. Fraud prevalence remains stable across the chronological train/validation/test partitions (3.52%, 3.43%, 3.48%).

## D012 — Sparse relationship evidence
Only 24.42% of transactions have a corresponding identity row. This is treated as a useful real-data property because it naturally creates strong, sparse, and missing relationship-evidence regimes for graph confidence and graceful fallback.

## D013 — Edge construction
Single low-cardinality values must never be treated as identity edges by themselves. In particular, DeviceType, card4/card6, address, and email-domain values are too broad. LinkRisk will use higher-specificity composite pseudo-entity keys, multiple independent shared attributes, and temporal evidence instead of naive same-value linking.

## D014 — Comparison fairness
The ML-only and graph-enhanced systems should receive the same raw point-in-time attributes wherever practical. LinkRisk's incremental signal must come from historical cross-transaction relationship features, not from secretly giving the graph model richer raw inputs.

## D015 — Leakage rule
For a transaction at time t, every relationship-derived feature must be computable from the current transaction and transactions strictly earlier than t. Future transactions are never allowed to influence the current score.
