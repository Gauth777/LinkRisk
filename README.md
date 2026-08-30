# LinkRisk

**Proactive payment-risk investigation: detect the pattern before the profile becomes known fraud.**

Razorpay AI Buildathon — Track 2: AI Risk Manager

## Product thesis
A transaction can look ordinary in isolation while its short-horizon behavior and local relationships form a suspicious case. LinkRisk keeps three evidence channels conceptually separate:

1. **Transaction intelligence** — the frozen transaction-only XGBoost baseline.
2. **Trusted relationship memory** — delayed adjudicated fraud/legitimate evidence from v0.5.
3. **Mentalist proactive deduction** — label-free velocity, behavior-change, coordination and reuse/churn clues available at decision time.

Historical fraud is evidence, never automatic guilt. Risk scores are ranking scores, not calibrated fraud probabilities.

## Evaluation status

### v1.0 final held-out result — frozen

The one-shot chronological held-out set contained **88,581 transactions** with **3,083 frauds (3.48%)**. No model fitting or threshold selection occurred on test, and test outcomes were excluded from all prediction features.

**Baseline hard detector**
- Precision: **49.81%**
- Recall: **21.08%**
- PR-AUC: **0.2873**
- FPR: **0.7661%**

**v0.5 hard REVIEW detector**
- Precision: **49.10%**
- Recall: **23.09%**
- PR-AUC: **0.3132**
- FPR: **0.8632%**

**Stable v0.5 operational policy**
- Precision: **21.64%**
- Fraud capture: **35.61%**
- FPR: **4.6516%**
- Intervention share: **5.73%**

**Final LinkRisk v1.0 — Mentalist routed**
- Precision: **17.44%**
- Fraud capture: **38.50%**
- FPR: **6.5744%**
- Intervention share: **7.69%**
- TP / FP / TN / FN: **1,187 / 5,621 / 79,877 / 1,896**

Mentalist produced a net **+89 frauds captured** versus stable v0.5, but the validation-calibrated scalar routing boundaries expanded intervention by **1,733 rows** under later temporal traffic. That capacity drift is treated as a real distribution-shift/policy-calibration finding and is not tuned away on the same held-out set.

**The v1.0 held-out result is final. Do not retune on this test set.**

### v2 cost-aware selective investigation — development validation only

v2 is a post-test engineering response, so the old v1.0 held-out set is not reused for an unbiased v2 claim.

The v2 development design adds:
- a cheap evidence-family gate before Mentalist inference;
- Mentalist only for structurally interesting v0.5-ALLOW cases;
- an explicit 6% batch intervention budget;
- immutable v0.5 REVIEW;
- a fixed 1% Mentalist reservation, with remaining capacity filled by strongest v0.5 VERIFY cases.

Development validation:
- Mentalist invoked: **2.27%** of transactions
- Mentalist bypassed: **97.73%**
- Intervention: **6.00% → 6.00%**
- Precision: **24.37% → 25.31%** (**+0.93 pp**)
- Recall / fraud capture: **42.57% → 44.21%** (**+1.64 pp**)
- FPR: **4.6973% → 4.6412%** (**−0.06 pp**)
- TP / FP delta: **+50 / −48**

This is development evidence for selective reasoning and explicit capacity control, not a new held-out result. See [`docs/evaluation_results.md`](docs/evaluation_results.md) for the evaluation ledger.

## Architecture

```text
Merchant telemetry ─┐
                    ├─→ FastAPI → LiveLinkRiskEngine
Razorpay payment ────┘               │
     │                              ├── transaction baseline
     ├─ Checkout callback ──────────┤── causal relationship state
     └─ signed webhook ─────────────┤── delayed trusted feedback
React/Vite product UI ←─────────────┤── Mentalist proactive features
                                    └── frozen runtime routing
                                             ↓
                                  ALLOW / VERIFY / REVIEW
```

The current live product still uses the frozen v1.0 per-transaction runtime contract. The v2 batch/development controller is merged as a separate cost-aware design; a streaming version must use causal/stateful capacity accounting rather than future-aware whole-batch ranking.

`app.py` remains a Streamlit engineering/debug console. The buildathon product surface is `frontend/` + `backend/api.py`.

## Run the product locally

### 1. Python API

```bash
python -m pip install -r requirements.txt
uvicorn backend.api:app --reload --port 8000
```

### 2. React UI

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). Vite proxies `/api` to FastAPI.

If the frozen model artifacts are present locally, **New payment** runs the real engine. If they are absent, the UI opens in clearly-labelled preview mode.

## Razorpay Test Mode Checkout

The buildathon checkout path accepts **Test Mode keys only**. Put credentials in a local `.env` or shell environment; `.env` is git-ignored.

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

Never expose `RAZORPAY_KEY_SECRET` or `RAZORPAY_WEBHOOK_SECRET` to the browser or repository.

The New payment flow performs:

```text
merchant telemetry form
      ↓
POST /api/integrations/razorpay/orders
      ↓
server creates Razorpay Test Order
      ↓
Razorpay Standard Checkout
      ↓
POST /api/integrations/razorpay/payments/verify
      ↓
server verifies signature and fetches authoritative Payment
      ↓
order + amount + currency cross-check
      ↓
LinkRisk scoring → ALLOW / VERIFY / REVIEW
```

The callback-verification path works during local development. Once deployed, the webhook remains the durable retry/event path and payment-id deduplication prevents duplicate scoring.

## Razorpay webhook integration

LinkRisk accepts signed Razorpay payment webhooks at:

```text
POST /api/webhooks/razorpay
```

The endpoint:
- verifies `X-Razorpay-Signature` using HMAC-SHA256 over the exact raw request body;
- uses `x-razorpay-event-id` for event idempotency with a body-hash fallback;
- accepts `payment.authorized` and `payment.captured`;
- deduplicates by Razorpay payment id;
- normalizes payment fields into the current IEEE-CIS-compatible runtime adapter;
- never claims or derives payer IP from the standard Razorpay Payment payload.

Razorpay's standard Payment entity does not provide the browser/device/session context used by LinkRisk's proactive relationship logic. Merchant-observed telemetry supplies that context. Missing telemetry uses payment-unique unknown contexts rather than a shared fake device.

## Frozen runtime assets
Raw IEEE-CIS data and trained model binaries are intentionally not committed.

Local runtime expects:

```text
artifacts/models/baseline_preprocessor.joblib
artifacts/models/baseline_xgboost.joblib
artifacts/models/feedback_specialist_v5.joblib
artifacts/models/mentalist_v7_candidate.joblib
artifacts/results/baseline_features.json
artifacts/results/mentalist_v7_validation.json
artifacts/results/mentalist_runtime_policy.json
```

The exact runtime policy JSON is source-controlled. Trained model files remain git-ignored.

## Buildathon deployment
The repository includes a multi-stage `Dockerfile` that builds the React app and serves it from the same FastAPI service.

For cloud deployment, package the frozen runtime files into a ZIP preserving repository-relative paths and configure:

```text
LINKRISK_MODEL_BUNDLE_URL=<https URL to frozen ZIP>
LINKRISK_MODEL_BUNDLE_SHA256=<recommended SHA-256>
RAZORPAY_KEY_ID=<rzp_test_...>
RAZORPAY_KEY_SECRET=<Test Mode key secret>
RAZORPAY_WEBHOOK_SECRET=<Razorpay webhook secret>
```

At startup, LinkRisk downloads the bundle only when local model assets are absent, optionally verifies SHA-256, safely extracts it, and refuses scoring if required files remain missing.

## Development commands

```bash
pytest -q
cd frontend && npm run build
```

CI runs both checks on `main` and feature branches.

Development-only v2 evaluation:

```bash
python scripts/evaluate_cost_aware_v2.py
```

Do **not** use the old v1.0 held-out set to tune or validate v2.

## Dataset
The current trained model is calibrated to IEEE-CIS-compatible attributes. Raw competition data is not committed. Put `train_transaction.csv` and `train_identity.csv` under `data/raw/` only for local experiment reproduction.

The live product uses a deterministic demo adapter to map human-readable simulator/merchant inputs into masked IEEE-compatible fields expected by the frozen model. This is not a claim that masked IEEE fields are literal customer identities.

## Safety / evaluation guardrails
- Same-timestamp transactions cannot see one another.
- Mentalist proactive features consume no fraud labels.
- Adjudicated history becomes usable only after `max(transaction_time + 72h, recorded_at)`.
- v0.5 hard REVIEW remains immutable.
- Correlated signals do not count as independent evidence families.
- Scores are risk/ranking scores, not calibrated fraud probabilities.
- v1.0 final held-out evaluation is immutable and is not reused for v2 tuning.
- v2 development results must remain labelled development validation until a new untouched evaluation source exists.
