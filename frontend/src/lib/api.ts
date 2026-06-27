const BASE = '/api'

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { headers: authHeaders() })
  if (res.status === 401) {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    window.location.href = '/'
    throw new Error('Sesión expirada')
  }
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json()
}

export async function changePassword(current: string, newPassword: string) {
  const res = await fetch(BASE + '/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ current, new_password: newPassword }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al cambiar contraseña')
  return data
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

export interface LongtermSupport {
  symbol:         string
  timeframe_used: string
  status:         'ACTIVE' | 'TESTING' | 'BROKEN' | 'NO_SUPPORT'
  p1?:            { fecha: string; value: number } | null
  p2?:            { fecha: string; value: number } | null
  line_points:    { fecha: string; value: number }[]
  current_value?: number | null
  distance_pct?:  number | null
  bars_of_data?:  number
  touch_count?:   number
  reading?:       string
  // Resistencia estructural (v2)
  resistance_status?:          'ACTIVE' | 'TESTING' | 'BROKEN' | 'NO_SUPPORT'
  resistance_p1?:              { fecha: string; value: number } | null
  resistance_p2?:              { fecha: string; value: number } | null
  resistance_line_points?:     { fecha: string; value: number }[]
  resistance_current_value?:   number | null
  resistance_distance_pct?:    number | null
  resistance_touch_count?:     number
  resistance_reading?:         string
  // Active support (v3)
  active_status?:              'ACTIVE' | 'TESTING' | 'BROKEN' | 'NO_SUPPORT'
  active_p1?:                  { fecha: string; value: number } | null
  active_p2?:                  { fecha: string; value: number } | null
  active_line_points?:         { fecha: string; value: number }[]
  active_current_value?:       number | null
  active_distance_pct?:        number | null
  active_touch_count?:         number
  active_reading?:             string
  // Active resistance (v3)
  active_resistance_status?:          'ACTIVE' | 'TESTING' | 'BROKEN' | 'NO_SUPPORT'
  active_resistance_p1?:              { fecha: string; value: number } | null
  active_resistance_p2?:              { fecha: string; value: number } | null
  active_resistance_line_points?:     { fecha: string; value: number }[]
  active_resistance_current_value?:   number | null
  active_resistance_distance_pct?:    number | null
  active_resistance_touch_count?:     number
  active_resistance_reading?:         string
}

export interface HorizontalZone {
  zone_low:        number
  zone_high:       number
  center:          number
  total_touches:   number
  recent_touches:  number
  distance_pct:    number
  last_touch:      string
  first_touch:     string
  score:           number
  type:            'support' | 'resistance'
  rank:            'primary' | 'secondary' | 'tertiary'
  pivots:          { fecha: string; price: number }[]
}

export interface HorizontalZonesResponse {
  symbol:           string
  fecha:            string
  current_price:    number | null
  support_zones:    HorizontalZone[]
  resistance_zones: HorizontalZone[]
  timeframe:        string
  status:           string
  pivot_lows_found:  number
  pivot_highs_found: number
}

// ── Tiered S/R (behavioral classification) ─────────────────────────────────
export interface TieredSRTier {
  classification:    'historical' | 'accelerated' | 'tactical'
  timeframe_used:    string
  status:            'ACTIVE' | 'TESTING' | 'BROKEN'
  kind:              'ascending' | 'descending' | 'horizontal'
  anchor1:           { fecha: string; value: number }
  anchor2:           { fecha: string; value: number }
  line_points:       { fecha: string; value: number }[]
  touch_points:      { fecha: string; value: number }[]
  current_value:     number
  distance_pct:      number
  slope_annual_pct:  number
  touches:           number
  violations:        number
  stop_hint:         number
  zone_top?:         number
  zone_low?:         number
}

export interface TieredSRResponse {
  symbol:  string
  price:   number | null
  fecha:   string
  support: {
    historical:  TieredSRTier | null
    accelerated: TieredSRTier | null
    tactical:    TieredSRTier | null
  }
  resistance: {
    historical:  TieredSRTier | null
    accelerated: TieredSRTier | null
    tactical:    TieredSRTier | null
  }
  acceleration: {
    support:    { detected: boolean; direction: string | null; distance_from_structural_pct: number }
    resistance: { detected: boolean; direction: string | null; distance_from_structural_pct: number }
  }
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

  ohlcvExtended: (id: number, tf: 'D' | 'W' | 'M' = 'D') =>
    get<{ candles: Candle[]; tf: string }>(`/assets/${id}/ohlcv-extended?tf=${tf}`),

  indicators: (id: number, days = 365) =>
    get<{ indicators: Indicator[] }>(`/assets/${id}/indicators?days=${days}`),

  wmaCross: (market = 'USA', top = 5, trend = false) =>
    get<{ setup: WmaCrossItem[]; cross: WmaCrossItem[]; fecha: string }>(
      `/scan/wma-cross?market=${market}&top=${top}&trend=${trend}`
    ),

  marketContext: () =>
    get<MarketContext>('/market-context'),

  longtermSupport: (id: number, horizon = 'long_term') =>
    get<LongtermSupport>(`/assets/${id}/longterm-support?horizon=${horizon}`),

  horizontalZones: (id: number) =>
    get<HorizontalZonesResponse>(`/assets/${id}/horizontal-zones`),

  tieredSR: (id: number) =>
    get<TieredSRResponse>(`/assets/${id}/tiered-sr`),
}
