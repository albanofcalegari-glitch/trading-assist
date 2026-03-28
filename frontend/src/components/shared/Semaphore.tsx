import { cn } from '@/lib/utils'

type Color = 'up' | 'down' | 'warn' | 'neutral' | 'signal'

interface Props {
  color:   Color
  label?:  string
  size?:   'sm' | 'md' | 'lg'
  pulse?:  boolean
}

const COLOR_MAP: Record<Color, string> = {
  up:      'bg-up',
  down:    'bg-down',
  warn:    'bg-warn',
  neutral: 'bg-neutral',
  signal:  'bg-signal',
}

const LABEL_MAP: Record<Color, string> = {
  up:      'text-up',
  down:    'text-down',
  warn:    'text-warn',
  neutral: 'text-neutral',
  signal:  'text-signal',
}

const SIZE_MAP = { sm: 'w-2 h-2', md: 'w-2.5 h-2.5', lg: 'w-3 h-3' }

export default function Semaphore({ color, label, size = 'md', pulse }: Props) {
  return (
    <div className="inline-flex items-center gap-1.5">
      <span className={cn(
        'rounded-full shrink-0',
        SIZE_MAP[size],
        COLOR_MAP[color],
        pulse && 'animate-pulse',
      )} />
      {label && (
        <span className={cn('text-xs font-medium', LABEL_MAP[color])}>
          {label}
        </span>
      )}
    </div>
  )
}

/** Badge semáforo con fondo */
export function SemaphoreBadge({ color, label }: { color: Color; label: string }) {
  const BG: Record<Color, string> = {
    up:      'bg-up/10 text-up border-up/20',
    down:    'bg-down/10 text-down border-down/20',
    warn:    'bg-warn/10 text-warn border-warn/20',
    neutral: 'bg-neutral/10 text-neutral border-neutral/20',
    signal:  'bg-signal/10 text-signal border-signal/20',
  }
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs font-medium',
      BG[color],
    )}>
      <span className={cn('w-1.5 h-1.5 rounded-full', COLOR_MAP[color])} />
      {label}
    </span>
  )
}
