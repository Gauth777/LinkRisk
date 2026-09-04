export type Action = 'ALLOW' | 'VERIFY' | 'REVIEW'

export type NetworkNode = {
  id: string
  label: string
  kind: string
  detail?: string
}

export type NetworkEdge = { source: string; target: string }

export type CaseRecord = {
  transaction_id: string
  transaction_time: number
  input: {
    amount: number
    payment_profile: string
    device_info: string
    receiver_domain: string
    browser_context: string
    product_code?: string
    payer_domain?: string
    device_type?: string
    card_network?: string
    card_type?: string
  }
  decision: {
    baseline_risk: number
    linkrisk_risk: number
    graph_confidence?: number
    v5_action: Action
    action: Action
    routing_reason: string
    policy_version?: string
  }
  mentalist?: {
    score: number
    score_threshold: number
    clue_count: number
    min_clue_families: number
    clue_families: Record<string, boolean>
    promoted_by_jane: boolean
    displaced_v5_verify: boolean
    uses_confirmed_fraud_as_input: boolean
  } | null
  analyst_jane?: {
    requested: boolean
    invocation_mode: string
    score: number
    score_threshold: number
    clue_count: number
    min_clue_families: number
    clue_families: Record<string, boolean>
    candidate: boolean
    corroborates_intervention: boolean
    assessment_label: string
    original_action: Action
    action_changed: boolean
    capacity_consumed: boolean
    uses_confirmed_fraud_as_input: boolean
    evidence_time: number
    scientific_note: string
  } | null
  case_file: {
    v5_action: Action
    final_action: Action
    action_changed: boolean
    routing_reason: string
    explanation: string
    trusted_history_channels: number
    trusted_fraud_channels: number
    trusted_fraud_evidence_present: boolean
  }
  network: { nodes: NetworkNode[]; edges: NetworkEdge[] }
  adjudication?: {
    outcome: string | null
    state: string
    seconds_remaining?: number | null
  }
}

export type FeedItem = {
  transaction_id: string
  transaction_time: number
  amount: number
  profile: string
  device: string
  baseline_risk: number
  v5_risk: number
  jane_score: number | null
  clue_count: number
  v5_action: Action
  action: Action
  routing_reason: string
}

export type OverviewPayload = {
  validation: {
    fraud_capture: number
    fraud_capture_lift_pp: number
    legitimate_friction: number
    legitimate_friction_delta_pp: number
    intervention_share: number
    mentalist_novel_cases: number
    mentalist_frauds_added: number
    v5_review_precision: number
    held_out_test_status: string
  }
  live: {
    transactions: number
    allow: number
    verify: number
    review: number
    clock: number
  }
  engine_ready: boolean
}
