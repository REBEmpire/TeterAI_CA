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
        sans: ['Arial', 'Helvetica', 'sans-serif'],
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
      },
    },
  },
  plugins: [],
}

export default config
