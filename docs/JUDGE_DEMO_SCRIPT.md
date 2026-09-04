# LinkRisk — judge demo and pitch script

Use this document as the operating script for the Razorpay AI Buildathon submission.

The goal is not to explain every subsystem. The goal is to make a judge understand the problem, the measured detector, Jane's differentiation, the false-positive trade-off, and the working product in under three minutes.

## Core thesis

> **A fraud detector scores a payment. LinkRisk also investigates the relationships around it. REVIEW is our measured hard detector; Jane is our relationship-aware verifier for suspicious cases a transaction-only view can miss.**

## What the judge must understand

By the end of the demo, the judge should know five things:

1. LinkRisk targets **coordinated payment fraud**, one specific loss class.
2. The hard `REVIEW` detector has a genuine one-shot chronological held-out result.
3. Jane is not a backup model; she is the central verifier for relationship evidence.
4. `VERIFY` is additional verification, not a fraud conviction, so false-positive cost is handled explicitly.
5. This is a working product: Razorpay Test payment → decision → investigation → analyst outcome → persistent merchant memory.

---

# 20-second opening

Say:

> **Most fraud systems ask: how risky is this transaction? LinkRisk asks a second question: what do the relationships around this transaction tell us? We built a frozen hard detector measured on 88,581 unseen chronological transactions, and Jane — a relationship-aware verifier that investigates the suspicious cases the hard detector may miss.**

Do not start with architecture names, graph terminology, or model versions.

---

# 60–90 second pitch

Say:

> **Our loss class is coordinated payment fraud. A payment can look legitimate in isolation while velocity, device reuse, profile churn or coordination across nearby transactions forms a suspicious pattern.**
>
> **The first stage is our frozen hard REVIEW detector. On 88,581 unseen chronological transactions it achieved 49.10% precision, 23.09% recall and a 0.8632% false-positive rate. Compared with the transaction-only baseline, relationship-aware risk increased recall from 21.08% to 23.09% while keeping precision around 49%.**
>
> **The second stage is Jane, our relationship-aware verifier. Jane looks at independent present-tense clue families rather than confirmed-fraud labels. In the original held-out policy, Jane captured 89 additional frauds, but also exposed a real false-positive capacity problem. We did not tune that result away. We redesigned Jane selectively, and on development validation she added 50 fraud investigations while removing 48 false positives at the same 6% intervention budget.**
>
> **That is why LinkRisk has ALLOW, VERIFY and REVIEW. REVIEW is a hard detector positive. VERIFY means extra defensive verification is warranted; it does not mean we are declaring the customer fraudulent. Resolved cases become delayed trusted merchant memory for future related transactions.**

Then immediately move into the product.

---

# Recommended live demo flow

## Act 1 — establish the metric contract

Open **Live Session / Overview**.

Point to the submission evidence strip.

Say:

> **The left side is the held-out hard detector: 49.10 precision, 23.09 recall, 0.8632 FPR. The right side is Jane's verifier evidence. We keep held-out and development claims visibly separated.**

Do not spend more than 15 seconds here.

## Act 2 — show the LinkRisk moment

Open a transaction where the transaction / v0.5 score looks modest but Jane has strong corroborated evidence and the operational action is `VERIFY`.

Selection rule:

- prefer a real Razorpay Test session row if one exists;
- otherwise use an explicitly labelled Demo Scenario;
- do not present a seeded synthetic dashboard row as if it came from an unrelated real customer;
- prefer at least two independent Jane clue families;
- prefer a Jane score above the frozen Jane threshold;
- avoid a case whose only reason for VERIFY is a manual operator override unless the point of the demo is human escalation.

On **Investigation**, say:

> **This is the central LinkRisk case. The payment itself does not cross our hard REVIEW detector, but the relationships around it create multiple independent clues. Jane crosses her frozen verifier boundary, so the payment moves to VERIFY. We are not calling it fraud; we are saying it deserves additional defensive verification.**

Point to:

- transaction / v0.5 risk;
- Jane score;
- clue count;
- final `VERIFY` action.

Then open the **relationship network** or Jane evidence view.

Say:

> **The evidence is point-in-time causal. The current transaction can only see prior context; same-timestamp peers cannot leak into one another. Jane's proactive features do not use confirmed-fraud labels.**

Do not narrate every edge.

## Act 3 — prove the hard detector exists

Open a `REVIEW` case.

Say:

> **This is different from VERIFY. REVIEW is our measured hard detector positive. This is the action associated with the 49.10% held-out precision and 23.09% recall.**

If useful, click **Ask Jane** to show that Jane can also act as an analyst second opinion, but do not let this consume the demo.

## Act 4 — close the product loop

Show the case resolution / persistent merchant-memory area.

Say:

> **The analyst can confirm fraud or legitimate. That outcome is not trusted instantly. After the fixed causal delay, it becomes merchant memory for future related payments. So LinkRisk is not just a classifier — it is Detect → Verify → Resolve → Remember.**

If time permits, show the Razorpay Test checkout path or persistent ledger.

Close with:

> **The hard detector gives us a defensible measured foundation. Jane is the innovation that investigates what a transaction-only view misses, and the operational layer controls the cost of acting on that uncertainty.**

---

# 3-minute timing target

- 0:00–0:25 — problem + thesis
- 0:25–0:50 — held-out detector metrics
- 0:50–1:45 — Jane VERIFY investigation
- 1:45–2:15 — hard REVIEW case
- 2:15–2:40 — resolution + merchant memory
- 2:40–3:00 — metric honesty + closing thesis

Do not demo configuration screens unless asked.

---

# Metric board — memorize these

## Hard REVIEW detector — untouched held-out

- rows: **88,581**
- frauds: **3,083 (3.48%)**
- precision: **49.10%**
- recall: **23.09%**
- FPR: **0.8632%**
- PR-AUC: **0.3132**

Transaction-only baseline:

- precision: **49.81%**
- recall: **21.08%**
- FPR: **0.7661%**
- PR-AUC: **0.2873**

## Jane v1 — held-out broader policy

- stable v0.5 capture: **35.61%**
- final v1 capture: **38.50%**
- net extra frauds captured: **+89**
- broad intervention precision: **17.44%**
- FPR: **6.5744%**
- intervention share: **7.69%**

## Jane v2 — development validation only

- precision: **24.37% → 25.31%**
- recall: **42.57% → 44.21%**
- FPR: **4.6973% → 4.6412%**
- TP: **1,295 → 1,345 (+50)**
- FP: **4,018 → 3,970 (−48)**
- intervention share: **6.00% → 6.00%**
- Jane invoked: **2.27%**

Never mix the held-out and development labels.

---

# Judge Q&A

## “49% precision still means half the REVIEWs are legitimate. Isn't that weak?”

Answer:

> **It means roughly half of the hard detector-positive cases were fraud on the held-out set, which is very different from saying the model is only 49% certain. Fraud prevalence was 3.48%, so the hard REVIEW queue is heavily enriched relative to the base rate. We also report the false-positive rate — 0.8632% — because precision alone does not describe merchant friction.**

Then add:

> **We deliberately do not turn every suspicious case into a decline. VERIFY is an intermediate verification state, while REVIEW is the hard detector-positive state.**

## “Why did your final v1 operational precision fall to 17.44%?”

Answer:

> **Because 17.44% describes the much broader VERIFY + REVIEW intervention queue, not the hard fraud detector. Jane increased fraud capture from 35.61% to 38.50%, but the first routing policy also expanded intervention too aggressively under later temporal traffic. We report that failure mode honestly. It directly motivated the selective v2 redesign.**

## “So are the v2 numbers held-out?”

Answer exactly:

> **No. They are development validation. The original held-out set was already opened after v1, so reusing it as a fresh v2 test would be methodologically dishonest. We keep the v1 held-out claims and v2 development claims separate.**

Do not soften this answer.

## “Then why should we care about v2?”

Answer:

> **Because it shows the engineering response to a real held-out failure mode. At a fixed 6% intervention budget on development validation, selective Jane increased fraud capture, increased precision and reduced false positives. We treat that as promising development evidence, not as a new unbiased test claim.**

## “Is Jane just another classifier?”

Answer:

> **No. The hard detector owns the high-priority REVIEW decision. Jane is a verifier for evidence-bearing cases that may sit below that hard boundary. Her job is to inspect relationship patterns — velocity, behavior change, coordination and reuse/churn — and decide whether the payment deserves additional verification.**

## “Why not run Jane on every payment?”

Answer:

> **Because most traffic is structurally ordinary. On development validation, the cheap evidence gate allowed Jane to be bypassed on 97.73% of transactions and invoked on only 2.27%, while preserving the useful verifier cases. Selective inference keeps deeper reasoning focused where it has evidence to work with.**

## “Is a Jane score of 90 a 90% fraud probability?”

Answer:

> **No. It is a ranking / evidence score relative to the frozen Jane policy. We do not claim calibrated fraud probability. A Jane action requires the score boundary plus enough independent clue families.**

## “What does false positive mean in your system?”

Answer:

> **At REVIEW, it means a legitimate payment was sent to high-priority risk review. At VERIFY, it usually means an unnecessary verification or investigation step, not necessarily an automatic decline. That distinction is why we separate detection from verification.**

## “Do you use future information or known fraud labels to create Jane's clues?”

Answer:

> **No. Relationship features are point-in-time causal; same-timestamp rows cannot see each other. Jane's proactive features do not consume confirmed-fraud labels. Adjudicated outcomes enter trusted merchant memory only after the fixed delay.**

## “Why IEEE-CIS if this is for Razorpay?”

Answer:

> **IEEE-CIS gives us a real labeled fraud benchmark for chronological ML evaluation. We do not claim the trained weights are production-calibrated to Razorpay traffic. Razorpay Test Mode is used to prove the integration and product workflow; a production deployment would require merchant/gateway-specific retraining and calibration.**

## “Are the identities in your graph real users?”

Answer:

> **No. IEEE-CIS fields are masked, and the research relationship keys are pseudo-entities. In the live merchant integration we use privacy-safe server-side identity tokens and masked display values rather than pretending masked benchmark fields are literal identities.**

## “Why not use a GNN? Isn't graph fraud detection more advanced?”

Answer:

> **We tested it. The GraphSAGE feasibility experiment and graph-feature/XGBoost fusion both underperformed the frozen transaction baseline on our development protocols. We rejected them rather than keeping complexity that did not earn its place. The useful relationship signal came from causal features, delayed trusted evidence and Jane's selective verifier.**

## “Is LinkRisk replacing Razorpay's fraud system?”

Answer:

> **No. LinkRisk is a merchant-side risk-operations layer around payment infrastructure. A gateway has network-wide signals; a merchant also has business-specific behavior, fulfillment context and its own resolved outcomes. LinkRisk turns that context into an explainable verification and memory workflow.**

## “Is this defense-only?”

Answer:

> **Yes. The product only detects, verifies, explains and responds to suspicious payment activity. It does not generate fraud techniques, evasion strategies or offensive tooling.**

---

# Phrases to avoid

Do not say:

- “Jane is 90% sure this is fraud.”
- “Our model has 49% accuracy.”
- “Our final model has 44.21% held-out recall.”
- “17.44% is our detector precision.”
- “This transaction is fraud” when the action is `VERIFY`.
- “The graph identified the criminal/customer.”
- “Jane learns instantly from every fraud.”
- “Razorpay doesn't already have fraud detection.”
- “We replace Razorpay Radar / internal risk systems.”

Preferred language:

- “risk score”;
- “evidence score”;
- “hard detector positive”;
- “additional verification warranted”;
- “independent clue families”;
- “delayed trusted merchant memory”;
- “point-in-time causal relationship evidence.”

---

# Pre-demo selection checklist

Before recording or presenting:

- confirm Render is on the intended commit;
- confirm CI is green;
- hard-refresh the product;
- identify one clean ALLOW case;
- identify one clean Jane-driven VERIFY case;
- identify one hard REVIEW case;
- prefer real Razorpay Test session cases when they tell the story cleanly;
- if using Demo Scenarios, state that they are curated examples;
- do not claim seeded synthetic ledger rows came from real external users;
- confirm the persistent ledger loads;
- confirm Investigation, Cases and Alerts agree on operational action;
- confirm Jane score/clues are unchanged by operator overrides;
- confirm no raw secrets appear in the browser.

## Freeze rule

Once the final demo cases and submission copy are selected, stop modifying model thresholds, evaluation numbers or historical outcomes unless a genuine correctness defect is discovered.

At that point, remaining work should be presentation, deployment reliability and submission packaging — not metric chasing on already-seen data.
