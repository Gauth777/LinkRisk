import { useEffect, useState } from 'react'
import { AlertTriangle, BrainCircuit, Check, RefreshCw, SearchCheck, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from './api'
import type { CaseRecord } from './types'
import './jane-escalation.css'

const pctScore = (value?: number | null) => value == null ? '—' : `${Math.round(Math.max(0, Math.min(1, value)) * 100)}`

export function JaneEscalationPanel({
  record,
  preview,
  onUpdated,
}: {
  record: CaseRecord
  preview: boolean
  onUpdated: (record: CaseRecord) => void
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    setLoading(false)
  }, [record.transaction_id])

  const analyst = record.analyst_jane ?? null
  const automatic = !!record.mentalist?.invoked
  const originalScore = automatic ? record.mentalist?.score : null
  const visibleScore = analyst?.score ?? originalScore
  const visibleClues = analyst?.clue_families ?? record.mentalist?.clue_families ?? {}
  const visibleClueCount = analyst?.clue_count ?? record.mentalist?.clue_count ?? 0
  const threshold = analyst?.score_threshold ?? record.mentalist?.score_threshold ?? null
  const corroborates = analyst?.corroborates_intervention ?? false

  const runJane = async () => {
    setLoading(true)
    setError('')
    try {
      const updated = await api.deepInvestigate(record.transaction_id)
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Jane investigation failed.')
    } finally {
      setLoading(false)
    }
  }

  return <section className={`card jane-escalation ${analyst ? 'completed' : ''}`}>
    <div className="jane-escalation-head">
      <div className="jane-escalation-title">
        <span className="jane-escalation-orb"><BrainCircuit size={25} /></span>
        <div>
          <span className="eyebrow">Analyst escalation</span>
          <h2>{analyst ? 'Jane has a second opinion' : automatic ? 'Jane already investigated this case' : 'Not satisfied with the first decision?'}</h2>
          <p>{automatic
            ? 'The selective runtime already invoked Jane because the cheap evidence gate found enough independent clues.'
            : 'A human investigator can explicitly spend deeper reasoning on this case without changing the frozen v0.5 decision automatically.'}</p>
        </div>
      </div>
      <span className={`jane-escalation-state ${analyst ? (corroborates ? 'corroborates' : 'advisory') : automatic ? 'automatic' : ''}`}>
        {analyst ? (corroborates ? <><Check size={16} />CORROBORATES</> : <><SearchCheck size={16} />SECOND OPINION</>) : automatic ? <><Sparkles size={16} />AUTO-INVOKED</> : <><SearchCheck size={16} />AVAILABLE</>}
      </span>
    </div>

    {(analyst || automatic) && <div className="jane-escalation-result">
      <div className="jane-signal-card">
        <span>Jane score</span>
        <strong>{pctScore(visibleScore)}<small>/100</small></strong>
        <em>{threshold == null ? 'advisory signal' : `frozen boundary ${Math.round(threshold * 100)}/100`}</em>
      </div>
      <div className="jane-signal-card">
        <span>Independent clues</span>
        <strong>{visibleClueCount}</strong>
        <em>velocity · behavior · coordination · reuse</em>
      </div>
      <div className="jane-signal-card conclusion">
        <span>Interpretation</span>
        <strong>{analyst?.assessment_label ?? (record.mentalist?.candidate ? 'Actionable evidence' : 'No escalation signal')}</strong>
        <em>Final action remains {record.decision.action}</em>
      </div>
    </div>}

    {(analyst || automatic) && <div className="jane-clue-strip">
      {Object.entries(visibleClues).map(([family, active]) => <span className={active ? 'active' : ''} key={family}>
        {active ? <Check size={14} /> : null}{family.replaceAll('_', ' ')}
      </span>)}
    </div>}

    {!automatic && !analyst && <div className="jane-escalation-callout">
      <ShieldCheck size={22} />
      <div>
        <b>System decision: {record.decision.action}</b>
        <span>Ask Jane to reconstruct the transaction-time evidence and run the frozen Mentalist model as an analyst-requested advisory readout.</span>
      </div>
      <button disabled={preview || loading} onClick={() => void runJane()}>
        {loading ? <><RefreshCw className="spin" size={18} />Investigating…</> : <><BrainCircuit size={18} />Ask Jane</>}
      </button>
    </div>}

    {analyst && <div className="jane-advisory-note">
      <AlertTriangle size={17} />
      <span><b>Advisory, not an override.</b> This analyst-requested pass uses the original transaction-time, label-free evidence snapshot. It does not consume fraud labels, intervention tokens, or silently change the frozen action.</span>
    </div>}

    {error && <div className="jane-escalation-error"><AlertTriangle size={17} />{error}</div>}
  </section>
}
