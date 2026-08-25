# Mentalist Runtime Reproduction Fix

The first fixed-threshold reproduction attempt failed despite matching aggregate validation metrics. Investigation found that the reproduction/runtime contract used the final v0.5 REVIEW mask as Mentalist eligibility, while the successful v0.8/v1.0 experiments had frozen eligibility against the transaction-baseline REVIEW boundary before final v0.5 routing.

This distinction matters because trusted relationship memory can move the final v0.5 action relative to the transaction-only baseline.

The corrected runtime contract therefore includes the exact frozen baseline REVIEW threshold and requires a Mentalist promotion candidate to satisfy all of the following:

- current full v0.5 action is ALLOW;
- transaction-only baseline risk is below its frozen REVIEW threshold;
- at least two independent proactive clue families are active;
- Mentalist score is at or above the frozen Jane cutoff.

The successful v1.0 batch reference is reconstructed using that same baseline eligibility rule. No labels are used to construct either action vector.

If exact action reproduction still fails after this correction, the remaining mismatch is treated as a boundary-tie problem and must be resolved explicitly before the held-out test is opened.
