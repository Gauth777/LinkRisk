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

export const previewFeed: FeedItem[] = [
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

export const previewCase: CaseRecord = {
  transaction_id: 'TX-8F2D7K1E',
  transaction_time: 15300,
  input: {
    amount: 8750,
    payment_profile: 'PROFILE-A',
    device_info: 'Chrome 124 / Windows 11',
    receiver_domain: 'merchant.example',
    browser_context: 'chrome-124-win11',
    product_code: 'W', payer_domain: 'gmail.com', device_type: 'desktop',
    card_network: 'visa', card_type: 'debit',
  },
  decision: {
    baseline_risk: .41,
    linkrisk_risk: .39,
    graph_confidence: 0,
    v5_action: 'ALLOW',
    action: 'VERIFY',
    routing_reason: 'MENTALIST_CAPACITY_AUTHORIZED',
    policy_version: 'cost_aware_v2_live',
  },
  mentalist: {
    score: .82,
    score_threshold: .67634242773056,
    clue_count: 3,
    min_clue_families: 2,
    clue_families: {
      coordination: true,
      velocity: true,
      behavior_change: true,
      reuse_churn: false,
    },
    promoted_by_jane: true,
    displaced_v5_verify: false,
    uses_confirmed_fraud_as_input: false,
  },
  case_file: {
    v5_action: 'ALLOW',
    final_action: 'VERIFY',
    action_changed: true,
    routing_reason: 'MENTALIST_CAPACITY_AUTHORIZED',
    explanation: 'Corroborating present-tense behavioral evidence justified selective Mentalist inference and available live capacity admitted the case to VERIFY.',
    trusted_history_channels: 0,
    trusted_fraud_channels: 0,
    trusted_fraud_evidence_present: false,
  },
  network: {
    nodes: [
      { id: 'tx:current', label: 'TX-8F2D7K1E', kind: 'current', detail: '$8,750 current payment' },
      { id: 'rel:device', label: 'Device context', kind: 'relation', detail: 'Shared device/browser context' },
      { id: 'rel:profile', label: 'Payment profile', kind: 'relation', detail: 'Profile relationship' },
      { id: 'tx:a', label: 'Prior TX A', kind: 'prior', detail: 'Unadjudicated prior payment' },
      { id: 'tx:b', label: 'Prior TX B', kind: 'prior', detail: 'Unadjudicated prior payment' },
      { id: 'tx:c', label: 'Prior TX C', kind: 'prior', detail: 'Unadjudicated prior payment' },
    ],
    edges: [
      { source: 'tx:current', target: 'rel:device' },
      { source: 'tx:current', target: 'rel:profile' },
      { source: 'rel:device', target: 'tx:a' },
      { source: 'rel:device', target: 'tx:b' },
      { source: 'rel:profile', target: 'tx:c' },
    ],
  },
  adjudication: { outcome: null, state: 'unadjudicated', seconds_remaining: null },
}
