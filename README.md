# LinkRisk

**Relationship-aware payment fraud detection and defensive verification.**

Razorpay AI Buildathon — Track 2: **AI Risk Manager**

**Live demo:** https://linkrisk.onrender.com/

## Track 2 fit

Razorpay asks for a working defensive detector, verifier or auto-responder for one class of loss, with measured precision and recall on a held-out test set and honest false-positive cost.

LinkRisk targets one loss class:

> **Coordinated payment fraud that can look ordinary when transactions are scored independently.**

The product separates a measured hard fraud detector from a broader defensive verification layer:

```text
ALLOW
  no sufficient evidence for intervention

VERIFY
  additional verification / investigation is warranted
  not a fraud-positive verdict

REVIEW
  frozen hard detector positive
  high-priority risk review
```

The complete metric/claim contract is frozen in [`docs/SUBMISSION_CONTRACT.md`](docs/SUBMISSION_CONTRACT.md).

## Headline held-out detector result

The **frozen v0.5 hard REVIEW boundary** is LinkRisk's official metric-bearing detector. It remains unchanged inside the deployed product.

The one-shot chronological held-out partition contained **88,581 transactions** with **3,083 frauds (3.48%)**. Models and thresholds were frozen before the test labels were opened.

| Frozen hard detector | Precision | Recall | PR-AUC | FPR |
| --- | ---: | ---: | ---: | ---: |
| Transaction-only baseline | 49.81% | 21.08% | 0.2873 | 0.7661% |
| **LinkRisk v0.5 hard REVIEW** | **49.10%** | **23.09%** | **0.3132** | **0.8632%** |

The relationship/trusted-memory layer therefore increased hard-detector recall from **21.08% → 23.09%** and PR-AUC from **0.2873 → 0.3132** while retaining approximately 49% precision.

**Important:** these are population-level held-out metrics. LinkRisk scores are ranking/risk scores, not calibrated fraud probabilities.

## Why VERIFY exists

Fraud operations should not force every suspicious case into an approve/decline binary.

LinkRisk uses `VERIFY` as an intermediate defensive action for transactions that deserve additional verification or investigation but have not crossed the hard `REVIEW` detector boundary.

This lets Jane/Mentalist surface suspicious relationship patterns without claiming every flagged payment is fraud.

The broader final v1 operational queue (`VERIFY + REVIEW`) was also measured honestly on the same held-out partition:

- precision: **17.44%**
- fraud capture / recall: **38.50%**
- FPR: **6.5744%**
- intervention share: **7.69%**
- TP / FP / TN / FN: **1,187 / 5,621 / 79,877 / 1,896**

That lower precision describes an intentionally broader intervention queue, **not** the precision of the hard fraud detector.

## What LinkRisk does

A payment can look ordinary in isolation while its short-horizon behavior, relationship history and surrounding context form a suspicious case. LinkRisk therefore keeps three evidence channels separate:

1. **Transaction intelligence** — frozen XGBoost transaction-risk baseline.
2. **Trusted relationship memory** — causal relationship features plus delayed adjudicated fraud/legitimate feedback.
3. **Mentalist proactive deduction (“Jane”)** — present-tense velocity, behavior-change, coordination and reuse/churn evidence that does **not** consume confirmed-fraud labels.

Historical fraud is evidence, never automatic guilt.

> **Jane** is the deliberately playful internal name for the proactive investigator that looks for a constellation of weak clues before a profile is already known fraud.

## Product architecture

```text
Razorpay Test payment + merchant telemetry
                    │
                    ▼
          Transaction baseline
                    │
                    ▼
       Trusted-memory v0.5 risk
                    │
          ┌─────────┴─────────┐
          │                   │
   hard REVIEW boundary    other traffic
   measured detector          │
          │                   ▼
          │           cheap evidence gate
          │              /          \
          │         ordinary      evidence-bearing
          │             │              │
          │             │              ▼
          │             │        Jane / Mentalist
          │             │        investigator
          │             │              │
          └─────────────┴──────┬───────┘
                               ▼
                     operational routing
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
                  ALLOW      VERIFY     REVIEW
```

The live product preserves the frozen hard `REVIEW` detector and adds operational capabilities around it:

- selective Jane inference;
- defensive VERIFY routing;
- analyst-requested Jane second opinions;
- explicit operator escalation;
- causal relationship visualization;
- delayed merchant adjudication memory;
- persistent Supabase-backed operational ledger;
- Razorpay Test Mode checkout and verification;
- intervention/capacity telemetry.

A Jane-positive automatic case is not silently downgraded to `ALLOW` solely because a tiny streaming reserve is exhausted. Capacity overflow remains observable as telemetry rather than vetoing strong frozen-threshold evidence.

## Evaluation boundary

### Frozen held-out detector

The v0.5 hard `REVIEW` detector is the headline measured detector because it is unchanged in the current stack and has untouched held-out precision/recall/FPR.

### Final v1 operational policy

The original Mentalist-routed `VERIFY + REVIEW` policy was evaluated once on the same chronological held-out set. Its broader fraud-capture/false-positive trade-off is reported above and in [`docs/evaluation_results.md`](docs/evaluation_results.md).

### v2 operational engineering

v2 was designed only after the v1 held-out results exposed intervention-capacity drift. The old final set is therefore spent and is **not** reused as an unbiased v2 test.

Development validation for the cost-aware selective design showed:

- intervention: **6.00% → 6.00%**
- precision: **24.37% → 25.31%**
- fraud capture: **42.57% → 44.21%**
- FPR: **4.6973% → 4.6412%**
- TP / FP delta: **+50 / −48**
- Mentalist invoked: **2.27%**
- Mentalist bypassed: **97.73%**

These are **development-validation metrics only**, not a new held-out claim.

## False-positive cost

LinkRisk does not hide legitimate-customer friction.

- A false positive at the hard `REVIEW` detector is a legitimate transaction escalated to high-priority risk review.
- A false positive in `VERIFY` is generally an unnecessary verification/investigation step, not necessarily an automatic decline.

The final one-shot evaluator also includes false-positive cost sensitivity scenarios. See [`docs/evaluation_results.md`](docs/evaluation_results.md).

## Challengers we rejected

More sophisticated was not automatically better. Post-final-test experiments stayed development-only and were rejected when they failed to earn their complexity.

| Challenger | Development result | Decision |
| --- | --- | --- |
| AutoGluon challenger | Effective ensemble collapsed to XGBoost; PR-AUC **0.3413** vs frozen baseline **0.3496** | **REJECT** |
| Heterogeneous GraphSAGE | Same-slice PR-AUC **0.1452** vs baseline **0.4019** | **REJECT** |
| Causal graph-feature + XGBoost fusion | PR-AUC **0.3613** vs same-slice frozen baseline **0.4019**; also lost recall | **REJECT** |

The useful gains came from **trusted delayed evidence, selective behavioral reasoning and explicit risk operations**, not from adding complexity for its own sake.

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
LinkRisk scoring → ALLOW / VERIFY / REVIEW
```

The backend also implements an optional signed Razorpay webhook ingestion path at `POST /api/webhooks/razorpay`.

Razorpay's standard Payment entity does not expose all browser/device/session context used by LinkRisk. Additional context comes from merchant-observed telemetry. LinkRisk does not invent payer IP or reinterpret masked IEEE fields as literal identities.

## Privacy and merchant identity

Persistent operational data is server-side only. Raw email/contact values are not stored in the risk tables; stable HMAC tokens and masked display values are used instead.

Missing device/browser context is not collapsed into one fake shared identity, because doing so would fabricate relationship evidence.

## Run locally

### API

```bash
python -m pip install -r requirements.txt
uvicorn backend.api:app --reload --port 8000
```

### React product UI

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`. Vite proxies `/api` to FastAPI.

## Environment variables

Razorpay Test Mode checkout:

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
```

Optional webhook verification:

```text
RAZORPAY_WEBHOOK_SECRET=...
```

Persistent merchant memory:

```text
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
LINKRISK_IDENTITY_SECRET=...
```

Optional operator protection:

```text
LINKRISK_ADMIN_TOKEN=...
```

Cloud model-bundle bootstrap:

```text
LINKRISK_MODEL_BUNDLE_URL=<https URL to frozen ZIP>
LINKRISK_MODEL_BUNDLE_SHA256=<SHA-256 of that ZIP>
```

Never expose server secrets to the browser or repository.

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

Do **not** rerun or retune against the already-opened v1 held-out partition.

## Safety and evaluation guardrails

- Defense-only payment-risk functionality.
- Same-timestamp transactions cannot see one another.
- Point-in-time relationship features use only information available before the current decision.
- Mentalist proactive features consume no confirmed-fraud labels.
- Adjudicated history becomes usable only after `max(transaction_time + 72h, recorded_at)`.
- v0.5 hard REVIEW remains immutable.
- Correlated signals do not count as independent evidence families.
- Confidence means independent evidence support, not fraud probability.
- Model scores are ranking/risk scores, not calibrated probabilities.
- v1 held-out evaluation is immutable.
- v2 and later post-test orchestration changes remain labelled development/operational engineering until evaluated on a new untouched source.

## Project status

- ✅ Frozen transaction baseline
- ✅ Measured relationship-aware hard REVIEW detector
- ✅ One-shot chronological held-out precision / recall / FPR
- ✅ Trusted delayed-memory specialist
- ✅ Jane / Mentalist investigator
- ✅ Defensive VERIFY workflow
- ✅ Analyst Jane escalation
- ✅ React + FastAPI product UI
- ✅ Razorpay Test Mode checkout + server verification
- ✅ Supabase-backed persistent operational ledger
- ✅ Render deployment
- ✅ Rejected-challenger ledger
- ⏳ New untouched evaluation source for unbiased post-v1 orchestration generalization
