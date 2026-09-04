# LinkRisk — Razorpay Track 2 submission contract

This document is the source of truth for how LinkRisk maps its product actions to the Razorpay Track 2 requirement:

> Build a working detector, verifier or auto-responder for one class of loss, with measured precision and recall on a held-out test set. Honest metrics including false-positive cost. Defense-only.

## Loss class

**Coordinated payment fraud:** transactions that can appear individually plausible but become suspicious when causal relationship, recurrence, velocity, or context evidence is considered.

LinkRisk is defense-only. It detects, verifies, investigates and supports merchant risk operations. It does not provide offensive fraud tooling or evasion guidance.

## Metric-bearing detector

The **frozen v0.5 hard REVIEW boundary** is the official measured detector.

A `REVIEW` action means the hard detector crossed its frozen risk boundary and the payment should enter high-priority risk review.

The chronological held-out test was opened once after models and thresholds were frozen:

- test transactions: **88,581**
- fraud transactions: **3,083 (3.48%)**
- precision: **49.10%**
- recall: **23.09%**
- false-positive rate: **0.8632%**
- PR-AUC of v0.5 risk: **0.3132**

For comparison, the frozen transaction-only hard detector achieved:

- precision: **49.81%**
- recall: **21.08%**
- false-positive rate: **0.7661%**
- PR-AUC: **0.2873**

Therefore the relationship/trusted-memory hard detector increased held-out recall from **21.08% to 23.09%** and PR-AUC from **0.2873 to 0.3132**, while retaining approximately 49% precision.

## VERIFY is not a fraud verdict

`VERIFY` is a broader defensive intervention state. It means the system has enough evidence to request additional verification or investigation, not that the transaction has been classified as fraud.

The product contract is:

```text
ALLOW
  No sufficient evidence for intervention.

VERIFY
  Additional defensive verification / investigation is warranted.
  This is not a fraud-positive label.

REVIEW
  Frozen hard detector positive.
  High-priority risk review is warranted.
```

Because `VERIFY + REVIEW` is intentionally broader than the hard detector, its precision is lower and must not be presented as the precision of the hard fraud detector.

## Broader held-out intervention result

The final v1.0 Mentalist-routed operational policy was also evaluated on the same one-shot held-out partition:

- precision: **17.44%**
- fraud capture / recall: **38.50%**
- false-positive rate: **6.5744%**
- intervention share: **7.69%**
- TP / FP / TN / FN: **1,187 / 5,621 / 79,877 / 1,896**

This metric describes the broad **VERIFY + REVIEW intervention queue**, not the hard detector alone.

The system therefore exposes the real trade-off instead of hiding it: broader intervention captures more fraud but creates more legitimate-customer friction.

## False-positive cost interpretation

A false positive in the hard `REVIEW` detector is a legitimate transaction sent to risk review.

A false positive in the broader `VERIFY` layer is generally an unnecessary verification/investigation step; it is not necessarily an automatic payment decline.

This distinction is central to LinkRisk's product design. Fraud capture is not optimized without regard for merchant/customer friction.

## Current live runtime

The deployed product contains the frozen detector plus post-held-out operational engineering:

- Razorpay Test Mode payment verification;
- trusted merchant memory and delayed adjudication;
- selective Jane / Mentalist investigation;
- causal relationship visualization;
- analyst-requested Jane second opinions;
- explicit operator escalation;
- persistent case/ledger state;
- cost/capacity telemetry.

The current v2 operational orchestration was developed after the v1 held-out set had already been opened. Its development-validation metrics therefore remain labelled **development only** and are not presented as new unbiased held-out performance.

The frozen hard `REVIEW` detector itself remains unchanged inside the live stack and is the component associated with the official held-out detector metrics above.

## Score semantics

LinkRisk scores are ranking/risk signals, not calibrated probabilities.

Do not say:

> “A score of 82 means an 82% probability of fraud.”

Do say:

> “The transaction received a risk score of 82/100 relative to the frozen decision policy.”

Similarly, 49.10% precision is a population-level held-out metric for the detector-positive set, not a per-transaction fraud probability.

## Submission headline

Recommended primary metric statement:

> **On 88,581 unseen chronological transactions, LinkRisk's frozen hard REVIEW detector achieved 49.10% precision, 23.09% recall and a 0.8632% false-positive rate. Relationship-aware risk improved recall over the transaction-only detector while preserving roughly 49% precision. A broader VERIFY layer captures additional suspicious cases as a defensive verification queue, with its false-positive cost reported separately rather than hidden.**

## Claims we must not make

- Do not describe `VERIFY` as a confirmed fraud prediction.
- Do not call Jane scores calibrated fraud probabilities.
- Do not attach v1 held-out metrics to post-test v2 orchestration as if v2 itself had an untouched test.
- Do not tune thresholds on the already-opened held-out partition.
- Do not hide the 17.44% precision / 6.5744% FPR of the broad v1 intervention policy when discussing that policy.
- Do not claim Razorpay Test Mode payments are real financial transactions.

## Judge-facing one-line distinction

> **REVIEW is our measured fraud detector. VERIFY is our defensive verification layer. Jane helps decide when an otherwise ordinary-looking payment deserves that extra verification.**
