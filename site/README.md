# Clippify — Marketing Landing Page

A self-contained, front-end-only marketing landing page for **Clippify**, an AI tool
that turns long videos into short vertical clips. Built with **React + Vite + Tailwind CSS**.

No backend, no API calls, no database — all content is hardcoded.

## Stack

- **React 18** + **TypeScript**
- **Vite 5** (dev server + build)
- **Tailwind CSS 3** (design tokens defined in `tailwind.config.js`)
- Google Fonts: **Archivo** (display) + **Inter** (body), loaded in `index.html`

## Run it

```bash
npm install      # install dependencies
npm run dev      # start the dev server (http://localhost:5173)
```

## Build for production

```bash
npm run build    # type-check + bundle to ./dist
npm run preview  # serve the production build locally
```

## Design system

All theme colors, fonts, shadows, and radii live in `tailwind.config.js` — the single
source of truth. The reusable component classes (`.glass`, `.btn-accent`, `.btn-ghost`,
`.chip`, `.app-bg`) are defined under `@layer components` in `src/index.css`.

Shared UI primitives are in `src/components/ui/`:

- `GlassCard` — frosted-glass surface
- `Button` — `variant="accent"` (orange gradient) or `variant="ghost"` (glass)
- `Chip` — small uppercase orange pill
- `Wordmark` — the "Clip" + "pify" text logo

## Structure

```
src/
  App.tsx                 # page composition + skip link
  index.css               # Tailwind layers + component classes
  data/content.ts         # all copy/data (steps, features, tiers, faqs)
  components/
    Nav.tsx               # sticky nav + mobile menu
    Hero.tsx              # headline + CSS/SVG 9:16 clip mock
    HowItWorks.tsx        # 6-step pipeline (from data array)
    Features.tsx          # feature grid (from data array)
    Pricing.tsx           # 4 tiers (from data array)
    FAQ.tsx               # accessible accordion (React state)
    Footer.tsx
    ui/                   # GlassCard, Button, Chip, Wordmark
```

## Accessibility & motion

- Semantic landmarks (`header`, `main`, `footer`, `nav`), skip link, focus-visible rings
- Keyboard-navigable nav and accordion with `aria-expanded` / `aria-controls`
- All animations and smooth scrolling are gated behind `prefers-reduced-motion`

© 2026 Clippify · GPL-3.0
