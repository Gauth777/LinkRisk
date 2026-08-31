import { useEffect, useState } from 'react'

type Capacity = {
  transactions_seen: number
  total_rate: number
  total_tokens: number
  total_burst: number
  mentalist_invoked: number
  mentalist_bypassed: number
  mentalist_invocation_share: number
  capacity_denials: number
  mandatory_review_overflow: number
}

type Overview = {
  validation?: {
    mentalist_invocation_share?: number
    mentalist_bypass_share?: number
  }
  live?: {
    capacity?: Capacity | null
  }
}

const pct = (value: number) => `${(value * 100).toFixed(1)}%`

export default function LiveEfficiencyStrip() {
  const [capacity, setCapacity] = useState<Capacity | null>(null)
  const [developmentInvocation, setDevelopmentInvocation] = useState(0.0227)

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const response = await fetch('/api/overview')
        if (!response.ok) return
        const payload = await response.json() as Overview
        if (!active) return
        setCapacity(payload.live?.capacity ?? null)
        if (typeof payload.validation?.mentalist_invocation_share === 'number') {
          setDevelopmentInvocation(payload.validation.mentalist_invocation_share)
        }
      } catch {
        // The main dashboard already handles preview/offline state. This strip is
        // supplemental and should never block the product if the API is absent.
      }
    }

    void refresh()
    const timer = window.setInterval(refresh, 3000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const liveSeen = capacity?.transactions_seen ?? 0
  const invoked = capacity?.mentalist_invoked ?? 0
  const bypassed = capacity?.mentalist_bypassed ?? 0
  const liveBypassShare = liveSeen > 0 ? bypassed / liveSeen : 1 - developmentInvocation
  const sustainedBudget = capacity?.total_rate ?? 0.06
  const tokens = capacity?.total_tokens ?? 6
  const burst = capacity?.total_burst ?? 6

  return <div style={{
    position: 'fixed',
    zIndex: 35,
    left: '50%',
    top: 72,
    transform: 'translateX(-50%)',
    display: 'flex',
    alignItems: 'center',
    gap: 18,
    maxWidth: 'calc(100vw - 360px)',
    padding: '8px 14px',
    border: '1px solid rgba(100, 190, 255, .22)',
    borderRadius: 10,
    background: 'rgba(7, 20, 34, .94)',
    boxShadow: '0 10px 30px rgba(0,0,0,.22)',
    color: '#d7e6f4',
    fontSize: 12,
    backdropFilter: 'blur(12px)',
    pointerEvents: 'none',
  }}>
    <b style={{ color: '#75d7ff', letterSpacing: '.04em' }}>V2 SELECTIVE</b>
    <span><strong>{liveSeen ? invoked : '2.27%'}</strong> {liveSeen ? `of ${liveSeen}` : 'development'} Mentalist {liveSeen ? 'invocations' : 'invocation rate'}</span>
    <span><strong>{pct(liveBypassShare)}</strong> reasoning bypass</span>
    <span><strong>{pct(sustainedBudget)}</strong> sustained intervention budget</span>
    <span><strong>{tokens.toFixed(1)}/{burst.toFixed(0)}</strong> live capacity tokens</span>
    {!!capacity?.capacity_denials && <span><strong>{capacity.capacity_denials}</strong> deferred</span>}
    {!!capacity?.mandatory_review_overflow && <span><strong>{capacity.mandatory_review_overflow}</strong> safety overflow</span>}
  </div>
}
