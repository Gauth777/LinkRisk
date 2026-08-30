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

## Evaluation boundary

The current honest claim is:

> LinkRisk v1.0 has a one-shot chronological held-out result. LinkRisk v2 is a post-test cost-aware engineering response validated on development data only; it requires a new untouched evaluation source before any unbiased v2 generalization claim.

The repository must not delete, overwrite or silently replace the v1.0 final result in order to make v2 look better.