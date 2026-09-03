import { useEffect, useState } from 'react'

type Health = {
  ok: boolean
  engine_loaded: boolean
  asset_status?: { ready?: boolean }
  last_error?: string | null
}

export default function LiveRuntimeStatus() {
  const [health, setHealth] = useState<Health | null>(null)
  const [reachable, setReachable] = useState(true)

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const response = await fetch('/api/health', { cache: 'no-store' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json() as Health
        if (!active) return
        setReachable(true)
        setHealth(payload)
      } catch {
        if (!active) return
        setReachable(false)
        setHealth(null)
      }
    }

    void refresh()
    const timer = window.setInterval(refresh, 5000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const assetsReady = !!health?.asset_status?.ready
  const engineReady = !!health?.engine_loaded
  const ready = reachable && !!health?.ok && assetsReady && engineReady

  let title = 'Checking engine'
  let detail = 'live session'
  let tone = 'warming'

  if (!reachable) {
    title = 'Engine unreachable'
    detail = 'deployment check'
    tone = 'error'
  } else if (health && !assetsReady) {
    title = 'Engine unavailable'
    detail = 'model assets missing'
    tone = 'error'
  } else if (health && assetsReady && !engineReady) {
    title = 'Runtime warming'
    detail = 'loading frozen models'
    tone = 'warming'
  } else if (ready) {
    title = 'Engine ready'
    detail = 'live session'
    tone = 'ready'
  }

  return <div className={`live-runtime-status ${tone}`} title={health?.last_error ?? undefined}>
    <span className="live-runtime-dot" />
    <b>{title}</b>
    <span>{detail}</span>
  </div>
}
