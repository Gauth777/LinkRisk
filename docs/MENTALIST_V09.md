# Mentalist v0.9 — Capacity-Preserving Case Router

## Why v0.9 exists

Mentalist v0.8 passed its usefulness gate as a proactive investigator:

- 1.00% VERIFY reservation;
- 110 baseline-missed frauds surfaced;
- 12.42% fraud rate in the Jane tier;
- 3.62x enrichment over validation prevalence;
- +3.62 percentage points incremental fraud recall;
- +0.91% legitimate friction.

That proves Jane can surface fraud before any local confirmed-fraud memory is required. The remaining question is whether Jane is complementary to the already-validated v0.5 trusted-memory policy or mostly duplicates it.

## No arbitrary score fusion

v0.9 does not average Jane and v0.5 scores. They represent different evidence types and remain interpretable.

Routing priority is frozen as:

1. **v0.5 REVIEW** — the validated hard-review decision remains authoritative;
2. **trusted-fraud VERIFY override** — matured confirmed-fraud evidence has first VERIFY priority;
3. **Mentalist proactive VERIFY** — the already-passed 1% Jane investigator reservation;
4. **v0.5 score-band VERIFY** — remaining capacity is filled by the existing v0.5 risk ranking.

Total intervention is capped at the same 6% validation capacity target used by the existing product policy.

## Why this is the right comparison

We do not allow Mentalist to claim a win by simply flagging more payments. v0.9 asks whether it can allocate the same intervention capacity more efficiently.

The experiment reports:

- overlap between Jane and v0.5 REVIEW / trusted VERIFY / score VERIFY;
- frauds Jane finds that the full v0.5 policy would otherwise ALLOW;
- final fraud capture at <=6% intervention;
- legitimate friction;
- fraud rate of each routing source.

No validation labels are used by the routing function. Labels are read only after actions are frozen to evaluate the policy.

## Predeclared promotion gate

v0.9 passes only if all are true:

1. Jane contributes at least **15 fraud transactions not already intervened by the full v0.5 policy**;
2. the 6% Mentalist router improves total fraud capture by at least **+0.50 percentage points** over the frozen v0.5 full policy;
3. legitimate friction does **not increase**;
4. the total intervention budget remains <=6%.

The gate is frozen before v0.9 results are observed.

## Leakage / evaluation controls

- chronological 70/15/15 split unchanged;
- held-out test remains sealed;
- Jane uses only causal proactive structure and the transaction model score;
- v0.5 trusted memory uses only training outcomes that have matured through the fixed simulated 72-hour delay;
- validation outcomes never enter validation relationship memory;
- no test labels are read;
- v0.8's 1% Jane reservation is reused rather than retuned.

## Run

```powershell
python scripts/evaluate_mentalist_router_v9.py
```

If v0.9 passes, the next step is to freeze the combined policy constants and integrate the two evidence channels into the live investigation engine. If it fails, v0.8 remains evidence that proactive Mentalist is useful as a specialist, while `stable-v0.5-live-engine` remains the guaranteed fallback submission.
