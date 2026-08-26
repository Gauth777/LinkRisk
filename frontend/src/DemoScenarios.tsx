import { useMemo, useState } from 'react'
import { ArrowRight, BrainCircuit, CheckCircle2, Eye, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react'
import { previewFeed } from './demoData'
import type { Action, FeedItem } from './types'
import './demoScenarios.css'

const score = (value?: number | null) => value == null ? '—' : Math.round(Math.max(0, Math.min(1, value)) * 100).toString()
const amount = (value: number) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
const titleCase = (value: string) => value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const scenarioCopy: Record<string, { title: string; summary: string; reason: string; clues: string[] }> = {
  'TX-8F2D7K1E': {
    title: 'Mentalist proactive escalation',
    summary: 'The transaction model would allow it, but multiple present-tense evidence families form a stronger case.',
    reason: 'Jane clears the frozen proactive threshold with at least two independent clue families, so ALLOW becomes VERIFY.',
    clues: ['Velocity', 'Behavior change', 'Coordination'],
  },
  'TX-7H9J3L0B': {
    title: 'Clean low-risk payment',
    summary: 'Low transaction risk, no corroborating behavioral evidence and no reason to consume intervention capacity.',
    reason: 'Both the v0.5 path and Mentalist remain below their escalation gates, so the payment stays ALLOW.',
    clues: [],
  },
  'TX-1K3M9P2Q': {
    title: 'v0.5 verification case',
    summary: 'The frozen v0.5 policy already considers this payment worthy of verification without Mentalist promotion.',
    reason: 'The v0.5 risk path reaches VERIFY. Mentalist does not need to override or promote the case.',
    clues: ['Single weak clue'],
  },
  'TX-6G7H2N4R': {
    title: 'Hard review boundary',
    summary: 'A high-risk transaction crosses the frozen review boundary and is escalated to manual review.',
    reason: 'v0.5 REVIEW is immutable. Mentalist can explain additional evidence but cannot downgrade or create REVIEW.',
    clues: ['High transaction risk', 'Corroborating context'],
  },
  'TX-9P8Q1S7T': {
    title: 'Routine payment',
    summary: 'A second benign example showing that ordinary activity is deliberately left untouched.',
    reason: 'Low v0.5 and Jane scores with zero clue families keep the payment ALLOW.',
    clues: [],
  },
}

function ActionBadge({ action }: { action: Action }) {
  return <span className={`demo-action demo-${action.toLowerCase()}`}>{action}</span>
}

function ScenarioIcon({ action }: { action: Action }) {
  if (action === 'REVIEW') return <ShieldAlert size={24} />
  if (action === 'VERIFY') return <Eye size={24} />
  return <CheckCircle2 size={24} />
}

export default function DemoScenarios({ onGoLive }: { onGoLive: () => void }) {
  const [selectedId, setSelectedId] = useState(previewFeed[0].transaction_id)
  const selected = useMemo(() => previewFeed.find((item) => item.transaction_id === selectedId) ?? previewFeed[0], [selectedId])
  const copy = scenarioCopy[selected.transaction_id]

  return <div className="demo-page">
    <header className="demo-header">
      <div className="demo-brand"><span className="demo-brand-mark">L</span><div><b>LinkRisk</b><small>Demo Scenarios</small></div></div>
      <div className="demo-disclaimer"><Sparkles size={16} />Illustrative scenarios — not live transactions</div>
      <button className="demo-live-button" onClick={onGoLive}>Go to live session <ArrowRight size={17} /></button>
    </header>

    <main className="demo-content">
      <section className="demo-hero">
        <span>Presentation workspace</span>
        <h1>Explain ALLOW, VERIFY and REVIEW without mixing demo data into the live feed.</h1>
        <p>These curated cases exist only to demonstrate the frozen LinkRisk routing logic. New payments and Razorpay Checkout are available exclusively in Live Session.</p>
      </section>

      <section className="demo-layout">
        <div className="demo-list">
          {previewFeed.map((item) => {
            const active = item.transaction_id === selected.transaction_id
            return <button key={item.transaction_id} className={`demo-scenario-card ${active ? 'active' : ''}`} onClick={() => setSelectedId(item.transaction_id)}>
              <span className={`demo-icon demo-icon-${item.action.toLowerCase()}`}><ScenarioIcon action={item.action} /></span>
              <div className="demo-scenario-copy">
                <small>{item.transaction_id}</small>
                <b>{scenarioCopy[item.transaction_id]?.title ?? titleCase(item.routing_reason)}</b>
                <span>{item.profile} · {amount(item.amount)}</span>
              </div>
              <ActionBadge action={item.action} />
            </button>
          })}
        </div>

        <article className="demo-detail">
          <div className="demo-detail-head">
            <div><small>Selected illustrative case</small><h2>{copy.title}</h2><p>{copy.summary}</p></div>
            <ActionBadge action={selected.action} />
          </div>

          <div className="demo-score-grid">
            <div><span>v0.5 risk</span><strong>{score(selected.v5_risk)}</strong><small>raw ranking score</small></div>
            <div><span>Jane score</span><strong>{score(selected.jane_score)}</strong><small>proactive evidence score</small></div>
            <div><span>Independent clues</span><strong>{selected.clue_count}</strong><small>evidence families</small></div>
          </div>

          <div className="demo-decision-flow">
            <div><span>v0.5 action</span><ActionBadge action={selected.v5_action} /></div>
            <ArrowRight size={22} />
            <div className="demo-jane-step"><BrainCircuit size={20} /><span>Mentalist</span><b>{score(selected.jane_score)}</b></div>
            <ArrowRight size={22} />
            <div><span>Final action</span><ActionBadge action={selected.action} /></div>
          </div>

          <div className="demo-reason">
            <ShieldCheck size={22} />
            <div><b>{titleCase(selected.routing_reason)}</b><p>{copy.reason}</p></div>
          </div>

          <div className="demo-clues">
            <span>Illustrative evidence</span>
            <div>{copy.clues.length ? copy.clues.map((clue) => <em key={clue}>{clue}</em>) : <em className="muted">No active clue families</em>}</div>
          </div>

          <footer className="demo-note">
            Scores are risk/ranking scores, not calibrated fraud probabilities. Demo values are illustrative and clearly separated from live model output.
          </footer>
        </article>
      </section>
    </main>
  </div>
}
