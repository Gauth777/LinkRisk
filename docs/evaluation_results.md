# LinkRisk evaluation record

This document is the public evaluation ledger for LinkRisk. It separates the one-shot v1.0 held-out result from later v2 development work so post-test engineering is not presented as unbiased test performance.

## v1.0 — final chronological held-out evaluation

The chronological held-out partition contained **88,581 transactions**, including **3,083 frauds (3.48%)**. The final evaluator used frozen models and thresholds only. Test labels were excluded from relationship, trusted-memory and Mentalist prediction features and were used only after predictions/actions had been frozen.

### Baseline hard detector

| Metric | Held-out result |
| --- | ---: |
| Precision | 49.81% |
| Recall | 21.08% |
| PR-AUC | 0.2873 |
| FPR | 0.7661% |
| TP / FP / TN / FN | 650 / 655 / 84,843 / 2,433 |

### v0.5 hard REVIEW detector

| Metric | Held-out result |
| --- | ---: |
| Precision | 49.10% |
| Recall | 23.09% |
| PR-AUC of v0.5 risk | 0.3132 |
| FPR | 0.8632% |

### Stable v0.5 operational policy — VERIFY + REVIEW

| Metric | Held-out result |
| --- | ---: |
| Precision | 21.64% |
| Recall / fraud capture | 35.61% |
| FPR | 4.6516% |
| Intervention share | 5.73% |

### Final LinkRisk v1.0 — Mentalist routed

| Metric | Held-out result |
| --- | ---: |
| Precision | 17.44% |
| Recall / fraud capture | 38.50% |
| FPR | 6.5744% |
| Intervention share | 7.69% |
| TP / FP / TN / FN | 1,187 / 5,621 / 79,877 / 1,896 |

Mentalist promoted **2,194** rows containing **93 frauds** and displaced **461** v0.5 VERIFY rows containing **4 frauds**. The net effect was **+89 frauds captured** versus stable v0.5, but intervention expanded by **1,733 rows**. Frozen v0.5 REVIEW decisions remained immutable.

### Interpretation

The learned risk layers generalized: v0.5 improved hard-review recall and PR-AUC over the transaction-only baseline. Mentalist also increased operational fraud capture. However, the v1.0 scalar validation-calibrated routing boundaries did **not** preserve the intended 6% intervention capacity under later temporal traffic: intervention rose from 5.73% to 7.69% and precision fell.

This is treated as a real policy-calibration/distribution-shift finding, not something to tune away on the same test set.

**Status: FINAL — DO NOT RETUNE ON THIS HELD-OUT SET.**

## v2 — cost-aware selective investigation

v2 was designed only after observing the v1.0 held-out capacity drift. Therefore the previous held-out partition is **not** an unbiased evaluation set for v2 and is not reused for v2 performance claims.

The v2 development-validation design adds two ideas:

1. **Selective inference:** compute cheap, label-free evidence-family clues first and invoke Mentalist only when a v0.5-ALLOW transaction has enough independent evidence to justify deeper reasoning.
2. **Explicit capacity allocation:** preserve mandatory REVIEW, reserve a fixed Mentalist share, then fill remaining intervention capacity with the strongest v0.5 VERIFY cases instead of assuming static scalar thresholds will preserve a global budget.

### v2 development-validation result

Validation rows: **88,581**.

| Metric | Stable v0.5 | Cost-aware v2 | Delta |
| --- | ---: | ---: | ---: |
| Intervention share | 6.00% | 6.00% | +0.00 pp |
| Precision | 24.37% | 25.31% | +0.93 pp |
| Recall / fraud capture | 42.57% | 44.21% | +1.64 pp |
| FPR | 4.6973% | 4.6412% | -0.06 pp |
| TP | 1,295 | 1,345 | +50 |
| FP | 4,018 | 3,970 | -48 |

Selective-reasoning accounting:

- Mentalist invoked: **2,011 / 88,581 = 2.27%**
- Mentalist bypassed: **86,570 / 88,581 = 97.73%**
- eligible Jane candidates: **519**
- Jane cases selected: **519**

This demonstrates the intended engineering principle on development validation: most traffic can use cheaper decision paths while the proactive model is reserved for structurally interesting cases.

## Post-final-test challenger ledger — development only

These experiments were run only after the v1.0 final partition had already been opened. They are therefore **development research**, not new held-out evaluations.

### AutoGluon tabular challenger — REJECT

The experiment used an internal chronological fit/tune split inside the original historical train partition and reported once on the existing development-validation partition. The old final partition was not scored.

Because of environment/dependency limits, the attempted AutoGluon ensemble effectively collapsed to XGBoost rather than producing a diversified ensemble.

| Metric | Challenger | Frozen baseline validation | Delta |
| --- | ---: | ---: | ---: |
| PR-AUC | 0.3413 | 0.3496 | -0.0082 |
| Precision | 53.50% | 50.72% | +2.77 pp |
| Recall | 25.64% | 28.83% | -3.19 pp |
| FPR | 0.7926% | 0.9960% | -0.203 pp |
| TP / FP | 780 / 678 | 877 / 852 | -97 / -174 |

**Decision:** reject. The challenger became more conservative but reduced both recall and PR-AUC.

### Heterogeneous GraphSAGE structural-signal test — REJECT

This was explicitly a **transductive structural-signal feasibility experiment**, not a deployment-valid GNN evaluation. Validation labels were excluded from training, but validation graph structure was visible during message passing. The old final partition was not included in the graph.

Sample used:

- historical graph rows: **120,000**
- fit rows: **102,000**
- internal tune rows: **18,000**
- development-validation rows: **30,000**

Same-slice result:

| Metric | GraphSAGE | Frozen baseline |
| --- | ---: | ---: |
| PR-AUC | 0.1452 | 0.4019 |
| Precision | 26.80% | 66.23% |
| Recall | 5.02% | 24.61% |
| FPR | 0.4903% | 0.4488% |

**Decision:** reject as a standalone detector. The graph model was dramatically weaker than the transaction model and did not earn further standalone tuning.

### Causal graph-feature + XGBoost fusion — REJECT

This experiment tested whether causal relationship statistics could add useful signal to the strong transaction model without using future graph structure. Graph-derived features were computed from strictly prior transactions, with same-timestamp rows isolated.

The fusion challenger added **27 causal relationship features** to the **63 raw transaction features** and compared against both a matched tabular-only XGBoost control and the frozen baseline on the same 30,000-row development slice.

| Metric | Matched tabular XGB | Graph + XGB | Frozen baseline |
| --- | ---: | ---: | ---: |
| PR-AUC | 0.3772 | 0.3613 | 0.4019 |
| Precision | 67.81% | 64.42% | 66.23% |
| Recall | 20.95% | 20.27% | 24.61% |
| FPR | 0.356% | 0.400% | 0.449% |

Graph fusion versus the matched control:

- PR-AUC: **-0.0159**
- recall: **-0.68 pp**
- precision: **-3.40 pp**
- FPR: **+0.045 pp**
- TP / FP: **-7 / +13**

**Decision:** reject. The added causal graph features caught fewer frauds while creating more false positives than the matched tabular control.

## What the challenger failures mean

The conclusion is intentionally narrow:

> On the tested IEEE-CIS development protocols, AutoML, standalone GraphSAGE and graph-feature/XGBoost fusion did not improve the frozen transaction baseline enough to justify production complexity.

This does **not** mean graph methods or AutoML are generally ineffective for fraud detection. It means LinkRisk kept only the components that earned their complexity under its own chronological development protocol.

The strongest measured product gains came from:

- trusted delayed feedback;
- evidence-gated Mentalist reasoning;
- one-for-one case reallocation;
- explicit intervention capacity control;
- selective live inference.

## Evaluation boundary

The current honest claim is:

> LinkRisk v1.0 has a one-shot chronological held-out result. LinkRisk v2 is a post-test cost-aware engineering response validated on development data only; it requires a new untouched evaluation source before any unbiased v2 generalization claim.

The repository must not delete, overwrite or silently replace the v1.0 final result in order to make v2 look better.
