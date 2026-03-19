/**
 * Teter brand design tokens.
 *
 * Colors sourced from teterae.com (inspected CSS).
 * These are the single source of truth — Tailwind config extends these values.
 */
export const teter = {
  colors: {
    // Core brand
    orange: '#d06f1a',
    orangeDark: '#b35e14',
    orangeLight: '#e8892a',
    dark: '#313131',
    darkSoft: '#3d3d3d',
    white: '#ffffff',
    gray: '#eeeeee',
    grayMid: '#d4d4d4',
    grayText: '#6b6b6b',

    // Confidence score indicator
    confidenceHigh: '#2e7d32',   // green  — ≥ 0.80
    confidenceMid: '#f9a825',    // amber  — 0.50–0.79
    confidenceLow: '#c62828',    // red    — < 0.50

    // Urgency badge
    urgencyHigh: '#c62828',
    urgencyMedium: '#e65100',
    urgencyLow: '#757575',
    urgencyHighBg: '#ffebee',
    urgencyMediumBg: '#fff3e0',
    urgencyLowBg: '#f5f5f5',
  },

  fonts: {
    base: 'Arial, Helvetica, sans-serif',
    weightPrimary: 600,
    weightNormal: 400,
  },

  /** CSS custom property declarations — paste into :root */
  cssVars: `
    --teter-orange: #d06f1a;
    --teter-orange-dark: #b35e14;
    --teter-orange-light: #e8892a;
    --teter-dark: #313131;
    --teter-dark-soft: #3d3d3d;
    --teter-white: #ffffff;
    --teter-gray: #eeeeee;
    --teter-gray-mid: #d4d4d4;
    --teter-gray-text: #6b6b6b;
    --confidence-high: #2e7d32;
    --confidence-mid: #f9a825;
    --confidence-low: #c62828;
  `,
} as const

/** Return the Tailwind color class for a confidence score 0–1. */
export function confidenceColor(score: number): string {
  if (score >= 0.8) return 'text-confidence-high'
  if (score >= 0.5) return 'text-confidence-mid'
  return 'text-confidence-low'
}

/** Return the Tailwind bg + text classes for an urgency level. */
export function urgencyClasses(urgency: string): { bg: string; text: string; dot: string } {
  switch (urgency) {
    case 'HIGH':
      return { bg: 'bg-urgency-high-bg', text: 'text-urgency-high', dot: 'bg-urgency-high' }
    case 'MEDIUM':
      return { bg: 'bg-urgency-medium-bg', text: 'text-urgency-medium', dot: 'bg-urgency-medium' }
    default:
      return { bg: 'bg-urgency-low-bg', text: 'text-urgency-low', dot: 'bg-urgency-low' }
  }
}
