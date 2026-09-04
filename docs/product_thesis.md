# LinkRisk Product Thesis

## Positioning

**LinkRisk is a merchant-side payment risk operations layer, not a replacement for a payment gateway's core fraud stack.**

A gateway has broad payment-network information. A merchant also has business-specific context: account history, product behavior, fulfilment context, device/browser signals, internal review outcomes and merchant-specific tolerance for friction. LinkRisk is designed to turn those merchant-side signals into an explainable investigation workflow around Razorpay payments.

The product loop is:

```text
Payment + merchant telemetry
        ↓
Fast transaction/trusted-memory decision
        ↓
Selective automatic Jane investigation when weak clues corroborate
        ↓
ALLOW / VERIFY / REVIEW
        ↓
Analyst case queue
        ↓
Optional analyst-requested Jane second opinion
        ↓
Human adjudication
        ↓
Delayed trusted memory
        ↓
Future related transactions
```

## The product gap

The weak pitch is:

> Razorpay needs fraud detection, so we built another fraud classifier.

The stronger pitch is:

> Merchants need a risk-control layer that decides which transactions deserve deeper investigation, explains why, preserves scarce review capacity, and adapts to merchant-confirmed outcomes without blindly treating past fraud as guilt.

LinkRisk therefore focuses on the **decision and investigation layer** around risk models rather than claiming that one model replaces the gateway's internal risk infrastructure.

## Two Jane modes

### 1. Automatic Jane — proactive discovery

The cost-aware v2 runtime computes cheap label-free clue families first. Jane is automatically invoked only when a v0.5-ALLOW case has enough independent evidence to justify deeper inference.

Purpose: catch subtle, evidence-bearing cases that a transaction-first policy would otherwise allow.

### 2. Analyst-requested Jane — second opinion

A REVIEW or VERIFY case can be manually escalated to Jane by an analyst who wants an independent present-tense readout.

This pass:

- uses the original transaction-time evidence snapshot;
- consumes no confirmed-fraud labels;
- does not consume live intervention-capacity tokens;
- does not silently override the frozen action;
- reports whether Jane independently corroborates the intervention.

Purpose: make REVIEW a real investigation workflow rather than a terminal score.

## Why this is product-like

LinkRisk has four operating loops:

1. **Detect** — score the incoming payment quickly.
2. **Investigate** — spend deeper reasoning only when evidence or an analyst justifies it.
3. **Decide** — route scarce ALLOW / VERIFY / REVIEW capacity explicitly.
4. **Learn from outcomes** — resolved merchant cases become delayed trusted memory for future related transactions without retraining the base model in real time.

The core value proposition is therefore not merely model accuracy. It is **risk operations under uncertainty and scarce intervention capacity**.

## Defensible differentiation

- **Selective reasoning:** expensive inference is earned, not applied to every payment.
- **Independent evidence families:** velocity, behavior change, coordination and reuse/churn are treated as corroborating clues rather than one opaque score.
- **Delayed trusted memory:** confirmed outcomes influence future related transactions only after causal availability rules are satisfied.
- **Past fraud is evidence, not guilt:** historical fraud is a soft prior, never a standalone conviction.
- **Capacity-aware routing:** REVIEW is preserved while VERIFY capacity is explicitly allocated.
- **Human-in-the-loop escalation:** analysts can request Jane as a second opinion without changing the frozen decision automatically.
- **Merchant telemetry:** LinkRisk can use business-side context that is not present in a standard payment object.
- **Auditability:** the system exposes the decision path and evidence rather than only a probability-like number.

## Target merchant

The most credible initial customer is not a bank-sized fraud team with its own mature risk platform. It is a growing online merchant that has enough payment volume for manual rules and blanket review to become expensive, but not enough fraud-engineering capacity to build a full risk stack internally.

For that merchant, LinkRisk acts as a risk-control plane on top of the payment provider:

- ingest payment + merchant context;
- prioritize investigations;
- explain the evidence;
- collect adjudication;
- reuse matured merchant outcomes;
- keep false-positive friction within an explicit operating budget.

## What not to claim

- Do not claim Razorpay lacks fraud detection.
- Do not claim LinkRisk replaces Razorpay's internal fraud systems.
- Do not claim a REVIEW transaction is confirmed fraud.
- Do not call scores calibrated probabilities.
- Do not present v2 development validation as a new held-out result.
- Do not claim the current IEEE-CIS-trained model is production-calibrated to Razorpay traffic.

## Demo story

The strongest three-act demo is:

### Act 1 — ordinary payment

A real Razorpay Test payment receives ALLOW. Deep inference is bypassed.

### Act 2 — subtle coordinated behavior

A case that v0.5 would ALLOW earns automatic Jane investigation because independent clues corroborate. Jane can promote it to VERIFY subject to capacity.

### Act 3 — analyst escalation

A reproducible REVIEW case enters the analyst queue. The analyst clicks **Ask Jane** because the first decision is not enough explanation. Jane reconstructs the original transaction-time evidence and returns an independent advisory second opinion while the REVIEW action remains unchanged.

The final message:

> A fraud score tells you something looks risky. LinkRisk decides what deserves attention, explains the case, and remembers what the merchant eventually learns.
