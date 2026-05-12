/** @type {import('tailwindcss').Config} */
//
// Los colores se mapean a CSS variables para soportar dark / light theme
// sin tocar las clases de los componentes. Los valores reales viven en
// `src/index.css` (`:root` = dark, `:root.light` = overrides light).
//
const rgb = (v) => `rgb(var(${v}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg:              rgb('--c-bg'),
        surface:         rgb('--c-surface'),
        elevated:        rgb('--c-elevated'),
        border:          rgb('--c-border'),
        'border-subtle': rgb('--c-border-subtle'),
        text: {
          primary:   rgb('--c-text-primary'),
          secondary: rgb('--c-text-secondary'),
          muted:     rgb('--c-text-muted'),
        },
        accent: {
          DEFAULT: rgb('--c-accent'),
          hover:   rgb('--c-accent-hover'),
        },
        up:      { DEFAULT: rgb('--c-up'),      muted: rgb('--c-up-muted') },
        down:    { DEFAULT: rgb('--c-down'),    muted: rgb('--c-down-muted') },
        warn:    { DEFAULT: rgb('--c-warn'),    muted: rgb('--c-warn-muted') },
        signal:  { DEFAULT: rgb('--c-signal'),  muted: rgb('--c-signal-muted') },
        neutral: { DEFAULT: rgb('--c-neutral'), muted: rgb('--c-neutral-muted') },
      },
      fontFamily: {
        sans: ['DM Sans', 'Inter', 'system-ui', 'sans-serif'],
        heading: ['Syne', 'DM Sans', 'system-ui', 'sans-serif'],
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
        card: 'var(--shadow-card)',
        glow: 'var(--shadow-glow)',
      },
    },
  },
  plugins: [],
}
