from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class CapacityDecision:
    authorized: bool
    reason: str
    total_tokens_after: float
    mentalist_tokens_after: float


class CausalCapacityController:
    """Token-bucket intervention controller for the live v2 runtime.

    The development batch policy targets 6% total intervention and reserves up to
    1% for proactive Mentalist cases. A streaming system cannot rank future rows,
    so the live analogue uses causal token buckets:

    - total intervention tokens refill at 0.06 per arriving transaction;
    - Mentalist tokens refill at 0.01 per arriving transaction;
    - small burst capacities absorb short legitimate spikes;
    - v0.5 REVIEW is always authorized, even if that temporarily exceeds budget.

    No labels, future rows or test outcomes are consumed by this controller.
    """

    def __init__(
        self,
        *,
        total_rate: float = 0.06,
        mentalist_rate: float = 0.01,
        total_burst: float = 6.0,
        mentalist_burst: float = 3.0,
    ) -> None:
        for name, value in (
            ("total_rate", total_rate),
            ("mentalist_rate", mentalist_rate),
            ("total_burst", total_burst),
            ("mentalist_burst", mentalist_burst),
        ):
            if float(value) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if total_rate <= 0.0 or total_rate >= 1.0:
            raise ValueError("total_rate must lie in (0, 1)")
        if mentalist_rate < 0.0 or mentalist_rate > total_rate:
            raise ValueError("mentalist_rate must lie in [0, total_rate]")
        if total_burst < 1.0:
            raise ValueError("total_burst must be at least 1 intervention")
        if mentalist_rate > 0.0 and mentalist_burst < 1.0:
            raise ValueError("mentalist_burst must be at least 1 when enabled")

        self.total_rate = float(total_rate)
        self.mentalist_rate = float(mentalist_rate)
        self.total_burst = float(total_burst)
        self.mentalist_burst = float(mentalist_burst)
        self.reset()

    def reset(self) -> None:
        # Start full: token buckets conventionally allow a bounded cold-start
        # burst rather than suppressing the first legitimate investigations.
        self.total_tokens = float(self.total_burst)
        self.mentalist_tokens = float(self.mentalist_burst)
        self.transactions_seen = 0
        self.interventions_authorized = 0
        self.mentalist_authorized = 0
        self.v5_verify_authorized = 0
        self.mandatory_reviews = 0
        self.mandatory_review_overflow = 0
        self.capacity_denials = 0
        self.mentalist_capacity_denials = 0
        self.mentalist_invoked = 0
        self.mentalist_bypassed = 0

    def begin_transaction(self) -> None:
        self.transactions_seen += 1
        self.total_tokens = min(
            self.total_burst,
            self.total_tokens + self.total_rate,
        )
        self.mentalist_tokens = min(
            self.mentalist_burst,
            self.mentalist_tokens + self.mentalist_rate,
        )

    def record_mentalist(self, *, invoked: bool) -> None:
        if invoked:
            self.mentalist_invoked += 1
        else:
            self.mentalist_bypassed += 1

    def _consume_total(self) -> bool:
        if self.total_tokens + 1e-12 < 1.0:
            return False
        self.total_tokens = max(self.total_tokens - 1.0, 0.0)
        return True

    def authorize_review(self) -> CapacityDecision:
        """REVIEW is a safety boundary and is never blocked by capacity."""
        self.mandatory_reviews += 1
        consumed = self._consume_total()
        if not consumed:
            self.mandatory_review_overflow += 1
        self.interventions_authorized += 1
        return CapacityDecision(
            authorized=True,
            reason=(
                "V5_REVIEW_MANDATORY"
                if consumed
                else "V5_REVIEW_MANDATORY_BUDGET_OVERFLOW"
            ),
            total_tokens_after=self.total_tokens,
            mentalist_tokens_after=self.mentalist_tokens,
        )

    def authorize_v5_verify(self) -> CapacityDecision:
        if self._consume_total():
            self.interventions_authorized += 1
            self.v5_verify_authorized += 1
            return CapacityDecision(
                authorized=True,
                reason="V5_VERIFY_CAPACITY_AUTHORIZED",
                total_tokens_after=self.total_tokens,
                mentalist_tokens_after=self.mentalist_tokens,
            )
        self.capacity_denials += 1
        return CapacityDecision(
            authorized=False,
            reason="V5_VERIFY_CAPACITY_DEFERRED",
            total_tokens_after=self.total_tokens,
            mentalist_tokens_after=self.mentalist_tokens,
        )

    def authorize_mentalist_verify(self) -> CapacityDecision:
        if self.total_tokens + 1e-12 < 1.0:
            self.capacity_denials += 1
            self.mentalist_capacity_denials += 1
            return CapacityDecision(
                authorized=False,
                reason="MENTALIST_TOTAL_CAPACITY_DEFERRED",
                total_tokens_after=self.total_tokens,
                mentalist_tokens_after=self.mentalist_tokens,
            )
        if self.mentalist_tokens + 1e-12 < 1.0:
            self.mentalist_capacity_denials += 1
            return CapacityDecision(
                authorized=False,
                reason="MENTALIST_RESERVE_DEFERRED",
                total_tokens_after=self.total_tokens,
                mentalist_tokens_after=self.mentalist_tokens,
            )

        self.total_tokens = max(self.total_tokens - 1.0, 0.0)
        self.mentalist_tokens = max(self.mentalist_tokens - 1.0, 0.0)
        self.interventions_authorized += 1
        self.mentalist_authorized += 1
        return CapacityDecision(
            authorized=True,
            reason="MENTALIST_CAPACITY_AUTHORIZED",
            total_tokens_after=self.total_tokens,
            mentalist_tokens_after=self.mentalist_tokens,
        )

    def snapshot(self) -> dict[str, Any]:
        seen = max(self.transactions_seen, 1)
        invoked = self.mentalist_invoked
        return {
            "policy": "causal_token_bucket_v2",
            "transactions_seen": self.transactions_seen,
            "total_rate": self.total_rate,
            "mentalist_rate": self.mentalist_rate,
            "total_burst": self.total_burst,
            "mentalist_burst": self.mentalist_burst,
            "total_tokens": self.total_tokens,
            "mentalist_tokens": self.mentalist_tokens,
            "interventions_authorized": self.interventions_authorized,
            "observed_intervention_share": self.interventions_authorized / seen,
            "mentalist_invoked": invoked,
            "mentalist_bypassed": self.mentalist_bypassed,
            "mentalist_invocation_share": invoked / seen,
            "mentalist_authorized": self.mentalist_authorized,
            "v5_verify_authorized": self.v5_verify_authorized,
            "mandatory_reviews": self.mandatory_reviews,
            "mandatory_review_overflow": self.mandatory_review_overflow,
            "capacity_denials": self.capacity_denials,
            "mentalist_capacity_denials": self.mentalist_capacity_denials,
        }
