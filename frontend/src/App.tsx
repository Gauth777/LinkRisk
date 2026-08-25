import { FormEvent, useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, Bell, Bot, BrainCircuit,
  Check, ChevronRight, CircleDollarSign, Clock3, Database, Eye, FileText,
  Gauge, GitBranch, Home, Layers3, LayoutDashboard, Menu, Network, Plus,
  Radar, Search, Settings, ShieldCheck, ShieldAlert, Sparkles, TimerReset,
  UserRoundSearch, UsersRound, WalletCards, X, Zap,
} from 'lucide-react'
import { api } from './api'
import { previewCase, previewFeed, previewOverview } from './demoData'
import type { Action, CaseRecord, FeedItem, NetworkNode, OverviewPayload } from './types'

type Page = 'overview' | 'investigator'

const clamp01 = (v: number) => Math.max(0, Math.min(1, v || 0))
const pct = (v: number, digits = 2) => `${(v * 100).toFixed(digits)}%`
const score = (v?: number | null) => v == null ? '—' : Math.round(clamp01(v) * 100).toString()
const money = (v: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(v)

function ActionBadge({ action, compact = false }: { action: Action; compact?: boolean }) {
  return <span className={`action-badge action-${action.toLowerCase()} ${compact ? 'compact' : ''}`}>{action}</span>
}

function Sparkline({ values, tone = 'cyan' }: { values: number[]; tone?: string }) {
  const min = Math.min(...values); const max = Math.max(...values); const span = Math.max(max - min, 1)
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 100},${34 - ((v - min) / span) * 24}`).join(' ')
  return <svg className={`sparkline tone-${tone}`} viewBox="0 0 100 38" preserveAspectRatio="none"><polyline points={points} /></svg>
}

function MetricCard({ icon, label, value, delta, foot, tone = 'cyan', values }: {
  icon: React.ReactNode; label: string; value: string; delta: string; foot: string; tone?: string; values: number[]
}) {
  return <div className="card metric-card">
    <div className="metric-title"><span>{icon}</span>{label}</div>
    <div className="metric-value-row"><strong>{value}</strong><span className={`delta tone-text-${tone}`}>{delta}</span></div>
    <Sparkline values={values} tone={tone} />
    <div className="metric-foot"><span>{foot}</span><span>development validation</span></div>
  </div>
}

const nav = [
  ['Overview', Home], ['Investigations', UserRoundSearch], ['Live Feed', Activity], ['Network', Network],
  ['Cases', FileText], ['Reports', BarChart3], ['Alerts', Bell], ['Models', BrainCircuit], ['Data', Database], ['Settings', Settings],
] as const

function Sidebar({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark"><GitBranch size={21} /></div><span>LinkRisk</span></div>
    <nav>
      {nav.map(([label, Icon], index) => {
        const active = (page === 'overview' && index === 0) || (page === 'investigator' && index === 1)
        return <button key={label} className={`nav-item ${active ? 'active' : ''}`} onClick={() => {
          if (index === 0) setPage('overview')
          if (index === 1) setPage('investigator')
        }}><Icon size={17} /><span>{label}</span>{label === 'Live Feed' && <i className="live-dot" />}</button>
      })}
    </nav>
    <div className="sidebar-spacer" />
    <div className="system-status"><ShieldCheck size={18}/><div><b>System Status</b><span>Runtime policy frozen</span></div></div>
    <div className="sidebar-footer">Buildathon candidate<br/><span>Held-out test sealed</span></div>
  </aside>
}

function Topbar({ preview, engineReady, onNewPayment }: { preview: boolean; engineReady: boolean; onNewPayment: () => void }) {
  return <header className="topbar">
    <div className="topbar-title"><span className={`status-pulse ${engineReady ? 'ready' : ''}`} />{engineReady ? 'Engine ready' : 'UI preview'}</div>
    <div className="topbar-actions">
      <div className="search-box"><Search size={17}/><span>Search transactions, entities, cases...</span><kbd>⌘ K</kbd></div>
      <span className={`mode-pill ${preview ? 'preview' : 'live'}`}><Sparkles size={14}/>{preview ? 'Preview data' : 'Live session'}</span>
      <button className="primary-button" onClick={onNewPayment}><Plus size={17}/>New payment</button>
      <button className="icon-button"><Bell size={18}/><i>3</i></button>
      <div className="avatar"><Bot size={18}/></div>
    </div>
  </header>
}

function FeedTable({ feed, onOpen }: { feed: FeedItem[]; onOpen: (item: FeedItem) => void }) {
  return <div className="card feed-card">
    <div className="card-head"><div><h3>Live Risk Feed</h3><span className="live-label"><i/>stream</span></div><div className="head-actions"><button>Filters</button><button>Columns</button></div></div>
    <div className="table-wrap"><table><thead><tr><th>Transaction</th><th>Profile</th><th>Amount</th><th>v0.5</th><th>Jane</th><th>Clues</th><th>Decision</th></tr></thead><tbody>
      {feed.slice(0, 6).map((item) => <tr key={item.transaction_id} onClick={() => onOpen(item)}>
        <td><b>{item.transaction_id}</b><small>point-in-time decision</small></td>
        <td>{item.profile}<small>{item.device}</small></td><td>{money(item.amount)}</td>
        <td><span className="score-chip">{score(item.v5_risk)}</span></td><td><span className="score-chip jane">{score(item.jane_score)}</span></td>
        <td>{item.clue_count}</td><td><ActionBadge action={item.action} compact/><ChevronRight size={15}/></td>
      </tr>)}
    </tbody></table></div>
    <div className="table-foot"><span>{feed.length} transactions shown</span><button>View full feed <ArrowRight size={14}/></button></div>
  </div>
}

function ImpactChart({ overview }: { overview: OverviewPayload }) {
  const before = overview.validation.fraud_capture - overview.validation.fraud_capture_lift_pp / 100
  const after = overview.validation.fraud_capture
  return <div className="card impact-card">
    <div className="card-head"><div><h3>Validation Impact</h3><span>same 6% intervention capacity</span></div><span className="frozen-pill">FROZEN</span></div>
    <div className="impact-chart">
      <div className="impact-row"><div><span>Stable v0.5</span><b>{pct(before)}</b></div><div className="bar-track"><i style={{width: `${before * 100}%`}}/></div></div>
      <div className="impact-row featured"><div><span>Mentalist v1.0</span><b>{pct(after)}</b></div><div className="bar-track"><i style={{width: `${after * 100}%`}}/></div></div>
      <div className="impact-note"><Zap size={16}/><div><b>+50 frauds investigated</b><span>while 50 legitimate investigations were removed</span></div></div>
    </div>
  </div>
}

function Donut({ feed }: { feed: FeedItem[] }) {
  const counts = useMemo(() => ({
    allow: feed.filter(x => x.action === 'ALLOW').length,
    verify: feed.filter(x => x.action === 'VERIFY').length,
    review: feed.filter(x => x.action === 'REVIEW').length,
  }), [feed])
  const total = Math.max(feed.length, 1)
  const a = counts.allow / total * 100, v = counts.verify / total * 100
  return <div className="card donut-card"><div className="card-head"><div><h3>Queue Distribution</h3><span>current visible feed</span></div></div>
    <div className="donut-wrap"><div className="donut" style={{background: `conic-gradient(#35d39a 0 ${a}%, #f3b847 ${a}% ${a+v}%, #8c6df2 ${a+v}% 100%)`}}><div><b>{feed.length}</b><span>Total</span></div></div>
      <div className="legend"><p><i className="green"/>ALLOW <b>{counts.allow}</b></p><p><i className="amber"/>VERIFY <b>{counts.verify}</b></p><p><i className="purple"/>REVIEW <b>{counts.review}</b></p></div>
    </div>
  </div>
}

const clueMeta: Record<string, { label: string; text: string; icon: React.ReactNode }> = {
  coordination: { label: 'Coordination', text: 'Multiple contexts forming one behavioral case.', icon: <Network size={16}/> },
  velocity: { label: 'Velocity', text: 'Short-horizon activity and acceleration.', icon: <Gauge size={16}/> },
  behavior_change: { label: 'Behavior Change', text: 'Deviation from established profile behavior.', icon: <Radar size={16}/> },
  reuse_churn: { label: 'Reuse / Churn', text: 'Context reuse or identity churn across activity.', icon: <TimerReset size={16}/> },
}

function MentalistPanel({ record }: { record: CaseRecord }) {
  const clues = record.mentalist?.clue_families || {}
  return <div className="card mentalist-panel">
    <div className="card-head"><div><h3>Mentalist Insights</h3><span className="proactive-pill"><Sparkles size={12}/>Proactive mode</span></div><span>no fraud label input</span></div>
    <div className="mentalist-body"><div className="mentalist-persona"><div className="persona-orb"><BrainCircuit size={28}/></div><b>Jane</b><span>proactive investigator</span><em>{score(record.mentalist?.score)} / 100</em></div>
      <div className="clue-grid">{Object.entries(clueMeta).map(([key, meta]) => {
        const active = !!clues[key]
        return <div className={`clue-tile ${active ? 'active' : ''}`} key={key}><div className="clue-icon">{meta.icon}</div><div><b>{meta.label}</b><span>{meta.text}</span></div><strong>{active ? <Check size={14}/> : '—'}</strong></div>
      })}</div>
    </div>
    <div className="mentalist-foot"><span><i className="live-dot"/> {record.mentalist?.clue_count ?? 0} independent families active</span><b>Threshold {record.mentalist ? score(record.mentalist.score_threshold) : '—'}</b></div>
  </div>
}

function NetworkGraph({ record, compact = false }: { record: CaseRecord; compact?: boolean }) {
  const nodes = record.network?.nodes || []
  const edges = record.network?.edges || []
  const positions = useMemo(() => {
    const map = new Map<string, {x:number;y:number}>()
    const current = nodes.find(n => n.kind === 'current') || nodes[0]
    if (current) map.set(current.id, {x:50,y:50})
    const relations = nodes.filter(n => n.kind === 'relation')
    relations.forEach((n,i) => { const a=(i/Math.max(relations.length,1))*Math.PI*2-Math.PI/2; map.set(n.id,{x:50+25*Math.cos(a),y:50+25*Math.sin(a)}) })
    const outer = nodes.filter(n => n.id !== current?.id && n.kind !== 'relation')
    outer.forEach((n,i) => { const a=(i/Math.max(outer.length,1))*Math.PI*2+0.35; map.set(n.id,{x:50+42*Math.cos(a),y:50+38*Math.sin(a)}) })
    return map
  }, [nodes])
  const kindClass = (n: NetworkNode) => `node-${n.kind}`
  return <div className={`card network-card ${compact ? 'compact-network' : ''}`}><div className="card-head"><div><h3>Relationship Graph</h3><span>causal neighborhood at decision time</span></div><button><Eye size={15}/>Expand</button></div>
    <svg className="network-svg" viewBox="0 0 100 100">
      {edges.map((e,i) => { const s=positions.get(e.source), t=positions.get(e.target); return s&&t ? <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y}/> : null })}
      {nodes.map((n) => { const p=positions.get(n.id); if(!p)return null; return <g key={n.id} className={`graph-node ${kindClass(n)}`} transform={`translate(${p.x} ${p.y})`}><circle r={n.kind==='current'?5.8:4.2}/><circle className="node-core" r={n.kind==='current'?2.1:1.5}/><text y={n.kind==='current'?9:7}>{n.label.slice(0,20)}</text></g> })}
    </svg>
    <div className="network-legend"><span><i className="current"/>Current</span><span><i className="relation"/>Context</span><span><i className="prior"/>Prior</span><span><i className="fraud"/>Matured fraud</span></div>
  </div>
}

function PriorityPanel() {
  const items = [
    ['Proactive coordination case', 'Mentalist', '3 clue families', 82],
    ['Account takeover pattern', 'Review', 'device + profile shift', 91],
    ['Velocity anomaly', 'Verify', 'burst across contexts', 76],
    ['Historical link only', 'Allow', 'insufficient current evidence', 34],
  ]
  return <div className="card priority-card"><div className="card-head"><div><h3>Priority Investigations</h3><span>illustrative operations queue</span></div><button>View all</button></div>
    {items.map(([title,tag,desc,risk]) => <div className="priority-row" key={title as string}><div className="priority-icon"><ShieldAlert size={16}/></div><div><b>{title}</b><span>{desc}</span></div><em>{tag}</em><strong>Risk {risk}</strong></div>)}
  </div>
}

function Overview({ overview, feed, selected, onOpen }: { overview: OverviewPayload; feed: FeedItem[]; selected: CaseRecord; onOpen:(f:FeedItem)=>void }) {
  return <main className="content overview-page">
    <div className="page-intro"><div><span className="eyebrow">Risk operations</span><h1>Proactive fraud intelligence</h1><p>Transaction risk, trusted history and Mentalist deductions—kept separate, routed under one frozen policy.</p></div><div className="sealed-card"><ShieldCheck size={18}/><div><b>Development candidate</b><span>Held-out chronological test remains sealed</span></div></div></div>
    <section className="kpi-grid">
      <MetricCard icon={<ShieldCheck size={16}/>} label="Fraud Capture" value={pct(overview.validation.fraud_capture)} delta={`+${overview.validation.fraud_capture_lift_pp.toFixed(2)}pp`} foot="same capacity" values={[40,41,40.8,42,41.7,43.1,44.21]} />
      <MetricCard icon={<UsersRound size={16}/>} label="Legit Friction" value={pct(overview.validation.legitimate_friction)} delta={`${overview.validation.legitimate_friction_delta_pp.toFixed(2)}pp`} foot="lower is better" tone="green" values={[5.1,5.0,4.9,4.82,4.76,4.7,4.64]} />
      <MetricCard icon={<Layers3 size={16}/>} label="Intervention Capacity" value={pct(overview.validation.intervention_share)} delta="unchanged" foot="policy budget" tone="blue" values={[6,6,6,6,6,6,6]} />
      <MetricCard icon={<Sparkles size={16}/>} label="Mentalist Novel Cases" value={overview.validation.mentalist_novel_cases.toString()} delta={`${overview.validation.mentalist_frauds_added} frauds`} foot="beyond v0.5 policy" tone="purple" values={[12,18,24,31,36,43,50]} />
      <MetricCard icon={<UserRoundSearch size={16}/>} label="v0.5 Review Precision" value={pct(overview.validation.v5_review_precision)} delta="hard REVIEW" foot="immutable layer" tone="amber" values={[48,50,49,51,52,53,53.36]} />
    </section>
    <section className="overview-grid top-grid"><FeedTable feed={feed} onOpen={onOpen}/><ImpactChart overview={overview}/><Donut feed={feed}/></section>
    <section className="overview-grid bottom-grid"><MentalistPanel record={selected}/><NetworkGraph record={selected} compact/><PriorityPanel/></section>
    <div className="proactive-banner"><div><BrainCircuit size={22}/><div><b>Detect the pattern before the profile becomes known fraud.</b><span>Mentalist acts only when independent present-tense evidence forms a case.</span></div></div><button>Explore proactive insights <ArrowRight size={15}/></button></div>
  </main>
}

function ScoreCard({ label, value, tone, sub, icon }: { label:string; value:number|null|undefined; tone:string; sub:string; icon:React.ReactNode }) {
  return <div className="score-card"><div className={`ring tone-${tone}`} style={{'--score': `${(value || 0)*360}deg`} as React.CSSProperties}><div><b>{score(value)}</b><span>/100</span></div></div><div className="score-copy"><span>{icon}{label}</span><b>{sub}</b><Sparkline values={[18,25,23,32,30,44,38,55,49,62]} tone={tone}/></div></div>
}

function Timeline({ record }: { record: CaseRecord }) {
  const jane = record.mentalist
  const events = [
    ['Payment created', money(record.input.amount), 'blue'],
    [`v0.5 evaluated`, `${record.decision.v5_action} · score ${score(record.decision.linkrisk_risk)}/100`, 'green'],
    ['Proactive clues evaluated', `${jane?.clue_count ?? 0} independent families`, 'amber'],
    ['Mentalist routed', `${record.decision.action} · score ${score(jane?.score)}/100`, 'purple'],
    ['Trusted memory checked', record.case_file.trusted_fraud_evidence_present ? `${record.case_file.trusted_fraud_channels} fraud channels` : 'No confirmed fraud required', 'cyan'],
    ['Adjudication', record.adjudication?.state || 'pending', 'muted'],
  ]
  return <div className="card timeline-card"><div className="card-head"><div><h3>Case Timeline</h3><span>decision journey</span></div></div><div className="timeline">{events.map(([title,sub,tone],i)=><div className="timeline-row" key={title}><div className={`timeline-dot ${tone}`}>{i+1}</div><div><b>{title}</b><span>{sub}</span></div><time>+{i*2}s</time></div>)}</div></div>
}

function CaseFile({ record }: { record: CaseRecord }) {
  const clues = record.mentalist?.clue_families || {}
  return <div className="card case-file"><div className="card-head"><div><h3>Jane / Mentalist Case File</h3><span className="proactive-pill">Proactive mode</span></div><span>{record.mentalist?.uses_confirmed_fraud_as_input ? 'history used' : 'no fraud-label input'}</span></div>
    <div className="case-file-body"><div className="persona-large"><div className="persona-orb large"><BrainCircuit size={34}/></div><b>Jane</b><span>Pattern investigator</span><strong>{score(record.mentalist?.score)}</strong><small>Mentalist score</small></div>
      <div className="family-list">{Object.entries(clueMeta).map(([key,m])=>{const active=!!clues[key]; return <div className={`family-row ${active?'active':''}`} key={key}><div className="family-icon">{m.icon}</div><div><b>{m.label}</b><span>{m.text}</span></div><em>{active?'ACTIVE':'INACTIVE'}</em><strong>{active?'Evidence':'Low'}</strong></div>})}</div>
    </div>
  </div>
}

function Investigator({ record, preview, onAdjudicate, onAdvance }: { record:CaseRecord; preview:boolean; onAdjudicate:(o:'fraud'|'legitimate')=>void; onAdvance:()=>void }) {
  const jane = record.mentalist
  return <main className="content investigator-page">
    <div className="case-header card"><div className="case-title"><span className="eyebrow">Investigation</span><h1>{record.transaction_id}</h1><ActionBadge action={record.decision.action}/></div><div className="case-meta"><div><span>Amount</span><b>{money(record.input.amount)}</b></div><div><span>Profile</span><b>{record.input.payment_profile}</b></div><div><span>Device context</span><b>{record.input.device_info}</b></div><div><span>Receiver domain</span><b>{record.input.receiver_domain}</b></div><div><span>Policy</span><b>{record.decision.policy_version || 'v0.5'}</b></div></div></div>
    <div className="decision-journey card"><div className="journey-stage"><span>v0.5 Action</span><div><ActionBadge action={record.decision.v5_action}/><b>{score(record.decision.linkrisk_risk)} / 100</b></div><small>transaction + trusted memory</small></div><ArrowRight size={25}/><div className="journey-stage jane-stage"><span>Mentalist deduction</span><div><ActionBadge action={record.decision.action}/><b>{score(jane?.score)} / 100</b></div><small>{jane?.clue_count ?? 0} independent clue families</small></div><ArrowRight size={25}/><div className="journey-stage final-stage"><span>Final action</span><div><ActionBadge action={record.decision.action}/><b>{record.decision.routing_reason.replaceAll('_',' ')}</b></div><small>frozen point-in-time router</small></div></div>
    <section className="score-strip card"><ScoreCard label="Transaction Risk" value={record.decision.baseline_risk} tone="red" sub="raw transaction model" icon={<Gauge size={14}/>}/><ScoreCard label="Trusted Memory" value={record.decision.linkrisk_risk} tone="amber" sub={record.case_file.trusted_fraud_evidence_present?'historical evidence present':'no matured fraud evidence'} icon={<Database size={14}/>}/><ScoreCard label="Mentalist Score" value={jane?.score} tone="purple" sub={`${jane?.clue_count ?? 0} / 4 families active`} icon={<BrainCircuit size={14}/>}/><div className="final-score"><span>Final Action</span><ActionBadge action={record.decision.action}/><small>{record.case_file.action_changed ? `${record.decision.v5_action} → ${record.decision.action}` : 'v0.5 preserved'}</small></div></section>
    <div className="investigator-layout"><div className="investigator-main"><div className="case-row"><CaseFile record={record}/><div className="card memory-card"><div className="card-head"><div><h3>Trusted History</h3><span>separate evidence channel</span></div></div><div className={`memory-status ${record.case_file.trusted_fraud_evidence_present?'has-history':''}`}><ShieldCheck size={26}/><b>{record.case_file.trusted_fraud_evidence_present?'Matured fraud evidence':'No confirmed fraud required'}</b><span>{record.case_file.trusted_history_channels} history channels · {record.case_file.trusted_fraud_channels} fraud channels</span></div><div className="principle"><Sparkles size={15}/><span>Past fraud is evidence, not guilt. Jane can form a case without it.</span></div></div></div><div className="lower-case-grid"><NetworkGraph record={record}/><Timeline record={record}/></div></div>
      <aside className="rationale card"><div className="card-head"><div><h3>Decision Rationale</h3><span>{record.decision.policy_version}</span></div></div><p className="rationale-lead">{record.case_file.explanation}</p><div className="rationale-list"><div><Network size={16}/><span>Coordination</span><b>{jane?.clue_families.coordination?'active':'not active'}</b></div><div><Gauge size={16}/><span>Velocity</span><b>{jane?.clue_families.velocity?'active':'not active'}</b></div><div><Radar size={16}/><span>Behavior change</span><b>{jane?.clue_families.behavior_change?'active':'not active'}</b></div><div><TimerReset size={16}/><span>Reuse / churn</span><b>{jane?.clue_families.reuse_churn?'active':'not active'}</b></div></div><div className="rationale-divider"/><h4>Recommended action</h4><div className="action-buttons"><button className={record.decision.action==='ALLOW'?'selected allow':''}><Check size={16}/>ALLOW<small>no action</small></button><button className={record.decision.action==='VERIFY'?'selected verify':''}><ShieldCheck size={16}/>VERIFY<small>step-up</small></button><button className={record.decision.action==='REVIEW'?'selected review':''}><UserRoundSearch size={16}/>REVIEW<small>analyst</small></button></div><div className="rationale-divider"/><h4>Adjudication feedback</h4><p className="mini-copy">Feedback becomes trusted memory only after the frozen 72-hour delay and actual recording time.</p><div className="feedback-actions"><button onClick={()=>onAdjudicate('legitimate')} disabled={preview}><Check size={15}/>Confirm legitimate</button><button onClick={()=>onAdjudicate('fraud')} disabled={preview}><AlertTriangle size={15}/>Confirm fraud</button><button onClick={onAdvance} disabled={preview}><Clock3 size={15}/>+72h</button></div>{preview&&<div className="preview-note">Create a real payment to enable adjudication controls.</div>}</aside>
    </div>
  </main>
}

function NewPaymentModal({ open, onClose, onCreated }: { open:boolean; onClose:()=>void; onCreated:(r:CaseRecord)=>void }) {
  const [form,setForm]=useState({amount:'2500',payment_profile:'PROFILE-A',device_info:'Windows / Chrome',receiver_domain:'gmail.com',browser_context:'chrome-124',product_code:'W'})
  const [busy,setBusy]=useState(false); const [error,setError]=useState('')
  if(!open)return null
  const submit=async(e:FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{const record=await api.createTransaction({amount:Number(form.amount),payment_profile:form.payment_profile,device_info:form.device_info,receiver_domain:form.receiver_domain,browser_context:form.browser_context,product_code:form.product_code,payer_domain:'gmail.com',device_type:'desktop',card_network:'visa',card_type:'debit'});onCreated(record);onClose()}catch(err){setError(err instanceof Error?err.message:String(err))}finally{setBusy(false)}}
  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal card" onSubmit={submit} onMouseDown={e=>e.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">Live engine</span><h2>Score a new payment</h2></div><button type="button" className="icon-button" onClick={onClose}><X size={18}/></button></div><div className="form-grid"><label>Amount<input value={form.amount} onChange={e=>setForm({...form,amount:e.target.value})}/></label><label>Payment profile<input value={form.payment_profile} onChange={e=>setForm({...form,payment_profile:e.target.value})}/></label><label>Device signature<input value={form.device_info} onChange={e=>setForm({...form,device_info:e.target.value})}/></label><label>Receiver domain<input value={form.receiver_domain} onChange={e=>setForm({...form,receiver_domain:e.target.value})}/></label><label>Browser context<input value={form.browser_context} onChange={e=>setForm({...form,browser_context:e.target.value})}/></label><label>Product code<select value={form.product_code} onChange={e=>setForm({...form,product_code:e.target.value})}><option>W</option><option>C</option><option>H</option><option>R</option><option>S</option></select></label></div>{error&&<div className="form-error"><AlertTriangle size={15}/>{error}</div>}<div className="modal-actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy}>{busy?'Scoring...':'Run LinkRisk'}<ArrowRight size={16}/></button></div></form></div>
}

export default function App() {
  const [page,setPage]=useState<Page>('overview')
  const [overview,setOverview]=useState<OverviewPayload>(previewOverview)
  const [feed,setFeed]=useState<FeedItem[]>(previewFeed)
  const [selected,setSelected]=useState<CaseRecord>(previewCase)
  const [preview,setPreview]=useState(true)
  const [engineReady,setEngineReady]=useState(false)
  const [modal,setModal]=useState(false)

  const refreshFeed=async()=>{try{const payload=await api.transactions();if(payload.items.length){setFeed(payload.items);setPreview(false)}}catch{/* frontend remains in preview mode */}}
  useEffect(()=>{void (async()=>{try{const [ov,health,tx]=await Promise.all([api.overview(),api.health(),api.transactions()]);setOverview(ov);setEngineReady(health.asset_status.ready);if(tx.items.length){setFeed(tx.items);setPreview(false);const last=tx.items[tx.items.length-1];setSelected(await api.transaction(last.transaction_id))}}catch{/* backend optional during UI-only preview */}})()},[])

  const openItem=async(item:FeedItem)=>{if(previewFeed.some(x=>x.transaction_id===item.transaction_id)&&preview){setSelected({...previewCase,transaction_id:item.transaction_id,input:{...previewCase.input,amount:item.amount,payment_profile:item.profile,device_info:item.device},decision:{...previewCase.decision,v5_action:item.v5_action,action:item.action,baseline_risk:item.baseline_risk,linkrisk_risk:item.v5_risk,routing_reason:item.routing_reason},mentalist:previewCase.mentalist?{...previewCase.mentalist,score:item.jane_score??.1,clue_count:item.clue_count}:null,case_file:{...previewCase.case_file,v5_action:item.v5_action,final_action:item.action,action_changed:item.v5_action!==item.action,routing_reason:item.routing_reason}});setPage('investigator');return}try{setSelected(await api.transaction(item.transaction_id));setPreview(false);setPage('investigator')}catch{setPage('investigator')}}
  const onCreated=(r:CaseRecord)=>{setSelected(r);setPreview(false);setEngineReady(true);setPage('investigator');void refreshFeed()}
  const adjudicate=async(outcome:'fraud'|'legitimate')=>{try{setSelected(await api.adjudicate(selected.transaction_id,outcome))}catch{/* surfaced by disabled preview or backend */}}
  const advance=async()=>{try{await api.advance(72*60*60);setSelected(await api.transaction(selected.transaction_id))}catch{/* no-op */}}

  return <div className="app-shell"><Sidebar page={page} setPage={setPage}/><div className="workspace"><Topbar preview={preview} engineReady={engineReady} onNewPayment={()=>setModal(true)}/>{page==='overview'?<Overview overview={overview} feed={feed} selected={selected} onOpen={openItem}/>:<Investigator record={selected} preview={preview} onAdjudicate={adjudicate} onAdvance={advance}/>}</div><NewPaymentModal open={modal} onClose={()=>setModal(false)} onCreated={onCreated}/></div>
}
