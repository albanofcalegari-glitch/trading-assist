/**
 * TradingViewChart — Widget oficial de TradingView embebido en React.
 *
 * MODO: solo visualización embebida (caja cerrada).
 *   - Sin overlays custom propios: no se dibujan soportes, resistencias,
 *     canales ni señales de nuestra lógica encima de este widget.
 *   - Los datos son de TradingView, no de la BD propia.
 *   - La escala logarítmica la activa el usuario desde la UI del widget
 *     (clic derecho en el eje Y → "Escala logarítmica").
 *   - No se puede acceder a los datos de velas desde JS.
 *
 * LICENCIA: revisar los términos y condiciones de TradingView antes de
 *   cualquier uso productivo o comercial del widget embebido.
 *   https://www.tradingview.com/widget-docs/
 */

import { useEffect, useRef } from 'react'

// ── Tipos globales ────────────────────────────────────────────────────────────

declare global {
  interface Window {
    TradingView?: {
      widget: new (config: TradingViewConfig) => TradingViewInstance
    }
  }
}

interface TradingViewConfig {
  container_id:       string
  symbol:             string
  interval:           string
  timezone:           string
  theme:              'light' | 'dark'
  style:              string
  locale:             string
  autosize:           boolean
  enable_publishing:  boolean
  allow_symbol_change:boolean
  hide_top_toolbar:   boolean
  hide_side_toolbar:  boolean
  save_image:         boolean
  studies?:           string[]
  toolbar_bg?:        string
  withdateranges?:    boolean
  show_popup_button?: boolean
}

interface TradingViewInstance {
  remove?: () => void
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface TradingViewChartProps {
  /** Símbolo completo TradingView: "NASDAQ:GOOGL", "NYSE:BABA", "NASDAQ:MELI" */
  symbol:   string
  /** Temporalidad: D=diario, W=semanal, M=mensual, 60=1h, 15=15m */
  interval?: 'D' | 'W' | 'M' | '60' | '30' | '15' | '5'
  theme?:    'light' | 'dark'
  height?:   number
  /** Si true, oculta la barra de herramientas superior */
  hideToolbar?: boolean
  /** Indicadores a mostrar por defecto, ej: ["RSI@tv-basicstudies"] */
  studies?: string[]
}

const TV_SCRIPT_URL = 'https://s3.tradingview.com/tv.js'

// ── Componente ────────────────────────────────────────────────────────────────

export default function TradingViewChart({
  symbol,
  interval     = 'D',
  theme        = 'dark',
  height       = 520,
  hideToolbar  = false,
  studies      = [],
}: TradingViewChartProps) {
  // ID estable por instancia (no cambia entre re-renders)
  const idRef        = useRef(`tv_${Math.random().toString(36).slice(2, 9)}`)
  const containerRef = useRef<HTMLDivElement>(null)
  const instanceRef  = useRef<TradingViewInstance | null>(null)

  useEffect(() => {
    const containerId = idRef.current

    function initWidget() {
      if (!window.TradingView || !containerRef.current) return

      // Limpiar instancia anterior si existe
      if (containerRef.current) containerRef.current.innerHTML = ''

      instanceRef.current = new window.TradingView.widget({
        container_id:        containerId,
        symbol,
        interval,
        timezone:            'America/New_York',
        theme,
        style:               '1',          // 1 = velas japonesas
        locale:              'es',
        autosize:            true,
        enable_publishing:   false,
        allow_symbol_change: true,
        hide_top_toolbar:    hideToolbar,
        hide_side_toolbar:   false,
        save_image:          false,
        withdateranges:      true,
        show_popup_button:   false,
        toolbar_bg:          theme === 'dark' ? '#131722' : '#f0f3fa',
        studies,
      })
    }

    // Si el script ya está cargado, inicializar directo
    if (window.TradingView) {
      initWidget()
      return
    }

    // Evitar cargar el script dos veces si otro componente lo está cargando
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${TV_SCRIPT_URL}"]`
    )

    if (existing) {
      // Ya existe el tag pero aún no terminó de cargar
      existing.addEventListener('load', initWidget)
      return () => existing.removeEventListener('load', initWidget)
    }

    // Cargar script por primera vez
    const script = document.createElement('script')
    script.src   = TV_SCRIPT_URL
    script.async = true
    script.onload = initWidget
    document.head.appendChild(script)

    return () => {
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [symbol, interval, theme, hideToolbar, studies])

  return (
    <div className="w-full">
      {/* Nota: visualización externa, sin overlays de nuestra lógica */}
      <p className="text-2xs text-text-muted px-2 pb-1 italic">
        TradingView Live: visualización externa, sin overlays propios
      </p>
      <div
        id={idRef.current}
        ref={containerRef}
        style={{ height }}
        className="w-full rounded-lg overflow-hidden"
      />
    </div>
  )
}
