/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:       '#0b0d11',
        surface:  '#111520',
        elevated: '#181d28',
        border:   '#1e2535',
        'border-subtle': '#161b27',
        text: {
          primary:   '#e2e8f0',
          secondary: '#7c8ca1',
          muted:     '#3f4f63',
        },
        accent:  { DEFAULT: '#4f79e8', hover: '#3b66d6' },
        up:      { DEFAULT: '#22c55e', muted: '#14532d' },
        down:    { DEFAULT: '#ef4444', muted: '#450a0a' },
        warn:    { DEFAULT: '#f59e0b', muted: '#451a03' },
        signal:  { DEFAULT: '#a78bfa', muted: '#2e1065' },
        neutral: { DEFAULT: '#475569', muted: '#1e293b' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.65rem', { lineHeight: '1rem' }],
        xs:    ['0.75rem', { lineHeight: '1.1rem' }],
        sm:    ['0.8125rem', { lineHeight: '1.25rem' }],
      },
      borderRadius: {
        sm:  '4px',
        md:  '6px',
        lg:  '8px',
        xl:  '12px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,.4), 0 0 0 1px rgba(255,255,255,.03)',
        glow: '0 0 12px rgba(79,121,232,.25)',
      },
    },
  },
  plugins: [],
}
