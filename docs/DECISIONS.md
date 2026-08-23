# SentinelGraph Engineering Decisions

## D001 — Scope
Detect coordinated payment abuse rather than build a general-purpose fraud platform.

## D002 — Baseline
Use a supervised transaction-level model to establish what can be detected without explicitly constructed relationship features.

## D003 — Baseline feature policy
IEEE-CIS contains features that already encode counts/history/entity relations. The initial baseline excludes explicitly relation-engineered `C*` and `V*` families. The exact feature set will be frozen after dataset audit and documented before final evaluation.

## D004 — Graph approach
Use lightweight, interpretable graph-derived signals rather than a GNN.

## D005 — Graph confidence
Graph evidence is not trusted unconditionally. A graph-confidence value describes how much usable relationship evidence exists for a transaction.

## D006 — Fusion
Graph influence is confidence-gated. Missing or weak relationship evidence moves the final score toward the transaction-only ML score.

## D007 — Missing graph data
Missing graph evidence must never crash the scoring path or silently imply low risk. Fallback is explicitly recorded as ML-dominant / ML-only scoring.

## D008 — LLM usage
LLM is not part of the fraud decision. Deterministic evidence explanations are MVP.

## D009 — Evaluation
Use chronological train/validation/test split. Final held-out test is not used for tuning.

## D010 — Claims
Do not claim graph fraud detection itself is novel. Buildathon differentiation is confidence-aware, interpretable, gracefully-degrading graph augmentation with honest evaluation.
