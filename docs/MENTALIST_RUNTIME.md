# Mentalist Runtime Freeze

This milestone converts the successful v1.0 validation reallocation into a fixed, per-transaction runtime contract without touching the held-out chronological test.

## Why a freeze step is required

The v1.0 experiment selected Jane's top 1% of corroborated validation cases and displaced the same number of lowest-risk v0.5 VERIFY cases. That is a valid capacity-allocation experiment, but a live payment engine cannot sort against future traffic.

The runtime policy therefore freezes the exact development boundaries already produced by the successful experiments:

- the exact transaction-baseline REVIEW threshold used to define Jane's v0.8/v1.0 candidate pool;
- the exact Mentalist score cutoff corresponding to the approved v0.8 1% proactive investigator tier;
- the exact maximum v0.5 LinkRisk score among the VERIFY cases displaced by v1.0;
- the already-frozen minimum of two independent proactive clue families.

No rounded console values are copied by hand.

## Runtime contract

For a transaction arriving at time `t`:

1. Run the frozen transaction baseline and the frozen v0.5 transaction + trusted-memory policy.
2. Build the frozen proactive Mentalist features using only prior transaction structure.
3. Count independent clue-family activations using the frozen v0.7 calibration thresholds.
4. Score the transaction with the frozen Mentalist model.
5. Apply these rules:
   - v0.5 `REVIEW` is immutable;
   - a v0.5 `ALLOW` can become `VERIFY` only when the transaction-only baseline is below its frozen REVIEW threshold, at least two independent clue families are active, and the Mentalist score is at or above the frozen Jane cutoff;
   - a v0.5 `VERIFY` becomes `ALLOW` only when its frozen v0.5 risk is at or below the frozen displacement boundary;
   - otherwise preserve the v0.5 action.

The baseline eligibility condition is important: v0.8 and successful v1.0 defined Jane's candidate pool before final v0.5 relationship-memory routing. Trusted memory can move the final v0.5 action relative to the transaction-only baseline, so substituting the final v0.5 REVIEW mask changes the experiment.

The thresholds are distribution-calibrated operating boundaries, not fraud probabilities. The 6% intervention level remains a validation calibration target rather than a guaranteed future traffic share.

## Reproduction check before final test

Before the held-out test can be opened, the fixed per-row contract must reproduce the successful v1.0 validation policy exactly. This proves that replacing batch ranking with thresholds did not change the development result.

Run:

```powershell
python scripts/freeze_mentalist_runtime_policy.py
python scripts/validate_mentalist_runtime_policy.py
```

The first script reads full-precision values from the local baseline, v0.8 and v1.0 JSON artifacts and writes `artifacts/results/mentalist_runtime_policy.json`.

The second script reconstructs validation causally, compares the fixed runtime action vector against the successful v1.0 batch action vector, and refuses promotion if even one action differs. Validation labels are used only to report already-development-known metrics after the action vectors are constructed.

The held-out test frame is deleted before validation evaluation begins.

If exact reproduction still fails, the checker reports how many eligible cases lie exactly on the Jane and displacement boundaries. That lets us distinguish a remaining deterministic score-tie issue from an architecture mismatch without opening the held-out test.
