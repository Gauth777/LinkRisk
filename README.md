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

## Scope
MVP: real fraud dataset; time-based ML baseline; interpretable temporal graph heuristics; graph confidence; confidence-gated fusion; graceful ML-only fallback; risk bands; deterministic evidence report; held-out evaluation; one failure case; lightweight demo.

Not MVP: GNN, merchant credit score, complex expected-loss optimizer, four-model benchmark, production Razorpay integration, LLM in the decision path.
