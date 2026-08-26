import type { RazorpayCheckoutOrder, RazorpaySuccess } from './api'

type RazorpayFailure = {
  error?: {
    description?: string
    reason?: string
  }
}

type RazorpayInstance = {
  open: () => void
  on: (event: 'payment.failed', handler: (response: RazorpayFailure) => void) => void
}

type RazorpayConstructor = new (options: Record<string, unknown>) => RazorpayInstance

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor
  }
}

let checkoutScriptPromise: Promise<void> | null = null

export function loadRazorpayCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve()
  if (checkoutScriptPromise) return checkoutScriptPromise

  checkoutScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-linkrisk-razorpay="checkout"]')
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Razorpay Checkout failed to load.')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.async = true
    script.dataset.linkriskRazorpay = 'checkout'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Razorpay Checkout failed to load.'))
    document.body.appendChild(script)
  })

  return checkoutScriptPromise
}

export async function openRazorpayCheckout(order: RazorpayCheckoutOrder): Promise<RazorpaySuccess> {
  await loadRazorpayCheckout()
  if (!window.Razorpay) throw new Error('Razorpay Checkout is unavailable in this browser.')

  return new Promise<RazorpaySuccess>((resolve, reject) => {
    let settled = false
    const settleReject = (message: string) => {
      if (settled) return
      settled = true
      reject(new Error(message))
    }

    const checkout = new window.Razorpay!({
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: order.name,
      description: order.description,
      order_id: order.order_id,
      prefill: order.prefill,
      handler: (response: RazorpaySuccess) => {
        if (settled) return
        settled = true
        resolve(response)
      },
      modal: {
        ondismiss: () => settleReject('Razorpay checkout was closed before payment completed.'),
      },
    })

    checkout.on('payment.failed', (response) => {
      const message = response.error?.description || response.error?.reason || 'Razorpay test payment failed.'
      settleReject(message)
    })
    checkout.open()
  })
}
