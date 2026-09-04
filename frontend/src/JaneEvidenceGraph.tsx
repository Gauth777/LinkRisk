import { useEffect, useMemo, useState } from 'react'
import { Check, Eye, GitBranch, Network, ShieldCheck, Sparkles } from 'lucide-react'
import type { CaseRecord, NetworkEdge, NetworkNode } from './types'
import './jane-evidence-graph.css'

type SelectedEvidence =
  | { type: 'node'; nodeId: string }
  | { type: 'edge'; edgeIndex: number }
  | null

const clueLabels: Record<string, string> = {
  velocity: 'Velocity',
  behavior_change: 'Behavior change',
  coordination: 'Coordination',
  reuse_churn: 'Reuse / churn',
}

const relationClueSupport: Record<string, string[]> = {
  profile: ['velocity', 'behavior_change', 'reuse_churn'],
  device: ['reuse_churn'],
  receiver: ['reuse_churn'],
  device_context: ['velocity', 'behavior_change', 'coordination', 'reuse_churn'],
}

const relationDescriptions: Record<string, string> = {
  profile: 'Prior payments sharing the same masked payment-profile composite.',
  device: 'Prior payments sharing the same strong device view.',
  receiver: 'Prior payments sharing the same receiver-domain view.',
  device_context: 'Prior payments sharing the same device/browser context.',
}

const nodeKindLabels: Record<string, string> = {
  current: 'Current transaction',
  relation: 'Relationship context',
  prior: 'Prior transaction',
  pending: 'Pending outcome',
  fraud: 'Matured confirmed fraud',
  legitimate: 'Matured confirmed legitimate',
}

const relationChannel = (node?: NetworkNode | null) => {
  if (!node?.id.startsWith('rel:')) return null
  return node.id.slice(4)
}

const relationForEdge = (edge: NetworkEdge, nodeMap: Map<string, NetworkNode>) => {
  const source = nodeMap.get(edge.source)
  const target = nodeMap.get(edge.target)
  return source?.kind === 'relation' ? source : target?.kind === 'relation' ? target : null
}

const supportedActiveClues = (node: NetworkNode | null | undefined, activeClues: string[]) => {
  const channel = relationChannel(node)
  if (!channel) return []
  return (relationClueSupport[channel] ?? []).filter((clue) => activeClues.includes(clue))
}

function EvidenceInspector({
  record,
  selected,
  nodeMap,
  activeClues,
}: {
  record: CaseRecord
  selected: SelectedEvidence
  nodeMap: Map<string, NetworkNode>
  activeClues: string[]
}) {
  if (!selected) {
    return <aside className="jane-evidence-inspector empty">
      <Eye size={22} />
      <div>
        <span className="eyebrow">Evidence inspector</span>
        <b>Select a node or connection</b>
        <p>Inspect the causal relationship context Jane could observe at transaction time.</p>
      </div>
    </aside>
  }

  if (selected.type === 'node') {
    const node = nodeMap.get(selected.nodeId)
    if (!node) return null
    const channel = relationChannel(node)
    const neighborIds = record.network.edges.flatMap((edge) => {
      if (edge.source === node.id) return [edge.target]
      if (edge.target === node.id) return [edge.source]
      return []
    })
    const neighbors = neighborIds.map((id) => nodeMap.get(id)).filter((value): value is NetworkNode => !!value)
    const priorNeighbors = neighbors.filter((neighbor) => neighbor.kind !== 'current' && neighbor.kind !== 'relation')
    const fraudNeighbors = priorNeighbors.filter((neighbor) => neighbor.kind === 'fraud')
    const supportingClues = supportedActiveClues(node, activeClues)

    return <aside className="jane-evidence-inspector">
      <div className="jane-evidence-inspector-head">
        <span className={`jane-evidence-kind kind-${node.kind}`}>{nodeKindLabels[node.kind] ?? node.kind}</span>
        {supportingClues.length > 0 && <span className="jane-evidence-support"><Sparkles size={13} />Supports Jane evidence</span>}
      </div>
      <h3>{node.label}</h3>
      <p>{channel ? relationDescriptions[channel] ?? node.detail : node.detail ?? 'Observed in the causal transaction snapshot.'}</p>

      {node.kind === 'current' && <div className="jane-evidence-facts">
        <span><small>Amount</small><b>₹{new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(record.input.amount)}</b></span>
        <span><small>Action</small><b>{record.decision.action}</b></span>
        <span><small>Graph confidence</small><b>{record.decision.graph_confidence == null ? '—' : `${Math.round(record.decision.graph_confidence * 100)}/100`}</b></span>
      </div>}

      {node.kind === 'relation' && <div className="jane-evidence-facts">
        <span><small>Prior matches shown</small><b>{priorNeighbors.length}</b></span>
        <span><small>Matured fraud among shown</small><b>{fraudNeighbors.length}</b></span>
        <span><small>Channel</small><b>{channel?.replaceAll('_', ' ') ?? 'relationship'}</b></span>
      </div>}

      {supportingClues.length > 0 && <div className="jane-why-box">
        <span>Why Jane notices this</span>
        <p>This observed relationship is consistent with the active <b>{supportingClues.map((clue) => clueLabels[clue] ?? clue).join(', ')}</b> evidence {supportingClues.length === 1 ? 'family' : 'families'}.</p>
      </div>}

      {node.kind === 'relation' && <small className="jane-evidence-caveat">Relationship support is explanatory context, not per-edge model attribution.</small>}
    </aside>
  }

  const edge = record.network.edges[selected.edgeIndex]
  if (!edge) return null
  const source = nodeMap.get(edge.source)
  const target = nodeMap.get(edge.target)
  const relation = relationForEdge(edge, nodeMap)
  const channel = relationChannel(relation)
  const supportingClues = supportedActiveClues(relation, activeClues)

  return <aside className="jane-evidence-inspector">
    <div className="jane-evidence-inspector-head">
      <span className="jane-evidence-kind kind-edge">Observed connection</span>
      {supportingClues.length > 0 && <span className="jane-evidence-support"><Sparkles size={13} />Supports Jane evidence</span>}
    </div>
    <h3>{source?.label ?? edge.source} → {target?.label ?? edge.target}</h3>
    <p>{channel
      ? `This connection exists because the transaction participates in the ${relation?.label.toLowerCase()} relationship available before the selected payment.`
      : 'This connection was present in the transaction-time causal network.'}</p>
    <div className="jane-evidence-facts">
      <span><small>Relationship</small><b>{relation?.label ?? 'Causal link'}</b></span>
      <span><small>Source</small><b>{nodeKindLabels[source?.kind ?? ''] ?? source?.kind ?? '—'}</b></span>
      <span><small>Target</small><b>{nodeKindLabels[target?.kind ?? ''] ?? target?.kind ?? '—'}</b></span>
    </div>
    {supportingClues.length > 0 && <div className="jane-why-box">
      <span>Why Jane notices this</span>
      <p>The shared context is consistent with Jane’s active <b>{supportingClues.map((clue) => clueLabels[clue] ?? clue).join(', ')}</b> evidence.</p>
    </div>}
    <small className="jane-evidence-caveat">The UI does not claim that this individual edge alone caused Jane’s score.</small>
  </aside>
}

export function JaneEvidenceGraph({
  record,
  clueFamilies,
}: {
  record: CaseRecord
  clueFamilies: Record<string, boolean>
}) {
  const [selected, setSelected] = useState<SelectedEvidence>(null)
  const [showLabels, setShowLabels] = useState(true)
  const nodes = record.network?.nodes ?? []
  const edges = record.network?.edges ?? []
  const activeClues = useMemo(() => Object.entries(clueFamilies).filter(([, active]) => active).map(([family]) => family), [clueFamilies])
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])

  useEffect(() => {
    setSelected(null)
  }, [record.transaction_id])

  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    const current = nodes.find((node) => node.kind === 'current') ?? nodes[0]
    if (current) map.set(current.id, { x: 50, y: 50 })

    const relations = nodes.filter((node) => node.kind === 'relation')
    relations.forEach((node, index) => {
      const angle = (index / Math.max(relations.length, 1)) * Math.PI * 2 - Math.PI / 2
      map.set(node.id, { x: 50 + 23 * Math.cos(angle), y: 50 + 23 * Math.sin(angle) })
    })

    const outer = nodes.filter((node) => node.id !== current?.id && node.kind !== 'relation')
    outer.forEach((node, index) => {
      const angle = (index / Math.max(outer.length, 1)) * Math.PI * 2 + 0.35
      map.set(node.id, { x: 50 + 41 * Math.cos(angle), y: 50 + 37 * Math.sin(angle) })
    })
    return map
  }, [nodes])

  const relationHasJaneSupport = (node: NetworkNode) => supportedActiveClues(node, activeClues).length > 0

  return <div className="jane-evidence-shell">
    <div className="jane-evidence-toolbar">
      <div>
        <span className="eyebrow">Causal evidence map</span>
        <b>What relationships were visible when Jane investigated?</b>
        <small>Only prior-time context from the frozen transaction snapshot is shown.</small>
      </div>
      <div className="jane-evidence-toolbar-actions">
        <span><ShieldCheck size={14} />No future rows</span>
        <button onClick={() => setShowLabels((value) => !value)}><Eye size={15} />Labels {showLabels ? 'on' : 'off'}</button>
      </div>
    </div>

    <div className="jane-evidence-clues">
      {Object.entries(clueFamilies).map(([family, active]) => <span className={active ? 'active' : ''} key={family}>
        {active && <Check size={13} />}{clueLabels[family] ?? family.replaceAll('_', ' ')}
      </span>)}
    </div>

    <div className="jane-evidence-layout">
      <div className="jane-evidence-canvas">
        {nodes.length === 0 ? <div className="jane-evidence-empty"><Network size={24} /><b>No prior relationship context</b><span>This transaction has no causal neighbors in the current snapshot.</span></div> : <svg viewBox="0 0 100 100" role="img" aria-label="Interactive causal relationship network">
          {edges.map((edge, index) => {
            const source = positions.get(edge.source)
            const target = positions.get(edge.target)
            if (!source || !target) return null
            const relation = relationForEdge(edge, nodeMap)
            const supportsJane = relation ? relationHasJaneSupport(relation) : false
            const isSelected = selected?.type === 'edge' && selected.edgeIndex === index
            return <line
              key={`${edge.source}-${edge.target}-${index}`}
              className={`${supportsJane ? 'jane-supported' : ''} ${isSelected ? 'selected' : ''}`}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              onClick={() => setSelected({ type: 'edge', edgeIndex: index })}
            />
          })}
          {nodes.map((node) => {
            const pos = positions.get(node.id)
            if (!pos) return null
            const supportsJane = node.kind === 'relation' && relationHasJaneSupport(node)
            const isSelected = selected?.type === 'node' && selected.nodeId === node.id
            return <g
              key={node.id}
              className={`jane-graph-node jane-graph-${node.kind} ${supportsJane ? 'jane-supported' : ''} ${isSelected ? 'selected' : ''}`}
              transform={`translate(${pos.x} ${pos.y})`}
              onClick={() => setSelected({ type: 'node', nodeId: node.id })}
            >
              {supportsJane && <circle className="jane-node-halo" r={node.kind === 'current' ? 8 : 6.7} />}
              <circle r={node.kind === 'current' ? 6 : 4.7} />
              <circle className="jane-node-core" r={node.kind === 'current' ? 2.3 : 1.8} />
              {showLabels && <text y={node.kind === 'current' ? 10 : 8.5}>{node.label.slice(0, 24)}</text>}
            </g>
          })}
        </svg>}
      </div>

      <EvidenceInspector record={record} selected={selected} nodeMap={nodeMap} activeClues={activeClues} />
    </div>

    <div className="jane-evidence-legend">
      <span><i className="legend-current" />Current payment</span>
      <span><i className="legend-relation" />Relationship</span>
      <span><i className="legend-prior" />Prior payment</span>
      <span><i className="legend-fraud" />Matured fraud</span>
      <span className="legend-jane"><Sparkles size={13} />Supports active Jane clue</span>
      <small><GitBranch size={13} />Observed evidence ≠ single-edge attribution</small>
    </div>
  </div>
}
