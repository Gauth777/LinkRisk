from __future__ import annotations

from pathlib import Path

import pytest

from backend.session_store import LocalSessionStore, SessionStoreError
from linkrisk.live_engine import LiveTransactionInput


class FakeEngine:
    def __init__(self) -> None:
        self.clock = 0.0
        self.records: dict[str, dict] = {}
        self.adjudications: dict[str, str] = {}

    def score_event(self, event: LiveTransactionInput, *, transaction_id: str) -> dict:
        record = {
            "transaction_id": transaction_id,
            "transaction_time": float(self.clock),
            "input": event,
        }
        self.records[transaction_id] = record
        return record

    def adjudicate(self, transaction_id: str, outcome: str) -> None:
        if transaction_id not in self.records:
            raise KeyError(transaction_id)
        self.adjudications[transaction_id] = outcome

    def clear_adjudication(self, transaction_id: str) -> None:
        self.adjudications.pop(transaction_id, None)


class FakeRazorpayState:
    def __init__(self) -> None:
        self.bindings: dict[str, str] = {}

    def bind_payment(self, payment_id: str, transaction_id: str) -> None:
        self.bindings[payment_id] = transaction_id


def sample_input() -> LiveTransactionInput:
    return LiveTransactionInput(
        amount=8750.0,
        payment_profile="CUSTOMER-A",
        device_info="DEVICE-X",
        receiver_domain="shop.example",
        browser_context="CHROME-X",
        product_code="W",
        payer_domain="gmail.com",
        device_type="desktop",
        card_network="upi",
        card_type="unknown",
    )


def test_journal_replays_causal_session_and_payment_binding(tmp_path: Path) -> None:
    store = LocalSessionStore(tmp_path / "session.jsonl")
    record = {
        "transaction_id": "RZP-pay_demo123",
        "transaction_time": 100.0,
        "input": sample_input(),
        "integration": {
            "source": "razorpay_checkout_verify",
            "payment_id": "pay_demo123",
            "event_type": "checkout.verified",
        },
    }

    store.append_transaction(record)
    store.append_adjudication("RZP-pay_demo123", "fraud", 110.0)
    store.append_clock(200.0)

    engine = FakeEngine()
    razorpay = FakeRazorpayState()
    replayed = store.replay(engine, razorpay)

    assert replayed == 1
    assert engine.clock == 200.0
    assert engine.records["RZP-pay_demo123"]["transaction_time"] == 100.0
    assert engine.records["RZP-pay_demo123"]["integration"]["source"] == "razorpay_checkout_verify"
    assert engine.adjudications["RZP-pay_demo123"] == "fraud"
    assert razorpay.bindings == {"pay_demo123": "RZP-pay_demo123"}
    assert store.status()["transaction_count"] == 1


def test_clear_removes_persisted_session(tmp_path: Path) -> None:
    store = LocalSessionStore(tmp_path / "session.jsonl")
    store.append_clock(123.0)
    assert store.has_events()

    store.clear()

    assert not store.has_events()
    assert not store.path.exists()


def test_corrupt_journal_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")
    store = LocalSessionStore(path)

    with pytest.raises(SessionStoreError, match="corrupt"):
        store.events()
