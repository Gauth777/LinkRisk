"""One-time deterministic patch for analyst-requested Jane escalation.

Adds a label-free, transaction-time second-opinion path for existing cases without
changing the frozen automatic routing decision or consuming live intervention
capacity. This helper is removed after the source patch lands.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Patch anchor not found: {label}")
    return text.replace(old, new, 1)


# --- live engine -----------------------------------------------------------
path = Path("src/linkrisk/live_engine_v2.py")
text = path.read_text(encoding="utf-8")
if "import pandas as pd\n" not in text:
    text = text.replace("import numpy as np\n", "import numpy as np\nimport pandas as pd\n", 1)

method = '''    def deep_investigate(self, transaction_id: str) -> dict[str, Any]:
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

'''
anchor = "    def score_event(\n"
if "    def deep_investigate(self, transaction_id: str)" not in text:
    if anchor not in text:
        raise SystemExit("Patch anchor not found: live engine score_event")
    text = text.replace(anchor, method + anchor, 1)
path.write_text(text, encoding="utf-8")


# --- session journal -------------------------------------------------------
path = Path("backend/session_store.py")
text = path.read_text(encoding="utf-8")
append_method = '''    def append_analyst_investigation(self, transaction_id: str, requested_at: float) -> None:
        self._append(
            "analyst_jane",
            {
                "transaction_id": transaction_id,
                "requested_at": float(requested_at),
            },
        )

'''
anchor = "    def append_clock(self, clock: float) -> None:\n"
if "    def append_analyst_investigation(" not in text:
    if anchor not in text:
        raise SystemExit("Patch anchor not found: session append_clock")
    text = text.replace(anchor, append_method + anchor, 1)

replay_block = '''            if event_type == "analyst_jane":
                if not hasattr(engine, "deep_investigate"):
                    raise SessionStoreError("Runtime cannot replay analyst Jane investigation")
                engine.deep_investigate(str(payload["transaction_id"]))
                continue

'''
anchor = '            if event_type == "clock":\n'
if '            if event_type == "analyst_jane":' not in text:
    if anchor not in text:
        raise SystemExit("Patch anchor not found: session replay clock")
    text = text.replace(anchor, replay_block + anchor, 1)
path.write_text(text, encoding="utf-8")


# --- API -------------------------------------------------------------------
path = Path("backend/api.py")
text = path.read_text(encoding="utf-8")
endpoint = '''@app.post("/api/transactions/{transaction_id}/deep-investigate")
def deep_investigate(transaction_id: str) -> dict[str, Any]:
    """Run an analyst-requested Jane deduction without changing frozen routing."""
    engine = _engine_or_503()
    if not hasattr(engine, "deep_investigate"):
        raise HTTPException(status_code=503, detail="Analyst Jane escalation is unavailable.")
    try:
        existing = engine.get_record(transaction_id).get("analyst_jane") is not None
        record = engine.deep_investigate(transaction_id)
        if not existing:
            try:
                session_store.append_analyst_investigation(transaction_id, float(engine.clock))
            except SessionStoreError:
                # The inference already succeeded; optional local persistence must
                # not turn a valid analyst deduction into a false HTTP failure.
                pass
        return _jsonable(record)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


'''
anchor = '@app.post("/api/transactions/{transaction_id}/adjudicate")\n'
if '@app.post("/api/transactions/{transaction_id}/deep-investigate")' not in text:
    if anchor not in text:
        raise SystemExit("Patch anchor not found: adjudicate endpoint")
    text = text.replace(anchor, endpoint + anchor, 1)
path.write_text(text, encoding="utf-8")


# --- frontend types --------------------------------------------------------
path = Path("frontend/src/types.ts")
text = path.read_text(encoding="utf-8")
analyst_type = '''  analyst_jane?: {
    requested: boolean
    invocation_mode: string
    score: number
    score_threshold: number
    clue_count: number
    min_clue_families: number
    clue_families: Record<string, boolean>
    candidate: boolean
    corroborates_intervention: boolean
    assessment_label: string
    original_action: Action
    action_changed: boolean
    capacity_consumed: boolean
    uses_confirmed_fraud_as_input: boolean
    evidence_time: number
    scientific_note: string
  } | null
'''
anchor = "  case_file: {\n"
if "  analyst_jane?: {" not in text:
    if anchor not in text:
        raise SystemExit("Patch anchor not found: CaseRecord case_file")
    text = text.replace(anchor, analyst_type + anchor, 1)
path.write_text(text, encoding="utf-8")


# --- frontend API ----------------------------------------------------------
path = Path("frontend/src/api.ts")
text = path.read_text(encoding="utf-8")
method = '''  deepInvestigate: (id: string) => request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/deep-investigate`, {
    method: 'POST',
  }),
'''
anchor = "  adjudicate: (id: string, outcome: 'fraud' | 'legitimate') => request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/adjudicate`, {\n"
if "  deepInvestigate: (id: string)" not in text:
    if anchor not in text:
        raise SystemExit("Patch anchor not found: frontend adjudicate api")
    text = text.replace(anchor, method + anchor, 1)
path.write_text(text, encoding="utf-8")


# --- Investigation UI -----------------------------------------------------
path = Path("frontend/src/App.tsx")
text = path.read_text(encoding="utf-8")
text = text.replace("import { ProtectionPanel } from './ProtectionPanel'\n", "import { JaneEscalationPanel } from './JaneEscalationPanel'\n")

props_old = '''  onAdvance,
  onNavigate,
}: {
  record: CaseRecord
  preview: boolean
  onBack: () => void
  onAdjudicate: (outcome: 'fraud' | 'legitimate') => void
  onAdvance: () => void
  onNavigate: (page: Page) => void
}) {
  const hasSelection = !isNeutralRecord(record)
  const mentalist = hasSelection ? record.mentalist : null
'''
props_new = '''  onAdvance,
  onNavigate,
  onRecordUpdate,
}: {
  record: CaseRecord
  preview: boolean
  onBack: () => void
  onAdjudicate: (outcome: 'fraud' | 'legitimate') => void
  onAdvance: () => void
  onNavigate: (page: Page) => void
  onRecordUpdate: (record: CaseRecord) => void
}) {
  const hasSelection = !isNeutralRecord(record)
  const mentalist = hasSelection ? record.mentalist : null
  const janeScore = record.analyst_jane?.score ?? mentalist?.score
  const janeClueCount = record.analyst_jane?.clue_count ?? mentalist?.clue_count ?? 0
  const evidenceClues = record.analyst_jane?.clue_families ?? mentalist?.clue_families ?? {}
'''
if "  const janeScore = record.analyst_jane?.score" not in text:
    if props_old not in text:
        raise SystemExit("Patch anchor not found: InvestigationPage props")
    text = text.replace(props_old, props_new, 1)

text = text.replace("<b>{score(mentalist?.score)}/100</b><small>{mentalist?.clue_count ?? 0} independent clue families</small>", "<b>{score(janeScore)}/100</b><small>{janeClueCount} independent clue families</small>")
text = text.replace('<ProtectionPanel record={record} preview={preview} />', '<JaneEscalationPanel record={record} preview={preview} onUpdated={onRecordUpdate} />')
text = text.replace('active={!!mentalist?.clue_families?.[key]}', 'active={!!evidenceClues[key]}')

call_old = "<InvestigationPage record={selected} preview={preview} onBack={() => setPage('overview')} onAdjudicate={(outcome) => void adjudicate(outcome)} onAdvance={() => void advance()} onNavigate={setPage} />"
call_new = "<InvestigationPage record={selected} preview={preview} onBack={() => setPage('overview')} onAdjudicate={(outcome) => void adjudicate(outcome)} onAdvance={() => void advance()} onNavigate={setPage} onRecordUpdate={setSelected} />"
if call_new not in text:
    if call_old not in text:
        raise SystemExit("Patch anchor not found: InvestigationPage render")
    text = text.replace(call_old, call_new, 1)
path.write_text(text, encoding="utf-8")


# --- regression test -------------------------------------------------------
path = Path("tests/test_live_engine_v2.py")
text = path.read_text(encoding="utf-8")
test = '''\n\ndef test_review_can_request_jane_second_opinion_without_changing_action_or_capacity():
    mentalist = CountingMentalistScorer(score=0.99, active_clues=True)
    engine = LiveLinkRiskEngineV2(
        _champion(baseline_score=0.95, specialist_score=0.95),
        mentalist_scorer=mentalist,
    )

    record = engine.score_event(_event(), transaction_id="TX-REVIEW-JANE")
    before = engine.capacity_status().copy()

    assert record["decision"]["action"] == "REVIEW"
    assert record["mentalist"]["invoked"] is False
    assert mentalist.calls == 0

    investigated = engine.deep_investigate("TX-REVIEW-JANE")
    after = engine.capacity_status().copy()

    assert mentalist.calls == 1
    assert investigated["decision"]["action"] == "REVIEW"
    assert investigated["analyst_jane"]["requested"] is True
    assert investigated["analyst_jane"]["invocation_mode"] == "analyst_requested"
    assert investigated["analyst_jane"]["corroborates_intervention"] is True
    assert investigated["analyst_jane"]["action_changed"] is False
    assert investigated["analyst_jane"]["capacity_consumed"] is False
    assert investigated["analyst_jane"]["uses_confirmed_fraud_as_input"] is False
    assert before == after

    # Idempotent repeat: the stored transaction-time deduction is reused.
    engine.deep_investigate("TX-REVIEW-JANE")
    assert mentalist.calls == 1
'''
if "def test_review_can_request_jane_second_opinion_without_changing_action_or_capacity" not in text:
    text += test
path.write_text(text, encoding="utf-8")

print("Analyst Jane escalation patch applied")
