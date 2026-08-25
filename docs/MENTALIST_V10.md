# Mentalist v1.0 — One-for-One Case Reallocation

## Why this experiment exists

v0.8 proved Mentalist can proactively surface baseline-missed fraud when at least two independent clue families corroborate. v0.9 then failed because its fixed routing priority placed historical-fraud overrides ahead of stronger current-risk evidence.

That failure supports a core LinkRisk design principle:

> Previous fraud is evidence, not guilt, and should not automatically outrank a stronger present-tense case.

v1.0 therefore starts from the complete frozen v0.5 policy rather than rebuilding it.

## Routing rule

1. Keep every v0.5 REVIEW decision unchanged.
2. Reuse the already-frozen v0.8 Mentalist 1% selection.
3. Keep only Mentalist cases that the full v0.5 policy would otherwise ALLOW.
4. Add those novel cases to VERIFY.
5. Preserve intervention capacity exactly by evicting the same number of existing v0.5 VERIFY cases with the lowest frozen v0.5 risk score.

The swap is one-for-one. No fraud labels are used to choose Mentalist additions or v0.5 evictions.

This means the experiment asks a clean product question:

> Are Jane's novel, corroborated cases more valuable than the weakest investigations already occupying scarce VERIFY capacity?

## Why this is not arbitrary score fusion

Mentalist and v0.5 scores are never averaged. v0.5 remains the hard-review authority. Mentalist only proposes novel investigations. The existing v0.5 risk score is used solely to identify the weakest current VERIFY cases when capacity must be freed.

## Development transparency

This architecture is a validation-driven iteration motivated by the failed v0.9 result. It is not presented as an untouched predeclared hypothesis. The held-out chronological test remains sealed and is still reserved for the final frozen architecture.

## Promotion gate frozen before v1.0 output

v1.0 passes only if:

- intervention count is exactly unchanged from the frozen v0.5 policy;
- every v0.5 REVIEW remains REVIEW;
- Mentalist contributes at least 15 frauds among its novel substituted cases;
- total fraud capture improves by at least +0.50 percentage points;
- legitimate friction does not increase.

If v1.0 passes, the reallocation policy becomes the leading Mentalist architecture candidate. If it fails, v0.8 remains a valid specialist result and `stable-v0.5-live-engine` remains the guaranteed fallback.

## Run

```powershell
python scripts/evaluate_mentalist_reallocation_v10.py
```
