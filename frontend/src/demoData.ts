import type { CaseRecord, FeedItem, OverviewPayload } from './types'

export const previewOverview: OverviewPayload = {
  validation: {
    fraud_capture: 0.4421,
    fraud_capture_lift_pp: 1.64,
    legitimate_friction: 0.0464,
    legitimate_friction_delta_pp: -0.06,
    intervention_share: 0.06,
    mentalist_novel_cases: 519,
    mentalist_frauds_added: 50,
    v5_review_precision: 0.5336,
    held_out_test_status: 'v1_final_opened_once',
  },
  live: { transactions: 0, allow: 0, verify: 0, review: 0, clock: 0 },
  engine_ready: false,
}

/* Live Session must never bootstrap with illustrative transactions. */
export const previewFeed: FeedItem[] = []

/* Curated examples are isolated to the explicitly labeled Demo Scenarios mode. */
export const demoScenarioFeed: FeedItem[] = [
  {
    transaction_id: 'TX-8F2D7K1E', transaction_time: 15300, amount: 8750,
    profile: 'PROFILE-A', device: 'Chrome / Windows', baseline_risk: .41,
    v5_risk: .39, jane_score: .82, clue_count: 3, v5_action: 'ALLOW',
    action: 'VERIFY', routing_reason: 'MENTALIST_CAPACITY_AUTHORIZED',
  },
  {
    transaction_id: 'TX-7H9J3L0B', transaction_time: 15000, amount: 83.45,
    profile: 'PROFILE-B', device: 'Safari / iOS', baseline_risk: .12,
    v5_risk: .12, jane_score: null, clue_count: 0, v5_action: 'ALLOW',
    action: 'ALLOW', routing_reason: 'MENTALIST_BYPASSED_EVIDENCE_GATE',
  },
  {
    transaction_id: 'TX-1K3M9P2Q', transaction_time: 14700, amount: 599,
    profile: 'PROFILE-C', device: 'Chrome / Android', baseline_risk: .69,
    v5_risk: .79, jane_score: null, clue_count: 1, v5_action: 'VERIFY',
    action: 'VERIFY', routing_reason: 'V5_VERIFY_CAPACITY_AUTHORIZED',
  },
  {
    transaction_id: 'TX-6G7H2N4R', transaction_time: 14400, amount: 2980,
    profile: 'PROFILE-D', device: 'Firefox / Windows', baseline_risk: .91,
    v5_risk: .93, jane_score: null, clue_count: 2, v5_action: 'REVIEW',
    action: 'REVIEW', routing_reason: 'V5_REVIEW_MANDATORY',
  },
  {
    transaction_id: 'TX-9P8Q1S7T', transaction_time: 14100, amount: 42,
    profile: 'PROFILE-E', device: 'Safari / macOS', baseline_risk: .08,
    v5_risk: .08, jane_score: null, clue_count: 0, v5_action: 'ALLOW',
    action: 'ALLOW', routing_reason: 'MENTALIST_BYPASSED_EVIDENCE_GATE',
  },
]

/* Neutral selection while a live session contains no transactions. */
export const previewCase: CaseRecord = {
  transaction_id: 'NO-LIVE-TRANSACTION',
  transaction_time: 0,
  input: {
    amount: 0,
    payment_profile: 'No live transaction selected',
    device_info: '—',
    receiver_domain: '—',
    browser_context: '—',
    product_code: '—', payer_domain: '—', device_type: '—',
    card_network: '—', card_type: '—',
  },
  decision: {
    baseline_risk: 0,
    linkrisk_risk: 0,
    graph_confidence: 0,
    v5_action: 'ALLOW',
    action: 'ALLOW',
    routing_reason: 'NO_LIVE_TRANSACTION',
    policy_version: 'cost_aware_v2_live',
  },
  mentalist: null,
  case_file: {
    v5_action: 'ALLOW',
    final_action: 'ALLOW',
    action_changed: false,
    routing_reason: 'NO_LIVE_TRANSACTION',
    explanation: 'Create or receive a live payment to populate the investigation workspace.',
    trusted_history_channels: 0,
    trusted_fraud_channels: 0,
    trusted_fraud_evidence_present: false,
  },
  network: { nodes: [], edges: [] },
  adjudication: { outcome: null, state: 'unadjudicated', seconds_remaining: null },
}
