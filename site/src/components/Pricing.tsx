import { useState } from 'react'
import { TIERS, APP_LINKS, type BillingInterval, type Tier } from '../data/content'
import { startCheckout } from '../lib/checkout'
import GlassCard from './ui/GlassCard'
import Button from './ui/Button'
import Chip from './ui/Chip'

function priceLabel(tier: Tier, interval: BillingInterval): { amount: string; cadence: string; sub: string } {
  if (tier.tierKey === 'free') return { amount: '$0', cadence: '', sub: tier.note }
  if (interval === 'monthly') {
    return { amount: `$${tier.monthlyUsd}`, cadence: '/mo', sub: 'billed monthly' }
  }
  return {
    amount: `$${tier.annualUsd.toFixed(2)}`,
    cadence: '/yr',
    sub: `$${tier.monthlyUsd}/mo · billed annually`,
  }
}

export default function Pricing() {
  const [interval, setInterval] = useState<BillingInterval>('annual')

  return (
    <section id="pricing" className="scroll-mt-24 py-20 sm:py-24">
      <div className="mx-auto max-w-content px-5 sm:px-8 lg:px-12">
        <div className="max-w-2xl">
          <Chip>Pricing</Chip>
          <h2 className="mt-5 font-display text-3xl font-extrabold tracking-display text-text sm:text-4xl">
            Simple, credit-based plans
          </h2>
          <p className="mt-4 text-text-dim">
            Credits renew monthly. Choose the billing cadence that suits you.
          </p>
        </div>

        {/* Monthly / Annual toggle */}
        <div className="mt-8 inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 p-1">
          {(['monthly', 'annual'] as BillingInterval[]).map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setInterval(opt)}
              aria-pressed={interval === opt}
              className={`rounded-full px-4 py-1.5 text-sm font-semibold capitalize transition-colors ${
                interval === opt ? 'bg-accent text-black' : 'text-text-dim hover:text-text'
              }`}
            >
              {opt}
            </button>
          ))}
        </div>

        <div className="mt-8 grid items-stretch gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TIERS.map((tier) => {
            const p = priceLabel(tier, interval)
            return (
              <GlassCard
                key={tier.name}
                className={`relative flex h-full flex-col p-6 transition-transform duration-200 hover:-translate-y-1 ${
                  tier.featured ? 'border-accent/60 shadow-accent-glow' : ''
                }`}
              >
                {tier.featured && (
                  <div className="absolute -top-3 left-6">
                    <Chip>Most popular</Chip>
                  </div>
                )}

                <h3 className="font-display text-xl font-extrabold tracking-display text-text">
                  {tier.name}
                </h3>

                <div className="mt-4 flex items-end gap-1">
                  <span className="font-display text-4xl font-extrabold tracking-display text-text">
                    {p.amount}
                  </span>
                  {p.cadence && <span className="mb-1 text-sm text-text-dim">{p.cadence}</span>}
                </div>

                <p className="mt-3 text-sm font-semibold text-accent-hot">{tier.credits}</p>
                <p className="mt-1 text-sm text-text-dim">{p.sub}</p>

                <div className="mt-6 flex-1" />

                <Button
                  variant={tier.featured ? 'accent' : 'ghost'}
                  href={
                    tier.tierKey === 'free'
                      ? APP_LINKS.signup
                      : `${APP_LINKS.signup}?tier=${tier.tierKey}&interval=${interval}`
                  }
                  onClick={(e) => {
                    e.preventDefault()
                    void startCheckout(tier.tierKey, interval)
                  }}
                  className="w-full"
                >
                  {tier.cta}
                </Button>
              </GlassCard>
            )
          })}
        </div>
      </div>
    </section>
  )
}
