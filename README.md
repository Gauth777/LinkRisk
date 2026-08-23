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

## Dataset candidate
IEEE-CIS Fraud Detection. Raw competition data is not committed. Place the original `train_transaction.csv` and `train_identity.csv` under `data/raw/`, then run `python scripts/check_dataset.py`.

> Important: the Kaggle `test_transaction.csv` split has no `isFraud` target and cannot be used for training or held-out evaluation.

## Scope
MVP: real fraud dataset; time-based ML baseline; interpretable temporal graph heuristics; graph confidence; confidence-gated fusion; graceful ML-only fallback; risk bands; deterministic evidence report; held-out evaluation; one failure case; lightweight demo.

Not MVP: GNN, merchant credit score, complex expected-loss optimizer, four-model benchmark, production Razorpay integration, LLM in the decision path.
