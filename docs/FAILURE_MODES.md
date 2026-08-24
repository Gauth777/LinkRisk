# LinkRisk Failure Modes and Guardrails

LinkRisk is intentionally conservative about relationship evidence. The champion policy never treats one shared identifier as proof of fraud, and graph evidence alone cannot force the highest-friction REVIEW action.

## 1. Cold start / no matured relationship history

**Risk:** a new or sparsely observed transaction has no usable graph memory.

**Guardrail:** graph confidence is zero and the final LinkRisk score falls back exactly to the transaction-only baseline. A high baseline risk can still trigger REVIEW; missing graph data is never interpreted as low risk.

## 2. Shared household, campus, office, or device context

**Risk:** legitimate users may share infrastructure or coarse device/browser context, creating broad graph connectivity.

**Guardrail:** broad context is treated as supporting context rather than verified identity. Relationship confidence without matured fraud evidence does not automatically create VERIFY or REVIEW friction.

## 3. High-support but mostly legitimate history

**Risk:** a frequently reused context can have many observations while remaining overwhelmingly legitimate.

**Guardrail:** evidence volume and historical confirmed-fraud rate are separate signals. High support alone is not suspicious, and a low historical fraud rate is not described as elevated risk.

## 4. Stale confirmed-fraud history

**Risk:** an entity may have an old confirmed-fraud association that is no longer representative.

**Guardrail:** the evidence report distinguishes recent 30-day matured fraud activity from older historical fraud evidence. A stale single channel does not automatically force VERIFY.

## 5. Single weak fraud-linked channel

**Risk:** one noisy or ambiguous relationship may connect a legitimate transaction to past fraud.

**Guardrail:** one non-strong fraud-linked channel is explained but does not by itself trigger VERIFY. This avoids implementing "one shared identifier = fraud."

## 6. Multiple corroborating fraud-linked channels

**Risk:** coordinated abuse may reuse several relationship views even when the transaction-only model is not highly suspicious.

**Guardrail:** at least two matured fraud-linked channels with sufficiently high structural confidence can route the transaction to VERIFY. This is a lower-friction escalation and still cannot directly force REVIEW.

## 7. Strong matured device/receiver fraud relationship with low ML risk

**Risk:** transaction-local features may look normal even when a strong relationship view has trustworthy confirmed-fraud history.

**Guardrail:** sufficiently confident strong device/receiver fraud evidence can force VERIFY, allowing step-up authentication or additional checks without treating the relationship as conclusive fraud.

## 8. High transaction-only risk with no graph evidence

**Risk:** confidence gating could accidentally suppress a strong baseline fraud signal when relationship data is absent.

**Guardrail:** exact fallback preserves the baseline score. If that score exceeds the frozen REVIEW threshold, the transaction still goes to REVIEW.

## Policy hierarchy

- **ALLOW:** low operational risk and no qualifying structural escalation.
- **VERIFY:** intermediate risk or sufficiently corroborated matured relationship evidence; intended for lower-friction step-up verification.
- **REVIEW:** final LinkRisk risk score exceeds the frozen v0.5 REVIEW threshold. Structural evidence alone never forces REVIEW.

## Known limitations

- IEEE-CIS fields are masked; composite keys are pseudo-entities, not verified real-world identities.
- The 72-hour confirmation delay is an explicit simulation assumption, not a property supplied by IEEE-CIS.
- Risk scores are ranking scores from class-weighted models, not calibrated fraud probabilities.
- The 6% intervention level is a validation-time policy calibration target, not a production traffic guarantee. A real deployment would monitor action volumes and distribution shift.
- The current benchmark does not contain explicit coordinated-fraud-ring ground truth; LinkRisk therefore evaluates incremental fraud detection and relationship-defined segments rather than claiming direct ring-label accuracy.
