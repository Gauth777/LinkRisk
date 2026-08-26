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

export const api = {
  health: () => request<{ ok: boolean; engine_loaded: boolean; asset_status: { ready: boolean; missing: string[] }; held_out_test: string }>('/api/health'),
  overview: () => request<OverviewPayload>('/api/overview'),
  transactions: () => request<{ items: FeedItem[]; clock: number }>('/api/transactions'),
  transaction: (id: string) => request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}`),
  createTransaction: (payload: Record<string, unknown>) => request<CaseRecord>('/api/transactions', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  adjudicate: (id: string, outcome: 'fraud' | 'legitimate') => request<CaseRecord>(`/api/transactions/${encodeURIComponent(id)}/adjudicate`, {
    method: 'POST', body: JSON.stringify({ outcome }),
  }),
  advance: (seconds: number) => request<{ clock: number }>('/api/session/advance', {
    method: 'POST', body: JSON.stringify({ seconds }),
  }),
  reset: () => request<{ ok: boolean; clock: number }>('/api/session/reset', { method: 'POST' }),
}
