# LinkRisk

**Detect the payment. Investigate the relationships.**

Razorpay AI Buildathon — Track 2: **AI Risk Manager**

**Live demo:** https://linkrisk.onrender.com/

LinkRisk is a defensive two-stage payment-risk system for **coordinated payment fraud**: fraud that can look ordinary when each transaction is scored independently.

```text
PAYMENT
   ↓
Frozen v0.5 scoring
(transaction intelligence + causal relationship features + matured trusted feedback)
   ↓
v0.5 operational action
   ├── REVIEW ───────────────→ hard detector positive
   ├── VERIFY ───────────────→ v0.5 verification routing
   └── ALLOW
         ↓
   cheap evidence gate
      ├── bypass ────────────→ ALLOW
      └── evidence-bearing ──→ Jane / Mentalist verifier
                                  ↓
                              ALLOW / VERIFY
                                  ↓
                         merchant risk queue
                                  ↓
                         analyst resolution
                                  ↓
                      fixed delayed merchant memory
```

The distinction is deliberate:

- **REVIEW** = hard detector positive;
- **VERIFY** = additional defensive verification / investigation, not a fraud conviction;
- **Jane** = the central relationship-aware verifier for evidence-bearing cases below the hard REVIEW boundary that a transaction-only view may miss.

The complete metric and claim contract is frozen in [`docs/SUBMISSION_CONTRACT.md`](docs/SUBMISSION_CONTRACT.md).

## Track 2 fit

Razorpay asks for a working defensive detector, verifier or auto-responder for one class of loss, with measured precision and recall on a held-out test set and honest false-positive cost.

LinkRisk provides both a **detector** and a **verifier** for one loss class:

> **Coordinated payment fraud that can be missed by transaction-only scoring.**

### 1. Measured hard detector

The frozen v0.5 hard `REVIEW` boundary is the headline metric-bearing detector. It remains unchanged inside the deployed stack.

The one-shot chronological held-out partition contained **88,581 transactions** with **3,083 frauds (3.48%)**. Models and thresholds were frozen before test outcomes were opened.

| Frozen hard detector | Precision | Recall | PR-AUC | FPR |
| --- | ---: | ---: | ---: | ---: |
| Transaction-only baseline | 49.81% | 21.08% | 0.2873 | 0.7661% |
| **LinkRisk v0.5 hard REVIEW** | **49.10%** | **23.09%** | **0.3132** | **0.8632%** |

The relationship/trusted-memory risk layer therefore improved held-out recall from **21.08% → 23.09%** and PR-AUC from **0.2873 → 0.3132** while retaining approximately 49% precision.

These are population-level detector metrics. LinkRisk scores are ranking / risk scores, **not calibrated fraud probabilities**.

### 2. Jane — the relationship-aware verifier

Jane / Mentalist is the core differentiated layer in LinkRisk.

A transaction can score below the hard REVIEW boundary while its surrounding behavior still shows multiple independent clues. Jane evaluates present-tense evidence families including:

- velocity;
- behavior change;
- coordination;
- reuse / churn.

Jane's proactive features do **not** consume confirmed-fraud labels.

In the deployed selective runtime, automatic Jane inference is reserved for **evidence-bearing v0.5 `ALLOW` rows**. Existing v0.5 `REVIEW` decisions remain immutable, and v0.5 `VERIFY` cases do not require Jane in order to remain verification candidates.

#### Jane v1 — held-out evidence

The original Mentalist-routed policy was evaluated on the same one-shot chronological held-out set.

Compared with stable v0.5 operational routing:

- fraud capture increased **35.61% → 38.50%**;
- Jane produced a net **+89 frauds captured**.

That first routing policy also increased false-positive/intervention cost. The broad `VERIFY + REVIEW` queue measured:

- precision: **17.44%**;
- FPR: **6.5744%**;
- intervention share: **7.69%**.

We report that trade-off rather than hiding it. The result showed that Jane had useful fraud signal, while the original routing policy needed better friction control.

#### Jane v2 — selective redesign, development validation

After the v1 held-out result exposed capacity drift, Jane was redesigned as a selective verifier.

At the **same 6.00% intervention share** on development validation:

| Metric | Stable v0.5 | Selective Jane v2 | Delta |
| --- | ---: | ---: | ---: |
| Precision | 24.37% | **25.31%** | **+0.93 pp** |
| Recall / fraud capture | 42.57% | **44.21%** | **+1.64 pp** |
| FPR | 4.6973% | **4.6412%** | **−0.06 pp** |
| TP | 1,295 | **1,345** | **+50** |
| FP | 4,018 | **3,970** | **−48** |

Jane was invoked on only **2.27%** of development-validation traffic and bypassed on **97.73%**.

These v2 figures are **development validation only**. The original held-out partition had already been opened and is not reused as a fresh v2 test.

**Runtime note:** the **6.00% intervention share is the fixed development-validation comparison budget**, not a claim that the current streaming demo hard-caps every session at exactly 6%. In the deployed runtime, capacity remains observable, but a case that crosses Jane's frozen verifier boundary is not downgraded solely because the small live reserve is exhausted; the overflow is recorded instead.

## Action semantics

```text
ALLOW
  No sufficient evidence for intervention.

VERIFY
  Additional defensive verification / investigation is warranted.
  Jane can create this action from corroborated relationship evidence.
  VERIFY is not a fraud-positive verdict.

REVIEW
  Frozen hard detector positive.
  High-priority risk review is warranted.
```

This is how LinkRisk handles false-positive cost operationally: not every suspicious transaction is treated as a confirmed fraud or automatic decline.

## Why LinkRisk is different

A common hackathon fraud stack ends at:

```text
CSV → classifier → fraud score → dashboard
```

LinkRisk implements a complete defensive loop:

```text
                         LINKRISK

                 Razorpay Test Checkout
                          │
                          ▼
            server verifies Checkout signature
                          │
                          ▼
             fetch authoritative Payment
                          │
               ┌──────────┴───────────┐
               │                      │
               ▼                      ▼
    privacy-safe recurring      merchant-observed
       HMAC identity               telemetry
               │                      │
               └──────────┬───────────┘
                          ▼
                 LiveTransactionInput
                          │
                          ▼
        ┌─────────────────────────────────┐
        │       FROZEN v0.5 SCORER        │
        │                                 │
        │ transaction intelligence        │
        │ + causal relationship features  │
        │ + matured trusted feedback      │
        └────────────────┬────────────────┘
                         │
                v0.5 operational action
                         │
            ┌────────────┼─────────────┐
            ▼            ▼             ▼
         REVIEW        VERIFY         ALLOW
            │            │              │
            │            │       cheap evidence gate
            │            │          ┌───┴────┐
            │            │          │        │
            │            │       bypass     Jane
            │            │                    │
            │            │          relationship-aware
            │            │              verifier
            │            │                    │
            │            │               ALLOW / VERIFY
            └────────────┴──────────────┬─────┘
                                       ▼
                              merchant risk queue
                                       │
                              ALLOW / VERIFY / REVIEW
                                       │
                                       ▼
                              analyst adjudication
                              fraud / legitimate
                                       │
                                       ▼
                              fixed 72h trust delay
                                       │
                                       ▼
                         persistent merchant memory
                              Supabase-backed
                                       │
                                       └────► future payments
```

Conceptually:

```text
DETECT → INVESTIGATE → VERIFY → RESOLVE → REMEMBER
```

Key product capabilities:

- frozen XGBoost transaction baseline;
- causal relationship features;
- trusted delayed merchant feedback;
- Jane / Mentalist relationship-aware verification;
- independent evidence-family gating;
- causal relationship-network visualization;
- analyst-requested Jane second opinions;
- explicit operator escalation;
- persistent Supabase-backed operational ledger;
- Razorpay Test Mode checkout and server-side verification;
- privacy-safe recurring customer context derived server-side;
- ALLOW / VERIFY / REVIEW case management;
- false-positive and intervention telemetry.

Historical fraud is evidence, never automatic guilt.

## False-positive cost

The challenge explicitly asks for honest false-positive cost, so LinkRisk exposes it at two levels:

- a false positive at `REVIEW` is a legitimate payment sent to high-priority risk review;
- a false positive at `VERIFY` is generally an unnecessary verification / investigation step, not necessarily a decline.

The final held-out evaluator also records false-positive cost sensitivity scenarios. See [`docs/evaluation_results.md`](docs/evaluation_results.md).

## Evaluation boundary

### Untouched held-out claims

- hard REVIEW detector: **49.10% precision, 23.09% recall, 0.8632% FPR**;
- v1 broader Mentalist policy: **38.50% fraud capture**, with the full false-positive cost reported;
- Jane v1 net contribution: **+89 frauds captured** versus stable v0.5.

### Development-only claims

The selective Jane v2 results are development validation:

- **+50 TP / −48 FP**;
- precision **24.37% → 25.31%**;
- recall **42.57% → 44.21%**;
- FPR **4.6973% → 4.6412%**;
- same **6.00%** intervention share;
- Jane invoked on **2.27%** of transactions.

We do not relabel these figures as new held-out performance.

## Razorpay Test Mode integration

The deployed demo uses Razorpay **Test Mode**. No real money is involved.

```text
merchant context
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
privacy-safe identity + LinkRisk scoring / verification
```

An optional signed webhook ingestion path also exists at `POST /api/webhooks/razorpay`.

Razorpay's standard Payment entity does not expose all browser/device/session context used by LinkRisk. Additional context comes from merchant-observed telemetry. LinkRisk does not invent payer IP or reinterpret masked IEEE fields as literal identities.

## Privacy and merchant memory

Persistent operational state is server-side. After Razorpay Checkout verification, recurring risk identity is derived from the **authoritative Razorpay Payment**, not a client-controlled profile name:

1. stable HMAC contact/phone token when available;
2. otherwise a stable HMAC email token;
3. otherwise a customer/payment-specific HMAC fallback.

Raw phone numbers and emails do not enter the risk graph/model identity field, and newly persisted integration metadata does not copy legacy client `payment_profile` values as payer identity.

Adjudicated outcomes do not become trusted immediately. The feedback layer applies the frozen delayed-trust rule before confirmed outcomes can influence future related transactions.

## Architecture safety rules

- Defense-only payment-risk functionality.
- Same-timestamp transactions cannot see one another.
- Point-in-time relationship features use only information available before the current decision.
- Mentalist proactive features consume no confirmed-fraud labels.
- Correlated signals do not count as independent evidence families.
- v0.5 hard REVIEW remains immutable.
- Scores are ranking signals, not calibrated probabilities.
- Operator overrides are kept separate from the original model decision.
- The v1 held-out evaluation is immutable and is not retuned.
- Missing payer device/browser telemetry is represented as payment-unique unknown context rather than fabricated shared identity.

## Repository architecture

```text
frontend/          React merchant risk console and cinematic product entry
backend/           FastAPI, Razorpay integration, Supabase persistence and operations
src/linkrisk/      ML scoring, causal relationship features, Jane and live routing
tests/             Runtime, integration, privacy and safety regression tests
docs/              Evaluation ledger, failure modes and frozen submission contract
.github/workflows/ Product CI
```

Important implementation files include:

```text
src/linkrisk/live_engine_v2.py
src/linkrisk/relationship_features_v4.py
src/linkrisk/feedback_features_v5.py
src/linkrisk/mentalist_features_v7.py
src/linkrisk/cost_aware_router_v2.py
backend/api.py
backend/razorpay_checkout.py
backend/razorpay_integration.py
backend/supabase_store.py
backend/jane_operations.py
```

## Reproduction

### API

```bash
python -m pip install -r requirements.txt
uvicorn backend.api:app --reload --port 8000
```

### React product

```bash
cd frontend
npm install
npm run dev
```

### Checks

```bash
pytest -q
cd frontend && npm run build
```

## Environment variables

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
LINKRISK_IDENTITY_SECRET=...
LINKRISK_ADMIN_TOKEN=...      # optional operator protection
```

Optional deployment/model settings:

```text
RAZORPAY_WEBHOOK_SECRET=...
LINKRISK_MODEL_BUNDLE_URL=<https URL to frozen ZIP>
LINKRISK_MODEL_BUNDLE_SHA256=<SHA-256>
```

Never expose server secrets to the browser or repository.

## Frozen runtime assets

The runtime expects the frozen artifact bundle containing:

```text
artifacts/models/baseline_preprocessor.joblib
artifacts/models/baseline_xgboost.joblib
artifacts/models/feedback_specialist_v5.joblib
artifacts/models/mentalist_v7_candidate.joblib
artifacts/results/baseline_features.json
artifacts/results/mentalist_v7_validation.json
artifacts/results/mentalist_runtime_policy.json
```

Raw IEEE-CIS data and trained binary artifacts are not committed.

## Key documentation

- [`docs/SUBMISSION_CONTRACT.md`](docs/SUBMISSION_CONTRACT.md) — exact judge-facing metric/claim contract
- [`docs/evaluation_results.md`](docs/evaluation_results.md) — complete evaluation ledger
- [`docs/product_thesis.md`](docs/product_thesis.md) — product positioning
- [`docs/FAILURE_MODES.md`](docs/FAILURE_MODES.md) — known limitations and safety boundaries

## Project status

- ✅ one-shot chronological held-out evaluation
- ✅ measured relationship-aware hard REVIEW detector
- ✅ Jane / Mentalist relationship-aware verifier
- ✅ v1 held-out Jane contribution reported with FP cost
- ✅ selective Jane v2 development validation
- ✅ trusted delayed merchant memory
- ✅ analyst investigation and operator escalation
- ✅ React + FastAPI product
- ✅ Razorpay Test Mode checkout verification
- ✅ privacy-safe authoritative-payment recurring identity
- ✅ Supabase-backed persistent operational ledger
- ✅ Render deployment
- ⏳ new untouched evaluation source for unbiased post-v1 orchestration generalization

## One-line thesis

> **A fraud detector scores a payment. LinkRisk also investigates the relationships around it: REVIEW is our measured hard detector, while Jane is our relationship-aware verifier for suspicious cases a transaction-only view can miss.**
