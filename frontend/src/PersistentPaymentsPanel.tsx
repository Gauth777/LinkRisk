import { useEffect, useMemo, useState } from 'react'
import { Cloud, Database, RefreshCw, ShieldCheck } from 'lucide-react'
import './persistent-payments.css'

type PersistentPayment = {
  transaction_id: string
  razorpay_payment_id: string | null
  amount: number
  currency: string | null
  payment_method: string | null
  payment_status: string | null
  contact_masked: string | null
  email_domain: string | null
  device_info: string | null
  device_type: string | null
  baseline_risk: number | null
  linkrisk_risk: number | null
  graph_confidence: number | null
  jane_score: number | null
  jane_clue_count: number | null
  v5_action: string | null
  final_action: string | null
  routing_reason: string | null
  trusted_history_channels: number
  trusted_fraud_channels: number
  transaction_time: number
  source: string | null
  created_at: string | null
}

type LedgerResponse = {
  items: PersistentPayment[]
  persistent: boolean
  healthy: boolean
  reason?: string
  poll_after_ms?: number
}

const POLL_MS = 6000

const riskScore = (value: number | null) => value == null ? '—' : Math.round(Math.max(0, Math.min(1, value)) * 100)

const formatAmount = (value: number, currency: string | null) => {
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currency || 'INR',
      maximumFractionDigits: 2,
    }).format(value)
  } catch {
    return `${currency || 'INR'} ${value.toFixed(2)}`
  }
}

const formatTime = (row: PersistentPayment) => {
  const date = row.created_at ? new Date(row.created_at) : new Date(row.transaction_time * 1000)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function PersistentPaymentsPanel() {
  const [items, setItems] = useState<PersistentPayment[]>([])
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [persistent, setPersistent] = useState(true)
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null)
  const [manualRefresh, setManualRefresh] = useState(0)

  useEffect(() => {
    let disposed = false
    let inFlight = false
    let timer: number | undefined

    const load = async () => {
      if (disposed || inFlight) return
      inFlight = true
      try {
        const response = await fetch('/api/merchant-memory/transactions?limit=12', { cache: 'no-store' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json() as LedgerResponse
        if (disposed) return
        setPersistent(payload.persistent)
        setHealthy(payload.healthy)
        if (payload.healthy) {
          setItems(payload.items)
          setLastSyncedAt(new Date())
        }
      } catch {
        if (!disposed) setHealthy(false)
      } finally {
        inFlight = false
      }
    }

    void load()
    timer = window.setInterval(() => void load(), POLL_MS)
    const onFocus = () => void load()
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void load()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      disposed = true
      if (timer) window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [manualRefresh])

  const status = useMemo(() => {
    if (!persistent) return { className: 'offline', label: 'NOT CONFIGURED' }
    if (healthy === false) return { className: 'waking', label: items.length ? 'RECONNECTING' : 'WAKING / RETRYING' }
    if (healthy === true) return { className: 'online', label: 'LIVE SYNC' }
    return { className: 'waking', label: 'CONNECTING' }
  }, [healthy, items.length, persistent])

  return <section className="card persistent-ledger-card">
    <div className="persistent-ledger-head">
      <div className="persistent-ledger-title">
        <span className="persistent-ledger-icon"><Database size={21} /></span>
        <div>
          <span className="eyebrow">Persistent merchant memory</span>
          <h2>Payment intelligence ledger</h2>
          <p>Supabase-backed payment records · survives app sleep and backend restarts</p>
        </div>
      </div>
      <div className="persistent-ledger-actions">
        <span className={`persistent-sync ${status.className}`}><i />{status.label}</span>
        <button className="icon-button" aria-label="Refresh persistent payment ledger" onClick={() => setManualRefresh((value) => value + 1)}>
          <RefreshCw size={17} />
        </button>
      </div>
    </div>

    <div className="persistent-ledger-meta">
      <span><Cloud size={15} />Auto-sync every 6s</span>
      <span><ShieldCheck size={15} />Masked customer context only</span>
      <small>{lastSyncedAt ? `Last synced ${lastSyncedAt.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : 'Waiting for first database sync'}</small>
    </div>

    <div className="persistent-ledger-table">
      <table>
        <thead>
          <tr><th>Payment</th><th>Customer context</th><th>Amount</th><th>Method</th><th>Risk path</th><th>Jane</th><th>Action</th></tr>
        </thead>
        <tbody>
          {items.map((row) => <tr key={row.transaction_id}>
            <td>
              <b>{row.razorpay_payment_id || row.transaction_id}</b>
              <small>{formatTime(row)}</small>
            </td>
            <td>
              <b>{row.contact_masked || 'Pseudonymous'}</b>
              <small>{row.email_domain || row.device_info || 'No raw PII stored'}</small>
            </td>
            <td><b>{formatAmount(Number(row.amount || 0), row.currency)}</b><small>{row.payment_status || 'verified'}</small></td>
            <td><b className="persistent-method">{row.payment_method || '—'}</b><small>{row.device_type || 'unknown device'}</small></td>
            <td>
              <div className="persistent-risk-path"><span>{riskScore(row.baseline_risk)}</span><i>→</i><strong>{riskScore(row.linkrisk_risk)}</strong></div>
              <small>{row.trusted_history_channels || 0} trusted history channels</small>
            </td>
            <td><b className="persistent-jane-score">{riskScore(row.jane_score)}</b><small>{row.jane_clue_count || 0} clues</small></td>
            <td><span className={`persistent-action ${(row.final_action || 'allow').toLowerCase()}`}>{row.final_action || 'ALLOW'}</span><small>{row.trusted_fraud_channels || 0} matured fraud channels</small></td>
          </tr>)}
        </tbody>
      </table>
      {items.length === 0 && <div className="persistent-ledger-empty">
        <Database size={27} />
        <div><b>{healthy === false ? 'Waiting for persistent memory' : 'No persisted payments yet'}</b><span>{healthy === false ? 'The dashboard will retry automatically while the service wakes.' : 'Complete a Razorpay Test payment and it will appear here automatically.'}</span></div>
      </div>}
    </div>
  </section>
}
