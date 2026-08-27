"""Find reproducible live-demo inputs that naturally cross the frozen REVIEW threshold.

This script is deliberately offline with respect to the LinkRisk live session:
- it does not call FastAPI or Razorpay;
- it does not read/write .linkrisk/session.jsonl;
- it does not alter model scores, thresholds, or policy;
- it only searches human-enterable inputs through the frozen baseline model.

For a fresh transaction with no matured trusted-feedback evidence, v0.5 falls back
exactly to the transaction-only baseline. Therefore any candidate whose baseline
risk is >= REVIEW_THRESHOLD will be a v0.5 REVIEW before Mentalist routing.
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

from linkrisk.decision import REVIEW_THRESHOLD
from linkrisk.engine import FrozenChampionScorer
from linkrisk.live_engine import LiveTransactionInput, live_input_to_model_row


AMOUNTS = (
    99.0,
    249.0,
    499.0,
    999.0,
    1499.0,
    2499.0,
    4999.0,
    7999.0,
    9999.0,
    14999.0,
    19999.0,
    24999.0,
    29999.0,
    34999.0,
    39999.0,
    44999.0,
    49500.0,
)
PRODUCT_CODES = ("W", "C", "H", "R", "S")
DEVICE_INFOS = (
    "Windows",
    "iOS Device",
    "MacOS",
    "Android",
    "SM-G960F Build/R16NW",
    "rv:52.0",
    "Trident/7.0",
)
BROWSER_CONTEXTS = (
    "chrome 65.0",
    "chrome 64.0",
    "mobile safari 11.0",
    "safari generic",
    "firefox 57.0",
    "edge 16.0",
    "ie 11.0 for desktop",
)
RECEIVER_DOMAINS = (
    "gmail.com",
    "hotmail.com",
    "anonymous.com",
    "yahoo.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
)


@dataclass(frozen=True)
class Candidate:
    amount: float
    payment_profile: str
    device_info: str
    browser_context: str
    receiver_domain: str
    product_code: str


def _bounded_amounts(max_amount: float) -> tuple[float, ...]:
    values = tuple(value for value in AMOUNTS if value <= max_amount)
    if max_amount > 0 and (not values or values[-1] != max_amount):
        values = (*values, float(max_amount))
    if not values:
        raise ValueError("max_amount must be positive")
    return values


def candidate_for(index: int, *, max_amount: float) -> Candidate:
    """Generate a deterministic, human-enterable candidate from an integer."""
    amounts = _bounded_amounts(max_amount)
    # Multipliers are pairwise different so adjacent profile tokens explore
    # different categorical/amount combinations instead of moving in lockstep.
    return Candidate(
        amount=amounts[(index * 11 + 3) % len(amounts)],
        payment_profile=f"REVIEW-{index:06d}",
        device_info=DEVICE_INFOS[(index * 5 + 1) % len(DEVICE_INFOS)],
        browser_context=BROWSER_CONTEXTS[(index * 3 + 2) % len(BROWSER_CONTEXTS)],
        receiver_domain=RECEIVER_DOMAINS[(index * 4 + 1) % len(RECEIVER_DOMAINS)],
        product_code=PRODUCT_CODES[(index * 7 + 2) % len(PRODUCT_CODES)],
    )


def _rows_for_candidates(
    candidates: list[Candidate],
    *,
    payer_domain: str,
    device_type: str,
    card_network: str,
    card_type: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for pos, candidate in enumerate(candidates):
        event = LiveTransactionInput(
            amount=candidate.amount,
            payment_profile=candidate.payment_profile,
            device_info=candidate.device_info,
            receiver_domain=candidate.receiver_domain,
            browser_context=candidate.browser_context,
            product_code=candidate.product_code,
            payer_domain=payer_domain,
            device_type=device_type,
            card_network=card_network,
            card_type=card_type,
        )
        rows.append(
            live_input_to_model_row(
                event,
                transaction_id=f"SEARCH-{pos:06d}",
                transaction_time=0.0,
            )
        )
    return pd.DataFrame(rows)


def search(
    *,
    count: int,
    batch_size: int,
    top_n: int,
    max_amount: float,
    payer_domain: str,
    device_type: str,
    card_network: str,
    card_type: str,
) -> list[tuple[float, Candidate]]:
    scorer = FrozenChampionScorer.from_artifacts(ROOT)
    best: list[tuple[float, Candidate]] = []

    for start in range(0, count, batch_size):
        stop = min(start + batch_size, count)
        candidates = [candidate_for(index, max_amount=max_amount) for index in range(start, stop)]
        frame = _rows_for_candidates(
            candidates,
            payer_domain=payer_domain,
            device_type=device_type,
            card_network=card_network,
            card_type=card_type,
        )
        raw_matrix = np.asarray(
            scorer.preprocessor.transform(frame[scorer.baseline_features]),
            dtype=np.float32,
        )
        scores = scorer.baseline_model.predict_proba(raw_matrix)[:, 1]
        best.extend((float(score), candidate) for score, candidate in zip(scores, candidates))
        best.sort(key=lambda pair: pair[0], reverse=True)
        del best[top_n:]

        current = best[0][0] if best else 0.0
        print(f"searched {stop:>7,}/{count:,}  best baseline={current:.6f}", flush=True)

    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100_000, help="Number of deterministic candidates to score")
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--top", type=int, default=10, help="How many highest-risk inputs to print")
    parser.add_argument("--max-amount", type=float, default=49_500.0)
    parser.add_argument(
        "--payer-domain",
        default="example.com",
        help="Checkout payer email domain. Default matches demo@example.com prefill.",
    )
    parser.add_argument("--device-type", default="desktop")
    parser.add_argument(
        "--card-network",
        default="netbanking",
        help="Use netbanking when the Razorpay test payment is completed with Netbanking.",
    )
    parser.add_argument(
        "--card-type",
        default="unknown",
        help="Netbanking normalizes to unknown card type; for cards use credit/debit as appropriate.",
    )
    args = parser.parse_args()

    if args.count <= 0 or args.batch_size <= 0 or args.top <= 0:
        parser.error("count, batch-size and top must be positive")
    if args.max_amount <= 0:
        parser.error("max-amount must be positive")

    print("Frozen REVIEW candidate search")
    print(f"threshold    : {REVIEW_THRESHOLD:.15f}")
    print(f"max amount   : INR {args.max_amount:,.2f}")
    print(f"payment path : {args.card_network}/{args.card_type}")
    print("session write: NO")
    print()

    best = search(
        count=args.count,
        batch_size=args.batch_size,
        top_n=args.top,
        max_amount=args.max_amount,
        payer_domain=args.payer_domain,
        device_type=args.device_type,
        card_network=args.card_network,
        card_type=args.card_type,
    )

    print("\nTop candidates")
    found_review = False
    for rank, (risk, candidate) in enumerate(best, start=1):
        action = "REVIEW" if risk >= REVIEW_THRESHOLD else "NOT REVIEW"
        found_review |= action == "REVIEW"
        print(f"\n#{rank}  baseline/v0.5={risk:.6f}  {action}")
        print(f"Amount          : {candidate.amount:g}")
        print(f"Payment profile : {candidate.payment_profile}")
        print(f"Device context  : {candidate.device_info}")
        print(f"Browser context : {candidate.browser_context}")
        print(f"Receiver domain : {candidate.receiver_domain}")
        print(f"Product code    : {candidate.product_code}")

    if found_review:
        print("\nAt least one candidate naturally crosses the frozen REVIEW threshold.")
        print("Enter the highest-ranked REVIEW candidate unchanged through Razorpay Test Checkout.")
        return 0

    print("\nNo REVIEW candidate was found in this search budget.")
    print("Increase --count; do not change the frozen threshold or model.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
