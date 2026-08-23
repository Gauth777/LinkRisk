# LinkRisk Dataset Audit — IEEE-CIS

Audit date: 2026-08-23

## Result

**GO** — IEEE-CIS supports the LinkRisk experiment without requiring a custom synthetic fraud-ring generator for the MVP.

## Observed dataset properties

| Property | Value |
|---|---:|
| Transactions | 590,540 |
| Identity rows | 144,233 |
| Transaction columns | 394 |
| Identity columns | 41 |
| Duplicate TransactionID | 0 |
| Fraud rows | 20,663 |
| Fraud prevalence | 3.50% |
| Transactions with identity row | 24.42% |

### Chronological split

| Split | Rows | Fraud prevalence |
|---|---:|---:|
| Train | 413,378 | 3.52% |
| Validation | 88,581 | 3.43% |
| Test | 88,581 | 3.48% |

The fraud rate is reasonably stable over time, so a chronological 70/15/15 split is viable.

## Relationship-data conclusion

Identity coverage is only 24.42%. This is useful for LinkRisk because it naturally creates three regimes:

1. strong relationship evidence,
2. sparse relationship evidence,
3. no identity-table evidence.

This directly supports the graph-confidence and graceful-fallback thesis.

## Edge-construction warning

A repeated categorical value is **not automatically an identity edge**.

Examples from the audit:

- `DeviceType`: only 2 unique values — never a graph identity edge.
- `card4` / `card6`: only 4 unique values — never standalone edges.
- `P_emaildomain`: 59 values — email provider/domain is not a person identifier.
- `addr1`: 332 values — far too broad to connect transactions by itself.
- `card1`: 13,553 values across 590,540 rows — potentially useful as part of a composite pseudo-entity, but not trusted as a unique customer identifier.
- `DeviceInfo`: 1,786 values with ~20% coverage — useful context, but documentation describes it as device information / user-agent-like metadata rather than a guaranteed physical-device fingerprint.

## Frozen graph policy

LinkRisk will not create an edge merely because two transactions share one low-specificity field.

Candidate relationship evidence will instead come from:

- higher-specificity **composite pseudo-entity keys** built from documented payment/address/session fields,
- multiple independent shared attributes,
- temporal proximity / burst behaviour,
- prior cross-transaction reuse counts,
- historical connected-component evidence computed using **past transactions only**.

Exact composite keys will be selected from structural audit results, not from target-label performance.

## Leakage rule

For a transaction at time `t`, every graph-derived feature must be computable only from:

- the current transaction's available attributes, and
- transactions with `TransactionDT < t`.

Future transactions must never influence the current graph score.

## Baseline fairness rule

The ML-only baseline may use the same raw point-in-time transaction/identity attributes that LinkRisk receives. The graph-enhanced model differs by adding **historical cross-transaction relationship features**, not by secretly receiving a richer raw dataset.

To avoid giving the ML baseline pre-engineered relationship/history signals, the initial baseline excludes:

- `C1`–`C14` (counting/history features),
- `D1`–`D15` (time-to-prior-event style features),
- `V*` (Vesta engineered ranking/counting/entity-relation features).

This policy may only be changed before final held-out evaluation and must remain documented.
