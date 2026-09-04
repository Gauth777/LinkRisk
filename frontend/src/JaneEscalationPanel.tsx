import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, BrainCircuit, Check, Clock3, Database, RefreshCw, SearchCheck, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from './api'
import type { CaseRecord } from './types'
import './jane-escalation.css'

const pctScore = (value?: number | null) => value == null ? '—' : `${Math.round(Math.max(0, Math.min(1, value)) * 100)}`

const JANE_PROCESSING_STEPS = [
  'Reconstructing transaction-time evidence',
  'Checking velocity, reuse, and coordination clues',
  'Running the frozen Mentalist model',
  'Preparing Jane’s analyst readout',
]

const JANE_MIN_PROCESSING_MS = 2200

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
  const [processingStep, setProcessingStep] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    setLoading(false)
    setProcessingStep(0)
  }, [record.transaction_id])

  const analyst = record.analyst_jane ?? null
  const automatic = !!record.mentalist?.invoked
  const originalScore = automatic ? record.mentalist?.score : null
  const visibleScore = analyst?.score ?? originalScore
  const visibleClues = analyst?.clue_families ?? record.mentalist?.clue_families ?? {}
  const visibleClueCount = analyst?.clue_count ?? record.mentalist?.clue_count ?? 0
  const threshold = analyst?.score_threshold ?? record.mentalist?.score_threshold ?? null
  const corroborates = analyst?.corroborates_intervention ?? false
  const adjudication = record.adjudication
  const outcome = adjudication?.outcome ?? null
  const memoryState = adjudication?.state ?? 'unadjudicated'
  const remainingHours = adjudication?.seconds_remaining == null
    ? null
    : Math.max(0, Math.ceil(adjudication.seconds_remaining / 3600))

  const janeLifecycle = analyst
    ? 'Analyst second opinion'
    : automatic
      ? 'Automatic investigation'
      : 'Available on demand'
  const analystLifecycle = outcome ? `Confirmed ${outcome}` : 'Awaiting resolution'
  const memoryLifecycle = memoryState === 'matured'
    ? 'Trusted memory active'
    : memoryState === 'pending'
      ? `${remainingHours ?? 0}h until trusted`
      : 'Waiting for outcome'

  const runJane = async () => {
    setLoading(true)
    setProcessingStep(0)
    setError('')

    const startedAt = Date.now()
    const timers = [500, 1050, 1650].map((delay, index) => window.setTimeout(() => {
      setProcessingStep(index + 1)
    }, delay))

    try {
      const updated = await api.deepInvestigate(record.transaction_id)
      const remainingDelay = Math.max(0, JANE_MIN_PROCESSING_MS - (Date.now() - startedAt))
      if (remainingDelay > 0) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, remainingDelay))
      }
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Jane investigation failed.')
    } finally {
      timers.forEach(window.clearTimeout)
      setLoading(false)
      setProcessingStep(0)
    }
  }

  return <section className={`card jane-escalation ${analyst ? 'completed' : ''}`}>
    <div className="jane-escalation-head">
      <div className="jane-escalation-title">
        <span className="jane-escalation-orb"><BrainCircuit size={25} /></span>
        <div>
          <span className="eyebrow">Analyst escalation</span>
          <h2>{loading ? 'Jane is investigating this payment' : analyst ? 'Jane has a second opinion' : automatic ? 'Jane already investigated this case' : 'Not satisfied with the first decision?'}</h2>
          <p>{loading
            ? 'The original transaction-time evidence is being reconstructed before the frozen Mentalist model produces its advisory readout.'
            : automatic
              ? 'The selective runtime already invoked Jane because the cheap evidence gate found enough independent clues.'
              : 'A human investigator can explicitly spend deeper reasoning on this case without changing the frozen v0.5 decision automatically.'}</p>
        </div>
      </div>
      <span className={`jane-escalation-state ${loading ? 'processing' : analyst ? (corroborates ? 'corroborates' : 'advisory') : automatic ? 'automatic' : ''}`}>
        {loading ? <><RefreshCw className="spin" size={16} />PROCESSING</> : analyst ? (corroborates ? <><Check size={16} />CORROBORATES</> : <><SearchCheck size={16} />SECOND OPINION</>) : automatic ? <><Sparkles size={16} />AUTO-INVOKED</> : <><SearchCheck size={16} />AVAILABLE</>}
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
        <span>{loading
          ? 'Jane is reconstructing the original evidence snapshot and running the advisory investigation.'
          : 'Ask Jane to reconstruct the transaction-time evidence and run the frozen Mentalist model as an analyst-requested advisory readout.'}</span>
      </div>
      <button disabled={preview || loading} onClick={() => void runJane()}>
        {loading ? <><RefreshCw className="spin" size={18} />Investigating…</> : <><BrainCircuit size={18} />Ask Jane</>}
      </button>
    </div>}

    {loading && !automatic && !analyst && <div className="jane-processing" role="status" aria-live="polite">
      <div className="jane-processing-visual" aria-hidden="true">
        <span className="jane-processing-core"><BrainCircuit size={27} /></span>
        <span className="jane-processing-ring ring-one" />
        <span className="jane-processing-ring ring-two" />
      </div>
      <div className="jane-processing-copy">
        <span className="eyebrow">Jane · live investigation</span>
        <b>{JANE_PROCESSING_STEPS[processingStep]}</b>
        <small>Analyzing the frozen transaction snapshot<span className="jane-thinking-dots"><i /><i /><i /></span></small>
        <div className="jane-processing-track" aria-hidden="true">
          {JANE_PROCESSING_STEPS.map((step, index) => <span
            className={index < processingStep ? 'complete' : index === processingStep ? 'active' : ''}
            key={step}
          />)}
        </div>
      </div>
    </div>}

    {analyst && <div className="jane-advisory-note">
      <AlertTriangle size={17} />
      <span><b>Advisory, not an override.</b> This analyst-requested pass uses the original transaction-time, label-free evidence snapshot. It does not consume fraud labels, intervention tokens, or silently change the frozen action.</span>
    </div>}

    {error && <div className="jane-escalation-error"><AlertTriangle size={17} />{error}</div>}

    <div className="risk-ops-loop">
      <div className="risk-ops-loop-head">
        <div><span className="eyebrow">Adaptive merchant memory</span><b>One case becomes context for the next.</b></div>
        <small>Resolved outcomes mature after the causal delay before they can influence future related payments.</small>
      </div>
      <div className="risk-ops-loop-steps">
        <div className="risk-loop-step complete"><span>1</span><b>PAYMENT</b><small>Received & scored</small></div>
        <ArrowRight size={17} />
        <div className="risk-loop-step complete"><span>2</span><b>DECISION</b><small>{record.decision.action}</small></div>
        <ArrowRight size={17} />
        <div className={`risk-loop-step ${automatic || analyst || loading ? 'complete' : ''}`}><span>3</span><b>JANE</b><small>{loading ? 'Investigation in progress' : janeLifecycle}</small></div>
        <ArrowRight size={17} />
        <div className={`risk-loop-step ${outcome ? 'complete' : ''}`}><span>4</span><b>RESOLVE</b><small>{analystLifecycle}</small></div>
        <ArrowRight size={17} />
        <div className={`risk-loop-step ${memoryState === 'matured' ? 'complete memory' : ''}`}><span>{memoryState === 'matured' ? <Database size={15} /> : <Clock3 size={15} />}</span><b>MEMORY</b><small>{memoryLifecycle}</small></div>
      </div>
    </div>
  </section>
}