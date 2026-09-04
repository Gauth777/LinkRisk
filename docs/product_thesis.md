# LinkRisk Product Thesis

## Positioning

**LinkRisk is a merchant-side payment risk operations layer built around a measured hard detector and a broader defensive verification workflow. It is not a replacement for a payment gateway's core fraud stack.**

A gateway has broad payment-network information. A merchant also has business-specific context: account history, product behavior, fulfilment context, device/browser signals, internal review outcomes and merchant-specific tolerance for friction. LinkRisk turns those merchant-side signals into an explainable investigation workflow around Razorpay payments.

The product loop is:

```text
Payment + merchant telemetry
        ↓
Transaction + trusted-memory risk
        ↓
Frozen hard REVIEW detector
        │
        ├──────── positive → REVIEW
        │
        └──────── otherwise
                    ↓
          selective Jane investigation
                    ↓
              ALLOW / VERIFY
                    ↓
             analyst case queue
                    ↓
 optional analyst-requested Jane second opinion
                    ↓
              human adjudication
                    ↓
            delayed trusted memory
                    ↓
        future related transactions
```

## Submission metric contract

The measured detector is the frozen **v0.5 hard REVIEW boundary**.

On the one-shot chronological held-out test of 88,581 transactions it achieved:

- **49.10% precision**
- **23.09% recall**
- **0.8632% false-positive rate**
- **0.3132 PR-AUC** for the underlying v0.5 risk

`VERIFY` is deliberately broader. It means additional defensive verification or investigation is warranted; it is **not** a fraud-positive verdict.

The complete source of truth is [`SUBMISSION_CONTRACT.md`](SUBMISSION_CONTRACT.md).

## The product gap

The weak pitch is:

> Razorpay needs fraud detection, so we built another fraud classifier.

The stronger pitch is:

> A transaction model can tell you a payment looks risky. Merchants also need to know which ambiguous payments deserve verification, why they deserve it, and how resolved cases should become trusted future context without turning past fraud into automatic guilt.

LinkRisk therefore separates:

- **hard fraud detection** — measured `REVIEW` boundary;
- **defensive verification** — broader `VERIFY` workflow;
- **investigation** — Jane evidence and network context;
- **learning from outcomes** — delayed merchant memory.

## Two Jane modes

### 1. Automatic Jane — proactive discovery

The live runtime computes cheap label-free clue families first. Jane is automatically invoked only when an otherwise non-REVIEW case has enough independent evidence to justify deeper inference.

If the frozen Jane score and clue boundaries are crossed, the case becomes `VERIFY`. A small streaming-capacity reserve may record an overflow, but it no longer turns a strong Jane-positive case back into `ALLOW`.

Purpose: catch subtle, evidence-bearing cases that a transaction-first policy would otherwise allow, while keeping `VERIFY` explicitly distinct from a hard fraud verdict.

### 2. Analyst-requested Jane — second opinion

An analyst can request Jane when the first decision is not enough explanation.

This pass:

- uses the original transaction-time evidence snapshot;
- consumes no confirmed-fraud labels;
- does not consume live intervention-capacity tokens;
- does not silently rewrite the frozen model decision;
- reports whether Jane crosses the frozen score/clue boundaries;
- can be explicitly escalated by an authorized operator into an operational `VERIFY` decision.

Purpose: make risk operations a genuine human-in-the-loop workflow rather than a terminal score.

## Why this is product-like

LinkRisk has four operating loops:

1. **Detect** — apply the frozen hard REVIEW detector.
2. **Verify / investigate** — spend deeper reasoning on evidence-bearing or analyst-selected cases.
3. **Decide** — route ALLOW / VERIFY / REVIEW with explicit semantics.
4. **Learn from outcomes** — resolved merchant cases become delayed trusted memory for future related transactions without retraining the base model in real time.

The core value proposition is therefore not merely model accuracy. It is **defensive payment-risk operations under uncertainty**.

## Defensible differentiation

- **Measured detector contract:** REVIEW has frozen held-out precision/recall/FPR.
- **Graduated intervention:** VERIFY is additional verification, not a fraud conviction.
- **Selective reasoning:** expensive inference is earned, not applied to every payment.
- **Independent evidence families:** velocity, behavior change, coordination and reuse/churn are treated as corroborating clues rather than one opaque score.
- **Delayed trusted memory:** confirmed outcomes influence future related transactions only after causal availability rules are satisfied.
- **Past fraud is evidence, not guilt:** historical fraud is a soft prior, never a standalone conviction.
- **Human-in-the-loop escalation:** analysts can request Jane and explicitly escalate qualifying second opinions without rewriting model history.
- **Merchant telemetry:** LinkRisk can use business-side context that is not present in a standard payment object.
- **Auditability:** the system exposes detector action, verification action, evidence and operator overrides separately.

## Target merchant

The most credible initial customer is not a bank-sized fraud team with its own mature risk platform. It is a growing online merchant that has enough payment volume for manual rules and blanket review to become expensive, but not enough fraud-engineering capacity to build a full risk stack internally.

For that merchant, LinkRisk acts as a risk-control plane on top of the payment provider:

- ingest payment + merchant context;
- apply a measured hard detector;
- prioritize additional verification;
- explain the evidence;
- collect adjudication;
- reuse matured merchant outcomes;
- expose false-positive friction rather than hiding it.

## What not to claim

- Do not claim Razorpay lacks fraud detection.
- Do not claim LinkRisk replaces Razorpay's internal fraud systems.
- Do not describe `VERIFY` as confirmed fraud.
- Do not call scores calibrated fraud probabilities.
- Do not attach v1 held-out metrics to post-test v2 orchestration as if v2 had an untouched test.
- Do not present development validation as a new held-out result.
- Do not claim the current IEEE-CIS-trained model is production-calibrated to Razorpay traffic.

## Demo story

The strongest three-act demo is:

### Act 1 — ordinary payment

A Razorpay Test payment receives `ALLOW`. Deep inference is bypassed when there is not enough independent evidence.

### Act 2 — subtle coordinated behavior

An ordinary-looking case accumulates independent relationship clues. Jane crosses its frozen evidence boundary and the payment moves to `VERIFY` — additional defensive verification, not a fraud conviction.

### Act 3 — hard detector / analyst workflow

A reproducible hard `REVIEW` case enters the risk queue. This is the metric-bearing detector-positive action. The analyst can inspect the relationship network, request Jane as a second opinion, resolve the case and feed the outcome into delayed trusted merchant memory.

The final message:

> **REVIEW is our measured fraud detector. VERIFY is our defensive verification layer. LinkRisk investigates relationships, explains why a payment deserves attention, and remembers what the merchant eventually learns.**
