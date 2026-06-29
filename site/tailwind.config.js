/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces
        surface: {
          DEFAULT: '#0A0A0A',
          2: '#111114',
          3: '#17171c',
        },
        // Accent neon orange
        accent: {
          DEFAULT: '#FF7A00',
          hot: '#ff9233',
          deep: '#c95f00',
        },
        // Text
        text: {
          DEFAULT: '#f5f5f7',
          dim: '#a9a9b2',
          faint: '#6c6c78',
        },
        success: '#2ecc71',
        error: '#ff4d4d',
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
