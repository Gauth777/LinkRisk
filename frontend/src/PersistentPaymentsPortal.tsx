import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight, ChevronRight } from 'lucide-react'
import { PersistentPaymentsPanel } from './PersistentPaymentsPanel'

type PersistedCase = {
  transaction_id: string
  amount: number
  contact_masked: string | null
  email_domain: string | null
  device_info: string | null
  baseline_risk: number | null
  linkrisk_risk: number | null
  jane_score: number | null
  jane_clue_count: number | null
  v5_action: 'ALLOW' | 'VERIFY' | 'REVIEW' | null
  final_action: 'ALLOW' | 'VERIFY' | 'REVIEW' | null
  routing_reason: string | null
  transaction_time: number
  source: string | null
}

type LedgerResponse = {
  items: PersistedCase[]
  persistent: boolean
  healthy: boolean
}

const formatAmount = (value: number) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
const riskScore = (value: number | null) => value == null ? '—' : Math.round(Math.max(0, Math.min(1, value)) * 100)

function PersistentDemoCases() {
  const [items, setItems] = useState<PersistedCase[]>([])

  useEffect(() => {
    let disposed = false
    let inFlight = false

    const load = async () => {
      if (disposed || inFlight) return
      inFlight = true
      try {
        const response = await fetch('/api/merchant-memory/transactions?limit=50', { cache: 'no-store' })
        if (!response.ok) return
        const payload = await response.json() as LedgerResponse
        if (disposed || !payload.healthy) return
        const cases = payload.items
          .filter((item) => item.source === 'synthetic_demo' && (item.final_action === 'VERIFY' || item.final_action === 'REVIEW'))
          .sort((a, b) => b.transaction_time - a.transaction_time)
        setItems(cases)
      } catch {
        // The live-engine case list remains usable if persistent memory is waking.
      } finally {
        inFlight = false
      }
    }

    void load()
    const timer = window.setInterval(() => void load(), 6000)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [])

  return <>
    {items.map((item) => {
      const v5Action = item.v5_action || 'ALLOW'
      const finalAction = item.final_action || 'ALLOW'
      return <div
        className="case-list-row card"
        key={`persistent-${item.transaction_id}`}
        title="Persistent dashboard case; excluded from the causal runtime."
      >
        <div>
          <span className="eyebrow">{item.transaction_id}</span>
          <b>{item.contact_masked || item.email_domain || 'Persistent test profile'}</b>
          <small>{item.device_info || 'Merchant-side context'}</small>
        </div>
        <div><span>Amount</span><b>{formatAmount(Number(item.amount || 0))}</b></div>
        <div>
          <span>v0.5 → final</span>
          <p>
            <span className={`action-badge action-${v5Action.toLowerCase()}`}>{v5Action}</span>
            <ArrowRight size={16} />
            <span className={`action-badge action-${finalAction.toLowerCase()}`}>{finalAction}</span>
          </p>
        </div>
        <div>
          <span>Jane</span>
          <b>{riskScore(item.jane_score)}/100</b>
          <small>{item.jane_clue_count || 0} clues</small>
        </div>
        <ChevronRight size={21} />
      </div>
    })}
  </>
}

export function PersistentPaymentsPortal() {
  const [overviewTarget, setOverviewTarget] = useState<HTMLElement | null>(null)
  const [casesTarget, setCasesTarget] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const findTargets = () => {
      const overviewGrid = document.querySelector('.overview-main-grid')
      const overviewMain = overviewGrid?.closest('main.content') as HTMLElement | null
      const caseList = document.querySelector('.case-list') as HTMLElement | null

      setOverviewTarget((current) => current === overviewMain ? current : overviewMain)
      setCasesTarget((current) => current === caseList ? current : caseList)
    }

    findTargets()
    const observer = new MutationObserver(findTargets)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  return <>
    {overviewTarget && createPortal(<PersistentPaymentsPanel />, overviewTarget)}
    {casesTarget && createPortal(<PersistentDemoCases />, casesTarget)}
  </>
}
