# LinkRisk

**Confidence-aware relationship intelligence for coordinated payment fraud detection.**

Razorpay AI Buildathon — Track 2: AI Risk Manager

## Problem
Coordinated fraud can hide across individually legitimate-looking transactions, making the fraud signal invisible to models that score transactions in isolation.

## Solution
LinkRisk turns delayed fraud confirmations into causal relationship memory for future transactions. A transaction-level XGBoost baseline is augmented by a relationship-feedback specialist, but the specialist's influence is confidence-gated. When trustworthy historical relationship evidence is unavailable, LinkRisk falls back exactly to the ML-only score.

## Buildathon novelty
**Confidence-aware relationship augmentation:** use matured historical fraud evidence without blindly trusting incomplete or noisy graph context.

Graph-based fraud detection itself is established. LinkRisk's contribution is the safe, interpretable, gracefully-degrading use of relationship evidence plus honest held-out evaluation.

## Interactive demo
Install dependencies, then launch the judge-facing console:

```bash
streamlit run app.py
```

The demo includes:
- frozen validation metrics loaded from `artifacts/results/policy_impact_validation.json` when available;
- guided ALLOW / VERIFY / REVIEW stories;
- exact cold-start ML fallback;
- a benign shared-context failure case;
- deterministic evidence explanations;
- a local relationship visualization;
- an interactive policy sandbox using the frozen gate and thresholds.

**Demo integrity note:** guided story inputs are illustrative and are passed through the real frozen LinkRisk decision contract. They are not presented as held-out dataset examples. The validation dashboard is read from locally generated experiment artifacts, and the chronological held-out test remains sealed until final evaluation.

## Core experiment
Compare only:
1. **ML-only baseline**
2. **LinkRisk v0.5: ML + delayed relationship feedback specialist + confidence gating**

Headline metrics: precision, recall, PR-AUC, false-positive rate, false-positive cost sensitivity.

## Dataset
IEEE-CIS Fraud Detection. Raw competition data is not committed. Place the original `train_transaction.csv` and `train_identity.csv` under `data/raw/`.

Run the dataset audit:

```bash
python scripts/check_dataset.py
```

> Important: the Kaggle `test_transaction.csv` split has no `isFraud` target and cannot be used for training or held-out evaluation.

## Baseline experiment
The transaction-only baseline deliberately excludes `C*`, `D*`, and `V*` feature families because they already encode historical/count/engineered relational information. The baseline uses raw point-in-time transaction, payment-profile, address/email, match, identity and device/session attributes.

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

## Frozen product policy
The final development policy uses:
- champion: `v0.5`;
- confidence gate strength: `1.00`;
- VERIFY threshold: `0.781202555`;
- REVIEW threshold: `0.8406179547309875`;
- exact baseline fallback when relationship confidence is zero;
- strong matured relationship evidence may force VERIFY, but never REVIEW by itself.

The 6% total intervention figure is a validation calibration target, not a runtime guarantee under distribution shift. Model outputs are risk/ranking scores, not calibrated fraud probabilities.

## Scope
MVP: real fraud dataset; time-based ML baseline; interpretable temporal relationship memory; delayed confirmed-fraud feedback; graph confidence; confidence-gated specialist; graceful ML-only fallback; ALLOW / VERIFY / REVIEW policy; deterministic evidence report; adversarial safeguards; held-out evaluation; lightweight Streamlit demo.

Not MVP: GNN, merchant credit score, complex expected-loss optimizer, production Razorpay integration, or LLM in the decision path.
