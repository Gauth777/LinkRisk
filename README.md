# LinkRisk

**Proactive payment-risk investigation: detect the pattern before the profile becomes known fraud.**

Razorpay AI Buildathon — Track 2: AI Risk Manager

## Product thesis
A transaction can look ordinary in isolation while its short-horizon behavior and local relationships form a suspicious case. LinkRisk therefore keeps three evidence channels conceptually separate:

1. **Transaction intelligence** — the frozen transaction-only XGBoost baseline.
2. **Trusted relationship memory** — delayed adjudicated fraud/legitimate evidence from v0.5.
3. **Mentalist proactive deduction** — label-free velocity, behavior-change, coordination and reuse/churn clues available at decision time.

The final router allocates scarce intervention capacity across these signals. Historical fraud is evidence, never automatic guilt.

## Current development-validation result
The successful Mentalist v1.0 reallocation keeps the same 6% intervention capacity while moving weak VERIFY capacity toward stronger proactive cases:

- Fraud capture: **42.57% → 44.21%** (**+1.64 pp**)
- Legitimate friction: **4.70% → 4.64%** (**−0.06 pp**)
- Novel Mentalist cases added: **519**
- Frauds among those added cases: **50**
- Frauds among the 519 displaced weak v0.5 VERIFY cases: **0**

The per-transaction runtime contract reproduced the successful v1.0 validation action vector with **100.000000% agreement** and zero action mismatches.

> The chronological held-out test remains sealed. These numbers are development-validation evidence, not final held-out performance.

## Architecture

```text
Merchant telemetry ─┐
                    ├─→ FastAPI → LiveLinkRiskEngine
Razorpay payment ────┘               │
     │                              ├── transaction baseline
     ├─ Checkout callback ──────────┤── causal relationship state
     └─ signed webhook ─────────────┤── delayed trusted feedback
React/Vite product UI ←─────────────┤── Mentalist proactive features
                                    └── frozen v1.0 router
                                             ↓
                                  ALLOW / VERIFY / REVIEW
```

`app.py` remains as a Streamlit engineering/debug console. The buildathon product surface is `frontend/` + `backend/api.py`.

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

If the frozen model artifacts are present locally, **New payment** runs the real engine. If they are absent, the UI still opens in clearly-labelled **Preview data** mode so the presentation layer can be reviewed without pretending the model is running.

## Razorpay Test Mode Checkout

The buildathon checkout path intentionally accepts **Test Mode keys only**. Put the credentials in a local `.env` or shell environment; `.env` is git-ignored.

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

Never expose `RAZORPAY_KEY_SECRET` or `RAZORPAY_WEBHOOK_SECRET` to the browser or repository. The Test Key ID is returned to Checkout because Razorpay requires it client-side.

The existing **New payment** flow now performs:

```text
merchant telemetry form
      ↓
POST /api/integrations/razorpay/orders
      ↓
server creates immutable Razorpay Test Order
      ↓
Razorpay Standard Checkout
      ↓
POST /api/integrations/razorpay/payments/verify
      ↓
server verifies payment signature
      ↓
server fetches authoritative Payment entity
      ↓
order + amount + currency cross-check
      ↓
LinkRisk scoring → ALLOW / VERIFY / REVIEW
```

This callback-verification path works during local development even though Razorpay cannot deliver a webhook to `localhost`. Once deployed, the webhook remains the durable retry/event path and payment-id deduplication prevents the same payment from being scored twice.

Checkout status:

```text
GET /api/integrations/razorpay/checkout/status
```

The original direct model simulator remains available programmatically at `POST /api/transactions` for engineering tests.

## Razorpay webhook integration

LinkRisk accepts signed Razorpay payment webhooks at:

```text
POST /api/webhooks/razorpay
```

The endpoint:

- verifies `X-Razorpay-Signature` using HMAC-SHA256 over the **exact raw request body** before JSON parsing,
- uses `x-razorpay-event-id` for event idempotency (with a body-hash fallback if the header is unexpectedly absent),
- accepts `payment.authorized` and `payment.captured`,
- deduplicates those events again by Razorpay payment id so one payment cannot create two LinkRisk transactions,
- normalizes Razorpay amount/method/card/email fields into the current IEEE-CIS-compatible runtime adapter,
- never claims or derives payer IP from the standard Razorpay Payment payload.

Integration status is visible at:

```text
GET /api/integrations/razorpay/status
```

### Merchant telemetry enrichment

Razorpay's standard Payment entity does not provide the browser/device/session context used by LinkRisk's proactive relationship logic. The checkout route automatically registers merchant-observed telemetry against the server-created Razorpay order id. Telemetry can also be registered explicitly at:

```text
POST /api/integrations/razorpay/telemetry
```

If telemetry is absent, LinkRisk uses payment-unique unknown device/browser contexts. It intentionally does **not** collapse missing telemetry into a shared fake device, because that could manufacture coordination evidence.

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

The exact v1.0 runtime policy JSON is source-controlled. The trained model files remain git-ignored.

## Buildathon deployment
The repository includes a multi-stage `Dockerfile` that builds the React app and serves it from the same FastAPI service. This gives us one deployable web service instead of separate frontend/backend infrastructure.

For cloud deployment, package the frozen runtime files above into a ZIP preserving their repository-relative paths and host it at a private or controlled download URL. Configure:

```text
LINKRISK_MODEL_BUNDLE_URL=<https URL to frozen ZIP>
LINKRISK_MODEL_BUNDLE_SHA256=<recommended SHA-256>
RAZORPAY_KEY_ID=<rzp_test_... during buildathon testing>
RAZORPAY_KEY_SECRET=<Test Mode key secret>
RAZORPAY_WEBHOOK_SECRET=<Razorpay webhook secret>
```

At startup, LinkRisk downloads the bundle only when local model assets are absent, optionally verifies its SHA-256, safely extracts it, and refuses scoring if required files are still missing.

A `render.yaml` is included as a deployment starting point. Other Docker hosts (Railway, Fly.io, Cloud Run, etc.) can use the same image.

## Development commands

```bash
pytest -q
cd frontend && npm run build
```

CI runs both checks on `main` and the buildathon feature branches.

## Dataset
The current trained model is calibrated to IEEE-CIS-compatible attributes. Raw competition data is not committed. Put `train_transaction.csv` and `train_identity.csv` under `data/raw/` only for local experiment reproduction.

The live product uses a deterministic demo adapter to map human-readable simulator/merchant inputs into the masked IEEE-compatible fields expected by the frozen model. This is not a claim that masked IEEE fields are literal customer identities.

## Safety / evaluation guardrails
- Same-timestamp transactions cannot see one another.
- Mentalist proactive features consume no fraud labels.
- Adjudicated history becomes usable only after `max(transaction_time + 72h, recorded_at)`.
- v0.5 hard REVIEW remains immutable.
- Mentalist requires corroborating independent clue families and a frozen score boundary.
- Scores are risk/ranking scores, not calibrated fraud probabilities.
- The final held-out test is opened only after the full product/runtime is frozen; no post-test threshold search is allowed.
