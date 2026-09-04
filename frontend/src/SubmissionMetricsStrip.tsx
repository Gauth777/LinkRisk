import { ShieldCheck } from 'lucide-react'
import './submission-metrics.css'

const HELDOUT = {
  rows: 88_581,
  frauds: 3_083,
  precision: 49.10,
  recall: 23.09,
  fpr: 0.8632,
  prAuc: 0.3132,
}

export default function SubmissionMetricsStrip() {
  return <aside className="submission-metrics" aria-label="Frozen held-out detector metrics">
    <div className="submission-metrics-head">
      <span className="submission-shield"><ShieldCheck size={18} /></span>
      <div>
        <b>Measured detector · hard REVIEW</b>
        <small>Frozen chronological held-out test · {HELDOUT.rows.toLocaleString('en-IN')} transactions · {HELDOUT.frauds.toLocaleString('en-IN')} frauds</small>
      </div>
    </div>

    <div className="submission-metric-values">
      <div><strong>{HELDOUT.precision.toFixed(2)}%</strong><span>precision</span></div>
      <div><strong>{HELDOUT.recall.toFixed(2)}%</strong><span>recall</span></div>
      <div><strong>{HELDOUT.fpr.toFixed(4)}%</strong><span>false-positive rate</span></div>
      <div><strong>{HELDOUT.prAuc.toFixed(4)}</strong><span>PR-AUC</span></div>
    </div>

    <div className="submission-action-contract">
      <span><b>REVIEW</b> detector-positive hard risk boundary</span>
      <span><b>VERIFY</b> defensive verification queue — not a fraud verdict</span>
      <span><b>Scores</b> ranking signals — not calibrated fraud probabilities</span>
    </div>
  </aside>
}
