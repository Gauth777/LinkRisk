import type { CaseRecord, FeedItem, OverviewPayload } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const payload = await response.json()
      message = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
    } catch {
      // keep status text
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export type RazorpayCheckoutOrder = {
  key_id: string
  order_id: string
  amount: number
  currency: string
  name: string
  description: string
  prefill: {
    name: string
    email: string
    contact: string
  }
  test_mode: boolean
}

export type RazorpaySuccess = {
  razorpay_payment_id: string
  razorpay_order_id: string
  razorpay_signature: string
}

// App.tsx refreshes the live feed immediately after a successful checkout.
// React state updates are asynchronous, so that refresh can still ask for the
// previously-selected transaction once. Preserve the authoritative record just
// returned by Razorpay verification for that single follow-up read, preventing
// the Investigation page from being overwritten with stale case details.
let pendingCreatedRecord: CaseRecord | null = null

async function createRazorpayBackedTransaction(payload: Record<string, unknown>): Promise<CaseRecord> {
  const order = await request<RazorpayCheckoutOrder>('/api/integrations/razorpay/orders', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  const { openRazorpayCheckout } = await import('./razorpay')
  const checkoutResult = await openRazorpayCheckout(order)
  const verified = await request<{ verified: boolean; duplicate_payment: boolean; transaction: CaseRecord }>('/api/integrations/razorpay/payments/verify', {
    method: 'POST',
    body: JSON.stringify(checkoutResult),
  })
  if (!verified.verified) throw new Error('Razorpay payment verification did not complete.')
  pendingCreatedRecord = verified.transaction
  return verified.transaction
}

async function getTransaction(id: string): Promise<CaseRecord> {
  if (pendingCreatedRecord) {
    const record = pendingCreatedRecord
    pendingCreatedRecord = null
    return record
  }
  return request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}`)
}

export const api = {
  health: () => request<{ ok: boolean; engine_loaded: boolean; asset_status: { ready: boolean; missing: string[] }; held_out_test: string }>('/api/health'),
  overview: () => request<OverviewPayload>('/api/overview'),
  transactions: () => request<{ items: FeedItem[]; clock: number }>('/api/transactions'),
  transaction: getTransaction,
  createTransaction: createRazorpayBackedTransaction,
  createSimulatorTransaction: (payload: Record<string, unknown>) => request<CaseRecord>('/api/transactions', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  razorpayCheckoutStatus: () => request<{ configured: boolean; test_mode: boolean; key_id: string | null; secret_exposed: false }>('/api/integrations/razorpay/checkout/status'),
  createRazorpayOrder: (payload: Record<string, unknown>) => request<RazorpayCheckoutOrder>('/api/integrations/razorpay/orders', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  verifyRazorpayPayment: (payload: RazorpaySuccess) => request<{ verified: boolean; duplicate_payment: boolean; transaction: CaseRecord }>('/api/integrations/razorpay/payments/verify', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  deepInvestigate: (id: string) => request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/deep-investigate`, {
    method: 'POST',
  }),
  adjudicate: (id: string, outcome: 'fraud' | 'legitimate') => request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/adjudicate`, {
    method: 'POST', body: JSON.stringify({ outcome }),
  }),
  advance: (seconds: number) => request<{ clock: number }>('/api/session/advance', {
    method: 'POST', body: JSON.stringify({ seconds }),
  }),
  reset: () => request<{ ok: boolean; clock: number }>('/api/session/reset', { method: 'POST' }),
}
