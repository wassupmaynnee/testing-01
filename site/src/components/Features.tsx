import { FEATURES } from '../data/content'
import GlassCard from './ui/GlassCard'
import Chip from './ui/Chip'

/** Minimal inline icon set, keyed by the `icon` field on each feature. */
function FeatureIcon({ name }: { name: string }) {
  const common = {
    width: 22,
    height: 22,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  switch (name) {
    case 'spark':
      return (
        <svg {...common}>
          <path d="M12 3v6M12 15v6M3 12h6M15 12h6M5.6 5.6l3 3M15.4 15.4l3 3M18.4 5.6l-3 3M8.6 15.4l-3 3" />
        </svg>
      )
    case 'target':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
        </svg>
      )
    case 'captions':
      return (
        <svg {...common}>
          <rect x="3" y="5" width="18" height="14" rx="3" />
          <path d="M8 11h2M8 14h5M14 11h2" />
        </svg>
      )
    case 'bolt':
      return (
        <svg {...common}>
          <path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />
        </svg>
      )
    case 'chip':
      return (
        <svg {...common}>
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
        </svg>
      )
    case 'download':
      return (
        <svg {...common}>
          <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
        </svg>
      )
    default:
      return null
  }
}

export default function Features() {
  return (
    <section id="features" className="scroll-mt-24 py-20 sm:py-24">
      <div className="mx-auto max-w-content px-5 sm:px-8 lg:px-12">
        <div className="max-w-2xl">
          <Chip>Features</Chip>
          <h2 className="mt-5 font-display text-3xl font-extrabold tracking-display text-text sm:text-4xl">
            Everything the clip needs, built in
          </h2>
          <p className="mt-4 text-text-dim">
            No timeline editor, no plugins, no render farm to manage. Upload and
            Clippify handles the rest.
          </p>
        </div>

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <GlassCard
              key={feature.title}
              className="group h-full p-6 transition-transform duration-200 hover:-translate-y-1"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent/15 text-accent-hot">
                <FeatureIcon name={feature.icon} />
              </div>
              <h3 className="mt-4 font-display text-lg font-extrabold tracking-display text-text">
                {feature.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-text-dim">
                {feature.description}
              </p>
            </GlassCard>
          ))}
        </div>
      </div>
    </section>
  )
}
