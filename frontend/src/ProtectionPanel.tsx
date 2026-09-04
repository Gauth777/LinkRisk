import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, Check, CircleDollarSign, RefreshCw, ShieldCheck, Zap } from 'lucide-react'
import type { CaseRecord } from './types'
import './protection.css'

type ProtectionRecord = {
  action: string
  provider: string
  test_mode: boolean
  transaction_id: string
  payment_id: string
  refund_id: string
  refund_status: string
  speed_requested: string
  speed_processed?: string | null
  amount_subunits: number
  amount: number
  currency: string
  created_at: number
  response_reason: string
}

type ProtectionStatus = {
  eligible: boolean
  has_response: boolean
  reason?: string
  amount?: number
  protection?: ProtectionRecord | null
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const payload = await response.json()
      message = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
    } catch {
      // keep the HTTP status text
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

const money = (value: number) => new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
}).format(value)

export function ProtectionPanel({ record, preview }: { record: CaseRecord; preview: boolean }) {
  const [status, setStatus] = useState<ProtectionStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadStatus = async () => {
    if (preview || record.decision.action !== 'REVIEW') return
    setLoading(true)
    setError('')
    try {
      const result = await postJson<ProtectionStatus>(`/api/transactions/${encodeURIComponent(record.transaction_id)}/protection/status`)
      setStatus(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load protection status.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setStatus(null)
    setError('')
    void loadStatus()
    // transaction id is the state boundary for one protection case
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.transaction_id, preview])

  if (record.decision.action !== 'REVIEW') return null

  const protection = status?.protection ?? null
  const processed = protection?.refund_status === 'processed'
  const initiated = protection && ['pending', 'processed'].includes(protection.refund_status)

  const protect = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await postJson<{ ok: boolean; duplicate: boolean; protection: ProtectionRecord }>(
        `/api/transactions/${encodeURIComponent(record.transaction_id)}/protect/refund`,
      )
      setStatus({ eligible: true, has_response: true, protection: result.protection })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Merchant protection action failed.')
    } finally {
      setLoading(false)
    }
  }

  return <section className={`card protection-panel ${processed ? 'protected' : ''}`}>
    <div className="protection-header">
      <div>
        <span className="eyebrow">Merchant protection</span>
        <h2>{processed ? 'Payment protected' : initiated ? 'Response initiated' : 'Close the risk loop'}</h2>
        <p>Detection is not the end state. A final REVIEW can trigger a real Razorpay Test Mode response.</p>
      </div>
      <span className={`protection-state ${processed ? 'done' : initiated ? 'pending' : ''}`}>
        {processed ? <><ShieldCheck size={17} />PROTECTED</> : initiated ? <><RefreshCw size={17} />{protection?.refund_status.toUpperCase()}</> : <><Zap size={17} />ACTION READY</>}
      </span>
    </div>

    <div className="response-journey">
      <div><span>1</span><b>DETECT</b><small>v0.5 risk {Math.round(record.decision.linkrisk_risk * 100)}/100</small></div>
      <ArrowRight size={19} />
      <div><span>2</span><b>DECIDE</b><small>Mandatory REVIEW</small></div>
      <ArrowRight size={19} />
      <div className={initiated ? 'active' : ''}><span>3</span><b>RESPOND</b><small>{initiated ? 'Razorpay refund' : 'Awaiting analyst action'}</small></div>
    </div>

    <div className="protection-body">
      <div className="protection-amount">
        <CircleDollarSign size={26} />
        <div><span>{processed ? 'Protected amount' : 'Amount at risk'}</span><strong>{money(protection?.amount ?? record.input.amount)}</strong></div>
      </div>

      {protection ? <div className="refund-details">
        <div><span>Response</span><b>Full Test refund</b></div>
        <div><span>Razorpay status</span><b>{protection.refund_status.toUpperCase()}</b></div>
        <div><span>Refund ID</span><b>{protection.refund_id}</b></div>
        <div><span>Payment ID</span><b>{protection.payment_id}</b></div>
      </div> : <div className="response-recommendation">
        <AlertTriangle size={22} />
        <div><b>Recommended response</b><span>Refund this Test payment and stop fulfilment while the case is reviewed.</span></div>
      </div>}

      {error && <div className="protection-error"><AlertTriangle size={17} />{error}</div>}

      {!protection && <button
        className="protect-button"
        disabled={preview || loading || status?.eligible === false}
        onClick={() => void protect()}
      >
        {loading ? <><RefreshCw className="spin" size={18} />Contacting Razorpay…</> : <><ShieldCheck size={18} />Refund Test Payment</>}
      </button>}

      {!protection && status?.eligible === false && <small className="protection-note">{status.reason}</small>}
      {!protection && !error && status == null && !preview && <small className="protection-note">Checking Razorpay response eligibility…</small>}
      {protection && <small className="protection-note">Test Mode only · this is a merchant response action, not a claim that the payment is confirmed fraud.</small>}
    </div>
  </section>
}
