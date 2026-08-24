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
Single low-cardinality values must never be treated as identity edges by themselves. In particular, DeviceType, card4/card6, address, and email-domain values are too broad. LinkRisk will use higher-specificity composite pseudo-entity keys, multiple shared attributes, and temporal evidence instead of naive same-value linking.

## D014 — Comparison fairness
The ML-only and graph-enhanced systems should receive the same raw point-in-time attributes wherever practical. LinkRisk's incremental signal must come from historical cross-transaction relationship features, not from secretly giving the graph model richer raw inputs.

## D015 — Leakage rule
For a transaction at time t, every relationship-derived feature must be computable from the current transaction and transactions strictly earlier than t. Future transactions are never allowed to influence the current score.

## D016 — Baseline operating point
For the first baseline experiment, use a 1% false-positive-rate budget on the validation period and choose the threshold that maximizes recall while staying within that budget. This thresholding rule is fixed before graph-enhanced results are inspected. PR-AUC remains the primary threshold-independent ranking metric.

## D017 — Selected relationship keys
The training-only structural audit selected two direct relationship keys:

1. `payment_device_profile = card1 + addr1 + DeviceInfo`
2. `payment_receiver_profile = card1 + addr1 + R_emaildomain`

These keys provide useful repetition while keeping observed group sizes materially smaller than broader alternatives. They are pseudo-entity keys, not assertions of real-world identity.

## D018 — Rejected direct-edge keys
`payment_core`, `payment_profile`, `identity_profile`, `device_environment`, and `device_display_profile` are rejected as direct graph edges for the MVP because their observed training groups can become excessively large, creating noisy or misleading components. `payment_email_profile` is also not promoted to a direct edge at this stage because its maximum group size remains too broad relative to the selected keys.

## D019 — Temporal graph representation
The MVP will use an implicit temporal bipartite graph implemented as streaming key histories rather than constructing one global NetworkX graph for all 590k transactions. This is more memory-efficient and makes the leakage rule explicit. NetworkX may still be used later for small local-neighborhood visualizations in the demo.

## D020 — Same-timestamp safety
Transactions sharing the exact same `TransactionDT` must not see each other as historical evidence. Features for all transactions at a timestamp are computed first; only then are those transactions added to relationship history. This preserves the rule that only strictly earlier events may influence the current score.

## D021 — Training-only temporal normalization
The training-only temporal audit found a 95th-percentile prior-1h count of 4 for both selected keys, and prior-24h 95th percentiles of 6 for `payment_device_profile` and 7 for `payment_receiver_profile`. These values are frozen as normalization caps before graph-enhanced validation results are inspected.

## D022 — Graph risk heuristic
For each selected relationship key, define an interpretable activity score using only prior history: `0.60 * clip(prior_1h / p95_1h, 0, 1) + 0.40 * clip(prior_24h / p95_24h, 0, 1)`. The overall graph-risk score is the maximum of the two key scores. This emphasizes short bursts while still capturing broader same-day reuse.

## D023 — Graph confidence and exact fallback
Graph confidence is based on corroborating relationship channels with prior 24h history: 0 active keys -> confidence 0.0; 1 active key -> 0.5; 2 active keys -> 1.0. When confidence is 0, the fused score must equal the ML baseline score exactly.

## D024 — Fusion form and validation tuning
Use monotonic confidence-gated uplift rather than allowing graph evidence to suppress the ML score: `fused = ml + alpha * confidence * graph_risk * (1 - ml)`. Before looking at graph-enhanced validation results, predeclare the alpha grid `[0.10, 0.20, 0.30, 0.40]`. On validation, each alpha receives its own threshold chosen under the same 1% FPR budget; select the alpha with highest recall, breaking ties by PR-AUC. The held-out test remains sealed until all choices are frozen.

## D025 — Champion architecture after development experiments
Validation experiments v0.1 through v0.4 established that unlabeled relationship structure alone did not materially improve the frozen transaction-only baseline. v0.5 adds delayed confirmed-fraud feedback memory: only training labels can enter the relationship memory, and only after a fixed simulated 72-hour adjudication delay. Validation labels never influence validation predictions. v0.5 achieved 32.12% recall, 53.36% precision, 0.3887 PR-AUC, and 0.9984% FPR on validation versus the frozen baseline's 28.83% recall, 50.72% precision, 0.3496 PR-AUC, and 0.9960% FPR.

## D026 — Final modelling champion and stopping rule
v0.6 added two-hop temporal fraud-network propagation under a replacement rule fixed before observing its result. It achieved 30.97% recall and 0.3735 PR-AUC, failing the rule relative to v0.5. v0.5 therefore remains the modelling champion. No further model or relationship-feature tuning will be performed before the sealed held-out evaluation. Frozen champion gate strength is 1.00 and the validation REVIEW operating threshold is 0.840618. Model scores are treated as risk/ranking scores, not calibrated fraud probabilities.

## D027 — Operational action policy
The product contract exposes `ALLOW`, `VERIFY`, and `REVIEW`. `REVIEW` begins at the frozen v0.5 validation operating threshold 0.840618. `VERIFY` begins at a transparent demonstration/business threshold equal to 75% of the REVIEW threshold (0.630464), or may be forced by high-confidence strong matured relationship evidence. Relationship evidence alone never forces `REVIEW`. These action bands are operational policy, not claims about calibrated fraud probability.

## D028 — Deterministic evidence contract
Every score must expose the transaction-only baseline risk, LinkRisk risk, graph confidence, selected action, model path, and deterministic evidence items. When graph confidence is zero, the model path is explicitly `baseline_fallback` and the LinkRisk risk must equal the baseline risk exactly. An LLM is not required to generate or interpret the evidence used for the risk decision.
