from __future__ import annotations

from pathlib import Path

from backend.protection import ProtectionStore, create_full_test_refund


class _Response:
    ok = True
    status_code = 200

    def json(self):
        return {
            "id": "rfnd_demo123",
            "entity": "refund",
            "amount": 49900,
            "currency": "INR",
            "payment_id": "pay_demo123",
            "status": "processed",
            "speed_requested": "normal",
            "speed_processed": "normal",
            "created_at": 1_700_000_000,
        }


def test_create_full_test_refund_uses_server_side_payment_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, auth, json, timeout):
        captured.update(url=url, auth=auth, json=json, timeout=timeout)
        return _Response()

    monkeypatch.setattr("backend.protection.requests.post", fake_post)
    result = create_full_test_refund(
        key_id="rzp_test_demo",
        key_secret="secret",
        payment_id="pay_demo123",
        transaction_id="RZP-pay_demo123",
    )

    assert result["id"] == "rfnd_demo123"
    assert captured["url"] == "https://api.razorpay.com/v1/payments/pay_demo123/refund"
    assert captured["auth"] == ("rzp_test_demo", "secret")
    request_json = captured["json"]
    assert isinstance(request_json, dict)
    assert "amount" not in request_json  # omission means full refund
    assert request_json["speed"] == "normal"
    assert request_json["notes"]["linkrisk_transaction"] == "RZP-pay_demo123"


def test_protection_store_persists_and_summarises_processed_refunds(tmp_path: Path) -> None:
    store = ProtectionStore(tmp_path / "protection.json")
    store.put(
        "RZP-pay_a",
        {
            "refund_status": "processed",
            "amount": 499.0,
            "refund_id": "rfnd_a",
        },
    )
    store.put(
        "RZP-pay_b",
        {
            "refund_status": "pending",
            "amount": 250.0,
            "refund_id": "rfnd_b",
        },
    )

    assert store.get("RZP-pay_a")["refund_id"] == "rfnd_a"
    summary = store.summary()
    assert summary["responses"] == 2
    assert summary["refunds_initiated"] == 2
    assert summary["protected_payments"] == 1
    assert summary["protected_amount"] == 499.0

    store.clear()
    assert store.summary()["responses"] == 0
