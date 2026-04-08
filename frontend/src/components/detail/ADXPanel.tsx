/**
 * ADXPanel — Panel de ADX (Average Directional Index).
 *
 * Muestra:
 *   - Linea ADX (amarilla, gruesa)            — fuerza de tendencia
 *   - Linea +DI (verde, fina, baja opacidad)  — presion compradora
 *   - Linea -DI (roja, fina, baja opacidad)   — presion vendedora
 *   - Niveles 25 (umbral tendencia) y 40 (tendencia fuerte)
 *
 * Lectura rapida:
 *   ADX < 20  → Sin tendencia (rangoso)
 *   20-40     → Tendencia en formacion
 *   > 40      → Tendencia fuerte
 */

import { useEffect, useRef, useState } from 'react'
import {
  createChart, ColorType, CrosshairMode, LineStyle,
  type IChartApi,
} from 'lightweight-charts'
import { Info } from 'lucide-react'
import type { Candle } from '@/lib/utils'

interface Props {
  candles:  Candle[]
  adx:     (number | null)[]
  plusDI:  (number | null)[]
  minusDI: (number | null)[]
  height?: number
}

const BG     = '#0b0d11'
const BORDER = '#1e2535'
const TEXT   = '#7c8ca1'

export default function ADXPanel({ candles, adx, plusDI, minusDI, height = 180 }: Props) {
  const ref      = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [showHelp, setShowHelp] = useState(false)

  useEffect(() => {
    if (!ref.current || !candles.length) return
    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null }

    const el    = ref.current
    const chart = createChart(el, {
      width:     el.clientWidth,
      height,
      watermark: { visible: false },
      layout: {
        background: { type: ColorType.Solid, color: BG },
        textColor:  TEXT,
        fontFamily: 'JetBrains Mono, monospace',
        fontSize:   10,
        attributionLogo: false,
      } as any,
      grid: {
        vertLines: { color: BORDER, style: 0 },
        horzLines: { color: BORDER, style: 0 },
      },
      crosshair: {
        mode:     CrosshairMode.Normal,
        vertLine: { color: '#334155', labelBackgroundColor: BORDER },
        horzLine: { color: '#334155', labelBackgroundColor: BORDER },
      },
      rightPriceScale: {
        borderColor:  BORDER,
        textColor:    TEXT,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor:    BORDER,
        timeVisible:    true,
        secondsVisible: false,
        tickMarkFormatter: (t: any) => {
          const str = typeof t === 'string' ? t : new Date(t * 1000).toISOString().slice(0, 10)
          const [y, m, d] = str.split('-').map(Number)
          return new Date(y, m - 1, d).toLocaleDateString('es', { day: 'numeric', month: 'short' })
        },
      },
    })
    chartRef.current = chart

    // Fallback DOM-hide del logo TradingView en versiones viejas
    const hideLogo = () => {
      el.querySelectorAll('a').forEach(a => {
        if (a.href.includes('tradingview')) (a as HTMLElement).style.display = 'none'
      })
    }
    hideLogo()
    setTimeout(hideLogo, 200)

    // -- ADX line (amarilla, mas gruesa: protagonista) --
    const adxSeries = chart.addLineSeries({
      color:            '#facc15',
      lineWidth:        3,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    })
    adxSeries.setData(
      candles
        .map((c, i) => ({ time: c.fecha as any, value: adx[i] }))
        .filter(p => p.value != null) as { time: any; value: number }[]
    )

    // -- +DI line (verde, fina, baja opacidad — secundaria) --
    const plusSeries = chart.addLineSeries({
      color:            'rgba(34,197,94,0.45)',
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    plusSeries.setData(
      candles
        .map((c, i) => ({ time: c.fecha as any, value: plusDI[i] }))
        .filter(p => p.value != null) as { time: any; value: number }[]
    )

    // -- -DI line (roja, fina, baja opacidad — secundaria) --
    const minusSeries = chart.addLineSeries({
      color:            'rgba(239,68,68,0.45)',
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    minusSeries.setData(
      candles
        .map((c, i) => ({ time: c.fecha as any, value: minusDI[i] }))
        .filter(p => p.value != null) as { time: any; value: number }[]
    )

    // Niveles horizontales con etiquetas legibles
    const levels: [number, string, string][] = [
      [40, 'rgba(250,204,21,0.45)', 'Tend. fuerte'],
      [25, 'rgba(100,116,139,0.40)', 'Sin tend.'],
    ]
    for (const [price, color, title] of levels) {
      adxSeries.createPriceLine({
        price, color, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, title,
      })
    }

    // -- Responsive --
    const ro = new ResizeObserver(entries => {
      for (const e of entries) chart.applyOptions({ width: e.contentRect.width })
    })
    ro.observe(el)
    chart.timeScale().fitContent()

    return () => { ro.disconnect(); chart.remove(); chartRef.current = null }
  }, [candles, adx, plusDI, minusDI, height])

  const lastAdx     = lastNonNull(adx)
  const lastPlus    = lastNonNull(plusDI)
  const lastMinus   = lastNonNull(minusDI)
  const reading     = readAdx(lastAdx, lastPlus, lastMinus)

  return (
    <div className="card p-1 overflow-hidden relative">
      <div className="flex items-center gap-3 px-2 pt-1 pb-0.5 flex-wrap">
        <p className="text-2xs text-text-muted font-mono">ADX 14</p>

        {/* Lectura actual */}
        {reading && (
          <span className={`text-2xs font-medium px-1.5 py-0.5 rounded border ${reading.cls}`}>
            {reading.label}
          </span>
        )}

        <div className="flex items-center gap-2 text-2xs font-mono">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-[3px] rounded bg-[#facc15]" />ADX
            {lastAdx != null && <span className="text-text-muted">{lastAdx.toFixed(0)}</span>}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-px rounded bg-[#22c55e] opacity-50" />+DI
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-px rounded bg-[#ef4444] opacity-50" />-DI
          </span>
        </div>

        {/* Botón de ayuda */}
        <button
          type="button"
          onClick={() => setShowHelp(s => !s)}
          className="ml-auto text-text-muted hover:text-text-primary p-0.5 rounded transition-colors"
          title="Cómo leer el ADX"
        >
          <Info size={11} />
        </button>
      </div>

      {/* Tooltip explicativo */}
      {showHelp && (
        <div className="absolute right-2 top-7 z-10 w-64 card-elevated rounded-lg shadow-xl p-3 text-2xs text-text-secondary leading-relaxed border border-border">
          <p className="font-medium text-text-primary mb-1">ADX (14)</p>
          <p>Mide la <span className="text-text-primary">fuerza</span> de la tendencia (no su dirección).</p>
          <ul className="mt-1.5 space-y-0.5">
            <li><span className="font-mono text-text-primary">&lt; 20</span> — sin tendencia, mercado en rango</li>
            <li><span className="font-mono text-text-primary">20-40</span> — tendencia en formación</li>
            <li><span className="font-mono text-text-primary">&gt; 40</span> — tendencia fuerte</li>
          </ul>
          <p className="mt-1.5">+DI &gt; −DI: presión compradora · −DI &gt; +DI: presión vendedora.</p>
        </div>
      )}

      <div ref={ref} style={{ height }} className="w-full" />
    </div>
  )
}

function lastNonNull(arr: (number | null)[]): number | null {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i] != null) return arr[i] as number
  }
  return null
}

function readAdx(
  adx: number | null,
  plus: number | null,
  minus: number | null,
): { label: string; cls: string } | null {
  if (adx == null) return null
  const dir = plus != null && minus != null
    ? (plus > minus ? ' (compradora)' : ' (vendedora)')
    : ''
  if (adx < 20) return { label: 'Sin tendencia', cls: 'border-border text-text-muted bg-transparent' }
  if (adx < 40) return { label: `En formación${dir}`, cls: 'border-yellow-500/30 text-yellow-300 bg-yellow-500/10' }
  return { label: `Tendencia fuerte${dir}`, cls: 'border-emerald-500/30 text-emerald-300 bg-emerald-500/10' }
}
