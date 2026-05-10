import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Atelier tokens (map to CSS vars for theme switching)
        paper: {
          0: 'var(--paper-0)',
          1: 'var(--paper-1)',
          2: 'var(--paper-2)',
          3: 'var(--paper-3)',
        },
        ink: {
          0: 'var(--ink-0)',
          1: 'var(--ink-1)',
          2: 'var(--ink-2)',
          3: 'var(--ink-3)',
          4: 'var(--ink-4)',
        },
        line: { 1: 'var(--line-1)', 2: 'var(--line-2)' },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          soft: 'var(--accent-soft)',
          line: 'var(--accent-line)',
        },
        pos:  { DEFAULT: 'var(--pos)',  soft: 'var(--pos-soft)' },
        warn: { DEFAULT: 'var(--warn)', soft: 'var(--warn-soft)' },
        neg:  { DEFAULT: 'var(--neg)',  soft: 'var(--neg-soft)' },
        info: { DEFAULT: 'var(--info)', soft: 'var(--info-soft)' },
        agent: {
          curr:  'var(--agent-curr)',
          quiz:  'var(--agent-quiz)',
          prog:  'var(--agent-prog)',
          doubt: 'var(--agent-doubt)',
        },
        // legacy aliases — kept so old imports don't crash during migration
        surface: { 1: '#1B1814', 2: '#23201A', 3: '#2D2922' },
        violet: { DEFAULT: '#6B5B95', light: '#9986C9', dim: '#4B3D75' },
        indigo: { DEFAULT: '#4A6B7A', light: '#7FA0B0' },
        amber: 'var(--warn)',
        rose:  'var(--neg)',
        emerald: 'var(--pos)',
      },
      fontFamily: {
        sans:    ['Geist', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        serif:   ['Instrument Serif', 'ui-serif', 'Georgia', 'serif'],
        mono:    ['Geist Mono', 'ui-monospace', 'JetBrains Mono', 'Menlo', 'monospace'],
        // legacy
        display: ['Instrument Serif', 'ui-serif', 'Georgia', 'serif'],
        body:    ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        'atl-xs':   ['11px', { lineHeight: '16px' }],
        'atl-sm':   ['12px', { lineHeight: '17px' }],
        'atl-base': ['13px', { lineHeight: '20px' }],
        'atl-md':   ['14px', { lineHeight: '21px' }],
        'atl-lg':   ['16px', { lineHeight: '24px' }],
        'atl-xl':   ['19px', { lineHeight: '26px' }],
        'atl-2xl':  ['24px', { lineHeight: '30px' }],
        'atl-3xl':  ['32px', { lineHeight: '38px', letterSpacing: '-0.02em' }],
        'atl-4xl':  ['44px', { lineHeight: '48px', letterSpacing: '-0.02em' }],
        'atl-5xl':  ['60px', { lineHeight: '62px', letterSpacing: '-0.02em' }],
      },
      borderRadius: {
        'atl-1': '3px',
        'atl-2': '5px',
        'atl-3': '8px',
        'atl-4': '12px',
        'atl-5': '16px',
        'pill':  '999px',
      },
      animation: {
        'fade-up':    'fadeUp 280ms cubic-bezier(0.2,0,0,1) both',
        'fade-in':    'fadeIn 180ms cubic-bezier(0.2,0,0,1) both',
        'shimmer':    'shimmer 1.6s infinite linear',
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
        'blink':      'blink 1s steps(1) infinite',
        'spin-fast':  'spin 0.7s linear infinite',
        'mesh-rotate':'meshRotate 20s linear infinite',
        'float':      'float 6s ease-in-out infinite',
        'drain-timer':'drainTimer linear forwards',
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}

export default config
