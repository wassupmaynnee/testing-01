import { APP_LINKS } from '../data/content'

/**
 * Take a visitor from a pricing CTA into the right next step:
 *  - Free            -> signup.
 *  - Paid, logged in -> POST /api/billing/checkout and redirect to Stripe.
 *  - Paid, logged out OR billing disabled -> signup carrying the tier, which
 *    continues to checkout right after the account is created.
 * Progressive enhancement: the anchors still have a real href, so this only
 * upgrades the click when JS is available.
 */
export async function startCheckout(tierKey: string): Promise<void> {
  if (tierKey === 'free') {
    window.location.href = APP_LINKS.signup
    return
  }
  const signupWithTier = `${APP_LINKS.signup}?tier=${encodeURIComponent(tierKey)}`
  try {
    const me = await fetch('/api/auth/me', { credentials: 'same-origin' })
    if (!me.ok) {
      window.location.href = signupWithTier
      return
    }
    const body = new FormData()
    body.append('tier', tierKey)
    const res = await fetch('/api/billing/checkout', {
      method: 'POST',
      body,
      credentials: 'same-origin',
    })
    const env = await res.json().catch(() => null)
    if (env?.ok && env.data?.url) {
      window.location.href = env.data.url
      return
    }
    // Billing disabled (deferred) or an error — fall back to signup-with-tier.
    window.location.href = signupWithTier
  } catch {
    window.location.href = signupWithTier
  }
}
