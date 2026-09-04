"""Find a reproducible live-input pair that demonstrates trusted-memory uplift.

This is a DEVELOPMENT/DEMO utility. It never calls FastAPI or Razorpay and never
writes the live session journal. It searches human-enterable LinkRisk inputs for
cases where the *same second transaction* receives a stronger v0.5 decision once
a prior related transaction's confirmed-fraud outcome has matured after 72 hours.

The comparison isolates trusted feedback on the second row:

    same relationship history + no eligible fraud label
        versus
    same relationship history + matured eligible fraud label

No model weights, thresholds or policy values are changed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import ID_COL, TARGET, TIME_COL
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import LABEL_DELAY_SECONDS, build_feedback_features_v5
from linkrisk.live_engine import LiveTransactionInput, live_input_to_model_row
from linkrisk.relationship_features_v4 import build_relationship_features_v4


ACTION_RANK = {"ALLOW": 0, "VERIFY": 1, "REVIEW": 2}
PRODUCT_CODES = ("W", "C", "H", "R", "S")
AMOUNTS = (49.0, 99.0, 199.0, 499.0, 999.0, 2499.0)
PAYMENT_PATHS = (
    ("visa", "debit"),
    ("visa", "credit"),
    ("mastercard", "debit"),
    ("mastercard", "credit"),
    ("netbanking", "unknown"),
)


@dataclass(frozen=True)
class Candidate:
    memory_delta: float
    before_risk: float
    after_risk: float
    before_action: str
    after_action: str
    amount: float
    profile: str
    device: str
    browser: str
    receiver: str
    product_code: str
    payer_domain: str
    card_network: str
    card_type: str

    @property
    def escalated(self) -> bool:
        return ACTION_RANK[self.after_action] > ACTION_RANK[self.before_action]


def _make_pair(index: int, *, amount: float, product_code: str, network: str, card_type: str) -> tuple[dict, dict, dict]:
    profile = f"MEMORY-DEMO-{index:07d}"
    # Keep each candidate pair isolated from every other pair. Within a pair the
    # relationship keys are intentionally identical so only its own first row is
    # eligible as history for its second row.
    device = f"device-demo-{index:07d}"
    browser = f"browser-demo-{index:07d}"
    receiver = f"merchant-{index:07d}.example"
    payer_domain = f"buyer-{index:07d}.example"

    event = LiveTransactionInput(
        amount=amount,
        payment_profile=profile,
        device_info=device,
        receiver_domain=receiver,
        browser_context=browser,
        product_code=product_code,
        payer_domain=payer_domain,
        device_type="desktop",
        card_network=network,
        card_type=card_type,
    )

    first_id = f"MEM-A-{index:07d}"
    second_id = f"MEM-B-{index:07d}"
    first = live_input_to_model_row(event, transaction_id=first_id, transaction_time=0.0)
    second = live_input_to_model_row(
        event,
        transaction_id=second_id,
        transaction_time=float(LABEL_DELAY_SECONDS + 1.0),
    )
    first[TARGET] = 1
    second[TARGET] = 0
    human = {
        "amount": amount,
        "profile": profile,
        "device": device,
        "browser": browser,
        "receiver": receiver,
        "product_code": product_code,
        "payer_domain": payer_domain,
        "card_network": network,
        "card_type": card_type,
    }
    return first, second, human


def _search_batch(
    scorer: FrozenChampionScorer,
    *,
    start: int,
    count: int,
    amount: float,
    product_code: str,
    network: str,
    card_type: str,
) -> list[Candidate]:
    rows: list[dict] = []
    humans: dict[str, dict] = {}
    first_ids: list[str] = []
    second_ids: list[str] = []

    for index in range(start, start + count):
        first, second, human = _make_pair(
            index,
            amount=amount,
            product_code=product_code,
            network=network,
            card_type=card_type,
        )
        rows.extend((first, second))
        first_id = str(first[ID_COL])
        second_id = str(second[ID_COL])
        first_ids.append(first_id)
        second_ids.append(second_id)
        humans[second_id] = human

    frame = pd.DataFrame(rows)
    frame.index = frame[ID_COL].astype(str)
    relationship = build_relationship_features_v4(frame)

    no_labels = pd.Series(False, index=frame.index, dtype=bool)
    matured = pd.Series(False, index=frame.index, dtype=bool)
    matured.loc[first_ids] = True

    feedback_without = build_feedback_features_v5(frame, no_labels)
    feedback_with = build_feedback_features_v5(frame, matured)

    second_frame = frame.loc[second_ids]
    second_relationship = relationship.loc[second_ids]
    before = scorer.score_batch(
        second_frame,
        second_relationship,
        feedback_without.loc[second_ids],
    )
    after = scorer.score_batch(
        second_frame,
        second_relationship,
        feedback_with.loc[second_ids],
    )

    results: list[Candidate] = []
    for tx_id in second_ids:
        before_risk = float(before.loc[tx_id, "linkrisk_risk"])
        after_risk = float(after.loc[tx_id, "linkrisk_risk"])
        before_action = str(before.loc[tx_id, "action"])
        after_action = str(after.loc[tx_id, "action"])
        human = humans[tx_id]
        results.append(
            Candidate(
                memory_delta=after_risk - before_risk,
                before_risk=before_risk,
                after_risk=after_risk,
                before_action=before_action,
                after_action=after_action,
                amount=human["amount"],
                profile=human["profile"],
                device=human["device"],
                browser=human["browser"],
                receiver=human["receiver"],
                product_code=human["product_code"],
                payer_domain=human["payer_domain"],
                card_network=human["card_network"],
                card_type=human["card_type"],
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles-per-config", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--min-delta", type=float, default=0.03)
    args = parser.parse_args()
    if args.profiles_per_config <= 0 or args.batch_size <= 0 or args.top <= 0:
        parser.error("profiles-per-config, batch-size and top must be positive")

    scorer = FrozenChampionScorer.from_artifacts(ROOT)
    best: list[Candidate] = []
    total = len(AMOUNTS) * len(PRODUCT_CODES) * len(PAYMENT_PATHS) * args.profiles_per_config
    searched = 0
    global_index = 0

    print("=== LinkRisk trusted-memory live-demo search ===")
    print("Development/demo utility only; no live session and no Razorpay calls.")
    print(f"Candidate second rows: {total:,}")
    print(f"Maturity delay       : {LABEL_DELAY_SECONDS / 3600:.0f}h")
    print()

    for amount in AMOUNTS:
        for product_code in PRODUCT_CODES:
            for network, card_type in PAYMENT_PATHS:
                remaining = args.profiles_per_config
                while remaining > 0:
                    batch = min(args.batch_size, remaining)
                    results = _search_batch(
                        scorer,
                        start=global_index,
                        count=batch,
                        amount=amount,
                        product_code=product_code,
                        network=network,
                        card_type=card_type,
                    )
                    global_index += batch
                    remaining -= batch
                    searched += batch

                    best.extend(results)
                    best.sort(
                        key=lambda c: (
                            c.escalated,
                            c.memory_delta,
                            c.after_risk,
                        ),
                        reverse=True,
                    )
                    del best[args.top:]

                    leader = best[0]
                    print(
                        f"searched {searched:>7,}/{total:,} | "
                        f"best {leader.before_action}->{leader.after_action} | "
                        f"risk {leader.before_risk:.4f}->{leader.after_risk:.4f} "
                        f"(delta {leader.memory_delta:+.4f})",
                        flush=True,
                    )

    print("\n=== BEST TRUSTED-MEMORY DEMO CANDIDATES ===")
    useful = False
    for rank, candidate in enumerate(best, start=1):
        qualifies = candidate.escalated or candidate.memory_delta >= args.min_delta
        useful |= qualifies
        flag = "ACTION ESCALATION" if candidate.escalated else "RISK UPLIFT"
        print(f"\n#{rank} {flag}")
        print(f"Before memory : {candidate.before_action:>6} | risk {candidate.before_risk:.6f}")
        print(f"After memory  : {candidate.after_action:>6} | risk {candidate.after_risk:.6f}")
        print(f"Memory delta  : {candidate.memory_delta:+.6f}")
        print(f"Amount        : {candidate.amount:g}")
        print(f"Profile       : {candidate.profile}")
        print(f"Device        : {candidate.device}")
        print(f"Browser       : {candidate.browser}")
        print(f"Receiver      : {candidate.receiver}")
        print(f"Product code  : {candidate.product_code}")
        print(f"Payer domain  : {candidate.payer_domain}")
        print(f"Payment path  : {candidate.card_network}/{candidate.card_type}")

    print("\n=== HOW TO DEMO THE TOP CANDIDATE ===")
    print("1. Reset the live session.")
    print("2. Create payment A using the candidate fields.")
    print("3. Confirm payment A as fraud in the Investigation page.")
    print("4. Advance the session by 72 hours.")
    print("5. Create payment B with the same candidate fields.")
    print("6. Compare the new v0.5 risk/action with the pre-memory reference above.")
    print("The uplift is trusted delayed evidence, not online model retraining.")

    if useful:
        return 0
    print(f"\nNo candidate exceeded the requested +{args.min_delta:.3f} risk uplift or action escalation.")
    print("Increase --profiles-per-config before changing any frozen model or threshold.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
