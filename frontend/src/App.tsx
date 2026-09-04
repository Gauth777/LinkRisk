import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, FormEvent, ReactNode } from 'react'
import {
  Activity, AlertTriangle, ArrowLeft, ArrowRight, BarChart3, Bell, BrainCircuit,
  Check, ChevronRight, CircleDollarSign, Clock3, Database, Eye, FileText,
  Gauge, GitBranch, Home, Layers3, Maximize2, MonitorUp, Network, Plus,
  Radar, RefreshCw, Search, Settings, ShieldAlert, ShieldCheck, Sparkles,
  TimerReset, UserRoundSearch, UsersRound, X, Zap,
} from 'lucide-react'
import { api } from './api'
import { JaneEscalationPanel } from './JaneEscalationPanel'
import { previewCase, previewFeed, previewOverview } from './demoData'
import type { Action, CaseRecord, FeedItem, NetworkNode, OverviewPayload } from './types'

type Page =
  | 'overview'
  | 'investigations'
  | 'feed'
  | 'network'
  | 'cases'
  | 'reports'
  | 'alerts'
  | 'models'
  | 'data'
  | 'settings'

type NavItem = {
  page: Page
  label: string
  icon: typeof Home
}

const NAV_ITEMS: NavItem[] = [
  { page: 'overview', label: 'Overview', icon: Home },
  { page: 'investigations', label: 'Investigations', icon: UserRoundSearch },
  { page: 'feed', label: 'Live Feed', icon: Activity },
  { page: 'network', label: 'Network', icon: Network },
  { page: 'cases', label: 'Cases', icon: FileText },
  { page: 'reports', label: 'Reports', icon: BarChart3 },
  { page: 'alerts', label: 'Alerts', icon: Bell },
  { page: 'models', label: 'Models', icon: BrainCircuit },
  { page: 'data', label: 'Data', icon: Database },
  { page: 'settings', label: 'Settings', icon: Settings },
]

const clueMeta: Record<string, { label: string; description: string; icon: ReactNode }> = {
  velocity: {
    label: 'Velocity',
    description: 'Short-horizon transaction bursts and acceleration.',
    icon: <Gauge size={20} />,
  },
  behavior_change: {
    label: 'Behavior change',
    description: 'Current behavior departs from the profile history.',
    icon: <Radar size={20} />,
  },
  coordination: {
    label: 'Coordination',
    description: 'Multiple contexts combine into one present-tense case.',
    icon: <Network size={20} />,
  },
  reuse_churn: {
    label: 'Reuse / churn',
    description: 'Context reuse or profile/context churn is elevated.',
    icon: <TimerReset size={20} />,
  },
}

const clamp01 = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
const pct = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`
const score = (value?: number | null) => value == null ? '—' : Math.round(clamp01(value) * 100).toString()
const amount = (value: number) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
const titleCase = (value: string) => value.toLowerCase().replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
const isNeutralRecord = (record: CaseRecord) => record.transaction_id === 'NO-LIVE-TRANSACTION'

function makePreviewRecord(item: FeedItem): CaseRecord {
  return {
    ...previewCase,
    transaction_id: item.transaction_id,
    transaction_time: item.transaction_time,
    input: {
      ...previewCase.input,
      amount: item.amount,
      payment_profile: item.profile,
      device_info: item.device,
    },
    decision: {
      ...previewCase.decision,
      baseline_risk: item.baseline_risk,
      linkrisk_risk: item.v5_risk,
      v5_action: item.v5_action,
      action: item.action,
      routing_reason: item.routing_reason,
    },
    mentalist: previewCase.mentalist ? {
      ...previewCase.mentalist,
      score: item.jane_score ?? 0,
      clue_count: item.clue_count,
    } : null,
    case_file: {
      ...previewCase.case_file,
      v5_action: item.v5_action,
      final_action: item.action,
      action_changed: item.v5_action !== item.action,
      routing_reason: item.routing_reason,
    },
  }
}

function ActionBadge({ action, large = false }: { action: Action; large?: boolean }) {
  return <span className={`action-badge action-${action.toLowerCase()} ${large ? 'large' : ''}`}>{action}</span>
}

function SectionHeader({ eyebrow, title, description, action }: {
  eyebrow: string
  title: string
  description: string
  action?: ReactNode
}) {
  return <div className="section-header">
    <div>
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
    {action && <div className="section-header-action">{action}</div>}
  </div>
}

function MetricCard({ icon, label, value, delta, note, tone = 'cyan' }: {
  icon: ReactNode
  label: string
  value: string
  delta: string
  note: string
  tone?: string
}) {
  return <article className={`card metric-card metric-${tone}`}>
    <div className="metric-top"><span className="metric-icon">{icon}</span><span>{label}</span></div>
    <div className="metric-main"><strong>{value}</strong><em>{delta}</em></div>
    <p>{note}</p>
  </article>
}

function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  return <aside className="sidebar">
    <button className="brand" onClick={() => onNavigate('overview')}>
      <span className="brand-mark"><GitBranch size={23} /></span>
      <span>LinkRisk</span>
    </button>
    <nav>
      {NAV_ITEMS.map(({ page: target, label, icon: Icon }) => (
        <button
          key={target}
          className={`nav-item ${page === target ? 'active' : ''}`}
          onClick={() => onNavigate(target)}
        >
          <Icon size={19} />
          <span>{label}</span>
          {target === 'feed' && <i className="live-dot" />}
        </button>
      ))}
    </nav>
    <div className="sidebar-spacer" />
    <div className="runtime-card">
      <ShieldCheck size={20} />
      <div><b>Selective v2 runtime</b><span>v1 final evaluated · v2 development</span></div>
    </div>
  </aside>
}

function Topbar({
  preview,
  engineReady,
  searchValue,
  onSearch,
  onNewPayment,
  presentationMode,
  onTogglePresentation,
  alertCount,
  alertsOpen,
  onToggleAlerts,
}: {
  preview: boolean
  engineReady: boolean
  searchValue: string
  onSearch: (value: string) => void
  onNewPayment: () => void
  presentationMode: boolean
  onTogglePresentation: () => void
  alertCount: number
  alertsOpen: boolean
  onToggleAlerts: () => void
}) {
  return <header className="topbar">
    <div className="runtime-status">
      <span className={`status-pulse ${engineReady ? 'ready' : ''}`} />
      <b>{engineReady ? 'Engine ready' : 'Preview mode'}</b>
      <span>{preview ? 'sample session' : 'live session'}</span>
    </div>
    <div className="topbar-actions">
      <label className="search-input">
        <Search size={18} />
        <input
          value={searchValue}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search transaction or profile"
        />
        {searchValue && <button type="button" onClick={() => onSearch('')}><X size={15} /></button>}
      </label>
      <button className={`ghost-button ${presentationMode ? 'active' : ''}`} onClick={onTogglePresentation}>
        <MonitorUp size={18} />
        <span>{presentationMode ? 'Demo view on' : 'Demo view'}</span>
      </button>
      <button className="primary-button" onClick={onNewPayment}><Plus size={18} />New payment</button>
      <div className="notification-wrap">
        <button className="icon-button" onClick={onToggleAlerts} aria-label="Notifications">
          <Bell size={19} />
          {alertCount > 0 && <i>{alertCount}</i>}
        </button>
        {alertsOpen && <div className="notification-popover">
          <b>Attention queue</b>
          <span>{alertCount} visible VERIFY / REVIEW cases</span>
          <small>Open Alerts for the complete queue.</small>
        </div>}
      </div>
    </div>
  </header>
}

function FeedTable({
  items,
  onOpen,
  emptyText = 'No transactions match this view.',
  limit,
}: {
  items: FeedItem[]
  onOpen: (item: FeedItem) => void
  emptyText?: string
  limit?: number
}) {
  const visible = typeof limit === 'number' ? items.slice(0, limit) : items
  return <div className="table-shell">
    <table>
      <thead><tr><th>Transaction</th><th>Profile</th><th>Amount</th><th>v0.5</th><th>Jane</th><th>Clues</th><th>Action</th></tr></thead>
      <tbody>
        {visible.map((item) => <tr key={item.transaction_id} onClick={() => onOpen(item)}>
          <td><b>{item.transaction_id}</b><small>{titleCase(item.routing_reason)}</small></td>
          <td><b>{item.profile}</b><small>{item.device}</small></td>
          <td>{amount(item.amount)}</td>
          <td><span className="score-pill">{score(item.v5_risk)}</span></td>
          <td><span className="score-pill jane">{score(item.jane_score)}</span></td>
          <td><b className="clue-count">{item.clue_count}</b></td>
          <td><ActionBadge action={item.action} /><ChevronRight size={17} /></td>
        </tr>)}
      </tbody>
    </table>
    {visible.length === 0 && <div className="empty-state">{emptyText}</div>}
  </div>
}

function ValidationImpact({ overview }: { overview: OverviewPayload }) {
  const before = overview.validation.fraud_capture - overview.validation.fraud_capture_lift_pp / 100
  const after = overview.validation.fraud_capture
  return <div className="card impact-card">
    <div className="card-heading"><div><h2>Capacity-preserving lift</h2><p>Development validation · same 6% intervention capacity</p></div><span className="frozen-label">DEVELOPMENT</span></div>
    <div className="impact-bars">
      <div className="impact-row"><div><span>Stable v0.5</span><b>{pct(before, 2)}</b></div><div className="bar-track"><i style={{ width: `${before * 100}%` }} /></div></div>
      <div className="impact-row featured"><div><span>Mentalist v1.0</span><b>{pct(after, 2)}</b></div><div className="bar-track"><i style={{ width: `${after * 100}%` }} /></div></div>
    </div>
    <div className="impact-callout"><Zap size={21} /><div><b>+50 frauds investigated</b><span>50 legitimate investigations removed at the same capacity.</span></div></div>
  </div>
}

function QueueDistribution({ items }: { items: FeedItem[] }) {
  const counts = useMemo(() => ({
    ALLOW: items.filter((item) => item.action === 'ALLOW').length,
    VERIFY: items.filter((item) => item.action === 'VERIFY').length,
    REVIEW: items.filter((item) => item.action === 'REVIEW').length,
  }), [items])
  const total = Math.max(items.length, 1)
  return <div className="card queue-card">
    <div className="card-heading"><div><h2>Visible queue</h2><p>Current session distribution</p></div></div>
    <div className="queue-total"><strong>{items.length}</strong><span>transactions</span></div>
    <div className="stacked-bar">
      <i className="allow" style={{ width: `${counts.ALLOW / total * 100}%` }} />
      <i className="verify" style={{ width: `${counts.VERIFY / total * 100}%` }} />
      <i className="review" style={{ width: `${counts.REVIEW / total * 100}%` }} />
    </div>
    <div className="queue-legend">
      {(['ALLOW', 'VERIFY', 'REVIEW'] as Action[]).map((action) => <div key={action}><span className={`legend-dot ${action.toLowerCase()}`} />{action}<b>{counts[action]}</b></div>)}
    </div>
  </div>
}

function MentalistSummary({ record, onInvestigate }: { record: CaseRecord; onInvestigate: () => void }) {
  const hasSelection = !isNeutralRecord(record)
  const mentalist = hasSelection ? record.mentalist : null
  return <div className="card mentalist-summary">
    <div className="mentalist-summary-head"><span className="jane-orb"><BrainCircuit size={26} /></span><div><span className="eyebrow">Mentalist</span><h2>Current case signal</h2></div></div>
    <div className="mentalist-score"><strong>{score(mentalist?.score)}</strong><span>/100 Jane score</span></div>
    {!hasSelection && <div className="mentalist-empty"><b>No active case</b><span>Select a transaction from Live Feed to inspect Jane's evidence.</span></div>}
    <div className="active-clues">
      {Object.entries(clueMeta).map(([key, meta]) => {
        const active = hasSelection && !!mentalist?.clue_families?.[key]
        return <div className={active ? 'active' : ''} key={key}>{meta.icon}<span>{meta.label}</span><b>{active ? 'ON' : '—'}</b></div>
      })}
    </div>
    <button className="wide-button" disabled={!hasSelection} onClick={onInvestigate}>{hasSelection ? 'Open case investigation' : 'Select a live transaction'} <ArrowRight size={17} /></button>
  </div>
}

function OverviewPage({
  overview,
  feed,
  sessionFeed,
  selected,
  onOpen,
  onNavigate,
}: {
  overview: OverviewPayload
  feed: FeedItem[]
  sessionFeed: FeedItem[]
  selected: CaseRecord
  onOpen: (item: FeedItem) => void
  onNavigate: (page: Page) => void
}) {
  const transactionsSeen = overview.live.transactions
  const interventions = overview.live.verify + overview.live.review
  const interventionShare = transactionsSeen > 0 ? interventions / transactionsSeen : 0
  const mentalistInvoked = sessionFeed.filter((item) => item.jane_score != null).length
  const mentalistShare = transactionsSeen > 0 ? mentalistInvoked / transactionsSeen : 0

  return <main className="content">
    <SectionHeader
      eyebrow="Risk operations"
      title="Proactive fraud intelligence"
      description="Live operational telemetry first; validated development benchmarks remain clearly separated below."
      action={<div className="sealed-pill"><ShieldCheck size={18} /><span>v1 final evaluated once</span></div>}
    />
    <section className="metric-grid four live-metric-grid">
      <MetricCard icon={<Activity />} label="Transactions seen" value={transactionsSeen.toString()} delta={transactionsSeen > 0 ? 'live session' : 'awaiting payment'} note="Scored by the current runtime" />
      <MetricCard icon={<Layers3 />} label="Intervention usage" value={pct(interventionShare, 1)} delta={`${interventions} actions`} note={`Sustained policy budget ${pct(overview.validation.intervention_share, 0)}`} tone="blue" />
      <MetricCard icon={<BrainCircuit />} label="Mentalist invoked" value={mentalistInvoked.toString()} delta={pct(mentalistShare, 1)} note="Jane runs only on eligible evidence-bearing cases" tone="purple" />
      <MetricCard icon={<ShieldCheck />} label="Actions" value={`${overview.live.allow} / ${overview.live.verify} / ${overview.live.review}`} delta="A / V / R" note="ALLOW / VERIFY / REVIEW" tone="green" />
    </section>
    <section className="overview-main-grid">
      <div className="card feed-card">
        <div className="card-heading"><div><h2>Live risk feed</h2><p>Click any transaction to investigate it</p></div><button className="text-button" onClick={() => onNavigate('feed')}>Full feed <ArrowRight size={16} /></button></div>
        <FeedTable items={feed} onOpen={onOpen} limit={5} />
      </div>
      <MentalistSummary record={selected} onInvestigate={() => onNavigate('investigations')} />
    </section>
    <section className="overview-bottom-grid">
      <ValidationImpact overview={overview} />
      <QueueDistribution items={sessionFeed} />
    </section>
  </main>
}

function EvidenceCard({ active, label, description, icon }: { active: boolean; label: string; description: string; icon: ReactNode }) {
  return <article className={`evidence-card ${active ? 'active' : ''}`}>
    <span className="evidence-icon">{icon}</span>
    <div><b>{label}</b><p>{description}</p></div>
    <strong>{active ? <><Check size={17} /> ACTIVE</> : 'INACTIVE'}</strong>
  </article>
}

function ScorePanel({ label, value, description, tone }: { label: string; value: number | null | undefined; description: string; tone: string }) {
  const percentage = Math.round(clamp01(value ?? 0) * 100)
  return <div className={`score-panel tone-${tone}`}>
    <div><span>{label}</span><strong>{value == null ? '—' : percentage}</strong></div>
    <div className="score-track"><i style={{ width: `${percentage}%` }} /></div>
    <p>{description}</p>
  </div>
}

function InvestigationPage({
  record,
  preview,
  onBack,
  onAdjudicate,
  onAdvance,
  onNavigate,
  onRecordUpdate,
}: {
  record: CaseRecord
  preview: boolean
  onBack: () => void
  onAdjudicate: (outcome: 'fraud' | 'legitimate') => void
  onAdvance: () => void
  onNavigate: (page: Page) => void
  onRecordUpdate: (record: CaseRecord) => void
}) {
  const hasSelection = !isNeutralRecord(record)
  const mentalist = hasSelection ? record.mentalist : null
  const janeScore = record.analyst_jane?.score ?? mentalist?.score
  const janeClueCount = record.analyst_jane?.clue_count ?? mentalist?.clue_count ?? 0
  const evidenceClues = record.analyst_jane?.clue_families ?? mentalist?.clue_families ?? {}

  if (!hasSelection) {
    return <main className="content">
      <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to overview</button>
      <SectionHeader
        eyebrow="Investigation"
        title="No transaction selected"
        description="Choose a live payment to inspect the complete point-in-time decision path."
      />
      <section className="card neutral-investigation">
        <div className="neutral-investigation-head"><UserRoundSearch size={28} /><div><h2>Waiting for a case</h2><p>No action has been produced because no live transaction is selected.</p></div></div>
        <div className="neutral-case-grid">
          <div><span>Transaction model</span><strong>—</strong></div>
          <div><span>v0.5 risk</span><strong>—</strong></div>
          <div><span>Mentalist / Jane</span><strong>—</strong></div>
          <div><span>Final action</span><strong>—</strong></div>
        </div>
        <button className="primary-button" onClick={() => onNavigate('feed')}>Open Live Feed <ArrowRight size={17} /></button>
      </section>
    </main>
  }

  return <main className="content">
    <button className="back-button" onClick={onBack}><ArrowLeft size={17} />Back to overview</button>
    <SectionHeader
      eyebrow="Investigation"
      title={record.transaction_id}
      description={`Amount ${amount(record.input.amount)} · ${record.input.payment_profile} · ${record.input.device_info}`}
      action={<ActionBadge action={record.decision.action} large />}
    />

    <section className="decision-journey card">
      <div><span>v0.5 action</span><ActionBadge action={record.decision.v5_action} large /><small>risk {score(record.decision.linkrisk_risk)}/100</small></div>
      <ArrowRight size={26} />
      <div className="jane-step"><span>Mentalist deduction</span><b>{score(janeScore)}/100</b><small>{janeClueCount} independent clue families</small></div>
      <ArrowRight size={26} />
      <div><span>Final action</span><ActionBadge action={record.decision.action} large /><small>{titleCase(record.decision.routing_reason)}</small></div>
    </section>

    <section className="score-grid">
      <ScorePanel label="Transaction model" value={record.decision.baseline_risk} description="Raw baseline risk score" tone="red" />
      <ScorePanel label="v0.5 risk" value={record.decision.linkrisk_risk} description="Transaction + trusted memory" tone="amber" />
      <ScorePanel label="Mentalist" value={mentalist?.score} description="Present-tense evidence ranking" tone="purple" />
    </section>

    <JaneEscalationPanel record={record} preview={preview} onUpdated={onRecordUpdate} />

    <section className="investigation-grid">
      <div className="card case-evidence-card">
        <div className="card-heading"><div><h2>Patrick Jane — case file</h2><p>Independent evidence families; clue count is a safety gate, not a verdict.</p></div><span className="proactive-label"><Sparkles size={15} />No fraud-label input</span></div>
        <div className="evidence-grid">
          {Object.entries(clueMeta).map(([key, meta]) => <EvidenceCard key={key} active={!!evidenceClues[key]} label={meta.label} description={meta.description} icon={meta.icon} />)}
        </div>
        <div className="case-explanation"><BrainCircuit size={22} /><div><b>{titleCase(record.case_file.routing_reason)}</b><p>{record.case_file.explanation}</p></div></div>
      </div>

      <aside className="card decision-panel">
        <div className="card-heading"><div><h2>Decision controls</h2><p>Point-in-time analyst workflow</p></div></div>
        <div className="decision-summary"><span>Current action</span><ActionBadge action={record.decision.action} large /></div>
        <div className="history-summary"><Database size={20} /><div><b>{record.case_file.trusted_fraud_evidence_present ? 'Matured fraud evidence present' : 'No confirmed fraud required'}</b><span>{record.case_file.trusted_history_channels} history channels · {record.case_file.trusted_fraud_channels} fraud channels</span></div></div>
        <p className="principle-copy">Past fraud is evidence, not guilt. Mentalist can form a case from current behavioral evidence alone.</p>
        <div className="decision-actions">
          <button disabled={preview} onClick={() => onAdjudicate('legitimate')}><Check size={18} />Confirm legitimate</button>
          <button disabled={preview} onClick={() => onAdjudicate('fraud')}><AlertTriangle size={18} />Confirm fraud</button>
          <button disabled={preview} onClick={onAdvance}><Clock3 size={18} />Advance 72h</button>
        </div>
        {preview && <span className="preview-warning">Create a live payment to enable adjudication.</span>}
      </aside>
    </section>

    <section className="investigation-links">
      <button onClick={() => onNavigate('network')}><Network size={20} /><div><b>Open relationship network</b><span>Inspect the causal neighborhood</span></div><ChevronRight /></button>
      <button onClick={() => onNavigate('models')}><BrainCircuit size={20} /><div><b>Inspect model layers</b><span>See how each layer contributes</span></div><ChevronRight /></button>
    </section>
  </main>
}

function FilterBar({
  actionFilter,
  onActionFilter,
  minClues,
  onMinClues,
  onRefresh,
}: {
  actionFilter: 'ALL' | Action
  onActionFilter: (value: 'ALL' | Action) => void
  minClues: number
  onMinClues: (value: number) => void
  onRefresh: () => void
}) {
  return <div className="filter-bar">
    <div className="segmented">
      {(['ALL', 'ALLOW', 'VERIFY', 'REVIEW'] as const).map((value) => <button className={actionFilter === value ? 'active' : ''} onClick={() => onActionFilter(value)} key={value}>{value}</button>)}
    </div>
    <label>Minimum clues<select value={minClues} onChange={(e) => onMinClues(Number(e.target.value))}><option value={0}>Any</option><option value={1}>1+</option><option value={2}>2+</option><option value={3}>3+</option></select></label>
    <button className="ghost-button" onClick={onRefresh}><RefreshCw size={17} />Refresh</button>
  </div>
}

function LiveFeedPage({ feed, onOpen, onRefresh }: { feed: FeedItem[]; onOpen: (item: FeedItem) => void; onRefresh: () => void }) {
  const [actionFilter, setActionFilter] = useState<'ALL' | Action>('ALL')
  const [minClues, setMinClues] = useState(0)
  const filtered = useMemo(() => feed.filter((item) => (actionFilter === 'ALL' || item.action === actionFilter) && item.clue_count >= minClues), [feed, actionFilter, minClues])
  return <main className="content">
    <SectionHeader eyebrow="Operations" title="Live risk feed" description="Filter, inspect and open any point-in-time LinkRisk decision." />
    <FilterBar actionFilter={actionFilter} onActionFilter={setActionFilter} minClues={minClues} onMinClues={setMinClues} onRefresh={onRefresh} />
    <div className="card large-table-card"><FeedTable items={filtered} onOpen={onOpen} /></div>
  </main>
}

function GraphCanvas({ record, showLabels }: { record: CaseRecord; showLabels: boolean }) {
  const nodes = record.network?.nodes ?? []
  const edges = record.network?.edges ?? []
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    const current = nodes.find((node) => node.kind === 'current') ?? nodes[0]
    if (current) map.set(current.id, { x: 50, y: 50 })
    const relations = nodes.filter((node) => node.kind === 'relation')
    relations.forEach((node, index) => {
      const angle = (index / Math.max(relations.length, 1)) * Math.PI * 2 - Math.PI / 2
      map.set(node.id, { x: 50 + 24 * Math.cos(angle), y: 50 + 24 * Math.sin(angle) })
    })
    const outer = nodes.filter((node) => node.id !== current?.id && node.kind !== 'relation')
    outer.forEach((node, index) => {
      const angle = (index / Math.max(outer.length, 1)) * Math.PI * 2 + 0.35
      map.set(node.id, { x: 50 + 42 * Math.cos(angle), y: 50 + 37 * Math.sin(angle) })
    })
    return map
  }, [nodes])

  return <div className="graph-canvas">
    {nodes.length === 0 ? <div className="empty-state">No relationship nodes for this transaction yet.</div> : <svg viewBox="0 0 100 100">
      {edges.map((edge, index) => {
        const source = positions.get(edge.source)
        const target = positions.get(edge.target)
        return source && target ? <line key={`${edge.source}-${edge.target}-${index}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null
      })}
      {nodes.map((node) => {
        const pos = positions.get(node.id)
        if (!pos) return null
        return <g key={node.id} className={`graph-node graph-${node.kind}`} transform={`translate(${pos.x} ${pos.y})`}>
          <circle r={node.kind === 'current' ? 6 : 4.6} />
          <circle className="node-core" r={node.kind === 'current' ? 2.3 : 1.7} />
          {showLabels && <text y={node.kind === 'current' ? 10 : 8}>{node.label.slice(0, 22)}</text>}
        </g>
      })}
    </svg>}
  </div>
}

function NetworkPage({ record, feed, onSelect }: { record: CaseRecord; feed: FeedItem[]; onSelect: (item: FeedItem) => void }) {
  const [showLabels, setShowLabels] = useState(true)
  return <main className="content">
    <SectionHeader eyebrow="Relationship intelligence" title="Causal network" description="Only relationships available before the selected transaction are shown." />
    <div className="toolbar card">
      <label>Transaction<select value={record.transaction_id} onChange={(e) => { const item = feed.find((entry) => entry.transaction_id === e.target.value); if (item) onSelect(item) }}>{feed.map((item) => <option key={item.transaction_id}>{item.transaction_id}</option>)}</select></label>
      <button className={`ghost-button ${showLabels ? 'active' : ''}`} onClick={() => setShowLabels((value) => !value)}><Eye size={17} />Labels {showLabels ? 'on' : 'off'}</button>
      <span className="toolbar-note"><ShieldCheck size={17} />Same-timestamp rows cannot see one another.</span>
    </div>
    <div className="card network-page-card">
      <div className="card-heading"><div><h2>{record.transaction_id}</h2><p>{record.network.nodes.length} nodes · {record.network.edges.length} edges</p></div>{!isNeutralRecord(record) && <ActionBadge action={record.decision.action} />}</div>
      <GraphCanvas record={record} showLabels={showLabels} />
      <div className="network-legend"><span><i className="current" />Current transaction</span><span><i className="relation" />Relationship context</span><span><i className="prior" />Prior transaction</span><span><i className="fraud" />Matured fraud</span></div>
    </div>
  </main>
}

function CasesPage({ feed, onOpen }: { feed: FeedItem[]; onOpen: (item: FeedItem) => void }) {
  const [onlyChanged, setOnlyChanged] = useState(false)
  const cases = useMemo(() => feed.filter((item) => !onlyChanged || item.action !== item.v5_action), [feed, onlyChanged])
  return <main className="content">
    <SectionHeader eyebrow="Case management" title="Cases" description="A clean queue of scored transactions and action changes." action={<button className={`ghost-button ${onlyChanged ? 'active' : ''}`} onClick={() => setOnlyChanged((value) => !value)}><Sparkles size={17} />{onlyChanged ? 'Showing changed actions' : 'Only action changes'}</button>} />
    <div className="case-list">
      {cases.map((item) => <button className="case-list-row card" key={item.transaction_id} onClick={() => onOpen(item)}>
        <div><span className="eyebrow">{item.transaction_id}</span><b>{item.profile}</b><small>{item.device}</small></div>
        <div><span>Amount</span><b>{amount(item.amount)}</b></div>
        <div><span>v0.5 → final</span><p><ActionBadge action={item.v5_action} /><ArrowRight size={16} /><ActionBadge action={item.action} /></p></div>
        <div><span>Jane</span><b>{score(item.jane_score)}/100</b><small>{item.clue_count} clues</small></div>
        <ChevronRight size={21} />
      </button>)}
      {cases.length === 0 && <div className="card empty-state">No cases match this filter.</div>}
    </div>
  </main>
}

function ReportsPage({ overview }: { overview: OverviewPayload }) {
  const before = overview.validation.fraud_capture - overview.validation.fraud_capture_lift_pp / 100
  return <main className="content">
    <SectionHeader eyebrow="Development validation" title="Performance report" description="Development validation results only. The v1 chronological held-out test was evaluated once and is not reused for tuning." action={<span className="sealed-pill"><ShieldCheck size={18} />v1 final evaluated once</span>} />
    <section className="metric-grid three">
      <MetricCard icon={<ShieldCheck />} label="Stable v0.5 capture" value={pct(before, 2)} delta="baseline policy" note="Before Mentalist reallocation" />
      <MetricCard icon={<Sparkles />} label="Mentalist v1.0 capture" value={pct(overview.validation.fraud_capture, 2)} delta={`+${overview.validation.fraud_capture_lift_pp.toFixed(2)}pp`} note="Same intervention count" tone="purple" />
      <MetricCard icon={<UsersRound />} label="Legitimate friction" value={pct(overview.validation.legitimate_friction, 2)} delta={`${overview.validation.legitimate_friction_delta_pp.toFixed(2)}pp`} note="Reduced despite higher capture" tone="green" />
    </section>
    <div className="report-grid">
      <ValidationImpact overview={overview} />
      <div className="card report-story">
        <div className="card-heading"><div><h2>What changed</h2><p>One-for-one case reallocation</p></div></div>
        <div className="story-number"><strong>519</strong><span>novel Jane cases added</span></div>
        <div className="story-arrow"><ArrowRight size={22} /></div>
        <div className="story-number positive"><strong>50</strong><span>frauds added to investigation</span></div>
        <div className="story-number"><strong>519</strong><span>weak v0.5 VERIFY cases evicted</span></div>
        <div className="story-number positive"><strong>0</strong><span>frauds in the evicted set</span></div>
      </div>
    </div>
  </main>
}

function AlertsPage({ feed, onOpen }: { feed: FeedItem[]; onOpen: (item: FeedItem) => void }) {
  const [proactiveOnly, setProactiveOnly] = useState(false)
  const alerts = useMemo(() => feed.filter((item) => item.action !== 'ALLOW' && (!proactiveOnly || item.routing_reason === 'MENTALIST_PROACTIVE')), [feed, proactiveOnly])
  return <main className="content">
    <SectionHeader eyebrow="Attention queue" title="Alerts" description="VERIFY and REVIEW decisions that currently require intervention." action={<button className={`ghost-button ${proactiveOnly ? 'active' : ''}`} onClick={() => setProactiveOnly((value) => !value)}><Sparkles size={17} />{proactiveOnly ? 'Proactive only' : 'Filter proactive'}</button>} />
    <div className="alert-grid">
      {alerts.map((item) => <button className={`card alert-card alert-${item.action.toLowerCase()}`} key={item.transaction_id} onClick={() => onOpen(item)}>
        <span className="alert-icon">{item.action === 'REVIEW' ? <ShieldAlert size={23} /> : <ShieldCheck size={23} />}</span>
        <div><span className="eyebrow">{item.action}</span><h2>{item.transaction_id}</h2><p>{titleCase(item.routing_reason)}</p></div>
        <div className="alert-metrics"><span>Jane <b>{score(item.jane_score)}</b></span><span>Clues <b>{item.clue_count}</b></span></div>
        <ChevronRight />
      </button>)}
      {alerts.length === 0 && <div className="card empty-state">No visible alerts match this filter.</div>}
    </div>
  </main>
}

function ModelsPage({ record }: { record: CaseRecord }) {
  const [activeLayer, setActiveLayer] = useState<'baseline' | 'memory' | 'mentalist'>('mentalist')
  const hasSelection = !isNeutralRecord(record)
  const details = {
    baseline: {
      title: 'Transaction baseline',
      score: hasSelection ? record.decision.baseline_risk : null,
      copy: 'Scores the incoming transaction from the frozen IEEE-CIS-compatible feature adapter. This is a risk score, not a calibrated probability.',
      icon: <Gauge size={28} />,
    },
    memory: {
      title: 'Trusted-memory specialist',
      score: hasSelection ? record.decision.linkrisk_risk : null,
      copy: 'Uses causal relationship structure plus delayed adjudicated feedback. Historical fraud remains soft evidence and never forces a verdict by itself.',
      icon: <Database size={28} />,
    },
    mentalist: {
      title: 'Mentalist investigator',
      score: hasSelection ? record.mentalist?.score : null,
      copy: 'Jane ranks present-tense velocity, behavioral change, coordination and reuse/churn only when the cheap evidence gate finds an eligible case. Confirmed-fraud labels are not Mentalist inputs.',
      icon: <BrainCircuit size={28} />,
    },
  }
  const detail = details[activeLayer]
  return <main className="content">
    <SectionHeader eyebrow="Decision architecture" title="Model layers" description="Separate layers, selective Jane inference, and explicit capacity control — no arbitrary score averaging or hidden action override." />
    <div className="model-tabs">
      {(['baseline', 'memory', 'mentalist'] as const).map((layer) => <button className={activeLayer === layer ? 'active' : ''} onClick={() => setActiveLayer(layer)} key={layer}>{details[layer].icon}<span>{details[layer].title}</span></button>)}
    </div>
    <div className="card model-detail">
      <div className="model-hero"><span>{detail.icon}</span><div><span className="eyebrow">Selected layer</span><h2>{detail.title}</h2><p>{detail.copy}</p></div><strong>{score(detail.score)}<small>{hasSelection ? '/100' : 'No active case'}</small></strong></div>
      <div className="architecture-flow architecture-v2">
        <div><Gauge /><b>Transaction model</b><span>raw risk</span></div><ArrowRight />
        <div><Database /><b>v0.5 memory</b><span>trusted history</span></div><ArrowRight />
        <div className="gate"><Radar /><b>Evidence gate</b><span>ordinary → bypass · eligible → Jane</span></div><ArrowRight />
        <div><BrainCircuit /><b>Mentalist / Jane</b><span>selective proactive clues</span></div><ArrowRight />
        <div className="final"><ShieldCheck /><b>Cost-aware v2 router</b><span>frozen thresholds · live capacity</span></div>
      </div>
      <div className="architecture-note"><Sparkles size={16} /><span>Ordinary cases bypass Jane and go straight to routing. REVIEW remains mandatory; the live controller targets 6% sustained intervention with a 1% Mentalist reserve.</span></div>
    </div>
  </main>
}

function DataPage({ overview, feed, engineReady, preview }: { overview: OverviewPayload; feed: FeedItem[]; engineReady: boolean; preview: boolean }) {
  return <main className="content">
    <SectionHeader eyebrow="Runtime data" title="Session data" description="Operational state only. Raw IEEE-CIS training data is not exposed through the product UI." />
    <section className="metric-grid four">
      <MetricCard icon={<Activity />} label="Session transactions" value={feed.length.toString()} delta={preview ? 'preview' : 'live'} note="Current browser/API session" />
      <MetricCard icon={<ShieldCheck />} label="Engine assets" value={engineReady ? 'READY' : 'MISSING'} delta={engineReady ? 'loaded locally' : 'preview fallback'} note="Frozen artifact bundle" tone="green" />
      <MetricCard icon={<Clock3 />} label="Simulation clock" value={`${Math.round(overview.live.clock / 3600)}h`} delta="causal time" note="Used for delayed feedback" tone="blue" />
      <MetricCard icon={<Database />} label="Dataset adapter" value="IEEE-CIS" delta="compatible" note="Masked fields are not literal identities" tone="purple" />
    </section>
    <div className="card data-contract">
      <div className="card-heading"><div><h2>Runtime contract</h2><p>What the product can and cannot claim</p></div></div>
      <div className="contract-grid">
        <div><Check /><b>Point-in-time causal features</b><span>Future rows and same-timestamp peers do not leak into the current decision.</span></div>
        <div><Check /><b>Delayed trusted feedback</b><span>Adjudicated outcomes become usable only after the frozen delay and actual recording time.</span></div>
        <div><Check /><b>Proactive Mentalist channel</b><span>Confirmed-fraud history is not an input to the Mentalist model.</span></div>
        <div><AlertTriangle /><b>Evaluation boundary</b><span>Development validation was reused during development; the v1 final held-out partition was evaluated once and is not reused for tuning.</span></div>
      </div>
    </div>
  </main>
}

function SettingsPage({
  presentationMode,
  onTogglePresentation,
  preview,
  onReset,
}: {
  presentationMode: boolean
  onTogglePresentation: () => void
  preview: boolean
  onReset: () => void
}) {
  const [showTechnicalLabels, setShowTechnicalLabels] = useState(true)
  return <main className="content">
    <SectionHeader eyebrow="Product preferences" title="Settings" description="Demo-friendly presentation controls and session management." />
    <div className="settings-grid">
      <div className="card setting-card"><MonitorUp size={26} /><div><h2>Buildathon demo view</h2><p>Larger typography, more whitespace and fewer low-value labels for screen recording.</p></div><button className={`toggle ${presentationMode ? 'on' : ''}`} onClick={onTogglePresentation}><i /></button></div>
      <div className="card setting-card"><Eye size={26} /><div><h2>Technical labels</h2><p>Keep policy names and model terminology visible for technical judging.</p></div><button className={`toggle ${showTechnicalLabels ? 'on' : ''}`} onClick={() => setShowTechnicalLabels((value) => !value)}><i /></button></div>
      <div className="card setting-card danger-setting"><RefreshCw size={26} /><div><h2>Reset live session</h2><p>Clear in-memory transactions and adjudications. Frozen models and thresholds are unchanged.</p></div><button className="danger-button" disabled={preview} onClick={onReset}>Reset session</button></div>
    </div>
  </main>
}

function NewPaymentModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (record: CaseRecord) => void }) {
  const [form, setForm] = useState({
    amount: '2500',
    payment_profile: 'PROFILE-A',
    device_info: 'Windows / Chrome',
    receiver_domain: 'merchant.example',
    browser_context: 'chrome-win',
    product_code: 'W',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!open) return null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const record = await api.createTransaction({
        amount: Number(form.amount),
        payment_profile: form.payment_profile,
        device_info: form.device_info,
        receiver_domain: form.receiver_domain,
        browser_context: form.browser_context,
        product_code: form.product_code,
        payer_domain: 'gmail.com',
        device_type: 'desktop',
        card_network: 'visa',
        card_type: 'debit',
      })
      onCreated(record)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return <div className="modal-backdrop" onMouseDown={onClose}>
    <form className="modal card" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}>
      <div className="modal-header"><div><span className="eyebrow">Live engine</span><h2>Score a new payment</h2><p>The event is sent to the real frozen LinkRisk runtime.</p></div><button type="button" className="icon-button" onClick={onClose}><X size={20} /></button></div>
      <div className="form-grid">
        <label>Amount<input required type="number" min="0" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
        <label>Payment profile<input required value={form.payment_profile} onChange={(e) => setForm({ ...form, payment_profile: e.target.value })} /></label>
        <label>Device context<input required value={form.device_info} onChange={(e) => setForm({ ...form, device_info: e.target.value })} /></label>
        <label>Receiver domain<input required value={form.receiver_domain} onChange={(e) => setForm({ ...form, receiver_domain: e.target.value })} /></label>
        <label>Browser context<input required value={form.browser_context} onChange={(e) => setForm({ ...form, browser_context: e.target.value })} /></label>
        <label>Product code<select value={form.product_code} onChange={(e) => setForm({ ...form, product_code: e.target.value })}><option>W</option><option>C</option><option>H</option><option>R</option><option>S</option></select></label>
      </div>
      {error && <div className="form-error"><AlertTriangle size={18} />{error}</div>}
      <div className="modal-actions"><button type="button" className="ghost-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy}>{busy ? 'Scoring…' : 'Run LinkRisk'}<ArrowRight size={17} /></button></div>
    </form>
  </div>
}

export default function App() {
  const [page, setPage] = useState<Page>('overview')
  const [overview, setOverview] = useState<OverviewPayload>(previewOverview)
  const [feed, setFeed] = useState<FeedItem[]>(previewFeed)
  const [selected, setSelected] = useState<CaseRecord>(previewCase)
  const [preview, setPreview] = useState(true)
  const [engineReady, setEngineReady] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [searchValue, setSearchValue] = useState('')
  const [presentationMode, setPresentationMode] = useState(true)
  const [alertsOpen, setAlertsOpen] = useState(false)

  const visibleFeed = useMemo(() => {
    const query = searchValue.trim().toLowerCase()
    if (!query) return feed
    return feed.filter((item) => [item.transaction_id, item.profile, item.device, item.action, item.routing_reason].some((value) => String(value).toLowerCase().includes(query)))
  }, [feed, searchValue])

  const alertCount = useMemo(() => feed.filter((item) => item.action !== 'ALLOW').length, [feed])

  const refreshAll = async () => {
    try {
      const [overviewPayload, healthPayload, transactionPayload] = await Promise.all([
        api.overview(),
        api.health(),
        api.transactions(),
      ])
      setOverview(overviewPayload)
      setEngineReady(healthPayload.asset_status.ready)
      if (transactionPayload.items.length > 0) {
        setFeed(transactionPayload.items)
        setPreview(false)
        const currentStillExists = transactionPayload.items.some((item) => item.transaction_id === selected.transaction_id)
        const target = currentStillExists ? selected.transaction_id : transactionPayload.items[transactionPayload.items.length - 1].transaction_id
        setSelected(await api.transaction(target))
      } else {
        setFeed([])
        setSelected(previewCase)
      }
    } catch {
      // Keep the explicitly-labelled preview session available while the API is unavailable.
    }
  }

  useEffect(() => { void refreshAll() }, [])

  const openItem = async (item: FeedItem, targetPage: Page = 'investigations') => {
    if (preview && previewFeed.some((entry) => entry.transaction_id === item.transaction_id)) {
      setSelected(makePreviewRecord(item))
      setPage(targetPage)
      return
    }
    try {
      setSelected(await api.transaction(item.transaction_id))
      setPreview(false)
      setPage(targetPage)
    } catch {
      setSelected(makePreviewRecord(item))
      setPage(targetPage)
    }
  }

  const onCreated = (record: CaseRecord) => {
    setSelected(record)
    setPreview(false)
    setEngineReady(true)
    setPage('investigations')
    void refreshAll()
  }

  const adjudicate = async (outcome: 'fraud' | 'legitimate') => {
    try {
      setSelected(await api.adjudicate(selected.transaction_id, outcome))
    } catch {
      // API error remains visible through backend logs; preview controls are disabled.
    }
  }

  const advance = async () => {
    try {
      await api.advance(72 * 60 * 60)
      setSelected(await api.transaction(selected.transaction_id))
      const nextOverview = await api.overview()
      setOverview(nextOverview)
    } catch {
      // no-op in preview
    }
  }

  const reset = async () => {
    try {
      await api.reset()
      setFeed([])
      setOverview(await api.overview())
      setSelected(previewCase)
      setPage('overview')
    } catch {
      // Reset is disabled in preview.
    }
  }

  const pageContent = (() => {
    switch (page) {
      case 'overview':
        return <OverviewPage overview={overview} feed={visibleFeed} sessionFeed={feed} selected={selected} onOpen={(item) => void openItem(item)} onNavigate={setPage} />
      case 'investigations':
        return <InvestigationPage record={selected} preview={preview} onBack={() => setPage('overview')} onAdjudicate={(outcome) => void adjudicate(outcome)} onAdvance={() => void advance()} onNavigate={setPage} onRecordUpdate={setSelected} />
      case 'feed':
        return <LiveFeedPage feed={visibleFeed} onOpen={(item) => void openItem(item)} onRefresh={() => void refreshAll()} />
      case 'network':
        return <NetworkPage record={selected} feed={visibleFeed} onSelect={(item) => void openItem(item, 'network')} />
      case 'cases':
        return <CasesPage feed={visibleFeed} onOpen={(item) => void openItem(item)} />
      case 'reports':
        return <ReportsPage overview={overview} />
      case 'alerts':
        return <AlertsPage feed={visibleFeed} onOpen={(item) => void openItem(item)} />
      case 'models':
        return <ModelsPage record={selected} />
      case 'data':
        return <DataPage overview={overview} feed={visibleFeed} engineReady={engineReady} preview={preview} />
      case 'settings':
        return <SettingsPage presentationMode={presentationMode} onTogglePresentation={() => setPresentationMode((value) => !value)} preview={preview} onReset={() => void reset()} />
      default:
        return null
    }
  })()

  return <div className={`app-shell ${presentationMode ? 'presentation-mode' : ''}`}>
    <Sidebar page={page} onNavigate={(next) => { setAlertsOpen(false); setPage(next) }} />
    <div className="workspace">
      <Topbar
        preview={preview}
        engineReady={engineReady}
        searchValue={searchValue}
        onSearch={setSearchValue}
        onNewPayment={() => setModalOpen(true)}
        presentationMode={presentationMode}
        onTogglePresentation={() => setPresentationMode((value) => !value)}
        alertCount={alertCount}
        alertsOpen={alertsOpen}
        onToggleAlerts={() => setAlertsOpen((value) => !value)}
      />
      {pageContent}
    </div>
    <NewPaymentModal open={modalOpen} onClose={() => setModalOpen(false)} onCreated={onCreated} />
  </div>
}
