import { STEPS } from '../data/content'
import GlassCard from './ui/GlassCard'
import Chip from './ui/Chip'

export default function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-24 py-20 sm:py-24">
      <div className="mx-auto max-w-content px-5 sm:px-8 lg:px-12">
        <div className="max-w-2xl">
          <Chip>How it works</Chip>
          <h2 className="mt-5 font-display text-3xl font-extrabold tracking-display text-text sm:text-4xl">
            Six steps, fully automatic
          </h2>
          <p className="mt-4 text-text-dim">
            The exact pipeline that runs on every upload — from raw audio to a
            captioned, speaker-tracked vertical clip.
          </p>
        </div>

        <ol className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((step, i) => (
            <li key={step.title}>
              <GlassCard className="h-full p-6">
                <div className="flex items-start gap-4">
                  <span
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 font-display text-lg font-extrabold text-accent-hot"
                    aria-hidden="true"
                  >
                    {i + 1}
                  </span>
                  <div>
                    <h3 className="font-display text-lg font-extrabold tracking-display text-text">
                      {step.title}
                    </h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-text-dim">
                      {step.description}
                    </p>
                  </div>
                </div>
              </GlassCard>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
