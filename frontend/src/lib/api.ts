const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json()
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface Mover {
  accion_id: number
  simbolo:   string
  nombre:    string
  mercado:   string
  precio:    number
  pct_cambio: number
}

export interface Asset {
  accion_id:  number
  simbolo:    string
  nombre:     string
  mercado:    string
  precio:     number
  pct_cambio: number
  volumen?:   number
  fecha?:     string
}

export interface AssetDetail extends Asset {
  id: number
}

export interface Candle {
  fecha:  string
  open:   number
  high:   number
  low:    number
  close:  number
  volume: number
}

export interface Indicator {
  fecha:           string
  sma50:           number | null
  sma200:          number | null
  rsi14:           number | null
  atr14_rel:       number | null
  dist_sma200_pct: number | null
  momentum_5d:     number | null
  momentum_20d:    number | null
  volume_ratio_5d: number | null
  volume_ratio_20d: number | null
}

export interface MarketContext {
  fecha:             string
  vix_level:         number | null
  vix_percentile_1y: number | null
  spy_return_5d:     number | null
  spy_return_20d:    number | null
  yield_10y:         number | null
  market_regime:     number | null
}

export interface WmaCrossItem {
  accion_id: number
  simbolo:   string
  nombre:    string
  mercado:   string
  precio:    number
  wma6:      number
  wma30:     number
  gap_pct:   number
  vol:       number
  trend_up:  boolean
  tipo:      'SETUP_SWING' | 'CROSS_SWING_BUY'
  slope?:    number
}

// ── Endpoints ──────────────────────────────────────────────────────────────────

export const api = {
  movers: (market: string, direction: string, n = 5) =>
    get<{ items: Mover[] }>(`/movers?market=${market}&direction=${direction}&n=${n}`),

  assets: (market = '', search = '', page = 0, limit = 50) =>
    get<{ items: Asset[]; total: number; page: number; pages: number }>(
      `/assets?market=${market}&search=${encodeURIComponent(search)}&page=${page}&limit=${limit}`
    ),

  asset: (id: number) =>
    get<AssetDetail>(`/assets/${id}`),

  ohlcv: (id: number, days = 400) =>
    get<{ candles: Candle[] }>(`/assets/${id}/ohlcv?days=${days}`),

  indicators: (id: number, days = 365) =>
    get<{ indicators: Indicator[] }>(`/assets/${id}/indicators?days=${days}`),

  wmaCross: (market = 'USA', top = 5, trend = false) =>
    get<{ setup: WmaCrossItem[]; cross: WmaCrossItem[]; fecha: string }>(
      `/scan/wma-cross?market=${market}&top=${top}&trend=${trend}`
    ),

  marketContext: () =>
    get<MarketContext>('/market-context'),
}
