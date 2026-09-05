# LinkRisk — frozen final demo cases

These are the three canonical Razorpay Test transactions for the final Track 2 demo. They were selected from the persistent merchant ledger and verified against the causal session journal.

Do not replace them with synthetic seeded rows or operator-overridden cases unless one becomes unavailable because of a genuine product defect.

## Case A — clean ALLOW

**Transaction:** `RZP-pay_TXzyUYLkmtgt8y`  
**Razorpay payment:** `pay_TXzyUYLkmtgt8y`  
**Amount:** ₹599  
**Source:** `razorpay_checkout_verify`  
**Final action:** `ALLOW`

Evidence snapshot:

- transaction / baseline risk: **17.23 / 100**
- LinkRisk v0.5 risk: **17.23 / 100**
- Jane score: **63.16 / 100**
- independent Jane clue families: **2**
- routing reason: `MENTALIST_SCORE_BELOW_THRESHOLD`

Why this case matters:

Jane had enough independent clue families to be considered, but her evidence score stayed below the frozen verifier threshold. LinkRisk therefore remained `ALLOW`. This proves Jane is not an automatic escalation mechanism.

Judge-facing line:

> **This payment was investigated but the evidence was not strong enough to justify friction, so LinkRisk left it ALLOW.**

---

## Case B — Jane-driven VERIFY

**Transaction:** `RZP-pay_TY00w8DFpzWiUJ`  
**Razorpay payment:** `pay_TY00w8DFpzWiUJ`  
**Amount:** ₹575  
**Source:** `razorpay_checkout_verify`  
**Final action:** `VERIFY`

Evidence snapshot:

- transaction / baseline risk: **17.23 / 100**
- LinkRisk v0.5 risk: **17.23 / 100**
- Jane score: **91.86 / 100**
- independent Jane clue families: **2**
- original v0.5 action: `ALLOW`
- routing reason: `MENTALIST_CAPACITY_AUTHORIZED`
- operator override: **none**

Why this is the central demo case:

The transaction model saw essentially the same low risk as Case A, but Jane found much stronger relationship evidence. The payment therefore moved from the v0.5 `ALLOW` path to `VERIFY` automatically.

Case A and Case B also share the same merchant-supplied profile/device context in the original demo sequence (`ALPHA-A`, `Windows / Chrome`, `chrome-win-alpha`). This makes the contrast easy to explain: the visible payment score alone does not account for the relationship state accumulated before the later payment.

Judge-facing line:

> **The payment itself scores only about 17/100, so the hard detector does not REVIEW it. Jane independently finds strong relationship evidence — 91.86 with two clue families — and escalates it to VERIFY. We are not declaring fraud; we are saying additional verification is warranted.**

This is the primary LinkRisk innovation moment. Prefer this case over the ₹7,500/₹7,900 cases because those were later operator overrides and would muddy the automatic-Jane story.

---

## Case C — hard REVIEW detector positive

**Transaction:** `RZP-pay_TY2xXXgqN2zOCf`  
**Razorpay payment:** `pay_TY2xXXgqN2zOCf`  
**Amount:** ₹499  
**Source:** `razorpay_checkout_verify`  
**Final action:** `REVIEW`

Evidence snapshot:

- transaction / baseline risk: **84.97 / 100**
- LinkRisk v0.5 risk: **84.97 / 100**
- v0.5 action: `REVIEW`
- final action: `REVIEW`
- routing reason: `V5_REVIEW_MANDATORY`
- source is a real Razorpay Test checkout row, not `synthetic_demo`

Why this case matters:

This is the metric-bearing hard detector positive. It is the action associated with the frozen held-out REVIEW metrics:

- precision **49.10%**
- recall **23.09%**
- FPR **0.8632%**

An analyst-requested Jane event also exists for this case, but Jane is optional during the timed demo. The key point is that `REVIEW` was already produced by the frozen hard detector.

Judge-facing line:

> **This case is different from VERIFY: it crossed the frozen hard REVIEW boundary. This is the detector-positive action tied to our 49.10% held-out precision and 23.09% recall.**

---

# Final three-case sequence

Use this exact order:

```text
₹599  → ALLOW
        baseline 17.23
        Jane 63.16 / 2 clues
        below verifier threshold

₹575  → VERIFY
        baseline 17.23
        Jane 91.86 / 2 clues
        automatic Jane escalation

₹499  → REVIEW
        hard risk 84.97
        frozen detector positive
```

The first two form the strongest comparison in the demo: approximately the same transaction-risk score, different relationship evidence, different defensive action.

# Demo navigation

1. Start on **Overview** and point to the held-out detector + Jane evidence strip.
2. Open **₹599 ALLOW** briefly to establish that Jane can inspect and still decline to escalate.
3. Open **₹575 VERIFY** and spend the most time here:
   - transaction/v0.5 risk;
   - Jane score;
   - clue count;
   - final VERIFY;
   - relationship/Jane evidence view.
4. Open **₹499 REVIEW**:
   - show hard detector risk/action;
   - explain that REVIEW owns the headline held-out detector metrics.
5. Close on **Cases / persistent merchant memory** and explain Resolve → delayed trusted memory → future protection.

# Freeze rules

- Do not hand-edit scores or labels on these three rows.
- Do not replace the automatic Jane VERIFY with an operator-overridden case for the main demo.
- Do not use `DEMO-*` seeded rows as proof of live model behavior.
- Do not describe Jane scores as calibrated fraud probabilities.
- Do not describe `VERIFY` as confirmed fraud.
- If the live UI disagrees with these frozen facts, treat it as a product consistency defect and fix the presentation/runtime linkage rather than rewriting the stored evidence.
