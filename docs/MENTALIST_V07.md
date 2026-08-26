# Mentalist v0.7 — Proactive Deduction Specialist

## Why this branch exists

The frozen v0.5 system is intentionally preserved on `stable-v0.5-live-engine`.
This branch asks a harder question:

> Can LinkRisk recover transaction-model fraud misses from causal temporal and
> network structure **before any related entity has already been confirmed
> fraudulent**?

If the answer is no, we do not weaken the published v0.5 system to rescue the
idea. The stable branch remains the fallback submission.

## Mentalist hypothesis

Fraud coordination may appear as a combination of weak clues before any single
identifier becomes a known fraud indicator. The model should learn from a small
set of interpretable, point-in-time measurements rather than from a blacklist.

Mentalist v0.7 therefore receives:

1. a deployment-like transaction-model risk score;
2. velocity/burst measurements;
3. behavioral-change measurements;
4. local network-coordination measurements; and
5. reuse/churn measurements.

It receives **zero confirmed-fraud-memory features**.

Historical confirmed fraud remains a separate v0.5 trusted-memory channel and
will only be combined with Mentalist if the proactive specialist first proves
useful on its own.

## Frozen clue families

### Velocity

- profile transactions in the previous 10 minutes;
- profile acceleration versus its recent hour;
- device-context transactions in the previous 10 minutes and hour.

Question: **Is activity happening unusually fast?**

### Behavioral change

- amount deviation from profile history;
- new device information for a known profile;
- new browser context for a known profile.

Question: **Is the current behavior inconsistent with this profile's past?**

### Coordination

- distinct masked payment profiles using a device/browser context recently;
- profile diversity inside that context;
- a new profile joining an already-active context;
- prior profile fan-out of the context.

Question: **Are nominally different profiles behaving as if they share
infrastructure?**

### Reuse / churn

- recent strong-device and R-domain relationship activity;
- number/diversity of device contexts recently used by a profile;
- new context for a recently active profile.

Question: **Are identifiers being reused or rotated unusually?**

`R_emaildomain` is treated only as a masked/contextual relationship signal. It
is not described as a unique receiver identity.

## Corroboration philosophy

Mentalist does not use a hand-written points system. The XGBoost meta-model
learns the risk mapping from the raw measurements.

For diagnostics and later explanations, independent clue-family activations are
calibrated from the 97.5th percentile of legitimate chronological training
traffic. This means several correlated velocity measurements still count as one
velocity family, rather than pretending they are independent witnesses.

The clue count is explanatory metadata, not an automatic REVIEW rule.

## Leakage controls

- chronological 70/15/15 split remains unchanged;
- held-out test remains sealed;
- structural features are point-in-time causal;
- exact same-timestamp rows cannot see one another;
- no current/prior fraud label is read by the v0.7 feature builder;
- Mentalist training receives chronological out-of-fold baseline scores;
- the first 40% of training data is baseline warm-up;
- expanding-window baselines predict the next 20% blocks;
- a training row is never given a baseline score from a model trained on that
  row or on future rows.

## Predeclared promotion gate

At the validation operating point constrained to <=1% FPR, Mentalist becomes a
promotion candidate only if either:

1. recall improves by at least +1.0 percentage point and PR-AUC does not fall;
   or
2. PR-AUC improves by at least +0.010 and recall does not fall.

The rule is frozen before the first v0.7 result is observed.

Passing this gate does **not** immediately replace v0.5. It means the proactive
specialist has earned the next experiment: combining Mentalist with the trusted
v0.5 prior while preserving the sealed held-out test.

## Run

```powershell
python scripts/evaluate_mentalist_v7.py
```

Expected outputs:

- `artifacts/results/mentalist_v7_validation.json`
- `artifacts/models/mentalist_v7_candidate.joblib`

The console reports baseline vs Mentalist validation precision, recall, PR-AUC,
FPR, recovered baseline false negatives, new/removed false positives, and
performance by number of independent clue families.
