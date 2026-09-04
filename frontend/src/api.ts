import type { CaseRecord, FeedItem, OverviewPayload } from './types'

const OPERATOR_TOKEN_KEY = 'linkrisk_operator_token'

async function parseResponse<T>(response: Response): Promise<T> {
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  return parseResponse<T>(response)
}

/**
 * Call an analyst/admin endpoint without changing the existing demo UX.
 *
 * If LINKRISK_ADMIN_TOKEN is not configured on the backend, the request behaves
 * exactly as before. If protection is enabled, the first protected action in a
 * browser tab asks the operator for the token once and keeps it only in
 * sessionStorage (cleared when that tab/session closes).
 */
export async function operatorRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const readToken = () => {
    if (typeof window === 'undefined') return ''
    try {
      return window.sessionStorage.getItem(OPERATOR_TOKEN_KEY) || ''
    } catch {
      return ''
    }
  }

  const send = (token: string) => fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-LinkRisk-Admin': token } : {}),
      ...(init?.headers || {}),
    },
    ...init,
  })

  let token = readToken()
  let response = await send(token)

  if (response.status === 401 && typeof window !== 'undefined') {
    try {
      window.sessionStorage.removeItem(OPERATOR_TOKEN_KEY)
    } catch {
      // Storage may be unavailable in privacy-restricted browsers.
    }

    const supplied = window.prompt('LinkRisk operator token required for this analyst action.')
    if (supplied?.trim()) {
      token = supplied.trim()
      try {
        window.sessionStorage.setItem(OPERATOR_TOKEN_KEY, token)
      } catch {
        // The retry can still use the token even if sessionStorage is blocked.
      }
      response = await send(token)
      if (response.status === 401) {
        try {
          window.sessionStorage.removeItem(OPERATOR_TOKEN_KEY)
        } catch {
          // no-op
        }
      }
    }
  }

  return parseResponse<T>(response)
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
  createSimulatorTransaction: (payload: Record<string, unknown>) => operatorRequest<CaseRecord>('/api/transactions', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  razorpayCheckoutStatus: () => request<{ configured: boolean; test_mode: boolean; key_id: string | null; secret_exposed: false }>('/api/integrations/razorpay/checkout/status'),
  createRazorpayOrder: (payload: Record<string, unknown>) => request<RazorpayCheckoutOrder>('/api/integrations/razorpay/orders', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  verifyRazorpayPayment: (payload: RazorpaySuccess) => request<{ verified: boolean; duplicate_payment: boolean; transaction: CaseRecord }>('/api/integrations/razorpay/payments/verify', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  deepInvestigate: (id: string) => operatorRequest<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/deep-investigate`, {
    method: 'POST',
  }),
  escalateJane: (id: string) => operatorRequest<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/jane-escalate`, {
    method: 'POST',
  }),
  adjudicate: (id: string, outcome: 'fraud' | 'legitimate') => operatorRequest<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/adjudicate`, {
    method: 'POST', body: JSON.stringify({ outcome }),
  }),
  advance: (seconds: number) => operatorRequest<{ clock: number }>('/api/session/advance', {
    method: 'POST', body: JSON.stringify({ seconds }),
  }),
  reset: () => operatorRequest<{ ok: boolean; clock: number }>('/api/session/reset', { method: 'POST' }),
}
