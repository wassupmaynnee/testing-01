import { useState } from 'react'
import { FAQS } from '../data/content'
import GlassCard from './ui/GlassCard'
import Chip from './ui/Chip'

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState<number | null>(0)

  return (
    <section id="faq" className="scroll-mt-24 py-20 sm:py-24">
      <div className="mx-auto max-w-content px-5 sm:px-8 lg:px-12">
        <div className="max-w-2xl">
          <Chip>FAQ</Chip>
          <h2 className="mt-5 font-display text-3xl font-extrabold tracking-display text-text sm:text-4xl">
            Questions, answered
          </h2>
        </div>

        <div className="mx-auto mt-10 max-w-3xl">
          <GlassCard className="divide-y divide-white/10 overflow-hidden">
            {FAQS.map((faq, i) => {
              const isOpen = openIndex === i
              const panelId = `faq-panel-${i}`
              const buttonId = `faq-button-${i}`
              return (
                <div key={faq.question}>
                  <h3>
                    <button
                      id={buttonId}
                      type="button"
                      aria-expanded={isOpen}
                      aria-controls={panelId}
                      onClick={() => setOpenIndex(isOpen ? null : i)}
                      className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left transition-colors hover:bg-white/5"
                    >
                      <span className="font-display text-base font-extrabold tracking-display text-text sm:text-lg">
                        {faq.question}
                      </span>
                      <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        aria-hidden="true"
                        className={`shrink-0 text-accent-hot transition-transform duration-200 ${
                          isOpen ? 'rotate-45' : ''
                        }`}
                      >
                        <path
                          d="M12 5v14M5 12h14"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                        />
                      </svg>
                    </button>
                  </h3>
                  <div
                    id={panelId}
                    role="region"
                    aria-labelledby={buttonId}
                    hidden={!isOpen}
                    className="px-6 pb-5 text-sm leading-relaxed text-text-dim"
                  >
                    {faq.answer}
                  </div>
                </div>
              )
            })}
          </GlassCard>
        </div>
      </div>
    </section>
  )
}
