# LinkRisk Frozen Champion Policy

This document records the frozen development configuration before held-out test evaluation.

## Champion

- Model version: `v0.5`
- Transaction baseline: frozen XGBoost baseline
- Relationship specialist: delayed confirmed-fraud feedback specialist
- Adjudication-delay simulation: 72 hours
- Champion gate strength: `1.00`
- Graph-confidence zero: exact transaction-only fallback
- Scores are ranking/risk scores, not calibrated fraud probabilities.

## Frozen thresholds

- REVIEW threshold: `0.8406179547309875`
- VERIFY threshold: `0.781202555`
- Validation calibration target: total `VERIFY + REVIEW` intervention share of 6%.

The 6% intervention value is a development-period business-policy calibration target, not a guarantee under distribution shift. In a production system, intervention volume would be monitored independently; model or policy thresholds must not be silently retuned from live labels.

## Actions

### REVIEW

A transaction enters REVIEW when its frozen LinkRisk risk score is at or above the REVIEW threshold. Structural relationship evidence alone cannot force REVIEW.

### VERIFY

A transaction enters VERIFY when it is below REVIEW and either:

1. its LinkRisk score is at or above the frozen VERIFY threshold;
2. it has a strong matured device/receiver confirmed-fraud relationship with sufficient confidence; or
3. it has corroborating matured confirmed-fraud evidence across at least two relationship channels with sufficient confidence.

### ALLOW

All remaining transactions are allowed through the normal path.

## Validation evidence at freeze time

At the v0.5 REVIEW operating point, validation recall was about 32.1% at about 1.0% FPR, compared with 28.8% recall for the frozen baseline. The paired transition analysis recovered 139 baseline false negatives, lost 39 baseline true positives, removed 122 baseline false positives, and introduced 124 new false positives: +100 net fraud detections for +2 net false positives.

The calibrated policy allocated approximately 2.07% of validation transactions to REVIEW and 3.93% to VERIFY, for a 6.00% total intervention share.

These are development/validation results. The held-out test remains sealed until the model, policy, evidence rules, and failure-case behavior are frozen.
