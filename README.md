# LinkRisk

**Confidence-aware relationship intelligence for coordinated payment fraud detection.**

Razorpay AI Buildathon — Track 2: AI Risk Manager

## Problem
Coordinated fraud can hide across individually legitimate-looking transactions, making the fraud signal invisible to models that score transactions in isolation.

## Solution
LinkRisk augments a transaction-level ML model with interpretable temporal relationship signals and confidence-gates their influence. When graph evidence is sparse or unreliable, the system gracefully degrades toward the ML-only score.

## Buildathon novelty
**Confidence-aware graph augmentation:** detect fraud between transactions without blindly trusting incomplete relationship data.

Graph-based fraud detection itself is established. LinkRisk's contribution is the safe, interpretable, gracefully-degrading use of relationship evidence plus honest held-out evaluation.

## Core experiment
Compare only:
1. **ML-only baseline**
2. **ML + confidence-gated graph augmentation**

Headline metrics: precision, recall, PR-AUC, false-positive rate, false-positive cost sensitivity.

## Dataset
IEEE-CIS Fraud Detection. Raw competition data is not committed. Place the original `train_transaction.csv` and `train_identity.csv` under `data/raw/`.

Run the dataset audit:

```bash
python scripts/check_dataset.py
```

> Important: the Kaggle `test_transaction.csv` split has no `isFraud` target and cannot be used for training or held-out evaluation.

## Baseline experiment
The initial transaction-only baseline deliberately excludes `C*`, `D*`, and `V*` feature families because they already encode historical/count/engineered relational information. The baseline uses raw point-in-time transaction, payment-profile, address/email, match, identity and device/session attributes.

Run:

```bash
python scripts/train_baseline.py
```

The script:
- uses the chronological 70/15/15 split;
- trains on the first 70%;
- selects its operating threshold on the 15% validation period;
- keeps the final 15% test period unevaluated;
- uses a 1% validation false-positive-rate budget as the initial operating constraint;
- writes validation metrics and the exact frozen feature list under `artifacts/results/`.

The held-out test set must not be evaluated until the graph-enhanced system and comparison protocol are frozen.

## Live engine demo
LinkRisk is not only an offline IEEE-CIS analysis. The Streamlit console runs a **stateful transaction engine** around the frozen v0.5 champion:

1. submit an incoming payment;
2. score it with the frozen transaction baseline;
3. reconstruct causal relationship features from earlier session transactions;
4. reconstruct delayed confirmed-fraud feedback using the same fixed 72-hour assumption as v0.5;
5. run the frozen relationship specialist and confidence gate;
6. return `ALLOW`, `VERIFY`, or `REVIEW` with deterministic evidence;
7. optionally adjudicate a transaction and let that outcome become relationship memory for later payments.

Launch:

```bash
streamlit run app.py
```

The live form is a **model-compatible simulator adapter**. A human-readable payment-profile identifier is deterministically mapped into stable masked card/address-style fields so repeated simulator profiles generate consistent relationship keys. This is not a claim that IEEE-CIS masked fields are literal customer identities.

The local network shown in the investigator is reconstructed from the actual session history and the relationship keys used by the model. Same-timestamp payments do not see one another, and an adjudicated outcome cannot influence future fraud memory before the frozen 72-hour delay.

The trained artifacts remain IEEE-CIS-specific. A separate batch/schema adapter for user-provided datasets is planned; the runtime architecture is designed so that adapter can feed the same live scoring engine without changing the frozen decision policy.

## Scope
MVP: real fraud dataset; time-based ML baseline; interpretable temporal relationship features; delayed confirmed-fraud memory; graph confidence; confidence-gated fusion; exact ML-only fallback; `ALLOW` / `VERIFY` / `REVIEW`; deterministic evidence; stateful live demo; local relationship visualization; held-out evaluation; adversarial failure cases.

Not MVP: GNN, merchant credit score, complex expected-loss optimizer, production Razorpay integration, LLM in the decision path.
