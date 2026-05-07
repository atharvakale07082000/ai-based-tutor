import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        ink: '#0A0F1E',
        'surface-1': '#111827',
        'surface-2': '#1F2937',
        'surface-3': '#374151',
        paper: '#F9FAFB',
        violet: {
          DEFAULT: '#7C3AED',
          light: '#8B5CF6',
          dim: '#4C1D95',
        },
        indigo: {
          DEFAULT: '#4338CA',
          light: '#6366F1',
        },
        amber: '#F59E0B',
        rose: '#F43F5E',
        emerald: '#10B981',
      },
      fontFamily: {
        display: ['"Playfair Display"', 'serif'],
        body: ['"DM Sans"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      animation: {
        'glow-pulse': 'glowPulse 2s ease-in-out infinite',
        'mesh-rotate': 'meshRotate 20s linear infinite',
        'float': 'float 6s ease-in-out infinite',
        'typewriter': 'typewriter 0.05s steps(1) forwards',
        'spin-slow': 'spin 8s linear infinite',
        'fade-in': 'fadeIn 0.3s ease forwards',
      },
      keyframes: {
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(124, 58, 237, 0.4)' },
          '50%': { boxShadow: '0 0 40px rgba(124, 58, 237, 0.8), 0 0 60px rgba(124, 58, 237, 0.3)' },
        },
        meshRotate: {
          '0%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-20px)' },
        },
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      backgroundImage: {
        'gradient-mesh': 'radial-gradient(at 40% 20%, #7C3AED22 0px, transparent 50%), radial-gradient(at 80% 0%, #4338CA22 0px, transparent 50%), radial-gradient(at 0% 50%, #4C1D9522 0px, transparent 50%)',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}

export default config
