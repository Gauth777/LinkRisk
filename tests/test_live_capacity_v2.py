from linkrisk.live_capacity_v2 import CausalCapacityController


def test_review_is_never_blocked_when_capacity_is_empty():
    controller = CausalCapacityController(total_burst=1.0, mentalist_burst=1.0)

    controller.begin_transaction()
    assert controller.authorize_v5_verify().authorized is True

    controller.begin_transaction()
    review = controller.authorize_review()

    assert review.authorized is True
    assert review.reason == "V5_REVIEW_MANDATORY_BUDGET_OVERFLOW"
    status = controller.snapshot()
    assert status["mandatory_review_overflow"] == 1


def test_verify_is_deferred_until_capacity_refills():
    controller = CausalCapacityController(total_rate=0.50, total_burst=1.0, mentalist_burst=1.0)

    controller.begin_transaction()
    assert controller.authorize_v5_verify().authorized is True

    controller.begin_transaction()
    denied = controller.authorize_v5_verify()
    assert denied.authorized is False
    assert denied.reason == "V5_VERIFY_CAPACITY_DEFERRED"

    controller.begin_transaction()
    allowed = controller.authorize_v5_verify()
    assert allowed.authorized is True


def test_mentalist_requires_both_total_and_proactive_capacity():
    controller = CausalCapacityController(
        total_rate=0.50,
        mentalist_rate=0.25,
        total_burst=2.0,
        mentalist_burst=1.0,
    )

    controller.begin_transaction()
    first = controller.authorize_mentalist_verify()
    assert first.authorized is True

    controller.begin_transaction()
    second = controller.authorize_mentalist_verify()
    assert second.authorized is False
    assert second.reason == "MENTALIST_RESERVE_DEFERRED"


def test_snapshot_tracks_selective_inference_accounting():
    controller = CausalCapacityController()
    for invoked in (False, False, True, False):
        controller.begin_transaction()
        controller.record_mentalist(invoked=invoked)

    status = controller.snapshot()
    assert status["transactions_seen"] == 4
    assert status["mentalist_invoked"] == 1
    assert status["mentalist_bypassed"] == 3
    assert status["mentalist_invocation_share"] == 0.25


def test_sustained_total_capacity_is_bounded_by_rate_plus_burst():
    controller = CausalCapacityController(
        total_rate=0.06,
        total_burst=6.0,
        mentalist_rate=0.01,
        mentalist_burst=3.0,
    )
    authorized = 0
    transactions = 1000
    for _ in range(transactions):
        controller.begin_transaction()
        if controller.authorize_v5_verify().authorized:
            authorized += 1

    # Token-bucket safety property: a stream cannot consume more than its initial
    # burst plus the sustained credits minted by arrivals (allow one rounding unit).
    assert authorized <= 6 + int(transactions * 0.06) + 1
    assert authorized < transactions * 0.07
