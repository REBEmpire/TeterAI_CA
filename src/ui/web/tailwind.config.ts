import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Teter brand palette (from teterae.com)
        teter: {
          orange: '#d06f1a',       // primary brand orange
          'orange-dark': '#b35e14', // hover state
          'orange-light': '#e8892a', // lighter variant
          dark: '#313131',          // nav/header background
          'dark-soft': '#3d3d3d',   // secondary dark
          gray: '#eeeeee',          // light background
          'gray-mid': '#d4d4d4',    // borders
          'gray-text': '#6b6b6b',   // muted text
          // Surface depth system
          'surface-0': '#f4f4f5',   // page background
          'surface-1': '#ffffff',   // card face
          // Typography
          ink: '#1a1a1a',           // near-black body text
          // Glow
          'orange-glow': 'rgba(208,111,26,0.18)',
        },
        // Confidence score colors
        confidence: {
          high: '#2e7d32',   // ≥ 0.80 — green
          mid: '#f9a825',    // 0.50–0.79 — amber
          low: '#c62828',    // < 0.50 — red
        },
        // Urgency badge colors
        urgency: {
          high: '#c62828',
          medium: '#e65100',
          low: '#757575',
          'high-bg': '#ffebee',
          'medium-bg': '#fff3e0',
          'low-bg': '#f5f5f5',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Arial', 'Helvetica', 'sans-serif'],
      },
      fontWeight: {
        primary: '600',
      },
      maxWidth: {
        content: '800px',
        wide: '1130px',
      },
      boxShadow: {
        card: '0 1px 3px 0 rgba(0,0,0,0.10), 0 1px 2px 0 rgba(0,0,0,0.06)',
        'card-hover': '0 4px 12px 0 rgba(0,0,0,0.12)',
        // Elevated card with orange warmth tint
        'card-lifted': '0 8px 24px -4px rgba(208,111,26,0.12), 0 2px 8px -2px rgba(0,0,0,0.08)',
        // Frosted glass nav
        'nav-glass': '0 1px 0 rgba(255,255,255,0.06), 0 4px 24px rgba(0,0,0,0.25)',
        // Stat chip
        'stat': '0 2px 8px rgba(0,0,0,0.07), inset 0 1px 0 rgba(255,255,255,0.8)',
      },
      keyframes: {
        // Card stagger entrance
        'slide-up': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Pulsing urgency dot for HIGH items
        'urgency-pulse': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.4', transform: 'scale(0.7)' },
        },
        // Confidence bar animated fill on mount
        'bar-fill': {
          '0%': { width: '0%' },
          '100%': { width: 'var(--bar-width)' },
        },
        // Login page grid fade-in
        'grid-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
      animation: {
        'slide-up': 'slide-up 0.35s cubic-bezier(0.16,1,0.3,1) both',
        'urgency-pulse': 'urgency-pulse 1.4s ease-in-out infinite',
        'bar-fill': 'bar-fill 0.6s cubic-bezier(0.34,1.56,0.64,1) forwards',
        'grid-in': 'grid-in 1.2s ease both',
      },
    },
  },
  plugins: [],
}

export default config
