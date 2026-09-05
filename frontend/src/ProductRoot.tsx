import { useEffect, useState } from 'react'
import App from './App'
import DemoScenarios from './DemoScenarios'
import EntryExperience from './EntryExperience'
import LiveEfficiencyStrip from './LiveEfficiencyStrip'
import LiveRuntimeStatus from './LiveRuntimeStatus'
import { PersistentPaymentsPortal } from './PersistentPaymentsPortal'
import './demoScenarios.css'
import './identity-overrides.css'
import './v2Overrides.css'

type ProductMode = 'live' | 'demo'
type LinkRiskHistoryState = {
  surface: 'entry' | 'console'
  mode: ProductMode
}

const readLinkRiskHistory = (): LinkRiskHistoryState | null => {
  if (typeof window === 'undefined') return null
  const state = window.history.state
  const value = state && typeof state === 'object' ? state.linkrisk : null
  if (!value || typeof value !== 'object') return null
  if (value.surface !== 'entry' && value.surface !== 'console') return null
  if (value.mode !== 'live' && value.mode !== 'demo') return null
  return value as LinkRiskHistoryState
}

const historyPayload = (linkrisk: LinkRiskHistoryState) => {
  const current = window.history.state
  const base = current && typeof current === 'object' ? current : {}
  return { ...base, linkrisk }
}

export default function ProductRoot() {
  const initialHistory = readLinkRiskHistory()
  const [entered, setEntered] = useState(initialHistory?.surface === 'console')
  const [mode, setMode] = useState<ProductMode>(initialHistory?.mode ?? 'live')

  useEffect(() => {
    const existing = readLinkRiskHistory()
    if (!existing) {
      window.history.replaceState(
        historyPayload({ surface: 'entry', mode: 'live' }),
        '',
        window.location.href,
      )
    }

    const restoreFromHistory = (event: PopStateEvent) => {
      const value = event.state?.linkrisk as LinkRiskHistoryState | undefined
      if (!value || (value.surface !== 'entry' && value.surface !== 'console')) return
      setMode(value.mode === 'demo' ? 'demo' : 'live')
      setEntered(value.surface === 'console')
    }

    window.addEventListener('popstate', restoreFromHistory)
    return () => window.removeEventListener('popstate', restoreFromHistory)
  }, [])

  const enterConsole = () => {
    const next: LinkRiskHistoryState = { surface: 'console', mode: 'live' }
    window.history.pushState(historyPayload(next), '', window.location.href)
    setMode('live')
    setEntered(true)
  }

  const switchMode = (nextMode: ProductMode) => {
    if (nextMode === mode) return
    const next: LinkRiskHistoryState = { surface: 'console', mode: nextMode }
    window.history.pushState(historyPayload(next), '', window.location.href)
    setMode(nextMode)
  }

  if (!entered) return <EntryExperience onEnter={enterConsole} />

  return <>
    <div className="product-mode-switch" role="group" aria-label="Product mode">
      <button aria-pressed={mode === 'live'} className={mode === 'live' ? 'active' : ''} onClick={() => switchMode('live')}>Live Session</button>
      <button aria-pressed={mode === 'demo'} className={mode === 'demo' ? 'active' : ''} onClick={() => switchMode('demo')}>Demo Scenarios</button>
    </div>
    {mode === 'live' ? <div className="live-product-root">
      <LiveRuntimeStatus />
      <LiveEfficiencyStrip />
      <App />
      <PersistentPaymentsPortal />
    </div> : <DemoScenarios onGoLive={() => switchMode('live')} />}
  </>
}
