import { useState } from 'react'
import App from './App'
import DemoScenarios from './DemoScenarios'
import './demoScenarios.css'

type ProductMode = 'live' | 'demo'

export default function ProductRoot() {
  const [mode, setMode] = useState<ProductMode>('live')

  return <>
    <div className="product-mode-switch" role="group" aria-label="Product mode">
      <button aria-pressed={mode === 'live'} className={mode === 'live' ? 'active' : ''} onClick={() => setMode('live')}>Live Session</button>
      <button aria-pressed={mode === 'demo'} className={mode === 'demo' ? 'active' : ''} onClick={() => setMode('demo')}>Demo Scenarios</button>
    </div>
    {mode === 'live' ? <App /> : <DemoScenarios onGoLive={() => setMode('live')} />}
  </>
}
