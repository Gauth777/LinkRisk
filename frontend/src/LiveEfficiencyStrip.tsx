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
        // Supplemental telemetry must never block the primary product surface.
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
  const deepCheckLabel = liveSeen > 0 ? `${invoked}/${liveSeen}` : pct(developmentInvocation)

  return <aside className="live-efficiency-strip" aria-label="Selective reasoning telemetry">
    <div className="efficiency-heading">
      <span className="efficiency-dot" />
      <div>
        <b>Selective reasoning</b>
        <small>{liveSeen > 0 ? 'live runtime' : 'development profile'}</small>
      </div>
    </div>

    <div className="efficiency-metrics">
      <div><strong>{pct(liveBypassShare)}</strong><span>reasoning bypass</span></div>
      <div><strong>{deepCheckLabel}</strong><span>{liveSeen > 0 ? 'deep checks' : 'invocation rate'}</span></div>
      <div><strong>{pct(sustainedBudget)}</strong><span>sustained budget</span></div>
      <div><strong>{tokens.toFixed(1)}/{burst.toFixed(0)}</strong><span>live capacity</span></div>
    </div>

    {(!!capacity?.capacity_denials || !!capacity?.mandatory_review_overflow) && <div className="efficiency-alerts">
      {!!capacity?.capacity_denials && <span>{capacity.capacity_denials} deferred</span>}
      {!!capacity?.mandatory_review_overflow && <span>{capacity.mandatory_review_overflow} safety overflow</span>}
    </div>}
  </aside>
}
