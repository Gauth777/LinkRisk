import { BrainCircuit, ShieldCheck } from 'lucide-react'
import './submission-metrics.css'

const HELDOUT = {
  rows: 88_581,
  frauds: 3_083,
  precision: 49.10,
  recall: 23.09,
  fpr: 0.8632,
  prAuc: 0.3132,
}

const JANE = {
  v1NetFrauds: 89,
  v2FraudsAdded: 50,
  v2FalsePositivesRemoved: 48,
  intervention: 6.00,
  invocation: 2.27,
}

export default function SubmissionMetricsStrip() {
  return <aside className="submission-metrics" aria-label="LinkRisk detector and Jane verifier evidence">
    <section className="submission-lane detector-lane">
      <div className="submission-metrics-head">
        <span className="submission-shield"><ShieldCheck size={18} /></span>
        <div>
          <b>Hard REVIEW detector · held-out</b>
          <small>Frozen chronological test · {HELDOUT.rows.toLocaleString('en-IN')} transactions · {HELDOUT.frauds.toLocaleString('en-IN')} frauds</small>
        </div>
      </div>
      <div className="submission-metric-values">
        <div><strong>{HELDOUT.precision.toFixed(2)}%</strong><span>precision</span></div>
        <div><strong>{HELDOUT.recall.toFixed(2)}%</strong><span>recall</span></div>
        <div><strong>{HELDOUT.fpr.toFixed(4)}%</strong><span>false-positive rate</span></div>
        <div><strong>{HELDOUT.prAuc.toFixed(4)}</strong><span>PR-AUC</span></div>
      </div>
    </section>

    <section className="submission-lane jane-lane">
      <div className="submission-metrics-head">
        <span className="submission-shield jane"><BrainCircuit size={18} /></span>
        <div>
          <b>Jane verifier · relationship intelligence</b>
          <small>Central verification layer. v1 has held-out evidence; the redesigned selective v2 result below is development validation.</small>
        </div>
      </div>
      <div className="jane-proof-grid">
        <div><strong>+{JANE.v1NetFrauds}</strong><span>net frauds captured</span><small>v1 held-out vs stable v0.5; with extra FP cost</small></div>
        <div><strong>+{JANE.v2FraudsAdded} / −{JANE.v2FalsePositivesRemoved}</strong><span>TP / FP delta</span><small>v2 development validation</small></div>
        <div><strong>{JANE.intervention.toFixed(2)}%</strong><span>same intervention</span><small>v2 development validation</small></div>
        <div><strong>{JANE.invocation.toFixed(2)}%</strong><span>Jane invoked</span><small>selective inference on development validation</small></div>
      </div>
    </section>

    <div className="submission-action-contract">
      <span><b>REVIEW</b> measured hard detector positive</span>
      <span><b>Jane</b> core relationship-aware verifier</span>
      <span><b>VERIFY</b> extra defensive verification — not a fraud verdict</span>
      <span><b>Scores</b> ranking signals — not calibrated probabilities</span>
    </div>
  </aside>
}
