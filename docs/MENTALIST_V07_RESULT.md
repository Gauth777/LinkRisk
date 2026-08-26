# Mentalist v0.7 — Validation Result

Mentalist v0.7 **failed its predeclared global promotion gate** and is not promoted as a replacement for the frozen baseline or v0.5 system.

## Global result

| Metric | Frozen baseline | Mentalist v0.7 |
| --- | ---: | ---: |
| Precision | 0.5072 | 0.5069 |
| Recall | 0.2883 | 0.2890 |
| PR-AUC | 0.3496 | 0.3350 |
| FPR | 0.9960% | 0.9995% |

Decision delta: +2 net true positives and +3 net false positives. PR-AUC fell by 0.0146, so the frozen gate fails.

## Diagnostic result

The failure is highly structured rather than uniform:

| Independent clue families | Rows | Fraud rate | Baseline recall | Jane recall |
| --- | ---: | ---: | ---: | ---: |
| 0 | 77,304 | 3.01% | 25.63% | 23.48% |
| 1 | 7,962 | 5.97% | 40.00% | 44.21% |
| 2 | 2,503 | 7.23% | 38.67% | 49.17% |
| 3+ | 812 | 7.51% | 34.43% | 55.74% |

Approximately 87.3% of validation traffic has zero activated clue families. Jane loses performance there. In every clue-bearing segment, however, fraud prevalence is higher and Jane recall improves, with the largest gain under corroborated evidence.

## Interpretation

v0.7 answered two different questions:

1. **Should Jane replace the transaction model globally?** No.
2. **Do proactive, label-free clue families contain useful fraud signal when evidence is present?** Yes, strongly enough to justify a specialist follow-up experiment.

The next experiment must therefore be a gated investigator/rescue layer. The frozen baseline remains authoritative outside Jane's evidence-bearing candidate set. The held-out test remains sealed.
