import Button from './ui/Button'
import Chip from './ui/Chip'

/** Pure CSS/SVG mock of a 9:16 vertical clip — no real media. */
function ClipMock() {
  return (
    <div className="relative mx-auto w-full max-w-[300px] animate-floaty">
      {/* Glow behind the frame */}
      <div
        className="absolute -inset-6 -z-10 rounded-[40px] bg-accent/20 blur-3xl"
        aria-hidden="true"
      />

      {/* Phone / 9:16 frame */}
      <div className="glass overflow-hidden rounded-[34px] p-3">
        <div className="relative aspect-[9/16] overflow-hidden rounded-[24px] bg-surface-3">
          {/* Faux scene — gradient + abstract speaker silhouette */}
          <div className="absolute inset-0 bg-gradient-to-br from-accent-deep/30 via-surface-2 to-surface" />
          <svg
            viewBox="0 0 180 320"
            className="absolute inset-0 h-full w-full"
            aria-hidden="true"
            preserveAspectRatio="xMidYMid slice"
          >
            {/* speaker head + shoulders, centered (mirrors 9:16 reframe) */}
            <circle cx="90" cy="120" r="42" fill="rgba(255,122,0,0.22)" />
            <circle cx="90" cy="120" r="42" stroke="rgba(255,146,51,0.6)" strokeWidth="2" fill="none" />
            <path
              d="M30 300c0-44 27-74 60-74s60 30 60 74"
              fill="rgba(255,122,0,0.14)"
            />
            {/* face-tracking reticle */}
            <rect
              x="58"
              y="86"
              width="64"
              height="72"
              rx="8"
              fill="none"
              stroke="rgba(255,146,51,0.85)"
              strokeWidth="2"
              strokeDasharray="10 8"
            />
          </svg>

          {/* Top bar: live badge + 9:16 tag */}
          <div className="absolute inset-x-0 top-0 flex items-center justify-between p-3 text-[10px] font-semibold">
            <span className="rounded-full bg-error/90 px-2 py-0.5 text-white">● REC</span>
            <span className="glass rounded-full px-2 py-0.5 text-text">9:16</span>
          </div>

          {/* Burned-in caption line */}
          <div className="absolute inset-x-0 bottom-16 px-4 text-center">
            <p className="inline-block rounded-md bg-black/55 px-2 py-1 text-sm font-bold leading-snug text-white">
              this is the <span className="text-accent-hot">moment</span> that hooks them
            </p>
          </div>

          {/* Caption "active word" pulse */}
          <div className="absolute inset-x-0 bottom-10 flex justify-center gap-1.5 px-4">
            <span className="h-1 w-8 rounded-full bg-white/30" />
            <span className="h-1 w-6 rounded-full bg-accent animate-caption-pulse" />
            <span className="h-1 w-10 rounded-full bg-white/30" />
          </div>

          {/* Thin animated render progress bar */}
          <div className="absolute inset-x-0 bottom-0 h-1.5 overflow-hidden bg-white/10">
            <div className="h-full w-1/3 rounded-full bg-gradient-to-r from-accent-hot to-accent-deep animate-progress" />
          </div>
        </div>
      </div>

      {/* Floating status pill */}
      <div className="glass absolute -right-3 top-10 rounded-full px-3 py-1.5 text-[11px] font-semibold text-text sm:-right-6">
        <span className="text-success">●</span> Rendering clip…
      </div>
    </div>
  )
}

export default function Hero() {
  return (
    <section id="top" className="relative pt-16 sm:pt-20 lg:pt-24">
      <div className="mx-auto grid max-w-content items-center gap-12 px-5 pb-16 sm:px-8 lg:grid-cols-2 lg:gap-8 lg:px-12 lg:pb-24">
        <div className="animate-fade-up">
          <Chip>AI clip engine · vertical · captioned</Chip>

          <h1 className="mt-6 font-display text-4xl font-extrabold leading-[1.05] tracking-display text-text sm:text-5xl lg:text-6xl">
            Turn long video into{' '}
            <span className="text-accent">scroll-stopping</span> vertical clips.
          </h1>

          <p className="mt-6 max-w-xl text-base leading-relaxed text-text-dim sm:text-lg">
            Upload an MP4 and Clippify transcribes it, scores every moment for
            engagement, cuts the best window, reframes it 9:16 onto the speaker,
            and burns in captions — start to finish.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button variant="accent" href="#" className="px-6 py-3.5 text-base">
              Start clipping free
            </Button>
            <Button variant="ghost" href="#pricing" className="px-6 py-3.5 text-base">
              See pricing
            </Button>
          </div>

          <p className="mt-5 text-sm text-text-faint">
            No GPU required · 30 free credits on signup · MP4 in, MP4 out
          </p>
        </div>

        <div className="relative">
          <ClipMock />
        </div>
      </div>
    </section>
  )
}
