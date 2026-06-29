/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // SINGLE SOURCE OF TRUTH: these consume the rgb-triplet CSS variables
        // defined in web/tokens.css (the canonical dashboard palette), imported
        // into the React app via src/main.tsx. rgb(var(--x) / <alpha-value>)
        // keeps Tailwind opacity modifiers (bg-accent/10, border-accent/40, …)
        // working while the dashboard and landing page share one palette.
        surface: {
          DEFAULT: 'rgb(var(--rgb-surface) / <alpha-value>)',
          2: 'rgb(var(--rgb-surface-2) / <alpha-value>)',
          3: 'rgb(var(--rgb-surface-3) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--rgb-accent) / <alpha-value>)',
          hot: 'rgb(var(--rgb-accent-hot) / <alpha-value>)',
          deep: 'rgb(var(--rgb-accent-deep) / <alpha-value>)',
        },
        text: {
          DEFAULT: 'rgb(var(--rgb-text) / <alpha-value>)',
          dim: 'rgb(var(--rgb-text-dim) / <alpha-value>)',
          faint: 'rgb(var(--rgb-text-faint) / <alpha-value>)',
        },
        success: 'rgb(var(--rgb-success) / <alpha-value>)',
        error: 'rgb(var(--rgb-error) / <alpha-value>)',
      },
      fontFamily: {
        display: ['Archivo', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
      letterSpacing: {
        display: '-0.02em',
      },
      maxWidth: {
        content: '1180px',
      },
      borderRadius: {
        card: '18px',
      },
      boxShadow: {
        glass: '0 24px 60px -20px rgba(0,0,0,0.8)',
        accent: '0 12px 30px -8px rgba(255,122,0,0.45)',
        'accent-glow': '0 0 0 1px rgba(255,122,0,0.55), 0 18px 50px -12px rgba(255,122,0,0.40)',
      },
      backdropBlur: {
        glass: '18px',
      },
      keyframes: {
        progress: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(250%)' },
        },
        floaty: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'caption-pulse': {
          '0%, 100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        progress: 'progress 2.4s ease-in-out infinite',
        floaty: 'floaty 6s ease-in-out infinite',
        'fade-up': 'fade-up 0.6s ease-out both',
        'caption-pulse': 'caption-pulse 2.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
