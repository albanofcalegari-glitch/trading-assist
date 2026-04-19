"""
dynamic_resistances.py  --  Resistencias dinamicas descendentes (3 tiers)

Espejo de `dynamic_supports.py` pero conectando MAXIMOS con trendlines
DESCENDENTES (slope < 0) en log-space, pensadas para mostrarse juntas en el
chart:

  long  (rojo)      estructural, primer ancla en la 1ra mitad del historico.
  mid   (naranja)   sigue rallies bajistas recientes, anclas en el ultimo 30%/15%.
  short (magenta)   la caida mas reciente, ancla #2 en el ultimo 3% (pasa por
                    las ultimas velas).

Algoritmo (cada tier):
  1. Pivots altos: `highs[i] = max(highs[i-win : i+win+1])`. Window adaptativo.
  2. Log-space fit: para cada par (i,j) con j-i >= min_span y pendiente < 0,
     trazar recta `y = slope*x + intercept` en log(high).
  3. Score = touches*4 - violations*10 + span*0.03.
  4. Para mid/short: filtrar por posicion de anclas y por ratio de proyeccion
     (si la linea proyecta muy por debajo del precio, es resistencia rota
     al alza: descartar).
  5. Back-transform: `precio(t) = exp(slope*t + intercept)`.

Funcion publica:
    get_dynamic_resistances(symbol, fecha=today) -> dict

Semantica respecto a supports (para mantener los invariantes al espejar):
  - "line crosses body": para supports rechaza si linea queda ARRIBA del
    body_low. Para resistances rechaza si linea queda DEBAJO del body_high.
  - "violation": para supports es close ROMPIO abajo (trend > body_low+tol).
    Para resistances es close ROMPIO arriba (trend < body_high-tol).
  - "touch": supports usa wick_low; resistances usa wick_high.
  - "chain": supports = higher lows; resistances = lower highs.
  - "obsolete post-anchor": supports detecta pivot con wick muy ARRIBA de
    la linea (mercado subio mucho); resistances detecta pivot con wick muy
    DEBAJO (mercado bajo mucho).
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db.connection import get_conn


# ── Constantes (espejo de dynamic_supports.py) ───────────────────────────────
# Se reusan los mismos valores asumiendo simetria up/down; si el user reporta
# que algun tier queda mal, ajustamos individualmente.

PRICE_TOL_PCT   = 4.0
PIVOT_WIN_W     = 12
PIVOT_WIN_W_SML = 6
MIN_SPAN_BARS   = 40
MIN_SPAN_BARS_SML = 25

MIN_TOUCHES = 3

INVALIDATE_RECENT_BARS   = 8
INVALIDATE_MAX_DIST_PCT  = 5.0

OBSOLETE_POST_ANCHOR_GAP_PCT = 30.0

REGRESSION_TOL_PCT = 13.0

# Para supports: si el precio esta >50% ARRIBA de la proyeccion, la linea
# quedo atras. Para resistances el mirror: si el precio esta >50% DEBAJO de
# la proyeccion (i.e. la linea quedo muy arriba), la resistencia ya no es
# actionable. Misma tolerancia que supports — ajustar si Julian lo pide.
LONG_MAX_BELOW_PROJECTION_PCT = 50.0

# La linea no puede atravesar ningun cuerpo de vela. Tolerancia visual minima.
NO_BODY_CROSS_TOL_PCT = 0.5

# Sideways (lateralizacion): detectar TECHO horizontal en vez de piso.
SIDEWAYS_WINDOW_BARS        = 10
SIDEWAYS_MAX_REL_STDEV      = 0.08
SIDEWAYS_CEILING_TOL_PCT    = 5.0    # bar "toca" techo si high dentro del 5%
SIDEWAYS_MIN_CEILING_TOUCHES = 2
# Si el techo sigue SUBIENDO (running_max crece mucho), es tendencia alcista
# no lateralizacion. Mirror de SIDEWAYS_MAX_FLOOR_DROP_PCT (en supports es
# negativo porque el floor baja; aca es positivo porque el ceiling sube).
SIDEWAYS_MAX_CEILING_RISE_PCT = 12.0
SIDEWAYS_MAX_TREND_PCT_YR     = 100.0

# Testing/broken bands (resistencia)
_TESTING_TOL = 0.03


# ── Carga de datos ───────────────────────────────────────────────────────────

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


# ── Pivots ───────────────────────────────────────────────────────────────────

def _pivot_highs(highs: list[float], win: int, min_fwd: int = 3) -> list[int]:
    """
    Detecta pivots altos con ventana simetrica `win`. Espejo de _pivot_lows.
    """
    n = len(highs)
    out: list[int] = []
    for i in range(win, n):
        right = min(i + win + 1, n)
        if right - i - 1 < min_fwd:
            continue
        window = highs[i - win: right]
        if highs[i] == max(window):
            out.append(i)
    return out


# ── Hard constraint: la linea no atraviesa cuerpos de velas ─────────────────

def _line_crosses_any_body(
    slope:     float,
    intercept: float,
    log_body:  list[float],
    i0:        int,
    i1:        int,
) -> bool:
    """
    Rechaza la linea si `slope*k + intercept < log(body_high[k]) - tol` para
    ALGUNA barra k en [i0, i1]. Es decir: la linea no puede quedar por debajo
    del techo del cuerpo (si queda abajo, la vela atraviesa la linea por
    arriba — resistencia atravesada por un cuerpo).
    """
    body_tol = math.log(1 + NO_BODY_CROSS_TOL_PCT / 100)
    for k in range(i0, i1 + 1):
        if slope * k + intercept < log_body[k] - body_tol:
            return True
    return False


# ── Best-line search en log-space ────────────────────────────────────────────

def _fit_trendline_log(
    highs:          list[float],
    body_highs:     list[float],
    pivots:         list[int],
    min_span:       int,
    tol_pct:        float,
    anchor1_range:  Optional[tuple[float, float]] = None,
    anchor2_min:    Optional[float] = None,
    min_proj_ratio: Optional[float] = None,
    n_total:        Optional[int] = None,
    min_touches:    int = MIN_TOUCHES,
    strict_wick:    bool = True,
    max_span:       Optional[int] = None,
) -> Optional[dict]:
    """
    Busca la mejor trendline DESCENDENTE (slope < 0) de resistencia.

    `strict_wick=True`: touch cuenta solo si la trendline pasa cerca de la
    MECHA superior (`highs[i]`) con tol — el approach clasico de unir puntas
    de sombras superiores.
    `strict_wick=False`: acepta tambien touches en el techo del cuerpo
    (`body_highs[i]`).

    `min_proj_ratio`: si la proyeccion en la ultima barra queda por debajo
    de `last_px * min_proj_ratio`, la linea esta "atras" (mercado ya la
    dejo muy abajo). Equivalente a `max_proj_ratio` en supports pero con
    sentido invertido.
    """
    if len(pivots) < 2:
        return None

    log_tol  = math.log(1 + tol_pct / 100)
    log_wick = [math.log(v) if v > 0 else 0.0 for v in highs]
    log_body = [math.log(v) if v > 0 else 0.0 for v in body_highs]
    N        = n_total if n_total is not None else len(highs)
    last_px  = highs[-1]
    best: Optional[dict] = None

    for a in range(len(pivots)):
        if anchor1_range is not None:
            f1 = pivots[a] / max(N - 1, 1)
            if f1 < anchor1_range[0] or f1 > anchor1_range[1]:
                continue

        for b in range(a + 1, len(pivots)):
            if anchor2_min is not None:
                f2 = pivots[b] / max(N - 1, 1)
                if f2 < anchor2_min:
                    continue

            i, j = pivots[a], pivots[b]
            span = j - i
            if span < min_span:
                continue
            if max_span is not None and span > max_span:
                continue

            slope = (log_wick[j] - log_wick[i]) / span
            if slope >= 0:  # descending only
                continue
            intercept = log_wick[i] - slope * i

            if min_proj_ratio is not None:
                proj_last = math.exp(slope * (N - 1) + intercept)
                if proj_last < last_px * min_proj_ratio:
                    continue

            # Obsolete post-anchor: pivot p > j con wick muy DEBAJO de la
            # linea proyectada → el mercado rompio hacia abajo, la linea
            # es historia. Solo aplica si el precio actual tambien sigue
            # debajo de la linea (analogo al criterio de supports).
            obsolete = False
            gap_thr = math.log(1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100)
            proj_last_val = math.exp(slope * (N - 1) + intercept)
            if last_px < proj_last_val * (1 - OBSOLETE_POST_ANCHOR_GAP_PCT / 100):
                for p in pivots:
                    if p <= j:
                        continue
                    if (slope * p + intercept) - log_wick[p] > gap_thr:
                        obsolete = True
                        break
            if obsolete:
                continue

            # Hard: la linea no puede atravesar cuerpos en [anchor1, anchor2].
            if _line_crosses_any_body(slope, intercept, log_body, i, j):
                continue

            touches = 0
            violations = 0
            violations_post = 0
            touching: list[int] = []
            for p in pivots:
                if p < i:
                    continue
                trend_val = slope * p + intercept
                hi = log_wick[p]        # techo: la mecha alta
                lo = log_body[p]        # piso del rango de contacto: cuerpo
                if trend_val < lo - log_tol:
                    # linea pasa por debajo del cuerpo — el close rompio por arriba
                    if p > j:
                        violations_post += 1
                    else:
                        violations += 1
                elif strict_wick:
                    if abs(trend_val - hi) <= log_tol:
                        touches += 1
                        touching.append(p)
                elif trend_val <= hi + log_tol:
                    # linea dentro de [body - tol, wick + tol] → toque
                    touches += 1
                    touching.append(p)

            if touches < min_touches:
                continue

            # Filtro "higher high missed": si existe un pivot p en (j-WINDOW, j)
            # cuyo wick es MAS ALTO que el de anchor2 AND queda flotando muy
            # DEBAJO de la linea, la linea deberia haber anclado en p.
            HIGHER_HIGH_WINDOW = 60
            HIGHER_HIGH_GAP = log_tol * 2
            skip_higher_high = False
            for p in pivots:
                if p >= j or p <= j - HIGHER_HIGH_WINDOW or p < i:
                    continue
                if highs[p] > highs[j] and (slope * p + intercept) - log_wick[p] > HIGHER_HIGH_GAP:
                    skip_higher_high = True
                    break
            if skip_higher_high:
                continue

            score = touches * 4.0 - violations * 10.0 - violations_post * 2.0 + span * 0.03
            if best is None or score > best['score']:
                best = dict(
                    slope=slope, intercept=intercept,
                    anchors=(i, j),
                    touches=touches, violations=violations + violations_post,
                    span=span, score=score,
                    touching_idxs=touching,
                )

    return best


def _try_fit(
    highs:      list[float],
    body_highs: list[float],
    piv_lists:  list[list[int]],
    **kwargs,
) -> Optional[dict]:
    """
    Prueba regresion sobre cadenas de lower-highs + linea exacta strict/flexible,
    se queda con el mejor score global.
    """
    exact_kwargs = {k: v for k, v in kwargs.items() if k != 'apply_obsolete'}
    req_touches = kwargs.get('min_touches', MIN_TOUCHES)

    best: Optional[dict] = None
    def keep(cand: Optional[dict]) -> None:
        nonlocal best
        if cand is None:
            return
        if best is None or cand['score'] > best['score']:
            best = cand

    for piv in piv_lists:
        if len(piv) < req_touches:
            continue
        keep(_fit_regression_log(highs, body_highs, piv, **kwargs))
        keep(_fit_trendline_log(highs, body_highs, piv, strict_wick=True,  **exact_kwargs))
        keep(_fit_trendline_log(highs, body_highs, piv, strict_wick=False, **exact_kwargs))
    return best


def _falling_chain(pivots: list[int], highs: list[float], start_k: int) -> list[int]:
    """
    Cadena greedy de LOWER highs arrancando en `pivots[start_k]`: suma el
    siguiente pivot si su `high` es estrictamente menor al ultimo incluido.
    """
    chain = [pivots[start_k]]
    for p in pivots[start_k + 1:]:
        if highs[p] < highs[chain[-1]]:
            chain.append(p)
    return chain


def _fit_regression_log(
    highs:          list[float],
    body_highs:     list[float],
    pivots:         list[int],
    min_span:       int,
    tol_pct:        float,
    anchor1_range:  Optional[tuple[float, float]] = None,
    anchor2_min:    Optional[float] = None,
    min_proj_ratio: Optional[float] = None,
    n_total:        Optional[int] = None,
    min_touches:    int = MIN_TOUCHES,
    apply_obsolete: bool = True,
    max_span:       Optional[int] = None,
) -> Optional[dict]:
    """
    Regresion lineal sobre cadenas de lower-highs en log-space.
    """
    if len(pivots) < min_touches:
        return None

    reg_tol  = math.log(1 + REGRESSION_TOL_PCT / 100)
    viol_tol = math.log(1 + tol_pct / 100)
    obs_gap  = math.log(1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100)
    log_wick = [math.log(v) if v > 0 else 0.0 for v in highs]
    log_body = [math.log(v) if v > 0 else 0.0 for v in body_highs]
    N        = n_total if n_total is not None else len(highs)
    last_px  = highs[-1]
    best: Optional[dict] = None

    for start_k in range(len(pivots) - min_touches + 1):
        chain = _falling_chain(pivots, highs, start_k)
        if len(chain) < min_touches:
            continue

        i0 = chain[0]
        i1 = chain[-1]

        if anchor1_range is not None:
            f1 = i0 / max(N - 1, 1)
            if f1 < anchor1_range[0] or f1 > anchor1_range[1]:
                continue
        if anchor2_min is not None:
            f2 = i1 / max(N - 1, 1)
            if f2 < anchor2_min:
                continue
        if i1 - i0 < min_span:
            continue
        if max_span is not None and i1 - i0 > max_span:
            continue

        m = len(chain)
        xs = chain
        ys = [log_wick[p] for p in chain]
        mean_x = sum(xs) / m
        mean_y = sum(ys) / m
        num = sum((xs[k] - mean_x) * (ys[k] - mean_y) for k in range(m))
        den = sum((xs[k] - mean_x) ** 2 for k in range(m))
        if den == 0:
            continue
        slope = num / den
        if slope >= 0:  # descending only
            continue
        intercept_reg = mean_y - slope * mean_x

        chain_ok = True
        for p in chain:
            if abs(log_wick[p] - (slope * p + intercept_reg)) > reg_tol:
                chain_ok = False
                break
        if not chain_ok:
            continue

        # Upper envelope: usar el slope de la regresion pero subir el intercept
        # para que la linea pase por la mecha mas alta de la cadena. Asi la
        # linea toca las puntas de las mechas superiores (como Julian dibuja
        # en TradingView) en vez de flotar por el medio de los cuerpos.
        intercept = max(log_wick[p] - slope * p for p in chain)

        if _line_crosses_any_body(slope, intercept, log_body, i0, i1):
            continue

        if min_proj_ratio is not None:
            proj_last = math.exp(slope * (N - 1) + intercept)
            if proj_last < last_px * min_proj_ratio:
                continue

        if apply_obsolete:
            proj_last_val = math.exp(slope * (N - 1) + intercept)
            if last_px < proj_last_val * (1 - OBSOLETE_POST_ANCHOR_GAP_PCT / 100):
                obsolete = any(
                    (slope * p + intercept) - log_wick[p] > obs_gap
                    for p in pivots if p > i1
                )
                if obsolete:
                    continue

        chain_set = set(chain)
        violations = 0
        violations_post = 0
        for p in pivots:
            if p < i0 or p in chain_set:
                continue
            # violation: close rompio por arriba → body_high > line + tol
            if slope * p + intercept < log_body[p] - viol_tol:
                if p > i1:
                    violations_post += 1
                else:
                    violations += 1

        HIGHER_HIGH_WINDOW = 60
        HIGHER_HIGH_GAP = math.log(1 + PRICE_TOL_PCT / 100) * 2
        skip_higher_high = False
        for p in pivots:
            if p >= i1 or p <= i1 - HIGHER_HIGH_WINDOW or p < i0:
                continue
            if highs[p] > highs[i1] and (slope * p + intercept) - log_wick[p] > HIGHER_HIGH_GAP:
                skip_higher_high = True
                break
        if skip_higher_high:
            continue

        touches = len(chain)
        span    = i1 - i0
        score   = touches * 4.0 - violations * 10.0 - violations_post * 2.0 + span * 0.03

        if best is None or score > best['score']:
            best = dict(
                slope=slope, intercept=intercept,
                anchors=(i0, i1),
                touches=touches, violations=violations + violations_post,
                span=span, score=score,
                touching_idxs=list(chain),
            )

    return best


def _detect_sideways_horizontal(
    highs:      list[float],
    body_highs: list[float],
    lows:       list[float],
    closes:     list[float],
    n:          int,
    tf:         str,
) -> Optional[dict]:
    """
    Detecta lateralizacion reciente y traza una resistencia horizontal + zona.

    Espejo de _detect_sideways_horizontal en supports:
    - supports: piso = min(lows), zona_top = max(highs) (banda del rango)
    - resistances: techo = max(highs), zona_bottom = min(lows) (banda del rango)

    Criterios:
      1. stdev(highs)/mean(highs) < SIDEWAYS_MAX_REL_STDEV
      2. >= SIDEWAYS_MIN_CEILING_TOUCHES bars con high dentro del SIDEWAYS_CEILING_TOL_PCT del max
      3. running_max no sigue creciendo mas que SIDEWAYS_MAX_CEILING_RISE_PCT
      4. slope close anualizado no rompe en breakout (|slope_pct_yr| < 100)
    """
    window = min(SIDEWAYS_WINDOW_BARS, n)
    if window < 6:
        return None

    start = n - window
    recent_highs  = highs[start:]
    recent_lows   = lows[start:]
    recent_closes = closes[start:]
    if min(recent_highs) <= 0:
        return None

    mean_high = sum(recent_highs) / len(recent_highs)
    var_high  = sum((v - mean_high) ** 2 for v in recent_highs) / len(recent_highs)
    stdev_high = var_high ** 0.5
    if mean_high <= 0 or stdev_high / mean_high > SIDEWAYS_MAX_REL_STDEV:
        return None

    ceiling = max(recent_highs)

    ceiling_tol = SIDEWAYS_CEILING_TOL_PCT / 100
    touches_idxs = [start + k for k, v in enumerate(recent_highs)
                    if 1 - v / ceiling <= ceiling_tol]
    if len(touches_idxs) < SIDEWAYS_MIN_CEILING_TOUCHES:
        return None

    # running_max no sigue creciendo mucho (si lo hace es breakout, no lateral)
    running_max = recent_highs[0]
    for v in recent_highs[1:]:
        if v > running_max:
            running_max = v
    ceiling_rise_pct = (running_max / recent_highs[0] - 1) * 100
    if ceiling_rise_pct > SIDEWAYS_MAX_CEILING_RISE_PCT:
        return None

    # Guard contra breakout bajista — pendiente close anualizada no muy negativa
    m = len(recent_closes)
    if m >= 3:
        xs = list(range(m))
        ys = [math.log(c) for c in recent_closes if c > 0]
        if len(ys) == m:
            mean_x = sum(xs) / m
            mean_y = sum(ys) / m
            num = sum((xs[k] - mean_x) * (ys[k] - mean_y) for k in range(m))
            den = sum((xs[k] - mean_x) ** 2 for k in range(m))
            if den != 0:
                slope_close  = num / den
                bars_per_year = {'W': 52, 'D': 252, 'M': 12}.get(tf, 252)
                slope_pct_yr = (math.exp(slope_close * bars_per_year) - 1) * 100
                if abs(slope_pct_yr) > SIDEWAYS_MAX_TREND_PCT_YR:
                    return None

    zone_bottom = min(recent_lows)

    return {
        'slope':         0.0,
        'intercept':     math.log(ceiling),
        'anchors':       (touches_idxs[0], touches_idxs[-1]),
        'touches':       len(touches_idxs),
        'violations':    0,
        'span':          touches_idxs[-1] - touches_idxs[0],
        'score':         len(touches_idxs) * 4.0,
        'touching_idxs': list(touches_idxs),
        # Para tier horizontal de resistencia, `zone_bottom` marca el piso de
        # la banda (mientras que en supports `zone_top` marcaba el techo).
        # El frontend usa este campo para renderizar la zona; mantengo el
        # nombre `zone_top` porque el componente PriceZone espera {floor, top}
        # y aca el "floor" es el ceiling de la lateral y el "top"... hmm.
        # Mejor usar nombres distintos para evitar confusion:
        'zone_floor':    zone_bottom,   # bottom of the lateral band
        'zone_ceiling':  ceiling,       # top of the lateral band = resistencia
        'kind':          'horizontal',
    }


def _slope_annual_pct(slope_per_bar: float, tf: str) -> float:
    bars_per_year = {'W': 52, 'D': 252, 'M': 12}.get(tf, 252)
    return (math.exp(slope_per_bar * bars_per_year) - 1) * 100


def _tier_is_invalidated_by_trend(tl: dict, rows: list[dict]) -> bool:
    """
    Si el precio reciente viene SUBIENDO y estamos cerca de la resistencia por
    arriba (ya la rompio y sigue subiendo), la "resistencia" ya no es
    resistencia. Espejo del mismo concepto en supports (ahi se aplica cuando
    el precio viene BAJANDO y la rompe por abajo).
    """
    n = len(rows)
    last_close   = float(rows[-1]['close'])
    current_val  = math.exp(tl['slope'] * (n - 1) + tl['intercept'])
    distance_pct = (last_close / current_val - 1) * 100

    # Solo aplica cuando el precio esta ARRIBA de la linea y a menos del
    # threshold de distancia. Si esta debajo con slope positivo todavia no
    # rompio — mostrar la linea.
    if distance_pct <= 0 or distance_pct >= INVALIDATE_MAX_DIST_PCT:
        return False

    closes = [float(r['close']) for r in rows[-INVALIDATE_RECENT_BARS:]]
    if len(closes) < 3:
        return False

    m = len(closes)
    xs = list(range(m))
    ys = [math.log(c) for c in closes if c > 0]
    if len(ys) != m:
        return False
    mean_x = sum(xs) / m
    mean_y = sum(ys) / m
    num = sum((xs[k] - mean_x) * (ys[k] - mean_y) for k in range(m))
    den = sum((xs[k] - mean_x) ** 2 for k in range(m))
    if den == 0:
        return False
    slope_recent = num / den
    return slope_recent > 0


# ── Dominant-high rescue ────────────────────────────────────────────────────

DOMINANT_HIGH_RATIO = 1.25  # argmax > 2do_max * 1.25 → pivot "dominante"


def _try_dominant_high_rescue(
    highs:         list[float],
    body_highs:    list[float],
    pivots_all:    list[int],
    min_span:      int,
    max_span:      int,
    anchor1_range: tuple[float, float],
    anchor2_min:   float,
    n_total:       int,
    tol_pct:       float,
) -> Optional[dict]:
    """
    Rescate para tickers donde el maximo absoluto es un pivot claramente
    dominante (>=25% por encima del 2do maximo) — tipico de bubbles post-rally
    fuerte. La linea exacta desde ese techo hasta un anchor2 reciente no suele
    tener 3 pivots colineares; aceptamos 2 toques cuando el anclaje en ese
    maximo dominante es obvio.
    """
    if len(pivots_all) < 2:
        return None
    pivots_all = sorted(set(pivots_all))
    piv_sorted = sorted(pivots_all, key=lambda p: -highs[p])
    imax = piv_sorted[0]
    second_high = highs[piv_sorted[1]]
    if second_high <= 0 or highs[imax] <= second_high * DOMINANT_HIGH_RATIO:
        return None

    N = n_total
    f1 = imax / max(N - 1, 1)
    if not (anchor1_range[0] <= f1 <= anchor1_range[1]):
        return None

    log_hi_imax = math.log(highs[imax])
    log_body    = [math.log(v) if v > 0 else 0.0 for v in body_highs]
    log_wick    = [math.log(v) if v > 0 else 0.0 for v in highs]
    log_tol     = math.log(1 + tol_pct / 100)
    obs_gap     = math.log(1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100)

    best: Optional[dict] = None
    for p2 in pivots_all:
        if p2 <= imax:
            continue
        f2 = p2 / max(N - 1, 1)
        if f2 < anchor2_min:
            continue
        span = p2 - imax
        if span < min_span or span > max_span:
            continue
        slope = (math.log(highs[p2]) - log_hi_imax) / span
        if slope >= 0:
            continue
        intercept = log_hi_imax - slope * imax

        if _line_crosses_any_body(slope, intercept, log_body, imax, p2):
            continue

        obsolete = False
        for p in pivots_all:
            if p <= p2:
                continue
            if (slope * p + intercept) - log_wick[p] > obs_gap:
                obsolete = True
                break
        if obsolete:
            continue

        touches = 0
        violations = 0
        touching: list[int] = []
        for p in pivots_all:
            trend = slope * p + intercept
            hi = log_wick[p]
            lo = log_body[p]
            if trend < lo - log_tol:
                violations += 1
            elif trend <= hi + log_tol:
                touches += 1
                touching.append(p)

        score = touches * 4.0 - violations * 10.0 + span * 0.03
        if best is None or score > best['score']:
            best = dict(
                slope=slope, intercept=intercept,
                anchors=(imax, p2),
                touches=touches, violations=violations,
                span=span, score=score,
                touching_idxs=touching,
            )

    return best


# ── Construccion del tier de respuesta ──────────────────────────────────────

def _build_tier(
    tl:         dict,
    rows:       list[dict],
    tf:         str,
) -> dict:
    """
    Arma el dict de respuesta de una trendline (resistencia).
    """
    n = len(rows)
    slope = tl['slope']
    intercept = tl['intercept']
    i0, i1 = tl['anchors']
    highs = [float(r['high']) for r in rows]

    line_points = []
    for x in range(i0, n):
        y = math.exp(slope * x + intercept)
        line_points.append({
            'fecha': rows[x]['fecha'].isoformat(),
            'value': round(y, 4),
        })

    current_value = math.exp(slope * (n - 1) + intercept)
    price = float(rows[-1]['close'])
    distance_pct = (price / current_value - 1) * 100

    # Para resistencias: distance > 0 = precio arriba de la linea = resistencia
    # ROTA/BROKEN; distance < 0 = precio abajo = ACTIVE. Invertido respecto a
    # supports.
    if distance_pct < -_TESTING_TOL * 100:
        status = 'ACTIVE'
    elif distance_pct > _TESTING_TOL * 100:
        status = 'BROKEN'
    else:
        status = 'TESTING'

    out = {
        'status': status,
        'anchor1': {
            'fecha': rows[i0]['fecha'].isoformat(),
            'value': round(highs[i0], 4),
        },
        'anchor2': {
            'fecha': rows[i1]['fecha'].isoformat(),
            'value': round(highs[i1], 4),
        },
        'line_points':      line_points,
        'current_value':    round(current_value, 4),
        'distance_pct':     round(distance_pct, 2),
        'slope_annual_pct': round(_slope_annual_pct(slope, tf), 2),
        'touches':          tl['touches'],
        'violations':       tl['violations'],
        'kind':             tl.get('kind', 'descending'),
    }
    # Zonas horizontales: floor + ceiling (equivalente a zone_top en supports
    # pero nombrado explicitamente para evitar confusion semantica).
    if 'zone_floor' in tl:
        out['zone_floor']   = round(tl['zone_floor'], 4)
    if 'zone_ceiling' in tl:
        out['zone_ceiling'] = round(tl['zone_ceiling'], 4)
    return out


# ── Main ─────────────────────────────────────────────────────────────────────

def get_dynamic_resistances(symbol: str, fecha: Optional[date] = None,
                            tf: Optional[str] = None) -> dict:
    """
    Devuelve 3 resistencias dinamicas (long/mid/short) sobre el historico
    semanal. Fallback a diario si no hay suficientes barras semanales.

    Si se pasa `tf` ('W' o 'D'), fuerza ese timeframe sin fallback.
    """
    fecha = fecha or date.today()

    rows: list[dict] = []
    if tf in ('W', 'D'):
        rows = _load(symbol, tf, fecha) or []
        if not rows or len(rows) < 80:
            rows = []
    else:
        tf = 'W'
        for cand in ('W', 'D'):
            r = _load(symbol, cand, fecha)
            if r and len(r) >= 80:
                rows = r
                tf = cand
                break

    if not rows:
        return {
            'symbol':         symbol,
            'timeframe_used': None,
            'bars_of_data':   0,
            'price':          None,
            'long':  None,
            'mid':   None,
            'short': None,
        }

    highs      = [float(r['high']) for r in rows]
    body_highs = [max(float(r['open']), float(r['close'])) for r in rows]
    n = len(rows)
    price = float(rows[-1]['close'])

    if tf == 'W':
        if n < 400:
            win_long_px, min_span_long = PIVOT_WIN_W_SML, MIN_SPAN_BARS_SML
        else:
            win_long_px, min_span_long = PIVOT_WIN_W, MIN_SPAN_BARS
    else:
        win_long_px, min_span_long = 20, MIN_SPAN_BARS * 5

    win_mid_px = max(4, win_long_px // 2)
    span_mid   = max(15, min_span_long // 2)
    span_short = max(6, span_mid // 3)

    piv_long  = _pivot_highs(highs, win_long_px)
    piv_mid   = _pivot_highs(highs, win_mid_px)
    piv_short = _pivot_highs(highs, 3)

    bars_per_year_tf = {'W': 52, 'D': 252, 'M': 12}.get(tf, 252)
    long_max_span = min(5 * bars_per_year_tf, int(n * 0.90))
    piv_combined = sorted(set(piv_long + piv_mid))

    # ── long (rojo): diagonal del bear market vigente ────────────────────────
    # Espejo de "rally start": el "decline start" = el pivot mas antiguo en el
    # rango reciente tal que TODOS los pivots posteriores tienen high <= su
    # high. Es el inicio del bear vigente (el precio nunca rompio por encima
    # desde entonces).
    anchor1_lo_idx = max(int(0.30 * (n - 1)), n - long_max_span)
    anchor1_hi_idx = int(0.98 * (n - 1))
    decline_candidates = []
    for k, p in enumerate(piv_combined):
        if not (anchor1_lo_idx <= p <= anchor1_hi_idx):
            continue
        later_highs = [highs[q] for q in piv_combined[k+1:]]
        if not later_highs or max(later_highs) <= highs[p]:
            decline_candidates.append(p)

    # min_proj_ratio=0.67 rechaza si la proyeccion queda >50% debajo de last_px
    # (la linea quedo muy arriba y el mercado ya no la alcanza). Mirror de
    # max_proj_ratio=1.5 en supports.
    long_tl = _try_fit(
        highs, body_highs, [piv_long, piv_mid, piv_combined],
        min_span=span_mid, tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.30, 0.98),
        anchor2_min=0.85,
        max_span=long_max_span,
        min_proj_ratio=1.0 / 1.5,
        n_total=n, apply_obsolete=True,
    )

    if decline_candidates:
        decline_start_idx = decline_candidates[0]
        piv_long_r     = [p for p in piv_long     if p >= decline_start_idx]
        piv_mid_r      = [p for p in piv_mid      if p >= decline_start_idx]
        piv_combined_r = [p for p in piv_combined if p >= decline_start_idx]
        f1_lock = decline_start_idx / (n - 1) if n > 1 else 0.0
        anchor1_range_lock = (max(0.0, f1_lock - 0.002), min(1.0, f1_lock + 0.002))
        long_tl_locked = _try_fit(
            highs, body_highs, [piv_long_r, piv_mid_r, piv_combined_r],
            min_span=span_mid, tol_pct=PRICE_TOL_PCT,
            anchor1_range=anchor1_range_lock,
            anchor2_min=0.85,
            max_span=long_max_span,
            min_proj_ratio=1.0 / 1.5,
            n_total=n, apply_obsolete=True,
        )
        if long_tl_locked is not None:
            long_tl = long_tl_locked

    rescue_long = _try_dominant_high_rescue(
        highs, body_highs, sorted(set(piv_long + piv_mid)),
        min_span=span_mid, max_span=long_max_span,
        anchor1_range=(0.30, 0.98), anchor2_min=0.85,
        n_total=n, tol_pct=PRICE_TOL_PCT,
    )
    if rescue_long is not None:
        if long_tl is None:
            long_tl = rescue_long
        else:
            cur_i0 = long_tl['anchors'][0]
            r_i0   = rescue_long['anchors'][0]
            if r_i0 < cur_i0 - 20 and highs[r_i0] > highs[cur_i0] * 1.25:
                long_tl = rescue_long

    # ── mid (naranja): diagonal descendente mas reciente ─────────────────────
    mid_tl = _try_fit(
        highs, body_highs, [piv_mid, piv_short],
        min_span=span_short, tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.80, 0.98),
        anchor2_min=0.97,
        n_total=n, apply_obsolete=False,
    )

    # ── short (magenta): diagonal descendente CP, fallback a horizontal ─────
    # PRIMERO: diagonal de "lower highs" de la pierna bajista actual, con
    # anchor1 muy cercano al presente (ultimo ~5%). Relajamos a min_touches=2
    # porque una resistencia CP recien formada tipicamente solo tiene 2 anclas
    # claras. Si no hay diagonal valida, cae al detector de lateralizacion.
    short_tl = _try_fit(
        highs, body_highs, [piv_short, piv_mid, piv_combined],
        min_span=span_short, tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.95, 0.998),
        anchor2_min=0.99,
        min_touches=2,
        n_total=n, apply_obsolete=False,
    )
    if short_tl is None:
        closes = [float(r['close']) for r in rows]
        lows   = [float(r['low'])  for r in rows]
        short_tl = _detect_sideways_horizontal(highs, body_highs, lows, closes, n, tf)

    # ── Invalidaciones ───────────────────────────────────────────────────────
    # Long: si el precio esta >50% ABAJO de la proyeccion (linea lejos en lo
    # alto, ya no es actionable como resistencia actual).
    if long_tl is not None:
        cur = math.exp(long_tl['slope'] * (n - 1) + long_tl['intercept'])
        dist_pct = (price / cur - 1) * 100
        if dist_pct < -LONG_MAX_BELOW_PROJECTION_PCT:
            long_tl = None

    if mid_tl and _tier_is_invalidated_by_trend(mid_tl, rows):
        mid_tl = None

    # Evitar redundancia: si mid comparte anchor1 con long (dentro de 8 bars),
    # dropear mid.
    if long_tl is not None and mid_tl is not None:
        if abs(mid_tl['anchors'][0] - long_tl['anchors'][0]) <= 8:
            mid_tl = None

    return {
        'symbol':         symbol,
        'timeframe_used': tf,
        'bars_of_data':   n,
        'price':          round(price, 4),
        'long':  _build_tier(long_tl,  rows, tf) if long_tl  else None,
        'mid':   _build_tier(mid_tl,   rows, tf) if mid_tl   else None,
        'short': _build_tier(short_tl, rows, tf) if short_tl else None,
    }


if __name__ == '__main__':
    import json
    sym = sys.argv[1] if len(sys.argv) > 1 else 'GOOGL'
    res = get_dynamic_resistances(sym)
    print(json.dumps({
        'symbol': res['symbol'],
        'tf': res['timeframe_used'],
        'bars': res['bars_of_data'],
        'price': res['price'],
        **{k: (None if res[k] is None else {
            'status': res[k]['status'],
            'anchor1': res[k]['anchor1'],
            'anchor2': res[k]['anchor2'],
            'current_value': res[k]['current_value'],
            'distance_pct': res[k]['distance_pct'],
            'slope_annual_pct': res[k]['slope_annual_pct'],
            'touches': res[k]['touches'],
            'line_points_count': len(res[k]['line_points']),
        }) for k in ('long','mid','short')},
    }, indent=2, default=str))
