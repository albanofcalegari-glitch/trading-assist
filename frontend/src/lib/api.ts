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

export async function setInvestorProfileApi(profile: 'conservador' | 'moderado' | 'agresivo') {
  const res = await fetch(BASE + '/auth/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ profile }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al guardar perfil')
  return data as { ok: boolean; investor_profile: 'conservador' | 'moderado' | 'agresivo' }
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

export interface TrendPullbackSignal {
  fecha:             string
  simbolo:           string
  trend_score:       number
  pullback_score:    number
  setup_state:       string
  context_alignment: string
  decision:          string  // 'BUY_CANDIDATE' | 'WATCHLIST' | 'NO_ACTION' | 'AVOID'
  confidence_level:  string
  allow_trade:       0 | 1
  reading:           string
  price:             number | null
  gap_pct:           number | null
}

export interface Fundamentals {
  symbol:              string
  market_cap:          number | null
  currency:            string | null
  revenue_ttm:         number | null
  gross_margin:        number | null
  operating_margin:    number | null
  profit_margin:       number | null
  net_income_ttm:      number | null
  total_cash:          number | null
  total_debt:          number | null
  debt_to_equity:      number | null
  revenue_growth_yoy:  number | null
  earnings_growth_yoy: number | null
  trailing_pe:         number | null
  forward_pe:          number | null
  price_to_book:       number | null
  ev_to_ebitda:        number | null
  dividend_yield:      number | null
  dividend_rate:       number | null
  last_earnings_date:  string | null
  next_earnings_date:  string | null
  updated_at:          number | null
}

export interface MarketContext {
  fecha:             string | null
  vix_level:         number | null
  vix_percentile_1y: number | null
  spy_return_5d:     number | null
  spy_return_20d:    number | null
  yield_10y:         number | null
  market_regime:     number | null
  // Nuevos: epoch unix segundos del último fetch live, y origen
  updated_at?:       number | null
  source?:           'live' | 'db_fallback'
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

export interface DynamicSupportTier {
  status:           'ACTIVE' | 'TESTING' | 'BROKEN'
  anchor1:          { fecha: string; value: number }
  anchor2:          { fecha: string; value: number }
  line_points:      { fecha: string; value: number }[]
  current_value:    number
  distance_pct:     number
  slope_annual_pct: number
  touches:          number
  violations:       number
  // 'horizontal' indica lateralizacion reciente; el chart la dibuja como ZONA
  // (piso + tope) en vez de linea.  Default 'ascending' para compat.
  kind?:            'ascending' | 'horizontal'
  zone_top?:        number  // solo si kind='horizontal'
  fallback?:        boolean // true = solo 2 toques (no hubo recta valida de 3+)
  touch_points?:    { fecha: string; value: number }[]
}

export interface DynamicSupports {
  symbol:         string
  timeframe_used: string | null
  bars_of_data:   number
  price:          number | null
  long:           DynamicSupportTier | null
  mid:            DynamicSupportTier | null
  short:          DynamicSupportTier | null
}

export interface DynamicResistanceTier {
  status:           'ACTIVE' | 'TESTING' | 'BROKEN'
  anchor1:          { fecha: string; value: number }
  anchor2:          { fecha: string; value: number }
  line_points:      { fecha: string; value: number }[]
  current_value:    number
  distance_pct:     number
  slope_annual_pct: number
  touches:          number
  violations:       number
  // 'horizontal' indica lateralizacion reciente bajo un techo; se dibuja como
  // ZONA (zone_floor + zone_ceiling). Default 'descending' para compat.
  kind?:            'descending' | 'horizontal'
  zone_floor?:      number  // piso de la banda (solo kind='horizontal')
  zone_ceiling?:    number  // techo = la resistencia (solo kind='horizontal')
  fallback?:        boolean
  touch_points?:    { fecha: string; value: number }[]
}

export interface DynamicResistances {
  symbol:         string
  timeframe_used: string | null
  bars_of_data:   number
  price:          number | null
  long:           DynamicResistanceTier | null
  mid:            DynamicResistanceTier | null
  short:          DynamicResistanceTier | null
}

export interface ChannelBreakdownZone {
  zone_low:        number
  zone_high:       number
  floor:           number
  ceiling:         number
  touches:         number
  first_touch:     string
  last_touch:      string
  max_bounce_pct:  number
}

export interface ChannelBreakdownScenario {
  scenario:      'BOUNCE_RETEST' | 'NEW_FLOOR' | 'BREAKDOWN' | 'ABOVE_ZONE' | 'BELOW_ZONE'
  scenario_num:  number
  signal:        'BUY' | 'SELL' | 'WAIT' | 'SKIP'
  description:   string
  entry:         number | null
  sl:            number | null
  sl_pct:        number | null
  zone:          ChannelBreakdownZone | null
}

export interface ChannelBreakdown {
  symbol:         string
  fecha:          string
  has_breakdown:  boolean
  channel:        ChannelItem | null
  price?:         number
  channel_lower?: number
  zones:          ChannelBreakdownZone[]
  scenarios?:     ChannelBreakdownScenario[]
  best_scenario:  ChannelBreakdownScenario | null
  near_support?:  boolean
  reading:        string
}

export interface UtBotPoint {
  fecha: string
  value: number
  state: 'UP' | 'DOWN'
}

export interface UtBotSignal {
  fecha: string
  kind:  'BUY' | 'SELL'
  price: number
}

export interface PivotsResponse {
  symbol:      string
  tf:          string
  pivot_lows:  { fecha: string; value: number }[]
  pivot_highs: { fecha: string; value: number }[]
}

export interface UtBotResponse {
  symbol:       string
  sensitivity:  number
  atr_period:   number
  bars_of_data: number
  points:       UtBotPoint[]
  signals:      UtBotSignal[]
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
  strength:        'weak' | 'normal' | 'strong'
  rank:            'primary' | 'secondary' | 'tertiary'
  pivots:          { fecha: string; price: number }[]
}

export interface ChannelItem {
  simbolo:          string
  fecha:            string
  channel_type:     'ASCENDING' | 'DESCENDING' | 'HORIZONTAL' | null
  upper_now:        number
  lower_now:        number
  width_pct:        number
  position:         number
  containment:      number
  slope_annual_pct: number
  decision:         string
  reading:          string
  pivot_highs_count: number
  pivot_lows_count:  number
  low_touches:      number
  up_touches:       number
  score:            number
  line_origin:      string
  line_slope:       number
  line_ic_lower:    number
  line_ic_upper:    number
  horizon:          'long' | 'medium' | 'short' | 'micro'
}

export interface ChannelData {
  symbol:   string
  channels: ChannelItem[]
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

export interface HistoricalLowSignal {
  fecha:              string
  simbolo:            string
  price:              number
  low_52w:            number
  low_52w_date:       string
  low_52w_days_ago:   number
  distance_52w_pct:   number | null
  low_all:            number
  low_all_date:       string
  distance_all_pct:   number | null
  is_all_time_low:    boolean
  setup_state:        string   // 'NO_SIGNAL' | 'NEAR_52W_LOW' | 'AT_52W_LOW' | 'NEW_52W_LOW'
  decision:           string
  confidence_level:   string
  reading:            string
  rsi14:              number | null
  mom20:              number | null
  sma200:             number | null
}

export interface HistoricalHighSignal {
  fecha:              string
  simbolo:            string
  price:              number
  high_52w:           number
  high_52w_date:      string
  high_52w_days_ago:  number
  distance_52w_pct:   number | null
  high_all:           number
  high_all_date:      string
  distance_all_pct:   number | null
  is_all_time_high:   boolean
  setup_state:        string   // 'NO_SIGNAL' | 'NEAR_52W_HIGH' | 'AT_52W_HIGH' | 'NEW_52W_HIGH'
  decision:           string
  confidence_level:   string
  reading:            string
  rsi14:              number | null
  mom20:              number | null
  sma200:             number | null
}

export interface Notification {
  id:               number
  batch_run_id:     number | null
  kind:             string            // 'close' | 'pre_market' | 'opening' | 'midday' | 'weekly_rank' | 'historical_lows' | 'watchlist' | 'watchlist_summary'
  title:            string
  body:             string
  data:             any | null
  created_at:       string
  read_at:          string | null
  user_id:          number | null
  accion_id:        number | null
  signal_code:      string | null     // 'UT_BOT' | 'NEAR_DYN_SUPPORT' | 'NEAR_LT_SUPPORT' | 'NEAR_LT_RESISTANCE' | '52W_LOW' | '52W_HIGH' | 'TREND_PULLBACK'
  signal_direction: 'BUY' | 'SELL' | null
  accion_simbolo:   string | null
}

export interface AssetSignal {
  id:               number
  kind:             string
  title:            string
  body:             string
  signal_code:      string | null
  signal_direction: 'BUY' | 'SELL' | null
  created_at:       string
  read_at:          string | null
}

export interface AssetSignalsResponse {
  items:            AssetSignal[]
  telegram_alerts:  boolean
  in_watchlist:     boolean
}

export interface CompanyInfo {
  symbol: string
  status: 'OK' | 'NO_DATA'
  profile?: {
    long_name?:   string | null
    sector?:      string | null
    industry?:    string | null
    website?:     string | null
    country?:     string | null
    employees?:   number | null
    description?: string | null
  }
  health?: {
    score?:          number | null
    label?:          string | null
    profit_margin?:  number | null
    roe?:            number | null
    debt_to_equity?: number | null
    current_ratio?:  number | null
    free_cashflow?:  number | null
    total_cash?:     number | null
    total_debt?:     number | null
  }
  growth?: {
    revenue_growth?:  number | null
    earnings_growth?: number | null
  }
  valuation?: {
    trailing_pe?:   number | null
    forward_pe?:    number | null
    peg_ratio?:     number | null
    price_to_book?: number | null
    market_cap?:    number | null
  }
  analyst?: {
    recommendation?:      string | null
    target_mean_price?:   number | null
    number_of_analysts?:  number | null
  }
  earnings_yearly?: { year: number | string | null; revenue: number | null; earnings: number | null }[]
  income_statements?: {
    end_date:         string | null
    total_revenue:    number | null
    gross_profit:     number | null
    operating_income: number | null
    net_income:       number | null
    ebit:             number | null
  }[]
}

export interface WatchlistItem {
  id:                number
  accion_id:         number
  simbolo:           string
  nombre:            string
  mercado:           string
  qty:               number | null
  avg_buy_price:     number | null
  stop_loss:         number | null
  take_profit:       number | null
  note:              string | null
  precio:            number | null
  pct_cambio_dia:    number | null
  pct_cambio_semana: number | null
  valor_corriente:   number | null
  ganancia_abs:      number | null
  ganancia_pct:      number | null
  added_at:          string | null
}

export interface WatchlistInput {
  accion_id:      number
  qty?:           number | null
  avg_buy_price?: number | null
  stop_loss?:     number | null
  take_profit?:   number | null
  note?:          string | null
}

export interface WatchlistPatch {
  qty?:           number | null
  avg_buy_price?: number | null
  stop_loss?:     number | null
  take_profit?:   number | null
  note?:          string | null
}

export interface Trade {
  id:         number
  accion_id:  number
  simbolo:    string
  nombre:     string
  mercado:    string
  qty:        number
  buy_price:  number
  buy_date:   string
  sell_price: number | null
  sell_date:  string | null
  fee:        number
  note:       string | null
  gross_pnl:  number | null
  net_pnl:    number | null
  pct:        number | null
  created_at: string | null
}

export interface TradeInput {
  accion_id:   number
  qty:         number
  buy_price:   number
  buy_date:    string
  sell_price?: number | null
  sell_date?:  string | null
  fee?:        number
  note?:       string | null
}

export interface TradePatch {
  qty?:         number
  buy_price?:   number
  buy_date?:    string
  sell_price?:  number | null
  sell_date?:   string | null
  fee?:         number
  note?:        string | null
}

export type PriceLevelKind = 'support' | 'resistance' | 'target' | 'note'

export interface PriceLevel {
  id:         number
  accion_id:  number
  price:      number
  kind:       PriceLevelKind
  label:      string | null
  created_at: string | null
}

export interface PriceLevelInput {
  accion_id: number
  price:     number
  kind:      PriceLevelKind
  label?:    string | null
}

export interface PriceLevelPatch {
  price?: number
  kind?:  PriceLevelKind
  label?: string | null
}

// ── Trendlines (polyline de N puntos, N>=2) ─────────────────────────────────
// kind reutiliza los 4 tipos de price_levels para consistencia de colores.
export type TrendlineKind = PriceLevelKind

export interface TrendlinePoint {
  t: string    // 'YYYY-MM-DD'
  p: number
}

export interface Trendline {
  id:         number
  accion_id:  number
  points:     TrendlinePoint[]   // ordenados por t ascendente, N>=2
  kind:       TrendlineKind
  label:      string | null
  created_at: string | null
}

export interface TrendlineInput {
  accion_id: number
  points:    TrendlinePoint[]
  kind:      TrendlineKind
  label?:    string | null
}

export interface TrendlinePatch {
  kind?:  TrendlineKind
  label?: string | null
}

// ── SR Engine V2 ─────────────────────────────────────────────────────────────

export interface SRV2Pivot {
  fecha: string
  price: number
  strength: number
}

export interface SRV2HorizontalLevel {
  id:                 string
  kind:               'horizontal'
  role:               'support' | 'resistance'
  center_price:       number
  zone_min:           number
  zone_max:           number
  time_start:         string
  time_end:           string
  touches:            number
  score:              number
  state:              string   // 'active' | 'tested' | 'weakening' | 'broken' | 'invalidated' | 'flipped'
  source_pivot_count: number
  avg_bounce_pct:     number
  explanation:        string
}

export interface SRV2Trendline {
  id:                  string
  kind:                'diagonal'
  role:                'support' | 'resistance'
  classification:      'structural' | 'acceleration'
  x1:                  string
  y1:                  number
  x2:                  string
  y2:                  number
  touches:             number
  violations:          number
  slope_annual_pct:    number
  score:               number
  state:               string
  distance_pct:        number
  current_value:       number
  line_points:         { fecha: string; value: number }[]
  zone_upper_points:   { fecha: string; value: number }[]
  zone_lower_points:   { fecha: string; value: number }[]
  explanation:         string
}

export interface SRV2Result {
  symbol:       string
  timeframe:    string
  bars:         number
  price:        number | null
  atr:          number | null
  supports:     SRV2HorizontalLevel[]
  resistances:  SRV2HorizontalLevel[]
  trendlines:   SRV2Trendline[]
  pivots_high:  SRV2Pivot[]
  pivots_low:   SRV2Pivot[]
  config:       Record<string, number | boolean>
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

// ── Elliott Wave types ─────────────────────────────────────────────────────────

export interface ElliottWavePoint {
  label:     string
  fecha:     string
  price:     number
  bar_index: number
}

export interface ElliottFibLevel {
  label: string
  price: number
  ratio: string
}

export interface ElliottResult {
  symbol:              string
  fecha:               string
  wave_count:          ElliottWavePoint[]
  current_wave:        string
  current_wave_label:  string
  signal:              'BUY' | 'SELL' | 'HOLD'
  signal_reason:       string
  confidence:          number
  rules_valid:         boolean
  rules_detail?:       Record<string, boolean>
  fib_targets:         ElliottFibLevel[]
  fib_levels:          ElliottFibLevel[]
  zigzag_pivots:       { fecha: string; price: number; type: 'high' | 'low' }[]
  bullish:             boolean
  direction:           string
  price?:              number
  error?:              string
}

export interface ElliottScanItem {
  accion_id:          number
  simbolo:            string
  nombre:             string
  signal:             string
  current_wave:       string
  current_wave_label: string
  confidence:         number
  direction:          string
  price:              number
}

export interface TrendSma200Item {
  simbolo:      string
  nombre:       string
  accion_id:    number | null
  price:        number
  sma200:       number
  distance_pct: number
  trend:        'ALCISTA' | 'BAJISTA'
}

// ── Bonds types ───────────────────────────────────────────────────────────────

export interface BondAnalysis {
  symbol:          string
  law:             string
  maturity:        string
  price_clean:     number
  price_dirty:     number
  tir:             number
  paridad:         number
  duration_mod:    number
  accrued_interest: number
  z_score:         number | null
  signal:          string | null
  avg_tir:         number | null
  std_tir:         number | null
}

export interface BondSpread {
  al:              string
  gd:              string
  spread_bps:      number
  spread_z:        number | null
  spread_signal:   string | null
  avg_spread:      number | null
}

export interface BondsDashboard {
  bonds:   BondAnalysis[]
  spreads: BondSpread[]
  fecha:   string
}

export interface BondHistoryRow {
  fecha:        string
  price_usd:    number | null
  price_ars:    number | null
  bid_usd:      number | null
  ask_usd:      number | null
  volume:       number | null
  tir:          number | null
  paridad:      number | null
  duration_mod: number | null
  z_score:      number | null
  signal:       string | null
}

export interface BondCurvePoint {
  symbol:       string
  law:          string
  maturity:     string
  tir:          number
  paridad:      number | null
  duration_mod: number | null
}

export interface SpreadHistoryRow {
  fecha:      string
  al_tir:     number
  gd_tir:     number
  spread_bps: number
}

export interface SpreadPair {
  al:      string
  gd:      string
  history: SpreadHistoryRow[]
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

  dynamicSupports: (id: number, tf?: 'D' | 'W') =>
    get<DynamicSupports>(`/assets/${id}/dynamic-supports${tf ? `?tf=${tf}` : ''}`),

  dynamicResistances: (id: number, tf?: 'D' | 'W') =>
    get<DynamicResistances>(`/assets/${id}/dynamic-resistances${tf ? `?tf=${tf}` : ''}`),

  pivots: (id: number, tf: 'D' | 'W' = 'W') =>
    get<PivotsResponse>(`/assets/${id}/pivots?tf=${tf}`),

  utBot: (id: number, sensitivity?: number, atrPeriod?: number) => {
    const qs = new URLSearchParams()
    if (sensitivity != null) qs.set('sensitivity', String(sensitivity))
    if (atrPeriod   != null) qs.set('atr_period',  String(atrPeriod))
    const s = qs.toString()
    return get<UtBotResponse>(`/assets/${id}/ut-bot${s ? '?' + s : ''}`)
  },

  horizontalZones: (id: number) =>
    get<HorizontalZonesResponse>(`/assets/${id}/horizontal-zones`),

  channel: (id: number) =>
    get<ChannelData>(`/assets/${id}/channel`),

  channelBreakdown: (id: number) =>
    get<ChannelBreakdown>(`/assets/${id}/channel-breakdown`),

  companyInfo: (id: number) =>
    get<CompanyInfo>(`/assets/${id}/company-info`),

  trendPullbackSignal: (id: number) =>
    get<TrendPullbackSignal | null>(`/assets/${id}/trend-pullback-signal`),

  historicalLowSignal: (id: number) =>
    get<HistoricalLowSignal | null>(`/assets/${id}/historical-low-signal`),

  historicalHighSignal: (id: number) =>
    get<HistoricalHighSignal | null>(`/assets/${id}/historical-high-signal`),

  fundamentals: (id: number) =>
    get<Fundamentals>(`/assets/${id}/fundamentals`),

  notifications: (kind = '', limit = 50) =>
    get<{ items: Notification[] }>(
      `/notifications?limit=${limit}${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`
    ),

  notificationsUnread: () =>
    get<{ unread: number }>('/notifications/unread-count'),

  watchlist: () =>
    get<{ items: WatchlistItem[] }>('/watchlist'),

  trades: () =>
    get<{ items: Trade[] }>('/trades'),

  priceLevels: (accionId: number) =>
    get<{ items: PriceLevel[] }>(`/price-levels?accion_id=${accionId}`),

  trendlines: (accionId: number) =>
    get<{ items: Trendline[] }>(`/trendlines?accion_id=${accionId}`),

  srV2: (id: number) =>
    get<SRV2Result>(`/assets/${id}/sr-v2`),

  elliott: (id: number) =>
    get<ElliottResult>(`/assets/${id}/elliott`),

  elliottScan: (market = 'USA') =>
    get<{ items: ElliottScanItem[]; fecha: string; market: string }>(
      `/scan/elliott?market=${market}`
    ),

  trendsSma200Weekly: () =>
    get<{ items: TrendSma200Item[]; fecha: string; total: number; alcistas: number; bajistas: number }>(
      '/trends/sma200-weekly'
    ),

  bondsDashboard: () =>
    get<BondsDashboard>('/bonds/dashboard'),

  bondsHistory: (symbol: string, days = 90) =>
    get<{ symbol: string; history: BondHistoryRow[] }>(`/bonds/${symbol}/history?days=${days}`),

  bondsCurve: () =>
    get<{ curve: BondCurvePoint[]; fecha: string }>('/bonds/curve'),

  bondsSpreads: (days = 90) =>
    get<{ pairs: SpreadPair[] }>(`/bonds/spreads?days=${days}`),

  assetSignals: (id: number, limit = 30) =>
    get<AssetSignalsResponse>(`/assets/${id}/signals?limit=${limit}`),
}

export async function addWatchlist(input: WatchlistInput) {
  const res = await fetch(BASE + '/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al agregar a la watchlist')
  return data as { ok: boolean; id: number }
}

export async function updateWatchlist(id: number, patch: WatchlistPatch) {
  const res = await fetch(BASE + `/watchlist/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al actualizar')
  return data as { ok: boolean }
}

export async function deleteWatchlist(id: number) {
  const res = await fetch(BASE + `/watchlist/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al eliminar')
  return data as { ok: boolean }
}

export async function toggleTelegramAlert(accionId: number, enabled: boolean) {
  const res = await fetch(BASE + `/assets/${accionId}/telegram-alert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ enabled }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al cambiar alerta Telegram')
  return data as { ok: boolean; telegram_alerts: boolean }
}

export async function addTrade(input: TradeInput) {
  const res = await fetch(BASE + '/trades', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al crear movimiento')
  return data as { ok: boolean; id: number }
}

export async function updateTrade(id: number, patch: TradePatch) {
  const res = await fetch(BASE + `/trades/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al actualizar movimiento')
  return data as { ok: boolean }
}

export async function deleteTrade(id: number) {
  const res = await fetch(BASE + `/trades/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al eliminar movimiento')
  return data as { ok: boolean }
}

export async function addPriceLevel(input: PriceLevelInput) {
  const res = await fetch(BASE + '/price-levels', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al crear nivel')
  return data.item as PriceLevel
}

export async function updatePriceLevel(id: number, patch: PriceLevelPatch) {
  const res = await fetch(BASE + `/price-levels/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al actualizar nivel')
  return data.item as PriceLevel
}

export async function deletePriceLevel(id: number) {
  const res = await fetch(BASE + `/price-levels/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al eliminar nivel')
  return data as { ok: boolean }
}

export async function addTrendline(input: TrendlineInput) {
  const res = await fetch(BASE + '/trendlines', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al crear trendline')
  return data.item as Trendline
}

export async function updateTrendline(id: number, patch: TrendlinePatch) {
  const res = await fetch(BASE + `/trendlines/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al actualizar trendline')
  return data.item as Trendline
}

export async function deleteTrendline(id: number) {
  const res = await fetch(BASE + `/trendlines/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Error al eliminar trendline')
  return data as { ok: boolean }
}

export async function markNotificationRead(id: number) {
  const res = await fetch(BASE + `/notifications/${id}/read`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Error al marcar leída: ${res.status}`)
  return res.json()
}

export async function backfillAsset(accionId: number) {
  const res = await fetch(BASE + `/assets/${accionId}/backfill`, {
    method: 'POST',
    headers: authHeaders(),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || `Backfill error ${res.status}`)
  return data as { symbol: string; results: Record<string, unknown> }
}
