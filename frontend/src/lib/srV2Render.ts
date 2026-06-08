import type { SRV2Result, SRV2HorizontalLevel, SRV2Trendline } from './api'

// ── Types ────────────────────────────────────────────────────────────────────

export type VisualTier = 'primary' | 'secondary' | 'tertiary' | 'ghosted'

export interface V2RenderZone {
  id:            string
  kind:          'horizontal'
  role:          'support' | 'resistance'
  visual_tier:   VisualTier
  zone_min:      number
  zone_max:      number
  label:         string
  fill_color:    string
  border_color:  string
  label_color:   string
  border_width:  number
  border_style:  'solid' | 'dashed' | 'dotted'
  label_visible: boolean
  z_index:       number
  tooltip: {
    score:       number
    state:       string
    touches:     number
    bounce_pct:  number
    touch_quality_avg: number
    explanation: string
  }
}

export interface V2RenderDiagonal {
  id:            string
  kind:          'diagonal'
  role:          'support' | 'resistance'
  classification: string
  visual_tier:   VisualTier
  label:         string
  line_color:    string
  zone_color:    string
  label_color:   string
  line_width:    number
  line_style:    'solid' | 'dashed' | 'dotted'
  label_visible: boolean
  z_index:       number
  line_points:         { fecha: string; value: number }[]
  zone_upper_points:   { fecha: string; value: number }[]
  zone_lower_points:   { fecha: string; value: number }[]
  tooltip: {
    score:           number
    state:           string
    touches:         number
    violations:      number
    slope_annual_pct: number
    distance_pct:    number
    touch_quality_avg: number
    explanation:     string
  }
}

export type V2RenderObject = V2RenderZone | V2RenderDiagonal

// ── Config ───────────────────────────────────────────────────────────────────

const WEIGHTS = {
  normalized_score: 0.35,
  proximity:        0.25,
  timeframe:        0.15,
  state:            0.15,
  recency:          0.10,
}

const PROXIMITY_BANDS: [number, number][] = [
  [8,   1.00],
  [15,  0.80],
  [25,  0.55],
  [40,  0.30],
  [Infinity, 0.10],
]

const TF_SCORES: Record<string, number> = {
  W: 1.00, D: 0.85, '4H': 0.65, '1H': 0.45,
}

const STATE_SCORES: Record<string, number> = {
  active: 1.00, tested: 0.85, flipped: 0.75,
  weakening: 0.55, broken: 0.20, invalidated: 0.00,
}

const RECENCY_BANDS: [number, number][] = [
  [30,  1.00],
  [80,  0.75],
  [150, 0.45],
  [Infinity, 0.20],
]

const MIN_ACCEL_SCORE = 30
const MAX_DISTANCE_PCT = 40.0
const ACCEL_MAX_DISTANCE = 12.0
const STRUCTURAL_MAX_DISTANCE = 35.0
const MERGE_OVERLAP_THRESHOLD = 0.60
const BROKEN_RETEST_WINDOW = 15
const ATH_ATL_ATR_FACTOR = 0.5

const BORDER_WIDTH: Record<VisualTier, number> = {
  primary: 2, secondary: 2, tertiary: 1.5, ghosted: 1,
}
const BORDER_STYLE: Record<VisualTier, 'solid' | 'dashed' | 'dotted'> = {
  primary: 'solid', secondary: 'solid', tertiary: 'dashed', ghosted: 'dotted',
}
const LABEL_VISIBLE: Record<VisualTier, boolean> = {
  primary: true, secondary: true, tertiary: true, ghosted: false,
}
const Z_ORDER: Record<VisualTier, number> = {
  ghosted: 1, tertiary: 2, secondary: 3, primary: 4,
}

const PALETTE: Record<string, Record<VisualTier, { fill: string; border: string; label: string }>> = {
  support: {
    primary:   { fill: 'rgba(0,230,118,0.35)',  border: 'rgba(0,230,118,0.90)',  label: '#00e676' },
    secondary: { fill: 'rgba(0,230,118,0.22)',  border: 'rgba(0,230,118,0.75)',  label: '#00e676' },
    tertiary:  { fill: 'rgba(79,195,247,0.14)',  border: 'rgba(79,195,247,0.55)',  label: '#4fc3f7' },
    ghosted:   { fill: 'rgba(0,230,118,0.08)',  border: 'rgba(0,230,118,0.30)',  label: '#00e67699' },
  },
  resistance: {
    primary:   { fill: 'rgba(239,68,68,0.35)',  border: 'rgba(239,68,68,0.90)',  label: '#ef4444' },
    secondary: { fill: 'rgba(239,68,68,0.22)',  border: 'rgba(239,68,68,0.75)',  label: '#ef4444' },
    tertiary:  { fill: 'rgba(251,146,60,0.14)',  border: 'rgba(251,146,60,0.55)',  label: '#fb923c' },
    ghosted:   { fill: 'rgba(239,68,68,0.08)',  border: 'rgba(239,68,68,0.30)',  label: '#ef444499' },
  },
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function bandLookup(bands: [number, number][], value: number): number {
  for (const [max, score] of bands) {
    if (value <= max) return score
  }
  return bands[bands.length - 1][1]
}

function roundPrice(price: number): string {
  if (price >= 100) return Math.round(price).toString()
  if (price >= 10) return price.toFixed(1)
  return price.toFixed(2)
}

function formatLabel(role: string, kind: string, classification: string, zoneMin: number, zoneMax: number): string {
  const roleAbbr = role === 'support' ? 'S' : 'R'
  let classAbbr: string
  if (kind === 'horizontal') classAbbr = 'Hz'
  else if (classification === 'structural') classAbbr = 'TD'
  else if (classification === 'acceleration') classAbbr = 'Acc'
  else classAbbr = 'Hist'
  return `${roleAbbr} ${classAbbr} · ${roundPrice(zoneMin)}–${roundPrice(zoneMax)}`
}

// ── Internal working type ───────────────────────────────────────────────────

interface WorkingLevel {
  id:               string
  kind:             'horizontal' | 'diagonal'
  role:             'support' | 'resistance'
  classification:   string
  center_price:     number
  zone_min:         number
  zone_max:         number
  score:            number
  state:            string
  touches:          number
  avg_bounce_pct:   number
  touch_quality_avg: number
  source_pivot_count: number
  distance_pct:     number
  last_interaction_bar: number
  explanation:      string
  // diagonal-specific
  line_points?:         { fecha: string; value: number }[]
  zone_upper_points?:   { fecha: string; value: number }[]
  zone_lower_points?:   { fecha: string; value: number }[]
  slope_annual_pct?:    number
  violations?:          number
  current_value?:       number
  // computed
  render_score:     number
  visual_tier?:     VisualTier
  pruned?:          boolean
  force_ghosted?:   boolean
}

// ── Pipeline ────────────────────────────────────────────────────────────────

export function computeV2RenderObjects(
  data: SRV2Result,
  recentHigh: number,
  recentLow: number,
): V2RenderObject[] {
  if (!data || data.bars === 0) return []

  const currentPrice = data.price ?? 0
  const atr = data.atr ?? currentPrice * 0.02
  const totalBars = data.bars
  const tf = data.timeframe ?? 'W'

  // Build working levels from horizontal supports/resistances
  let horizontals: WorkingLevel[] = []

  for (const s of data.supports) {
    horizontals.push(horizontalToWorking(s, totalBars, currentPrice))
  }
  for (const r of data.resistances) {
    horizontals.push(horizontalToWorking(r, totalBars, currentPrice))
  }

  // Phase 1: Merge overlapping horizontals (same role only)
  const hSupports = mergeOverlapping(horizontals.filter(l => l.role === 'support'))
  const hResistances = mergeOverlapping(horizontals.filter(l => l.role === 'resistance'))
  horizontals = [...hSupports, ...hResistances]

  // Build working levels from diagonals
  const diagonals: WorkingLevel[] = data.trendlines.map(tl => diagonalToWorking(tl, totalBars))

  let allLevels = [...horizontals, ...diagonals]

  // Phase 2: Compute render_score
  const scores = allLevels.map(l => l.score)
  const minScore = scores.length ? Math.min(...scores) : 0
  const maxScore = scores.length ? Math.max(...scores) : 1
  const scoreRange = Math.max(maxScore - minScore, 1)

  for (const level of allLevels) {
    const ns = (level.score - minScore) / scoreRange
    const ps = bandLookup(PROXIMITY_BANDS, Math.abs(level.distance_pct))
    const ts = TF_SCORES[tf] ?? 1.0
    const ss = STATE_SCORES[level.state] ?? 0.5
    const barsSince = Math.max(0, totalBars - level.last_interaction_bar)
    const rs = bandLookup(RECENCY_BANDS, barsSince)

    const qualityBonus = level.touch_quality_avg >= 0.7 ? 0.10 : 0

    level.render_score =
      WEIGHTS.normalized_score * ns +
      WEIGHTS.proximity * ps +
      WEIGHTS.timeframe * ts +
      WEIGHTS.state * ss +
      WEIGHTS.recency * rs +
      qualityBonus
  }

  // Phase 3: Pruning

  // D1: state
  allLevels = allLevels.filter(l => l.state !== 'invalidated')
  for (const l of allLevels) {
    if (l.state === 'broken') {
      const barsSince = totalBars - l.last_interaction_bar
      if (barsSince <= BROKEN_RETEST_WINDOW) {
        l.force_ghosted = true
      } else {
        l.pruned = true
      }
    }
  }
  allLevels = allLevels.filter(l => !l.pruned)

  // D2: distance
  const hasStructuralSupport = allLevels.some(l =>
    l.role === 'support' && l.classification !== 'acceleration' && Math.abs(l.distance_pct) <= MAX_DISTANCE_PCT
  )
  const hasStructuralResistance = allLevels.some(l =>
    l.role === 'resistance' && l.classification !== 'acceleration' && Math.abs(l.distance_pct) <= MAX_DISTANCE_PCT
  )

  for (const l of allLevels) {
    if (Math.abs(l.distance_pct) > MAX_DISTANCE_PCT) {
      if (l.role === 'support' && !hasStructuralSupport) {
        l.force_ghosted = true
      } else if (l.role === 'resistance' && !hasStructuralResistance) {
        l.force_ghosted = true
      } else {
        l.pruned = true
      }
    }
  }
  allLevels = allLevels.filter(l => !l.pruned)

  // D3: redundancy with ATH/ATL
  for (const l of allLevels) {
    if (l.kind === 'horizontal' && l.role === 'resistance') {
      if (Math.abs(l.zone_max - recentHigh) <= ATH_ATL_ATR_FACTOR * atr) {
        l.pruned = true
      }
    }
    if (l.kind === 'horizontal' && l.role === 'support') {
      if (Math.abs(l.zone_min - recentLow) <= ATH_ATL_ATR_FACTOR * atr) {
        l.pruned = true
      }
    }
  }
  allLevels = allLevels.filter(l => !l.pruned)

  // Phase 4: Slot selection
  const selected = new Set<WorkingLevel>()
  const result: V2RenderObject[] = []

  // Slot 1: primary resistance (horizontal, above price)
  const resAbove = allLevels
    .filter(l => l.role === 'resistance' && l.kind === 'horizontal' && l.center_price > currentPrice)
    .sort((a, b) => b.render_score - a.render_score)
  if (resAbove.length) {
    const pick = resAbove[0]
    pick.visual_tier = 'primary'
    selected.add(pick)
  }

  // Slot 1b: secondary resistance (next horizontal above price)
  if (resAbove.length > 1) {
    const pick = resAbove[1]
    pick.visual_tier = 'secondary'
    selected.add(pick)
  }

  // Slot 2: primary support (horizontal, below price)
  const supBelow = allLevels
    .filter(l => l.role === 'support' && l.kind === 'horizontal' && l.center_price < currentPrice)
    .sort((a, b) => b.render_score - a.render_score)
  if (supBelow.length) {
    const pick = supBelow[0]
    pick.visual_tier = 'primary'
    selected.add(pick)
  }

  // Slot 2b: secondary support (next horizontal below price)
  if (supBelow.length > 1) {
    const pick = supBelow[1]
    pick.visual_tier = 'secondary'
    selected.add(pick)
  }

  // Slot 3: structural diagonal
  const structDiag = allLevels
    .filter(l => l.kind === 'diagonal' && l.classification === 'structural'
      && Math.abs(l.distance_pct) <= STRUCTURAL_MAX_DISTANCE && !selected.has(l))
    .sort((a, b) => b.render_score - a.render_score)
  if (structDiag.length) {
    const pick = structDiag[0]
    pick.visual_tier = 'secondary'
    selected.add(pick)
  }

  // Slot 4: acceleration
  const accelCand = allLevels
    .filter(l => l.classification === 'acceleration'
      && Math.abs(l.distance_pct) <= ACCEL_MAX_DISTANCE
      && (l.state === 'active' || l.state === 'tested')
      && l.score >= MIN_ACCEL_SCORE
      && !selected.has(l))
    .sort((a, b) => b.render_score - a.render_score)
  if (accelCand.length) {
    const pick = accelCand[0]
    pick.visual_tier = 'tertiary'
    selected.add(pick)
  }

  // Slot 5: historical ghost
  const ghostCand = allLevels
    .filter(l => !selected.has(l) && (l.force_ghosted || l.classification === 'historical'))
    .sort((a, b) => b.render_score - a.render_score)
  if (ghostCand.length) {
    const pick = ghostCand[0]
    pick.visual_tier = 'ghosted'
    selected.add(pick)
  }

  // If we have fewer than max slots and there are unselected diagonals that are structural
  // but were too far for slot 3, allow them as ghosted
  if (selected.size < 5) {
    const farStructural = allLevels
      .filter(l => !selected.has(l) && l.kind === 'diagonal' && l.classification === 'structural'
        && Math.abs(l.distance_pct) > STRUCTURAL_MAX_DISTANCE)
      .sort((a, b) => b.render_score - a.render_score)
    if (farStructural.length) {
      farStructural[0].visual_tier = 'ghosted'
      selected.add(farStructural[0])
    }
  }

  // Phase 5: Build render objects
  for (const level of selected) {
    const tier = level.visual_tier!
    const pal = PALETTE[level.role][tier]

    if (level.kind === 'horizontal') {
      result.push({
        id:           level.id,
        kind:         'horizontal',
        role:         level.role,
        visual_tier:  tier,
        zone_min:     level.zone_min,
        zone_max:     level.zone_max,
        label:        formatLabel(level.role, level.kind, level.classification, level.zone_min, level.zone_max),
        fill_color:   pal.fill,
        border_color: pal.border,
        label_color:  pal.label,
        border_width: BORDER_WIDTH[tier],
        border_style: BORDER_STYLE[tier],
        label_visible: LABEL_VISIBLE[tier],
        z_index:      Z_ORDER[tier],
        tooltip: {
          score:       level.score,
          state:       level.state,
          touches:     level.touches,
          bounce_pct:  level.avg_bounce_pct,
          touch_quality_avg: level.touch_quality_avg,
          explanation: level.explanation,
        },
      })
    } else {
      result.push({
        id:             level.id,
        kind:           'diagonal',
        role:           level.role,
        classification: level.classification,
        visual_tier:    tier,
        label:          formatLabel(level.role, level.kind, level.classification, level.zone_min, level.zone_max),
        line_color:     pal.border,
        zone_color:     pal.fill,
        label_color:    pal.label,
        line_width:     BORDER_WIDTH[tier],
        line_style:     BORDER_STYLE[tier],
        label_visible:  LABEL_VISIBLE[tier],
        z_index:        Z_ORDER[tier],
        line_points:         level.line_points ?? [],
        zone_upper_points:   level.zone_upper_points ?? [],
        zone_lower_points:   level.zone_lower_points ?? [],
        tooltip: {
          score:           level.score,
          state:           level.state,
          touches:         level.touches,
          violations:      level.violations ?? 0,
          slope_annual_pct: level.slope_annual_pct ?? 0,
          distance_pct:    level.distance_pct,
          touch_quality_avg: level.touch_quality_avg,
          explanation:     level.explanation,
        },
      })
    }
  }

  result.sort((a, b) => a.z_index - b.z_index)
  return result
}

// ── Converters ──────────────────────────────────────────────────────────────

function horizontalToWorking(h: SRV2HorizontalLevel, totalBars: number, currentPrice: number): WorkingLevel {
  const barsSinceEnd = Math.max(0, Math.round(
    (Date.now() - new Date(h.time_end).getTime()) / (7 * 86400000)
  ))
  const distPct = currentPrice > 0 ? (h.center_price / currentPrice - 1) * 100 : 0
  return {
    id:                  h.id,
    kind:                'horizontal',
    role:                h.role,
    classification:      'horizontal',
    center_price:        h.center_price,
    zone_min:            h.zone_min,
    zone_max:            h.zone_max,
    score:               h.score,
    state:               h.state,
    touches:             h.touches,
    avg_bounce_pct:      h.avg_bounce_pct,
    touch_quality_avg:   h.touch_quality_avg ?? 0,
    source_pivot_count:  h.source_pivot_count,
    distance_pct:        distPct,
    last_interaction_bar: totalBars - barsSinceEnd,
    explanation:         h.explanation,
    render_score:        0,
  }
}

function diagonalToWorking(tl: SRV2Trendline, totalBars: number): WorkingLevel {
  const lastPt = tl.line_points[tl.line_points.length - 1]
  const firstPt = tl.line_points[0]
  return {
    id:                   tl.id,
    kind:                 'diagonal',
    role:                 tl.role,
    classification:       tl.classification,
    center_price:         tl.current_value,
    zone_min:             tl.zone_lower_points.length ? tl.zone_lower_points[tl.zone_lower_points.length - 1].value : tl.current_value * 0.98,
    zone_max:             tl.zone_upper_points.length ? tl.zone_upper_points[tl.zone_upper_points.length - 1].value : tl.current_value * 1.02,
    score:                tl.score,
    state:                tl.state,
    touches:              tl.touches,
    avg_bounce_pct:       0,
    touch_quality_avg:    tl.touch_quality_avg ?? 0,
    source_pivot_count:   tl.touches,
    distance_pct:         tl.distance_pct,
    last_interaction_bar: totalBars,
    explanation:          tl.explanation,
    line_points:          tl.line_points,
    zone_upper_points:    tl.zone_upper_points,
    zone_lower_points:    tl.zone_lower_points,
    slope_annual_pct:     tl.slope_annual_pct,
    violations:           tl.violations,
    current_value:        tl.current_value,
    render_score:         0,
  }
}

// ── Merge ───────────────────────────────────────────────────────────────────

function mergeOverlapping(levels: WorkingLevel[]): WorkingLevel[] {
  if (levels.length <= 1) return levels

  let changed = true
  while (changed) {
    changed = false
    for (let i = 0; i < levels.length; i++) {
      for (let j = i + 1; j < levels.length; j++) {
        const a = levels[i], b = levels[j]
        const overlap = Math.max(0, Math.min(a.zone_max, b.zone_max) - Math.max(a.zone_min, b.zone_min))
        const widthRef = Math.min(a.zone_max - a.zone_min, b.zone_max - b.zone_min)
        const distCenters = Math.abs(a.center_price - b.center_price)
        const maxWidth = Math.max(a.zone_max - a.zone_min, b.zone_max - b.zone_min)

        const shouldMerge =
          (widthRef > 0 && overlap / widthRef >= MERGE_OVERLAP_THRESHOLD) ||
          distCenters <= maxWidth

        if (shouldMerge) {
          const winner = a.score >= b.score ? a : b
          const loser = a.score >= b.score ? b : a
          const merged: WorkingLevel = {
            ...winner,
            id: winner.id + '_merged',
            zone_min: Math.min(a.zone_min, b.zone_min),
            zone_max: Math.max(a.zone_max, b.zone_max),
            center_price: (Math.min(a.zone_min, b.zone_min) + Math.max(a.zone_max, b.zone_max)) / 2,
            touches: a.touches + b.touches,
            source_pivot_count: a.source_pivot_count + b.source_pivot_count,
            avg_bounce_pct: a.touches + b.touches > 0
              ? (a.avg_bounce_pct * a.touches + b.avg_bounce_pct * b.touches) / (a.touches + b.touches)
              : 0,
            touch_quality_avg: a.touches + b.touches > 0
              ? (a.touch_quality_avg * a.touches + b.touch_quality_avg * b.touches) / (a.touches + b.touches)
              : 0,
            last_interaction_bar: Math.max(a.last_interaction_bar, b.last_interaction_bar),
          }
          levels.splice(j, 1)
          levels.splice(i, 1)
          levels.push(merged)
          changed = true
          break
        }
      }
      if (changed) break
    }
  }
  return levels
}
