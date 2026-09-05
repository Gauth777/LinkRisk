import { useMemo, useState } from 'react'
import type { CSSProperties, MouseEvent } from 'react'
import {
  ArrowRight, BrainCircuit, Fingerprint, GitBranch, Radar, ShieldCheck,
  Sparkles, Target, Waypoints,
} from 'lucide-react'
import './entry-experience.css'

type EntryExperienceProps = {
  onEnter: () => void
}

type NodeSpec = {
  id: string
  x: number
  y: number
  size: number
  kind: 'normal' | 'signal' | 'focus'
  label?: string
  delay: number
}

const nodes: NodeSpec[] = [
  { id: 'a', x: 14, y: 21, size: 8, kind: 'normal', delay: 0.2 },
  { id: 'b', x: 23, y: 33, size: 11, kind: 'normal', delay: 0.45 },
  { id: 'c', x: 19, y: 62, size: 7, kind: 'normal', delay: 0.65 },
  { id: 'd', x: 34, y: 72, size: 9, kind: 'signal', delay: 0.8 },
  { id: 'e', x: 43, y: 43, size: 13, kind: 'focus', label: '₹575', delay: 1.0 },
  { id: 'f', x: 56, y: 27, size: 8, kind: 'normal', delay: 0.55 },
  { id: 'g', x: 61, y: 61, size: 10, kind: 'signal', delay: 0.95 },
  { id: 'h', x: 73, y: 43, size: 7, kind: 'normal', delay: 0.75 },
  { id: 'i', x: 84, y: 24, size: 9, kind: 'normal', delay: 0.35 },
  { id: 'j', x: 86, y: 68, size: 8, kind: 'signal', delay: 1.1 },
  { id: 'k', x: 71, y: 80, size: 6, kind: 'normal', delay: 0.9 },
  { id: 'l', x: 48, y: 84, size: 7, kind: 'normal', delay: 0.5 },
]

const edges: Array<[string, string, 'quiet' | 'signal']> = [
  ['a', 'b', 'quiet'], ['b', 'c', 'quiet'], ['b', 'e', 'signal'], ['c', 'd', 'quiet'],
  ['d', 'e', 'signal'], ['e', 'f', 'quiet'], ['e', 'g', 'signal'], ['f', 'h', 'quiet'],
  ['g', 'h', 'signal'], ['g', 'k', 'quiet'], ['g', 'j', 'signal'], ['h', 'i', 'quiet'],
  ['h', 'j', 'quiet'], ['d', 'l', 'quiet'], ['l', 'g', 'signal'],
]

const nodeById = Object.fromEntries(nodes.map((node) => [node.id, node])) as Record<string, NodeSpec>

function pxVars(x: number, y: number): CSSProperties {
  return { '--x': `${x}%`, '--y': `${y}%` } as CSSProperties
}

export default function EntryExperience({ onEnter }: EntryExperienceProps) {
  const [leaving, setLeaving] = useState(false)
  const [pointer, setPointer] = useState({ x: 0, y: 0 })

  const rootStyle = useMemo(() => ({
    '--mx': `${pointer.x}px`,
    '--my': `${pointer.y}px`,
  }) as CSSProperties, [pointer])

  const handlePointer = (event: MouseEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width - 0.5) * 22
    const y = ((event.clientY - rect.top) / rect.height - 0.5) * 18
    setPointer({ x, y })
  }

  const enter = () => {
    if (leaving) return
    setLeaving(true)
    window.setTimeout(onEnter, 880)
  }

  return <main
    className={`entry-experience ${leaving ? 'is-leaving' : ''}`}
    style={rootStyle}
    onMouseMove={handlePointer}
    onMouseLeave={() => setPointer({ x: 0, y: 0 })}
  >
    <div className="entry-noise" />
    <div className="entry-grid" />
    <div className="entry-aurora entry-aurora-a" />
    <div className="entry-aurora entry-aurora-b" />
    <div className="entry-scanline" />

    <header className="entry-nav">
      <div className="entry-brand">
        <span className="entry-brand-mark"><GitBranch size={22} /></span>
        <div><b>LinkRisk</b><small>AI Risk Manager · Razorpay Test Mode</small></div>
      </div>
      <div className="entry-nav-status"><i /><span>Risk intelligence online</span></div>
    </header>

    <section className="entry-stage">
      <div className="entry-copy">
        <div className="entry-kicker"><Sparkles size={15} /><span>Confidence-aware relationship intelligence</span></div>
        <h1>
          <span>Fraud can hide</span>
          <em>between transactions.</em>
        </h1>
        <p>
          A payment can look ordinary in isolation. LinkRisk scores the payment, investigates the relationships around it,
          and sends uncertain evidence to <strong>Jane</strong> — our relationship-aware verifier.
        </p>

        <div className="entry-proof-row">
          <article>
            <small>HARD REVIEW DETECTOR · HELD-OUT</small>
            <strong>49.10%</strong>
            <span>precision</span>
          </article>
          <article className="jane-proof">
            <small>JANE V1 · HELD-OUT</small>
            <strong>+89</strong>
            <span>net frauds captured</span>
          </article>
          <article>
            <small>SELECTIVE JANE V2 · DEVELOPMENT</small>
            <strong>+50 / −48</strong>
            <span>TP / FP delta</span>
          </article>
        </div>

        <div className="entry-actions">
          <button className="entry-launch" onClick={enter}>
            <span>Enter Risk Console</span><ArrowRight size={18} />
            <i className="entry-launch-glow" />
          </button>
          <div className="entry-access-note"><ShieldCheck size={15} /><span>Demo access · no credentials required</span></div>
        </div>
      </div>

      <div className="entry-visual" aria-hidden="true">
        <div className="entry-orbit orbit-one" />
        <div className="entry-orbit orbit-two" />
        <div className="entry-risk-sweep" />

        <svg className="entry-network-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
          <defs>
            <linearGradient id="quietEdge" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="rgba(90, 185, 216, .04)" />
              <stop offset=".5" stopColor="rgba(115, 220, 234, .34)" />
              <stop offset="1" stopColor="rgba(90, 185, 216, .04)" />
            </linearGradient>
            <linearGradient id="signalEdge" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="rgba(142, 113, 255, .10)" />
              <stop offset=".5" stopColor="rgba(179, 152, 255, .86)" />
              <stop offset="1" stopColor="rgba(87, 221, 229, .25)" />
            </linearGradient>
          </defs>
          {edges.map(([from, to, kind], index) => {
            const a = nodeById[from]
            const b = nodeById[to]
            return <line
              key={`${from}-${to}`}
              className={`entry-edge ${kind}`}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              style={{ '--edge-delay': `${0.45 + index * 0.07}s` } as CSSProperties}
            />
          })}
        </svg>

        {nodes.map((node) => <div
          key={node.id}
          className={`entry-node ${node.kind}`}
          style={{ ...pxVars(node.x, node.y), '--node-size': `${node.size}px`, '--node-delay': `${node.delay}s` } as CSSProperties}
        >
          <i />
          {node.label && <span>{node.label}<small>transaction risk 17</small></span>}
        </div>)}

        <div className="entry-jane-core">
          <div className="entry-jane-rings"><i /><i /><i /></div>
          <div className="entry-jane-icon"><BrainCircuit size={34} /></div>
          <div className="entry-jane-copy"><small>RELATIONSHIP INVESTIGATOR</small><b>JANE</b><span>92 evidence score · 2 clue families</span></div>
          <div className="entry-jane-beam" />
        </div>

        <div className="entry-clue clue-a"><Radar size={14} /><span>velocity</span><b>ACTIVE</b></div>
        <div className="entry-clue clue-b"><Waypoints size={14} /><span>coordination</span><b>ACTIVE</b></div>
        <div className="entry-clue clue-c"><Fingerprint size={14} /><span>reuse / churn</span><b>WATCH</b></div>

        <div className="entry-verdict-card">
          <div><Target size={18} /><span>RELATIONSHIP VERDICT</span></div>
          <strong>VERIFY</strong>
          <small>additional defensive verification warranted</small>
        </div>

        <div className="entry-forensic-label label-left"><span>01</span><b>PAYMENT</b><small>looks ordinary</small></div>
        <div className="entry-forensic-label label-right"><span>02</span><b>RELATIONSHIPS</b><small>tell the story</small></div>
      </div>
    </section>

    <footer className="entry-footer">
      <span>DETECT THE PAYMENT</span><i />
      <span>INVESTIGATE THE RELATIONSHIPS</span><i />
      <span>PROTECT THE NEXT ONE</span>
    </footer>

    <div className="entry-transition-curtain"><span><GitBranch size={28} />LinkRisk</span></div>
  </main>
}
