// Single source of truth for all page copy/data.

export interface Step {
  title: string
  description: string
}

export interface Feature {
  title: string
  description: string
  icon: string // simple inline SVG path id, mapped in the Features component
}

export interface Tier {
  name: string
  price: string
  cadence: string
  credits: string
  note: string
  cta: string
  tierKey: 'free' | 'starter' | 'pro' | 'scale'
  featured?: boolean
}

// Live app destinations — the marketing page is the public front door; these
// links cross into the unified single-origin app. No dead CTAs anywhere.
export const APP_LINKS = {
  signup: '/signup',
  signin: '/dashboard',
  dashboard: '/dashboard',
} as const

export interface Faq {
  question: string
  answer: string
}

export const NAV_LINKS = [
  { label: 'Features', href: '#features' },
  { label: 'How it works', href: '#how' },
  { label: 'Pricing', href: '#pricing' },
  { label: 'FAQ', href: '#faq' },
] as const

export const STEPS: Step[] = [
  {
    title: 'Transcribe audio',
    description: 'Speech-to-text turns your full video into a word-timed transcript.',
  },
  {
    title: 'Score every moment',
    description: 'A frozen model weighs hook, pace, sentiment, and on-screen face.',
  },
  {
    title: 'Select the strongest window',
    description: 'The highest-scoring segment becomes your clip candidate.',
  },
  {
    title: 'Cut',
    description: 'Clippify trims the source down to that single best window.',
  },
  {
    title: 'Reframe 9:16 onto the speaker',
    description: 'Face tracking recenters the vertical crop on whoever is talking.',
  },
  {
    title: 'Burn in captions',
    description: 'Word-timed subtitles are styled and rendered into the final clip.',
  },
]

export const FEATURES: Feature[] = [
  {
    title: 'Engagement scoring',
    description:
      'A frozen weighting of hook, pace, sentiment, and on-screen face picks the strongest moment automatically.',
    icon: 'spark',
  },
  {
    title: 'Speaker-tracked 9:16',
    description:
      'YuNet face detection keeps the talking head centered in the vertical crop.',
    icon: 'target',
  },
  {
    title: 'Captions burned in',
    description:
      'Word-timed subtitles, styled and rendered straight into the clip.',
    icon: 'captions',
  },
  {
    title: 'Fast cloud rendering',
    description:
      'Clips render in the cloud in under a minute, so you can batch a whole episode in one sitting.',
    icon: 'bolt',
  },
  {
    title: 'No GPU required',
    description:
      'Everything runs on standard CPU — no graphics card, no local setup, nothing to install.',
    icon: 'chip',
  },
  {
    title: 'Download-ready MP4',
    description:
      'Export H.264 MP4 sized for TikTok, Reels, and Shorts — ready to post the moment it finishes.',
    icon: 'download',
  },
]

export const TIERS: Tier[] = [
  {
    name: 'Free',
    price: '$0',
    cadence: '',
    credits: '30 credits',
    note: 'one-time trial on signup',
    cta: 'Start free',
    tierKey: 'free',
  },
  {
    name: 'Starter',
    price: '$14.99',
    cadence: '/mo',
    credits: '200 credits',
    note: 'billed annually',
    cta: 'Choose Starter',
    tierKey: 'starter',
  },
  {
    name: 'Pro',
    price: '$29.99',
    cadence: '/mo',
    credits: '500 credits',
    note: 'billed annually',
    cta: 'Choose Pro',
    tierKey: 'pro',
    featured: true,
  },
  {
    name: 'Scale',
    price: '$59.99',
    cadence: '/mo',
    credits: '1,200 credits',
    note: 'billed annually',
    cta: 'Choose Scale',
    tierKey: 'scale',
  },
]

export const FAQS: Faq[] = [
  {
    question: 'How long can my source video be?',
    answer:
      'Upload anything from a 30-second take to a multi-hour podcast or webinar. Longer videos simply use more credits, since Clippify scans the entire transcript to find the strongest moment.',
  },
  {
    question: 'Do I need a GPU or special hardware?',
    answer:
      'No. Clippify runs entirely in the cloud on standard CPUs. All you need is a browser and an MP4 to upload — there is nothing to install and no graphics card required.',
  },
  {
    question: 'What format are the clips?',
    answer:
      'Every clip exports as a vertical 9:16 H.264 MP4 with captions burned in — ready to upload directly to TikTok, Instagram Reels, and YouTube Shorts.',
  },
  {
    question: 'How do credits work?',
    answer:
      'One credit covers one rendered clip. Paid plans refresh their credit allowance every month on annual billing, and the Free tier includes a one-time 30-credit trial when you sign up.',
  },
  {
    question: 'Can I adjust the captions and framing?',
    answer:
      'Yes. Clippify auto-places word-timed captions and tracks the speaker for the 9:16 crop, and you can fine-tune the wording, caption style, and framing before exporting the final MP4.',
  },
  {
    question: 'Which languages are supported?',
    answer:
      'Transcription works across dozens of spoken languages, and captions are generated in the same language that is spoken in your video.',
  },
]
