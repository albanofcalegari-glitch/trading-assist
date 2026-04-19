"""
sr_engine_v2.py — Motor de Soportes y Resistencias V2

Detecta, puntúa y clasifica niveles horizontales, líneas diagonales
estructurales y líneas de aceleración.  Todo se expresa como ZONAS
(rango de precio) en vez de líneas exactas.

Uso:
    from strategies.sr_engine_v2 import calculate_sr
    result = calculate_sr('AMD', timeframe='W')
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db.connection import get_conn


# ── Config por defecto ────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    'pivot_left_bars':                    5,
    'pivot_right_bars':                   5,
    'min_swing_percent':                  1.5,
    'zone_width_atr_multiplier':          0.6,
    'horizontal_merge_tolerance_percent': 4.0,
    'touch_tolerance_percent':            0.8,
    'min_touches_for_strong_level':       3,
    'min_bars_between_touches':           5,
    'break_close_count':                  2,
    'break_distance_atr_multiplier':      0.5,
    'max_visible_horizontal_supports':    3,
    'max_visible_horizontal_resistances': 3,
    'max_visible_trendlines':             2,
    'classify_steep_lines_as_acceleration': True,
    'acceleration_slope_annual_pct':      80.0,
    'diagonal_min_touches':               2,
    'diagonal_zone_atr_multiplier':       0.4,
    'bounce_lookforward_bars':            8,
    'horizontal_max_distance_pct':        60.0,
    'horizontal_lookback_bars':           260,
    # Diagonal lookback
    'diagonal_lookback_bars':             520,
    # Wick-anchor fitting
    'anchor_search_steps':                5,
    'max_body_crosses':                   3,
    'body_penetration_penalty':           1.5,
    'pivot_touch_bonus':                  1.2,
    'w_anchor':                           0.30,
    'w_contact':                          0.45,
    'w_clean':                            0.25,
    'min_wick_ratio':                     0.001,
}


# ── Carga de datos ────────────────────────────────────────────────────────────

def _load(symbol: str, tf: str, fecha_max: date) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = %s AND fecha <= %s
                   ORDER BY fecha ASC""",
                (symbol, tf, fecha_max),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ── Phase 1: ATR ──────────────────────────────────────────────────────────────

def _calc_atr(rows: list[dict], period: int = 14) -> list[Optional[float]]:
    n = len(rows)
    trs: list[float] = []
    for i in range(n):
        h = float(rows[i]['high'])
        l = float(rows[i]['low'])
        if i == 0:
            trs.append(h - l)
        else:
            pc = float(rows[i - 1]['close'])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    atrs: list[Optional[float]] = [None] * n
    if n >= period:
        atrs[period - 1] = sum(trs[:period]) / period
        for i in range(period, n):
            atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period
    return atrs


# ── Phase 2: Pivots ──────────────────────────────────────────────────────────

def _detect_pivots(
    highs: list[float],
    lows: list[float],
    config: dict,
) -> tuple[list[dict], list[dict]]:
    left = config['pivot_left_bars']
    right = config['pivot_right_bars']
    min_swing = config['min_swing_percent'] / 100
    n = len(highs)

    pivot_highs: list[dict] = []
    pivot_lows: list[dict] = []

    for i in range(left, n - right):
        # ── Pivot high ────────────────────────────────────────────────────
        is_high = (
            highs[i] >= max(highs[i - left:i])
            and highs[i] >= max(highs[i + 1:i + right + 1])
        )
        if is_high:
            neighbors = highs[i - left:i] + highs[i + 1:i + right + 1]
            swing = highs[i] / min(neighbors) - 1 if min(neighbors) > 0 else 0
            if swing >= min_swing:
                left_d = (highs[i] - min(highs[max(0, i - left):i])) / highs[i]
                right_d = (highs[i] - min(highs[i + 1:i + right + 1])) / highs[i]
                strength = min(1.0, (left_d + right_d) / 2 / 0.05)
                pivot_highs.append({
                    'id': f'ph_{i}', 'idx': i, 'type': 'high',
                    'price': highs[i], 'strength': round(strength, 3),
                })

        # ── Pivot low ─────────────────────────────────────────────────────
        is_low = (
            lows[i] <= min(lows[i - left:i])
            and lows[i] <= min(lows[i + 1:i + right + 1])
        )
        if is_low:
            neighbors = lows[i - left:i] + lows[i + 1:i + right + 1]
            swing = max(neighbors) / lows[i] - 1 if lows[i] > 0 else 0
            if swing >= min_swing:
                left_d = (max(lows[max(0, i - left):i]) - lows[i]) / lows[i]
                right_d = (max(lows[i + 1:i + right + 1]) - lows[i]) / lows[i]
                strength = min(1.0, (left_d + right_d) / 2 / 0.05)
                pivot_lows.append({
                    'id': f'pl_{i}', 'idx': i, 'type': 'low',
                    'price': lows[i], 'strength': round(strength, 3),
                })

    return pivot_highs, pivot_lows


# ── Phase 3: Horizontal levels ───────────────────────────────────────────────

def _cluster_pivots(pivots: list[dict], tol_pct: float) -> list[list[dict]]:
    if not pivots:
        return []
    pts = sorted(pivots, key=lambda p: p['price'])
    clusters: list[list[dict]] = [[pts[0]]]
    for p in pts[1:]:
        center = sum(pp['price'] for pp in clusters[-1]) / len(clusters[-1])
        if abs(p['price'] / center - 1) <= tol_pct / 100:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [c for c in clusters if len(c) >= 2]


def _count_touches(
    rows: list[dict],
    zone_min: float,
    zone_max: float,
    role: str,
    config: dict,
) -> tuple[int, list[int], float]:
    """Count touches with min temporal separation. Returns (count, indices, avg_bounce_pct)."""
    min_bars = config['min_bars_between_touches']
    tol = config['touch_tolerance_percent'] / 100
    lookfwd = config['bounce_lookforward_bars']
    n = len(rows)

    zmin_expanded = zone_min * (1 - tol)
    zmax_expanded = zone_max * (1 + tol)

    touches = 0
    indices: list[int] = []
    last_touch = -min_bars - 1
    bounces: list[float] = []

    for i in range(n):
        if i - last_touch < min_bars:
            continue
        low_i = float(rows[i]['low'])
        high_i = float(rows[i]['high'])

        entered = False
        if role == 'support':
            entered = low_i <= zmax_expanded and low_i >= zmin_expanded * 0.97
        else:
            entered = high_i >= zmin_expanded and high_i <= zmax_expanded * 1.03

        if entered:
            touches += 1
            indices.append(i)
            last_touch = i
            # bounce: max opposite movement in lookfwd bars
            center = (zone_min + zone_max) / 2
            bounce = 0.0
            for j in range(i + 1, min(i + lookfwd + 1, n)):
                if role == 'support':
                    bounce = max(bounce, float(rows[j]['high']) / center - 1)
                else:
                    bounce = max(bounce, 1 - float(rows[j]['low']) / center)
            bounces.append(bounce * 100)

    avg_bounce = sum(bounces) / len(bounces) if bounces else 0
    return touches, indices, avg_bounce


def _score_horizontal(
    touches: int,
    touch_indices: list[int],
    avg_bounce_pct: float,
    cluster: list[dict],
    center: float,
    total_bars: int,
    state: str,
) -> int:
    # Touches: 25%
    touch_s = min(100, max(0, touches * 20))

    # Temporal separation: 10%
    if len(touch_indices) >= 2:
        gaps = [touch_indices[i + 1] - touch_indices[i] for i in range(len(touch_indices) - 1)]
        avg_gap = sum(gaps) / len(gaps)
        sep_s = min(100, avg_gap / max(total_bars * 0.15, 1) * 100)
    else:
        sep_s = 0

    # Reaction (bounce): 20%
    react_s = min(100, avg_bounce_pct * 15)

    # Cleanness: 15%
    prices = [p['price'] for p in cluster]
    if center > 0 and len(prices) >= 2:
        stdev = (sum((p - center) ** 2 for p in prices) / len(prices)) ** 0.5
        rel = stdev / center * 100
        clean_s = max(0, 100 - rel * 30)
    else:
        clean_s = 50

    # Timeframe: 15% (weekly=100 for now)
    tf_s = 100

    # State: 15%
    state_scores = {'active': 100, 'tested': 80, 'weakening': 50, 'broken': 20, 'invalidated': 10, 'flipped': 90}
    state_s = state_scores.get(state, 50)

    raw = (touch_s * 0.25 + sep_s * 0.10 + react_s * 0.20 +
           clean_s * 0.15 + tf_s * 0.15 + state_s * 0.15)
    return int(min(100, max(0, raw)))


def _build_horizontal_levels(
    pivots: list[dict],
    role: str,
    rows: list[dict],
    atrs: list[Optional[float]],
    config: dict,
) -> list[dict]:
    tol = config['horizontal_merge_tolerance_percent']
    n = len(rows)
    last_close = float(rows[-1]['close'])
    max_dist = config['horizontal_max_distance_pct'] / 100
    lookback = config['horizontal_lookback_bars']

    recent_pivots = [p for p in pivots if p['idx'] >= n - lookback]
    clusters = _cluster_pivots(recent_pivots, tol)
    levels: list[dict] = []

    for ci, cluster in enumerate(clusters):
        prices = [p['price'] for p in cluster]
        center = sum(prices) / len(prices)
        if abs(center / last_close - 1) > max_dist:
            continue

        latest_idx = max(p['idx'] for p in cluster)
        atr = atrs[latest_idx] if atrs[latest_idx] else (max(prices) - min(prices))
        zone_half = atr * config['zone_width_atr_multiplier'] / 2
        zone_min = min(min(prices), center - zone_half)
        zone_max = max(max(prices), center + zone_half)

        # State
        state = _horizontal_state(last_close, zone_min, zone_max, rows, atrs, config)

        touches, t_indices, avg_bounce = _count_touches(rows, zone_min, zone_max, role, config)

        score = _score_horizontal(touches, t_indices, avg_bounce, cluster, center, n, state)

        earliest_idx = min(p['idx'] for p in cluster)
        explanation = (
            f'Zona de {role} formada por {len(cluster)} pivots entre '
            f'${min(prices):.2f} y ${max(prices):.2f}. '
            f'{touches} toques con rebote promedio {avg_bounce:.1f}%. '
            f'Estado: {state}.'
        )

        levels.append({
            'id': f'{role[0]}h_{ci}',
            'kind': 'horizontal',
            'role': role,
            'center_price': round(center, 2),
            'zone_min': round(zone_min, 2),
            'zone_max': round(zone_max, 2),
            'time_start': rows[earliest_idx]['fecha'].isoformat(),
            'time_end': rows[-1]['fecha'].isoformat(),
            'touches': touches,
            'score': score,
            'state': state,
            'source_pivot_count': len(cluster),
            'avg_bounce_pct': round(avg_bounce, 1),
            'explanation': explanation,
        })

    return levels


def _horizontal_state(
    last_close: float,
    zone_min: float,
    zone_max: float,
    rows: list[dict],
    atrs: list[Optional[float]],
    config: dict,
) -> str:
    n = len(rows)
    atr = atrs[-1] if atrs[-1] else (zone_max - zone_min)
    break_dist = atr * config['break_distance_atr_multiplier']
    break_n = config['break_close_count']

    # Check last N closes for break
    in_zone = zone_min <= last_close <= zone_max
    above = last_close > zone_max
    below = last_close < zone_min

    if in_zone:
        recent_closes = [float(rows[i]['close']) for i in range(max(0, n - 5), n)]
        came_from_outside = any(c < zone_min or c > zone_max for c in recent_closes[:-1])
        if came_from_outside:
            return 'tested'
        return 'active'

    # Count consecutive closes beyond the zone
    consec_beyond = 0
    for i in range(n - 1, max(n - 10, -1), -1):
        c = float(rows[i]['close'])
        if below and c < zone_min:
            consec_beyond += 1
        elif above and c > zone_max:
            consec_beyond += 1
        else:
            break

    if consec_beyond >= break_n:
        dist = abs(last_close - (zone_min if below else zone_max))
        if dist > break_dist * 2:
            return 'invalidated'
        return 'broken'

    # Price is outside but not enough consecutive closes
    dist = abs(last_close - (zone_min if below else zone_max))
    if dist < break_dist:
        return 'weakening'

    return 'broken'


# ── Phase 4: Diagonal trendlines ─────────────────────────────────────────────

def _build_trendlines(
    pivot_lows: list[dict],
    pivot_highs: list[dict],
    rows: list[dict],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atrs: list[Optional[float]],
    config: dict,
) -> list[dict]:
    trendlines: list[dict] = []

    # Ascending supports from rising pivot lows
    sup = _fit_diagonals(
        pivot_lows, rows, lows, closes, atrs, config,
        role='support', ascending=True,
    )
    trendlines.extend(sup)

    # Descending resistances from falling pivot highs
    res = _fit_diagonals(
        pivot_highs, rows, highs, closes, atrs, config,
        role='resistance', ascending=False,
    )
    trendlines.extend(res)

    return trendlines


def _fit_diagonals(
    pivots: list[dict],
    rows: list[dict],
    prices: list[float],
    closes: list[float],
    atrs: list[Optional[float]],
    config: dict,
    role: str,
    ascending: bool,
) -> list[dict]:
    if len(pivots) < 2:
        return []

    n = len(rows)
    lookback = config.get('diagonal_lookback_bars', 520)
    min_idx = max(0, n - lookback)
    pivots = [p for p in pivots if p['idx'] >= min_idx]
    if len(pivots) < 2:
        return []

    min_touches = config['diagonal_min_touches']
    tol_pct = config['touch_tolerance_percent']
    log_tol = math.log(1 + tol_pct / 100)
    bars_per_year = 52
    last_close = closes[-1]

    # Pre-compute log arrays for wick-anchor fitting
    log_low = [math.log(float(r['low'])) if float(r['low']) > 0 else 0 for r in rows]
    log_high = [math.log(float(r['high'])) if float(r['high']) > 0 else 0 for r in rows]
    log_bbot = [math.log(min(float(r['open']), float(r['close']))) if min(float(r['open']), float(r['close'])) > 0 else 0 for r in rows]
    log_btop = [math.log(max(float(r['open']), float(r['close']))) if max(float(r['open']), float(r['close'])) > 0 else 0 for r in rows]

    # For support: anchor in lower wick [low, body_bottom]
    # For resistance: anchor in upper wick [body_top, high]
    if ascending:
        log_anchor_lo = log_low       # wick tip (preferred)
        log_anchor_hi = log_bbot      # body edge (less preferred)
    else:
        log_anchor_lo = log_btop      # body edge (less preferred)
        log_anchor_hi = log_high      # wick tip (preferred)

    anchor_steps = config['anchor_search_steps']
    max_body_crosses = config['max_body_crosses']
    min_wick_log = math.log(1 + config['min_wick_ratio'])
    pivot_idx_set = set(p['idx'] for p in pivots)

    refine_fracs = [k / max(anchor_steps - 1, 1) for k in range(1, anchor_steps)]

    best_structural: Optional[dict] = None
    best_accel: Optional[dict] = None

    for a in range(len(pivots)):
        for b in range(a + 1, len(pivots)):
            i = pivots[a]['idx']
            j = pivots[b]['idx']
            span = j - i
            if span < 6:
                continue

            # Wick ranges at anchors
            if ascending:
                wick_range_i = log_bbot[i] - log_low[i]
                wick_range_j = log_bbot[j] - log_low[j]
            else:
                wick_range_i = log_high[i] - log_btop[i]
                wick_range_j = log_high[j] - log_btop[j]

            # Phase A: try wick tips first (fi=0, fj=0) — fast path
            best_fit = _try_anchor(
                0.0, 0.0, i, j, span, n, ascending,
                log_low, log_high, log_bbot, log_btop,
                wick_range_i, wick_range_j, min_wick_log,
                log_tol, pivot_idx_set, config, max_body_crosses,
            )

            # Phase B: if wick tips have body crosses, refine with grid search
            if best_fit is not None and best_fit['body_crosses'] > 0:
                has_wick_i = wick_range_i >= min_wick_log
                has_wick_j = wick_range_j >= min_wick_log
                for fi in (refine_fracs if has_wick_i else []):
                    for fj in ([0.0] + (refine_fracs if has_wick_j else [])):
                        cand = _try_anchor(
                            fi, fj, i, j, span, n, ascending,
                            log_low, log_high, log_bbot, log_btop,
                            wick_range_i, wick_range_j, min_wick_log,
                            log_tol, pivot_idx_set, config, max_body_crosses,
                        )
                        if cand and cand['fit_total'] > best_fit['fit_total']:
                            best_fit = cand
                for fj in (refine_fracs if has_wick_j else []):
                    cand = _try_anchor(
                        0.0, fj, i, j, span, n, ascending,
                        log_low, log_high, log_bbot, log_btop,
                        wick_range_i, wick_range_j, min_wick_log,
                        log_tol, pivot_idx_set, config, max_body_crosses,
                    )
                    if cand and cand['fit_total'] > best_fit['fit_total']:
                        best_fit = cand
            elif best_fit is None:
                # Wick tips didn't produce a valid slope, try a few combos
                has_wick_i = wick_range_i >= min_wick_log
                has_wick_j = wick_range_j >= min_wick_log
                for fi in ([0.0] + (refine_fracs if has_wick_i else [])):
                    for fj in ([0.0] + (refine_fracs if has_wick_j else [])):
                        if fi == 0.0 and fj == 0.0:
                            continue
                        cand = _try_anchor(
                            fi, fj, i, j, span, n, ascending,
                            log_low, log_high, log_bbot, log_btop,
                            wick_range_i, wick_range_j, min_wick_log,
                            log_tol, pivot_idx_set, config, max_body_crosses,
                        )
                        if cand and (best_fit is None or cand['fit_total'] > best_fit['fit_total']):
                            best_fit = cand

            if best_fit is None or best_fit['touches'] < min_touches:
                continue

            slope = best_fit['slope']
            intercept = best_fit['intercept']
            touches = best_fit['touches']
            touch_idxs = best_fit['touch_idxs']
            violations = best_fit['violations']

            slope_annual = (math.exp(abs(slope) * bars_per_year) - 1) * 100
            accel_thresh = config['acceleration_slope_annual_pct']
            classification = 'acceleration' if slope_annual > accel_thresh else 'structural'

            score = _score_diagonal(
                touches, touch_idxs, violations, slope_annual,
                span, n, classification, last_close,
                slope, intercept, rows, closes, atrs, config,
            )

            # Build line_points for rendering
            line_points = []
            zone_upper = []
            zone_lower = []
            atr_last = atrs[-1] if atrs[-1] else abs(prices[-1] * 0.02)
            zone_half_log = math.log(1 + atr_last * config['diagonal_zone_atr_multiplier'] / max(last_close, 1))

            for x in range(i, n):
                val = math.exp(slope * x + intercept)
                line_points.append({
                    'fecha': rows[x]['fecha'].isoformat(),
                    'value': round(val, 4),
                })
                zone_upper.append({
                    'fecha': rows[x]['fecha'].isoformat(),
                    'value': round(math.exp(slope * x + intercept + zone_half_log), 4),
                })
                zone_lower.append({
                    'fecha': rows[x]['fecha'].isoformat(),
                    'value': round(math.exp(slope * x + intercept - zone_half_log), 4),
                })

            current_val = math.exp(slope * (n - 1) + intercept)
            distance_pct = (last_close / current_val - 1) * 100

            state = _diagonal_state(distance_pct, closes, slope, intercept, n, atrs, config, ascending)

            if ascending:
                y1_price = math.exp(log_low[i] + best_fit['fi'] * (log_bbot[i] - log_low[i]))
                y2_price = math.exp(log_low[j] + best_fit['fj'] * (log_bbot[j] - log_low[j]))
            else:
                y1_price = math.exp(log_high[i] - best_fit['fi'] * (log_high[i] - log_btop[i]))
                y2_price = math.exp(log_high[j] - best_fit['fj'] * (log_high[j] - log_btop[j]))

            tl = {
                'id': f'{role[0]}d_{i}_{j}',
                'kind': 'diagonal',
                'role': role,
                'classification': classification,
                'x1': rows[i]['fecha'].isoformat(),
                'y1': round(y1_price, 2),
                'x2': rows[j]['fecha'].isoformat(),
                'y2': round(y2_price, 2),
                'touches': touches,
                'violations': violations,
                'slope_annual_pct': round(slope_annual, 1),
                'score': score,
                'state': state,
                'distance_pct': round(distance_pct, 2),
                'current_value': round(current_val, 2),
                'line_points': line_points,
                'zone_upper_points': zone_upper,
                'zone_lower_points': zone_lower,
                'explanation': (
                    f'Trendline {classification} de {role}: {touches} toques, '
                    f'slope {slope_annual:.0f}%/año, {violations} violaciones. '
                    f'Estado: {state}.'
                ),
            }

            target = best_accel if classification == 'acceleration' else best_structural
            if target is None or score > target['score']:
                if classification == 'acceleration':
                    best_accel = tl
                else:
                    best_structural = tl

    results = []
    if best_structural:
        results.append(best_structural)
    if best_accel:
        results.append(best_accel)
    return results


def _try_anchor(
    fi: float, fj: float,
    i: int, j: int, span: int, n: int, ascending: bool,
    log_low: list[float], log_high: list[float],
    log_bbot: list[float], log_btop: list[float],
    wick_range_i: float, wick_range_j: float, min_wick_log: float,
    log_tol: float, pivot_idx_set: set, config: dict,
    max_body_crosses: int,
) -> Optional[dict]:
    if ascending:
        yi = log_low[i] + fi * wick_range_i
        yj = log_low[j] + fj * wick_range_j
    else:
        yi = log_high[i] - fi * wick_range_i
        yj = log_high[j] - fj * wick_range_j

    slope = (yj - yi) / span
    if ascending and slope <= 0:
        return None
    if not ascending and slope >= 0:
        return None
    intercept = yi - slope * i

    anchor_sc = _anchor_score(fi, fj, wick_range_i, wick_range_j, min_wick_log)

    contact_sc, body_crosses, touches, touch_idxs, violations = (
        _evaluate_contacts(
            slope, intercept, i, n,
            log_low, log_high, log_bbot, log_btop,
            log_tol, pivot_idx_set, config, ascending,
        )
    )
    if body_crosses > max_body_crosses:
        return None

    clean_sc = 1.0 - body_crosses / max(n - i, 1)
    fit_total = (
        config['w_anchor'] * anchor_sc
        + config['w_contact'] * contact_sc
        + config['w_clean'] * clean_sc
    )
    return {
        'slope': slope, 'intercept': intercept,
        'fi': fi, 'fj': fj,
        'anchor_score': anchor_sc, 'contact_score': contact_sc,
        'body_crosses': body_crosses,
        'touches': touches, 'touch_idxs': touch_idxs,
        'violations': violations, 'fit_total': fit_total,
    }


def _anchor_score(
    fi: float, fj: float,
    wick_range_i: float, wick_range_j: float,
    min_wick_log: float,
) -> float:
    if wick_range_i >= min_wick_log:
        si = 1.0 - 0.6 * fi
    else:
        si = 0.7
    if wick_range_j >= min_wick_log:
        sj = 1.0 - 0.6 * fj
    else:
        sj = 0.7
    return (si + sj) / 2


def _evaluate_contacts(
    slope: float,
    intercept: float,
    i_start: int,
    n: int,
    log_low: list[float],
    log_high: list[float],
    log_bbot: list[float],
    log_btop: list[float],
    log_tol: float,
    pivot_idx_set: set,
    config: dict,
    ascending: bool,
) -> tuple:
    penalty_mult = config['body_penetration_penalty']
    pivot_bonus = config['pivot_touch_bonus']
    contact_total = 0.0
    body_crosses = 0
    touches = 0
    touch_idxs: list[int] = []
    violations = 0

    # Check wick touches at pivot positions only (fast)
    for k in sorted(pivot_idx_set):
        if k < i_start:
            continue
        line_k = slope * k + intercept
        if ascending:
            delta = line_k - log_low[k]
            wick_range = log_bbot[k] - log_low[k]
            if abs(delta) <= log_tol:
                contact_total += pivot_bonus
                touches += 1
                touch_idxs.append(k)
            elif wick_range > 0 and 0 < delta <= wick_range:
                frac = delta / wick_range
                contact_total += 0.6 * (1.0 - frac)
                touches += 1
                touch_idxs.append(k)
            elif delta < -log_tol:
                pass
            elif line_k > log_bbot[k]:
                violations += 1
        else:
            delta = log_high[k] - line_k
            wick_range = log_high[k] - log_btop[k]
            if abs(delta) <= log_tol:
                contact_total += pivot_bonus
                touches += 1
                touch_idxs.append(k)
            elif wick_range > 0 and 0 < delta <= wick_range:
                frac = delta / wick_range
                contact_total += 0.6 * (1.0 - frac)
                touches += 1
                touch_idxs.append(k)
            elif delta < -log_tol:
                pass
            elif line_k < log_btop[k]:
                violations += 1

    # Body-cross scan: check all bars between anchors and beyond (with early exit)
    max_bc = config['max_body_crosses']
    for k in range(i_start, n):
        line_k = slope * k + intercept
        if ascending:
            if line_k > log_bbot[k] + log_tol * 0.3:
                body_crosses += 1
                body_range = log_btop[k] - log_bbot[k]
                depth = min((line_k - log_bbot[k]) / body_range, 1.0) if body_range > 0 else 1.0
                contact_total -= penalty_mult * depth
                if body_crosses > max_bc:
                    break
        else:
            if line_k < log_btop[k] - log_tol * 0.3:
                body_crosses += 1
                body_range = log_btop[k] - log_bbot[k]
                depth = min((log_btop[k] - line_k) / body_range, 1.0) if body_range > 0 else 1.0
                contact_total -= penalty_mult * depth
                if body_crosses > max_bc:
                    break

    pivot_count = max(len([k for k in pivot_idx_set if k >= i_start]), 1)
    normalized = contact_total / (pivot_count ** 0.5)

    return normalized, body_crosses, touches, touch_idxs, violations


def _score_diagonal(
    touches: int,
    touch_idxs: list[int],
    violations: int,
    slope_annual: float,
    span: int,
    total_bars: int,
    classification: str,
    last_close: float,
    slope: float,
    intercept: float,
    rows: list[dict],
    closes: list[float],
    atrs: list[Optional[float]],
    config: dict,
) -> int:
    # Touches: 25%
    touch_s = min(100, touches * 25)

    # Slope: 15% — penalize steep
    if slope_annual < 30:
        slope_s = 100
    elif slope_annual < 60:
        slope_s = 75
    elif slope_annual < 100:
        slope_s = 45
    else:
        slope_s = 20

    # Span: 10%
    span_s = min(100, span / max(total_bars * 0.3, 1) * 100)

    # Violations: 15%
    viol_s = max(0, 100 - violations * 30)

    # Bounce reaction: 20%
    n = len(rows)
    lookfwd = config['bounce_lookforward_bars']
    bounces: list[float] = []
    for ti in touch_idxs:
        current_line = math.exp(slope * ti + intercept)
        best_bounce = 0
        for j in range(ti + 1, min(ti + lookfwd + 1, n)):
            if slope > 0:
                best_bounce = max(best_bounce, float(rows[j]['high']) / current_line - 1)
            else:
                best_bounce = max(best_bounce, 1 - float(rows[j]['low']) / current_line)
        bounces.append(best_bounce * 100)
    avg_bounce = sum(bounces) / len(bounces) if bounces else 0
    react_s = min(100, avg_bounce * 15)

    # State: 15%
    n = len(rows)
    current_val = math.exp(slope * (n - 1) + intercept)
    dist = (last_close / current_val - 1) * 100
    if slope > 0:
        if dist > 3:
            state_s = 100
        elif dist > -3:
            state_s = 70
        else:
            state_s = 30
    else:
        if dist < -3:
            state_s = 100
        elif dist < 3:
            state_s = 70
        else:
            state_s = 30

    raw = (touch_s * 0.25 + slope_s * 0.15 + react_s * 0.20 +
           viol_s * 0.15 + span_s * 0.10 + state_s * 0.15)
    return int(min(100, max(0, raw)))


def _diagonal_state(
    distance_pct: float,
    closes: list[float],
    slope: float,
    intercept: float,
    n: int,
    atrs: list[Optional[float]],
    config: dict,
    ascending: bool,
) -> str:
    atr = atrs[-1] if atrs[-1] else abs(closes[-1] * 0.02)
    current_val = math.exp(slope * (n - 1) + intercept)
    break_dist_pct = (atr * config['break_distance_atr_multiplier'] / max(current_val, 1)) * 100

    if ascending:
        if distance_pct > 3:
            return 'active'
        elif distance_pct > -break_dist_pct:
            return 'tested'
        else:
            consec = 0
            for i in range(n - 1, max(n - 6, -1), -1):
                line_i = math.exp(slope * i + intercept)
                if closes[i] < line_i:
                    consec += 1
                else:
                    break
            if consec >= config['break_close_count']:
                if distance_pct < -break_dist_pct * 3:
                    return 'invalidated'
                return 'broken'
            return 'weakening'
    else:
        if distance_pct < -3:
            return 'active'
        elif distance_pct < break_dist_pct:
            return 'tested'
        else:
            consec = 0
            for i in range(n - 1, max(n - 6, -1), -1):
                line_i = math.exp(slope * i + intercept)
                if closes[i] > line_i:
                    consec += 1
                else:
                    break
            if consec >= config['break_close_count']:
                if distance_pct > break_dist_pct * 3:
                    return 'invalidated'
                return 'broken'
            return 'weakening'


# ── Phase 5: Deduplication ───────────────────────────────────────────────────

def _dedup_levels(levels: list[dict], tol_pct: float = 2.0) -> list[dict]:
    if len(levels) <= 1:
        return levels

    levels = sorted(levels, key=lambda l: -l['score'])
    keep: list[dict] = []
    for lvl in levels:
        center = lvl['center_price']
        dup = False
        for kept in keep:
            if abs(center / kept['center_price'] - 1) < tol_pct / 100:
                dup = True
                break
        if not dup:
            keep.append(lvl)
    return keep


# ── Phase 6: Flip detection ─────────────────────────────────────────────────

def _detect_flips(
    supports: list[dict],
    resistances: list[dict],
    rows: list[dict],
    config: dict,
) -> None:
    """Mark broken supports that act as resistance (and vice versa) as flipped."""
    n = len(rows)
    lookback = min(20, n)
    last_close = float(rows[-1]['close'])

    for s in supports:
        if s['state'] != 'broken':
            continue
        zone_max = s['zone_max']
        # Broken support: price below zone. If price came back UP to the zone
        # and got rejected DOWN → flipped to resistance
        zone_tests = 0
        for i in range(n - lookback, n):
            h = float(rows[i]['high'])
            c = float(rows[i]['close'])
            if h >= s['zone_min'] and c < s['zone_max']:
                zone_tests += 1
        if zone_tests >= 2 and last_close < s['zone_min']:
            s['state'] = 'flipped'
            s['role'] = 'resistance'
            s['explanation'] += ' Flip: soporte roto ahora actúa como resistencia.'

    for r in resistances:
        if r['state'] != 'broken':
            continue
        zone_tests = 0
        for i in range(n - lookback, n):
            l = float(rows[i]['low'])
            c = float(rows[i]['close'])
            if l <= r['zone_max'] and c > r['zone_min']:
                zone_tests += 1
        if zone_tests >= 2 and last_close > r['zone_max']:
            r['state'] = 'flipped'
            r['role'] = 'support'
            r['explanation'] += ' Flip: resistencia rota ahora actúa como soporte.'


# ── Phase 7: Limit visible ──────────────────────────────────────────────────

def _limit_visible(items: list[dict], max_n: int) -> list[dict]:
    items = sorted(items, key=lambda x: -x['score'])
    return items[:max_n]


# ── Main ─────────────────────────────────────────────────────────────────────

def calculate_sr(
    symbol: str,
    timeframe: str = 'W',
    fecha: Optional[date] = None,
    config: Optional[dict] = None,
) -> dict:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    fecha = fecha or date.today()

    rows: list[dict] = []
    tf = timeframe
    for cand in ([tf] if tf else ['W', 'D']):
        r = _load(symbol, cand, fecha)
        if r and len(r) >= 50:
            rows = r
            tf = cand
            break

    if not rows:
        return {
            'symbol': symbol, 'timeframe': tf, 'bars': 0,
            'price': None, 'atr': None,
            'supports': [], 'resistances': [], 'trendlines': [],
            'pivots_high': [], 'pivots_low': [],
            'config': cfg,
        }

    n = len(rows)
    highs = [float(r['high']) for r in rows]
    lows = [float(r['low']) for r in rows]
    closes = [float(r['close']) for r in rows]
    atrs = _calc_atr(rows)

    # Phase 2: Pivots
    pivot_highs, pivot_lows = _detect_pivots(highs, lows, cfg)

    # Phase 3: Horizontal levels
    h_supports = _build_horizontal_levels(pivot_lows, 'support', rows, atrs, cfg)
    h_resistances = _build_horizontal_levels(pivot_highs, 'resistance', rows, atrs, cfg)

    # Phase 4: Diagonal trendlines
    trendlines = _build_trendlines(
        pivot_lows, pivot_highs, rows, highs, lows, closes, atrs, cfg,
    )

    # Phase 5: Dedup
    h_supports = _dedup_levels(h_supports)
    h_resistances = _dedup_levels(h_resistances)

    # Phase 6: Flips
    _detect_flips(h_supports, h_resistances, rows, cfg)

    # Phase 7: Limit visible
    h_supports = _limit_visible(h_supports, cfg['max_visible_horizontal_supports'])
    h_resistances = _limit_visible(h_resistances, cfg['max_visible_horizontal_resistances'])
    trendlines = _limit_visible(trendlines, cfg['max_visible_trendlines'])

    return {
        'symbol': symbol,
        'timeframe': tf,
        'bars': n,
        'price': round(closes[-1], 2),
        'atr': round(atrs[-1], 2) if atrs[-1] else None,
        'supports': h_supports,
        'resistances': h_resistances,
        'trendlines': trendlines,
        'pivots_high': [{'fecha': rows[p['idx']]['fecha'].isoformat(), 'price': p['price'], 'strength': p['strength']} for p in pivot_highs],
        'pivots_low': [{'fecha': rows[p['idx']]['fecha'].isoformat(), 'price': p['price'], 'strength': p['strength']} for p in pivot_lows],
        'config': cfg,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import json
    sym = sys.argv[1] if len(sys.argv) > 1 else 'AMD'
    res = calculate_sr(sym)
    # Strip line_points for compact output
    for tl in res.get('trendlines', []):
        tl['line_points_count'] = len(tl.get('line_points', []))
        tl.pop('line_points', None)
        tl.pop('zone_upper_points', None)
        tl.pop('zone_lower_points', None)
    print(json.dumps(res, indent=2, default=str))
