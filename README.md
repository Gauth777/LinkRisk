# LinkRisk

**Proactive payment-risk investigation: detect the pattern before the profile becomes known fraud.**

Razorpay AI Buildathon — Track 2: **AI Risk Manager**

**Live demo:** https://linkrisk.onrender.com/

## What LinkRisk does

A payment can look ordinary in isolation while its short-horizon behavior, relationship history and surrounding context form a suspicious case. LinkRisk therefore does not rely on one monolithic fraud score.

It keeps three evidence channels separate:

1. **Transaction intelligence** — a frozen XGBoost transaction-risk baseline.
2. **Trusted relationship memory** — causal relationship features plus delayed adjudicated fraud/legitimate feedback from v0.5.
3. **Mentalist proactive deduction (“Jane”)** — present-tense velocity, behavior-change, coordination and reuse/churn evidence that does **not** consume confirmed-fraud labels.

Historical fraud is evidence, never automatic guilt. Scores are ranking/risk scores, not calibrated fraud probabilities.

> **Jane** is the deliberately playful internal name for the Mentalist investigator: the component that looks for a constellation of weak clues before a profile is already known fraud.

## Product architecture

```text
Razorpay Test payment + merchant telemetry
                    │
                    ▼
          Transaction baseline
                    │
                    ▼
       Trusted-memory v0.5 layer
                    │
          ┌─────────┴─────────┐
          │                   │
   mandatory REVIEW      other traffic
   remains immutable          │
                              ▼
                     Cheap evidence gate
                       /             \
               ordinary             evidence-bearing
                  │                        │
                  │                        ▼
                  │                  Jane / Mentalist
                  │                  investigator
                  │                        │
                  └─────────────┬──────────┘
                                ▼
                      Cost-aware v2 router
                 frozen thresholds + live capacity
                                │
                     ┌──────────┼──────────┐
                     ▼          ▼          ▼
                   ALLOW      VERIFY     REVIEW
```

The live v2 runtime uses **selective inference** and causal/stateful capacity accounting:

- sustained total intervention rate: **6%**;
- sustained Mentalist reserve: **1%**;
- bounded cold-start burst capacity;
- v0.5 REVIEW is mandatory and is never downgraded because capacity is exhausted;
- Mentalist is invoked only for eligible evidence-bearing cases rather than every transaction.

The buildathon product surface is `frontend/` + `backend/api.py`. `app.py` remains an engineering/debug console.

## Why selective reasoning?

The development experiment showed that Mentalist did not need to run on most traffic:

- Mentalist invoked: **2.27%**
- Mentalist bypassed: **97.73%**
- intervention held at **6.00%**
- precision: **24.37% → 25.31%**
- fraud capture: **42.57% → 44.21%**
- FPR: **4.6973% → 4.6412%**
- TP / FP delta: **+50 / −48**

This is **development validation**, not a new held-out claim.

## Evaluation status

### v1.0 final chronological held-out evaluation — opened once, frozen

The one-shot held-out partition contained **88,581 transactions** with **3,083 frauds (3.48%)**. No fitting or threshold selection occurred on this test partition.

| System | Precision | Recall / capture | PR-AUC | FPR | Intervention |
| --- | ---: | ---: | ---: | ---: | ---: |
| Transaction baseline hard detector | 49.81% | 21.08% | 0.2873 | 0.7661% | — |
| v0.5 hard REVIEW | 49.10% | 23.09% | 0.3132 | 0.8632% | — |
| Stable v0.5 operational | 21.64% | 35.61% | — | 4.6516% | 5.73% |
| Final v1.0 Mentalist-routed | 17.44% | 38.50% | — | 6.5744% | 7.69% |

Final v1.0 confusion matrix: **TP / FP / TN / FN = 1,187 / 5,621 / 79,877 / 1,896**.

Mentalist produced a net **+89 frauds captured** over stable v0.5, but validation-calibrated routing expanded intervention from **5.73% to 7.69%** under later temporal traffic. That capacity drift is treated as a real temporal policy-calibration finding, not tuned away on the same held-out set.

**The v1.0 held-out result is final and is not reused for v2 tuning.**

### v2 cost-aware selective investigation — development validation only

v2 was designed after observing the v1.0 capacity drift. The old final set is therefore spent and is not relabelled as an unbiased v2 evaluation.

See [`docs/evaluation_results.md`](docs/evaluation_results.md) for the complete evaluation ledger.

## Challengers we rejected

More sophisticated was not automatically better. Post-final-test experiments stayed development-only and were rejected when they failed to improve the frozen baseline.

| Challenger | Development result | Decision |
| --- | --- | --- |
| AutoGluon challenger | Effective ensemble collapsed to XGBoost; PR-AUC **0.3413** vs frozen baseline **0.3496** | **REJECT** |
| Heterogeneous GraphSAGE | Same-slice PR-AUC **0.1452** vs baseline **0.4019** | **REJECT** |
| Causal graph-feature + XGBoost fusion | PR-AUC **0.3613** vs same-slice frozen baseline **0.4019**; also lost recall | **REJECT** |

The conclusion is intentionally conservative: on the tested IEEE-CIS development protocols, these challengers did not earn their additional complexity. The useful gains came from **trusted delayed evidence, selective behavioral reasoning and capacity-aware routing**.

## Razorpay Test Mode integration

The deployed demo uses Razorpay **Test Mode**. No real money is involved.

The primary checkout path is:

```text
merchant telemetry
      ↓
POST /api/integrations/razorpay/orders
      ↓
server creates Razorpay Test Order
      ↓
Razorpay Standard Checkout
      ↓
POST /api/integrations/razorpay/payments/verify
      ↓
server verifies checkout signature
      ↓
fetch authoritative Razorpay Payment
      ↓
order + amount + currency + status checks
      ↓
LinkRisk scoring → ALLOW / VERIFY / REVIEW
```

The backend also implements an **optional signed webhook ingestion path** at:

```text
POST /api/webhooks/razorpay
```

When configured, it:

- verifies `X-Razorpay-Signature` over the exact raw request body;
- accepts `payment.authorized` and `payment.captured`;
- deduplicates events and Razorpay payment IDs;
- normalizes payment metadata into the current runtime adapter.

The public buildathon deployment currently relies on the working checkout-verification path; webhook support exists in code but is not required for the demo.

Razorpay's standard Payment entity does not expose all browser/device/session context needed by LinkRisk. That context comes from merchant-observed telemetry. LinkRisk does not invent payer IP or reinterpret masked IEEE fields as literal identities.

## Run locally

### 1. API

```bash
python -m pip install -r requirements.txt
uvicorn backend.api:app --reload --port 8000
```

### 2. React product UI

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). Vite proxies `/api` to FastAPI.

## Environment variables

For Razorpay Test Mode checkout:

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
```

Optional webhook verification:

```text
RAZORPAY_WEBHOOK_SECRET=...
```

Cloud model-bundle bootstrap:

```text
LINKRISK_MODEL_BUNDLE_URL=<https URL to frozen ZIP>
LINKRISK_MODEL_BUNDLE_SHA256=<SHA-256 of that ZIP>
```

Never expose API secrets or webhook secrets to the browser or repository.

## Frozen runtime assets

Raw IEEE-CIS data and trained model binaries are intentionally not committed.

The runtime expects:

```text
artifacts/models/baseline_preprocessor.joblib
artifacts/models/baseline_xgboost.joblib
artifacts/models/feedback_specialist_v5.joblib
artifacts/models/mentalist_v7_candidate.joblib
artifacts/results/baseline_features.json
artifacts/results/mentalist_v7_validation.json
artifacts/results/mentalist_runtime_policy.json
```

The exact policy metadata is source-controlled. Trained model binaries remain git-ignored and are loaded from the frozen deployment bundle when absent locally.

## Dataset

The current trained model and feature adapter are calibrated to **IEEE-CIS-compatible transaction attributes**. Raw competition data is not committed.

For experiment reproduction, place:

```text
data/raw/train_transaction.csv
data/raw/train_identity.csv
```

The engine architecture is conceptually dataset-independent; the currently trained weights and adapter are not.

## Reproduction / checks

```bash
pytest -q
cd frontend && npm run build
```

Key development-only experiments:

```bash
python scripts/evaluate_cost_aware_v2.py
python scripts/evaluate_autogluon_challenger.py
python scripts/evaluate_gnn_signal_feasibility.py
python scripts/evaluate_graph_xgb_fusion.py
```

Do **not** rerun or retune against the old v1.0 final held-out partition.

## Safety and evaluation guardrails

- Same-timestamp transactions cannot see one another.
- Point-in-time relationship features use only information available before the current decision.
- Mentalist proactive features consume no confirmed-fraud labels.
- Adjudicated history becomes usable only after `max(transaction_time + 72h, recorded_at)`.
- v0.5 hard REVIEW remains immutable.
- Correlated signals do not count as independent evidence families.
- Confidence means independent evidence support, not fraud probability.
- Model scores are ranking/risk scores, not calibrated probabilities.
- v1.0 final held-out evaluation is immutable.
- v2 and all later challengers remain labelled development validation until evaluated on a new untouched source.

## Project status

- ✅ Frozen transaction baseline
- ✅ Trusted delayed-memory specialist
- ✅ Jane / Mentalist selective investigator
- ✅ Cost-aware v2 live router
- ✅ React + FastAPI product UI
- ✅ Razorpay Test Mode checkout + server verification
- ✅ Render deployment
- ✅ Rejected-challenger ledger
- ⏳ New untouched evaluation source for unbiased v2 generalization
