from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from linkrisk.baseline import ID_COL
from linkrisk.cost_aware_router_v2 import evidence_gate
from linkrisk.feedback_features_v5 import build_feedback_features_v5
from linkrisk.live_capacity_v2 import CausalCapacityController
from linkrisk.live_engine import LiveLinkRiskEngine, LiveTransactionInput, live_input_to_model_row
from linkrisk.mentalist_features_v7 import (
    MENTALIST_FAMILIES,
    build_mentalist_features_v7,
    clue_activations,
)
from linkrisk.relationship_features_v4 import build_relationship_features_v4


class LiveLinkRiskEngineV2(LiveLinkRiskEngine):
    """Live selective-inference runtime for LinkRisk v2.

    This runtime keeps the frozen v0.5 scorer and frozen Mentalist model intact.
    It changes orchestration only:

    1. score v0.5 first;
    2. compute cheap label-free clue families;
    3. invoke the Mentalist model only for evidence-bearing v0.5 ALLOW rows;
    4. track causal intervention capacity without vetoing a frozen-threshold
       Mentalist-positive case;
    5. preserve v0.5 REVIEW unconditionally.

    The controller is a streaming engineering policy, not a new held-out-tested
    model claim. The old v1.0 final held-out result remains the final v1 result.
    """

    POLICY_VERSION = "cost_aware_v2_live"

    def __init__(
        self,
        scorer,
        *,
        mentalist_scorer=None,
        capacity_controller: CausalCapacityController | None = None,
        start_time: float = 0.0,
    ) -> None:
        super().__init__(
            scorer,
            mentalist_scorer=mentalist_scorer,
            start_time=start_time,
        )
        self.capacity_controller = capacity_controller or CausalCapacityController()

    def reset(self, *, start_time: float = 0.0) -> None:
        super().reset(start_time=start_time)
        self.capacity_controller.reset()

    def capacity_status(self) -> dict[str, Any]:
        return self.capacity_controller.snapshot()

    def deep_investigate(self, transaction_id: str) -> dict[str, Any]:
        """Run Jane on the original transaction-time evidence as an analyst request.

        Automatic v2 routing intentionally bypasses Mentalist for v0.5 REVIEW and
        many low-evidence rows. A human analyst may still request a second opinion.
        This method reuses the proactive feature snapshot captured when the
        transaction was scored, so later traffic and adjudications cannot leak into
        the deduction. It does not consume capacity tokens or alter the frozen action.
        """
        tx_id = str(transaction_id)
        if tx_id not in self._records:
            raise KeyError(f"Unknown transaction id: {tx_id}")
        if self.mentalist_scorer is None:
            raise RuntimeError("Mentalist scorer is unavailable")

        record = self._records[tx_id]
        if record.get("analyst_jane") is not None:
            return record

        proactive_row = record.get("proactive_features")
        if not isinstance(proactive_row, dict) or not proactive_row:
            raise ValueError("Transaction has no stored proactive evidence snapshot")

        proactive = pd.DataFrame([proactive_row], index=[tx_id])
        baseline_risk = float(record["decision"]["baseline_risk"])
        state = self.mentalist_scorer.score_batch(
            proactive,
            np.asarray([baseline_risk], dtype=float),
        )

        jane_score = float(state.jane_scores[0])
        clue_count = int(state.clue_count[0])
        clue_row = state.clue_frame.iloc[0].to_dict()
        clue_families = {
            family: bool(int(clue_row.get(f"clue_{family}", 0)))
            for family in MENTALIST_FAMILIES
        }
        threshold = float(self.mentalist_scorer.policy.jane_score_threshold)
        min_clues = int(self.mentalist_scorer.policy.min_clue_families)
        corroborates = bool(jane_score >= threshold and clue_count >= min_clues)
        action = str(record["decision"]["action"])

        if action == "REVIEW":
            assessment = (
                "Corroborates REVIEW"
                if corroborates
                else "Does not independently corroborate REVIEW"
            )
        elif action == "VERIFY":
            assessment = (
                "Corroborates VERIFY"
                if corroborates
                else "Weak secondary evidence"
            )
        else:
            assessment = (
                "Finds elevated present-tense evidence"
                if corroborates
                else "No actionable secondary evidence"
            )

        record["analyst_jane"] = {
            "requested": True,
            "invocation_mode": "analyst_requested",
            "score": jane_score,
            "score_threshold": threshold,
            "clue_count": clue_count,
            "min_clue_families": min_clues,
            "clue_families": clue_families,
            "candidate": corroborates,
            "corroborates_intervention": bool(corroborates and action in {"VERIFY", "REVIEW"}),
            "assessment_label": assessment,
            "original_action": action,
            "action_changed": False,
            "capacity_consumed": False,
            "uses_confirmed_fraud_as_input": False,
            "evidence_time": float(record["transaction_time"]),
            "scientific_note": (
                "Analyst-requested advisory inference on the original transaction-time "
                "label-free evidence snapshot; not a validated routing override."
            ),
        }
        record["case_file"]["analyst_jane_requested"] = True
        record["case_file"]["analyst_jane_assessment"] = assessment
        return record

    def score_event(
        self,
        event: LiveTransactionInput,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        tx_id = transaction_id or self.next_transaction_id()
        if tx_id in self._records:
            raise ValueError(f"Duplicate transaction id: {tx_id}")

        current_row = live_input_to_model_row(
            event,
            transaction_id=tx_id,
            transaction_time=self.clock,
        )
        frame = self._history_frame(current_row)
        eligibility = self._label_eligibility(frame, tx_id)

        relationship = build_relationship_features_v4(frame)
        feedback = build_feedback_features_v5(frame, eligibility)
        scored = self.scorer.score_batch(
            frame.loc[[tx_id]],
            relationship.loc[[tx_id]],
            feedback.loc[[tx_id]],
        )
        decision = scored.loc[tx_id].to_dict()
        v5_action = str(decision["action"])
        decision["v5_action"] = v5_action
        decision["policy_version"] = self.POLICY_VERSION

        mentalist_payload: dict[str, Any] | None = None
        proactive_row: dict[str, Any] = {}
        mentalist_invoked = False
        mentalist_candidate = False
        mentalist_score = float("nan")
        clue_count = 0

        if self.mentalist_scorer is not None:
            proactive = build_mentalist_features_v7(frame)
            proactive_current = proactive.loc[[tx_id]]
            proactive_row = proactive.loc[tx_id].to_dict()

            # Cheap evidence-family evaluation happens before predict_proba.
            cheap_clues = clue_activations(
                proactive_current,
                self.mentalist_scorer.clue_thresholds,
            )
            clue_values = cheap_clues.iloc[0].to_dict()
            clue_count = int(clue_values["independent_clue_count"])
            clue_families = {
                family: bool(int(clue_values.get(f"clue_{family}", 0)))
                for family in MENTALIST_FAMILIES
            }
            below_baseline_review = bool(
                float(decision["baseline_risk"])
                < self.mentalist_scorer.policy.baseline_review_threshold
            )
            gated = evidence_gate(
                v5_actions=np.asarray([v5_action], dtype=object),
                baseline_risk=np.asarray([float(decision["baseline_risk"])], dtype=float),
                clue_count=np.asarray([clue_count], dtype=int),
                min_clue_families=self.mentalist_scorer.policy.min_clue_families,
                baseline_review_threshold=self.mentalist_scorer.policy.baseline_review_threshold,
            )
            mentalist_invoked = bool(gated[0])

            if mentalist_invoked:
                mentalist_state = self.mentalist_scorer.score_batch(
                    proactive_current,
                    np.asarray([float(decision["baseline_risk"])], dtype=float),
                )
                mentalist_score = float(mentalist_state.jane_scores[0])
                mentalist_candidate = bool(
                    mentalist_score >= self.mentalist_scorer.policy.jane_score_threshold
                )

            if v5_action != "ALLOW":
                bypass_reason = "v0.5 already requires intervention"
            elif not below_baseline_review:
                bypass_reason = "transaction baseline already crosses REVIEW boundary"
            elif clue_count < self.mentalist_scorer.policy.min_clue_families:
                bypass_reason = "insufficient independent clue families"
            else:
                bypass_reason = None

            mentalist_payload = {
                "score": mentalist_score,
                "score_threshold": float(self.mentalist_scorer.policy.jane_score_threshold),
                "clue_count": clue_count,
                "min_clue_families": int(self.mentalist_scorer.policy.min_clue_families),
                "clue_families": clue_families,
                "below_baseline_review_boundary": below_baseline_review,
                "invoked": mentalist_invoked,
                "bypassed": not mentalist_invoked,
                "bypass_reason": bypass_reason,
                "candidate": mentalist_candidate,
                "promoted_by_jane": False,
                "displaced_v5_verify": False,
                "capacity_authorized": False,
                "uses_confirmed_fraud_as_input": False,
            }

        # Capacity state advances only after all model/feature work succeeded, so
        # failed requests do not consume or mint intervention capacity.
        self.capacity_controller.begin_transaction()
        self.capacity_controller.record_mentalist(invoked=mentalist_invoked)

        final_action = "ALLOW"
        routing_reason = "V5_ALLOW"
        capacity_decision = None

        if v5_action == "REVIEW":
            capacity_decision = self.capacity_controller.authorize_review()
            final_action = "REVIEW"
            routing_reason = capacity_decision.reason
        elif v5_action == "VERIFY":
            capacity_decision = self.capacity_controller.authorize_v5_verify()
            final_action = "VERIFY" if capacity_decision.authorized else "ALLOW"
            routing_reason = capacity_decision.reason
        elif mentalist_candidate:
            # A frozen-threshold Jane-positive case is operationally actionable.
            # Capacity remains observable, but the tiny streaming reserve no longer
            # turns a strong Jane result back into ALLOW in a small live session.
            capacity_decision = self.capacity_controller.authorize_mentalist_verify(
                enforce_budget=False,
            )
            final_action = "VERIFY" if capacity_decision.authorized else "ALLOW"
            routing_reason = capacity_decision.reason
            if mentalist_payload is not None:
                mentalist_payload["promoted_by_jane"] = bool(capacity_decision.authorized)
                mentalist_payload["capacity_authorized"] = bool(
                    capacity_decision.budget_authorized
                )
        elif mentalist_invoked:
            routing_reason = "MENTALIST_SCORE_BELOW_THRESHOLD"
        elif self.mentalist_scorer is not None:
            routing_reason = "MENTALIST_BYPASSED_EVIDENCE_GATE"

        decision["action"] = final_action
        decision["routing_reason"] = routing_reason

        feedback_row = feedback.loc[tx_id].to_dict()
        case_file = self._build_case_file(
            decision=decision,
            mentalist=mentalist_payload,
            feedback=feedback_row,
        )
        explanations = {
            "V5_REVIEW_MANDATORY": "The frozen v0.5 hard-review decision is immutable and consumed available live capacity.",
            "V5_REVIEW_MANDATORY_BUDGET_OVERFLOW": "The frozen v0.5 hard-review decision is immutable; safety overrides the live intervention budget when necessary.",
            "V5_VERIFY_CAPACITY_AUTHORIZED": "The frozen v0.5 VERIFY case was admitted by the causal intervention-capacity controller.",
            "V5_VERIFY_CAPACITY_DEFERRED": "The v0.5 VERIFY request was deferred because the live intervention budget had no token available.",
            "MENTALIST_CAPACITY_AUTHORIZED": "Present-tense evidence crossed the frozen Mentalist boundary and available live capacity admitted the proactive VERIFY case.",
            "MENTALIST_PROACTIVE_RESERVE_OVERFLOW": "Present-tense evidence crossed the frozen Mentalist boundary, so the case was promoted to VERIFY while the exhausted Jane reserve was recorded as an operational overflow.",
            "MENTALIST_PROACTIVE_TOTAL_BUDGET_OVERFLOW": "Present-tense evidence crossed the frozen Mentalist boundary, so the case was promoted to VERIFY while the exhausted total intervention budget was recorded as an operational overflow.",
            "MENTALIST_TOTAL_CAPACITY_DEFERRED": "Mentalist formed an eligible case, but total live intervention capacity was exhausted.",
            "MENTALIST_RESERVE_DEFERRED": "Mentalist formed an eligible case, but its proactive intervention reserve was temporarily exhausted.",
            "MENTALIST_SCORE_BELOW_THRESHOLD": "The evidence gate justified deeper reasoning, but the frozen Mentalist score did not cross its action boundary.",
            "MENTALIST_BYPASSED_EVIDENCE_GATE": "Cheap evidence was sufficient to bypass Mentalist model inference for this transaction.",
        }
        if routing_reason in explanations:
            case_file["explanation"] = explanations[routing_reason]

        capacity_snapshot = self.capacity_controller.snapshot()
        capacity_payload = {
            "decision": None,
            "state": capacity_snapshot,
        }
        if capacity_decision is not None:
            capacity_payload["decision"] = {
                "authorized": bool(capacity_decision.authorized),
                "budget_authorized": bool(capacity_decision.budget_authorized),
                "reason": capacity_decision.reason,
                "total_tokens_after": float(capacity_decision.total_tokens_after),
                "mentalist_tokens_after": float(capacity_decision.mentalist_tokens_after),
            }

        network = self._build_network_snapshot(frame, tx_id)
        record = {
            "transaction_id": tx_id,
            "transaction_time": float(self.clock),
            "input": event,
            "raw": dict(current_row),
            "decision": decision,
            "mentalist": mentalist_payload,
            "capacity": capacity_payload,
            "case_file": case_file,
            "relationship_features": relationship.loc[tx_id].to_dict(),
            "proactive_features": proactive_row,
            "feedback_features": feedback_row,
            "network": network,
        }

        self._rows.append(dict(current_row))
        self._records[tx_id] = record
        return record
