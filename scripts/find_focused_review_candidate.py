"""Focused offline REVIEW search around the strongest broad-search input pattern.

This utility varies only the human-enterable payment_profile token while keeping
all other fields fixed. The live adapter deterministically maps payment_profile
into masked IEEE-CIS-compatible card/address fields, so this is an input search,
not score/threshold manipulation.

It never calls FastAPI or Razorpay and never touches .linkrisk/session.jsonl.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.decision import REVIEW_THRESHOLD
from linkrisk.engine import FrozenChampionScorer
from linkrisk.live_engine import LiveTransactionInput, live_input_to_model_row


def _rows(start: int, stop: int, *, amount: float) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, object]] = []
    profiles: list[str] = []
    for index in range(start, stop):
        profile = f"REVIEW-F-{index:07d}"
        profiles.append(profile)
        event = LiveTransactionInput(
            amount=amount,
            payment_profile=profile,
            device_info="rv:52.0",
            browser_context="safari generic",
            receiver_domain="gmail.com",
            product_code="H",
            payer_domain="example.com",
            device_type="desktop",
            card_network="netbanking",
            card_type="unknown",
        )
        rows.append(
            live_input_to_model_row(
                event,
                transaction_id=f"FOCUS-{index:07d}",
                transaction_time=0.0,
            )
        )
    return pd.DataFrame(rows), profiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1_000_000)
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--amount", type=float, default=499.0)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    if args.count <= 0 or args.batch_size <= 0 or args.top <= 0 or args.amount <= 0:
        parser.error("count, batch-size, top and amount must be positive")

    scorer = FrozenChampionScorer.from_artifacts(ROOT)
    best: list[tuple[float, str]] = []

    print("Focused frozen REVIEW profile sweep")
    print(f"threshold    : {REVIEW_THRESHOLD:.15f}")
    print(f"amount       : INR {args.amount:,.2f}")
    print("device       : rv:52.0")
    print("browser      : safari generic")
    print("receiver     : gmail.com")
    print("product      : H")
    print("payment path : netbanking/unknown")
    print("session write: NO")
    print()

    for start in range(0, args.count, args.batch_size):
        stop = min(start + args.batch_size, args.count)
        frame, profiles = _rows(start, stop, amount=args.amount)
        raw_matrix = np.asarray(
            scorer.preprocessor.transform(frame[scorer.baseline_features]),
            dtype=np.float32,
        )
        scores = scorer.baseline_model.predict_proba(raw_matrix)[:, 1]
        best.extend((float(risk), profile) for risk, profile in zip(scores, profiles))
        best.sort(key=lambda pair: pair[0], reverse=True)
        del best[args.top:]

        current = best[0][0]
        status = " REVIEW FOUND" if current >= REVIEW_THRESHOLD else ""
        print(f"searched {stop:>9,}/{args.count:,}  best={current:.6f}{status}", flush=True)
        if current >= REVIEW_THRESHOLD:
            break

    print("\nTop focused candidates")
    found = False
    for rank, (risk, profile) in enumerate(best, start=1):
        action = "REVIEW" if risk >= REVIEW_THRESHOLD else "NOT REVIEW"
        found |= action == "REVIEW"
        print(f"\n#{rank}  baseline/v0.5={risk:.6f}  {action}")
        print(f"Amount          : {args.amount:g}")
        print(f"Payment profile : {profile}")
        print("Device context  : rv:52.0")
        print("Browser context : safari generic")
        print("Receiver domain : gmail.com")
        print("Product code    : H")

    if found:
        print("\nUse the highest-ranked REVIEW candidate unchanged in Razorpay Test Checkout.")
        return 0

    print("\nNo REVIEW candidate found in the focused sweep.")
    print("Increase --count or try another amount; do not change the frozen threshold/model.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
