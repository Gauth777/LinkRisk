# LinkRisk — Razorpay Track 2 submission contract

This document is the source of truth for how LinkRisk maps to Razorpay Track 2:

> Build a working detector, verifier or auto-responder for one class of loss, with measured precision and recall on a held-out test set. Honest metrics including false-positive cost. Defense-only.

## Loss class

**Coordinated payment fraud:** transactions that can appear individually plausible but become suspicious when causal relationship, recurrence, velocity, or context evidence is considered.

LinkRisk is defense-only. It detects, verifies, investigates and supports merchant risk operations. It does not provide offensive fraud tooling or evasion guidance.

## Submission hierarchy

LinkRisk has three layers with different responsibilities:

```text
1. HARD DETECTOR
   frozen v0.5 REVIEW boundary
   owns the headline untouched held-out precision / recall / FPR

2. JANE VERIFIER
   relationship-aware Mentalist investigator
   central innovation: finds suspicious cases the hard detector may not REVIEW
   routes qualifying evidence-bearing cases to VERIFY

3. RISK OPERATIONS
   analyst workflow + merchant memory + persistence + Razorpay integration
   turns detection and verification into a working defensive product
```

**Jane is not a fallback or backup model.** The hard REVIEW detector provides the clean metric anchor required by the challenge; Jane is the core differentiated verifier that expands coverage using relationship evidence.

## 1. Metric-bearing hard detector

The **frozen v0.5 hard REVIEW boundary** is the official hard fraud detector.

A `REVIEW` action means the frozen detector crossed its hard risk boundary and the payment should enter high-priority risk review.

The chronological held-out test was opened once after models and thresholds were frozen:

- test transactions: **88,581**
- fraud transactions: **3,083 (3.48%)**
- precision: **49.10%**
- recall: **23.09%**
- false-positive rate: **0.8632%**
- PR-AUC of v0.5 risk: **0.3132**

For comparison, the frozen transaction-only hard detector achieved:

- precision: **49.81%**
- recall: **21.08%**
- false-positive rate: **0.7661%**
- PR-AUC: **0.2873**

Therefore the relationship/trusted-memory hard detector increased held-out recall from **21.08% to 23.09%** and PR-AUC from **0.2873 to 0.3132**, while retaining approximately 49% precision.

## 2. Jane — the central verifier

Jane / Mentalist exists for the exact class of fraud LinkRisk targets: a payment may look ordinary in isolation while its surrounding relationships create a suspicious case.

Jane consumes present-tense, label-free evidence families such as:

- velocity;
- behavior change;
- coordination;
- reuse / churn.

Jane does **not** consume confirmed-fraud labels as Mentalist inputs. It is therefore capable of surfacing a suspicious relationship pattern before that profile is already known fraud.

### Jane v1 — held-out evidence

On the one-shot chronological held-out set, the original Mentalist-routed policy increased operational fraud capture from **35.61% to 38.50%** versus stable v0.5.

The net effect was **+89 frauds captured**.

That first policy also increased intervention cost and false positives:

- broad intervention precision: **17.44%**
- FPR: **6.5744%**
- intervention share: **7.69%**

This result is not hidden. It showed that Jane had useful signal, but that the original scalar routing policy did not control merchant friction well enough under later temporal traffic.

### Jane v2 — development response to the held-out failure mode

After the v1 held-out result exposed capacity drift, v2 redesigned Jane as a selective verifier rather than running deeper reasoning everywhere.

On development validation at the **same 6.00% intervention share**:

| Metric | Stable v0.5 | Selective Jane v2 | Delta |
| --- | ---: | ---: | ---: |
| Precision | 24.37% | **25.31%** | **+0.93 pp** |
| Recall / fraud capture | 42.57% | **44.21%** | **+1.64 pp** |
| FPR | 4.6973% | **4.6412%** | **−0.06 pp** |
| True positives | 1,295 | **1,345** | **+50** |
| False positives | 4,018 | **3,970** | **−48** |

Selective-inference accounting:

- Jane invoked: **2.27%** of transactions;
- Jane bypassed: **97.73%**;
- eligible Jane candidates: **519**;
- selected Jane cases: **519**.

These v2 numbers are **development validation**, not a new untouched held-out result. They demonstrate why Jane remains central to the product while preserving evaluation honesty.

## VERIFY is a verifier action, not a fraud verdict

The product contract is:

```text
ALLOW
  No sufficient evidence for intervention.

VERIFY
  Jane / risk evidence justifies additional defensive verification or investigation.
  This is not a fraud-positive verdict.

REVIEW
  Frozen hard detector positive.
  High-priority risk review is warranted.
```

This lets LinkRisk be both a **detector** and a **verifier**, which directly matches the Track 2 wording.

Because `VERIFY + REVIEW` is intentionally broader than the hard detector, its precision is lower and must not be presented as the precision of the hard fraud detector.

## 3. Risk-operations layer

The deployed product turns those two ML stages into a working risk workflow:

- Razorpay Test Mode checkout and server-side payment verification;
- causal relationship visualization;
- selective automatic Jane investigation;
- analyst-requested Jane second opinions;
- explicit operator escalation;
- persistent Supabase-backed case/ledger state;
- delayed adjudicated merchant memory;
- ALLOW / VERIFY / REVIEW queues;
- false-positive / intervention telemetry.

The product story is therefore:

```text
DETECT
hard REVIEW boundary
       ↓
VERIFY
Jane investigates relationship evidence
       ↓
RESOLVE
analyst / merchant adjudication
       ↓
REMEMBER
matured merchant outcome becomes causal future context
```

## False-positive cost interpretation

LinkRisk does not optimize fraud capture while pretending legitimate-customer friction is free.

A false positive in the hard `REVIEW` detector is a legitimate transaction escalated to high-priority risk review.

A false positive in the broader `VERIFY` layer is generally an unnecessary verification / investigation step; it is not necessarily an automatic payment decline.

This distinction is central to the product design and to the judge explanation.

## Evaluation boundary

The current live runtime contains post-held-out engineering changes. Therefore claims are separated as follows:

### Untouched held-out claims

Allowed:

- hard REVIEW detector: **49.10% precision, 23.09% recall, 0.8632% FPR**;
- v1 broader Mentalist policy: **38.50% fraud capture**, with the reported false-positive cost;
- Jane v1 net contribution: **+89 frauds captured** versus stable v0.5.

### Development-only claims

Allowed only when explicitly labelled development validation:

- Jane v2: **+50 TP, −48 FP** at fixed 6% intervention;
- precision **24.37% → 25.31%**;
- recall **42.57% → 44.21%**;
- FPR **4.6973% → 4.6412%**;
- Jane invocation share **2.27%**.

Do not describe those v2 figures as fresh held-out performance.

## Score semantics

LinkRisk scores are ranking / risk signals, not calibrated probabilities.

Do not say:

> “Jane score 82 means an 82% probability of fraud.”

Do say:

> “Jane assigned an 82/100 evidence-ranking score, and it crossed the frozen verifier boundary with enough independent clue families.”

Similarly, 49.10% precision is a population-level held-out metric for detector-positive cases, not a per-transaction fraud probability.

## Recommended submission headline

> **LinkRisk is a two-stage defensive payment-risk system for coordinated fraud: a frozen hard detector measured at 49.10% precision and 23.09% recall on 88,581 unseen chronological transactions, plus Jane, a relationship-aware verifier that investigates suspicious cases the detector may miss. Jane added 89 net fraud captures in the original held-out policy; after that test exposed false-positive capacity drift, the selective v2 redesign added 50 fraud investigations while removing 48 false positives at the same 6% intervention budget on development validation.**

## Recommended 20-second distinction

> **The hard detector gives us the trustworthy held-out metric foundation. Jane is the innovation: she looks between transactions, not just at one payment, and decides when an ordinary-looking case deserves VERIFY. REVIEW is a detector-positive action; VERIFY is extra defensive verification, not a fraud conviction.**

## Claims we must not make

- Do not describe `VERIFY` as confirmed fraud.
- Do not call Jane scores calibrated fraud probabilities.
- Do not attach v1 held-out metrics to post-test v2 orchestration as if v2 itself had an untouched test.
- Do not tune thresholds on the already-opened held-out partition.
- Do not hide the 17.44% precision / 6.5744% FPR when discussing the broad v1 intervention policy.
- Do not claim Razorpay Test Mode payments are real financial transactions.
- Do not claim IEEE-CIS masked fields are literal real-world identities.

## Final judge-facing one-line thesis

> **A fraud detector scores a payment. LinkRisk also investigates the relationships around it: REVIEW is our measured hard detector, while Jane is our relationship-aware verifier for the suspicious cases a transaction-only view can miss.**
