"""
dynamic_supports.py  --  Soportes dinamicos ascendentes (3 tiers)

Traza hasta TRES trendlines de soporte sobre el historico semanal en log-space,
pensadas para mostrarse juntas en el chart:

  long  (verde)     estructural, primer ancla en la 1ra mitad del historico.
  mid   (amarillo)  sigue pullbacks recientes, anclas en el ultimo 30%/15%.
  short (cyan)      el rally mas reciente, ancla #2 en el ultimo 3% (pasa por
                    las ultimas velas).

Algoritmo (cada tier):
  1. Pivots bajos: `lows[i] = min(lows[i-win : i+win+1])`.  Window adaptativo.
  2. Log-space fit: para cada par (i,j) con j-i >= min_span y pendiente > 0,
     trazar recta `y = slope*x + intercept` en log(low).
  3. Score = touches*4 - violations*10 + span*0.03.
  4. Para mid/short: filtrar por posicion de anclas y por ratio de proyeccion
     (si la linea proyecta >N% arriba del precio, es soporte roto: descartar).
  5. Back-transform: `precio(t) = exp(slope*t + intercept)`.

Funcion publica:
    get_dynamic_supports(symbol, fecha=today) -> dict
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db.connection import get_conn


# ── Constantes (validadas con Julian sobre AAPL/SHOP/PLTR/NVDA/GOOGL/...) ────

PRICE_TOL_PCT   = 4.0   # +/- 4% para contar "toque"
PIVOT_WIN_W     = 12    # historias >= 400 barras semanales
PIVOT_WIN_W_SML = 6     # historias < 400 barras semanales (IPOs recientes)
MIN_SPAN_BARS   = 40    # long — ~10 meses semanal
MIN_SPAN_BARS_SML = 25  # long en histories cortas

# Regla Julian (2026-04-14): cada trendline necesita al menos 3 pivots tocando.
# Los 2 anchors siempre cuentan — entonces hace falta 1 pivot extra confirmatorio.
MIN_TOUCHES = 3

# Regla Julian (2026-04-14): invalidar cuando el precio ya cambio de direccion
# cerca del soporte.  slope reciente (ult 8 closes) opuesta al tier + distance<5%.
INVALIDATE_RECENT_BARS   = 8
INVALIDATE_MAX_DIST_PCT  = 5.0

# Regla Julian (2026-04-14): descartar trendline "obsoleta".  Si existe un pivot
# posterior al anchor2 cuya mecha esta >30% por encima de la proyeccion, la
# linea no representa el soporte actual — el mercado se movio mucho mas arriba
# y se necesita una linea mas reciente.  Ejemplo ORCL: linea 2002→2022 proyecta
# ~$78 en 2025-04, pero el low real fue $118 (50% por encima) → obsoleta.
OBSOLETE_POST_ANCHOR_GAP_PCT = 30.0

# Regla Julian (2026-04-14): la esencia de una trendline es "minimos cada vez
# mas altos que coinciden con una linea recta".  Aparte del approach clasico
# (linea exacta entre 2 anchors), probamos regresion lineal sobre cadenas de
# higher lows — asi un pivot intermedio que queda 5-10% por encima de la recta
# exacta todavia puede ser "el punto del medio" de una tendencia ascendente.
# Tolerancia mas laxa porque la regresion busca el mejor fit medio.
REGRESSION_TOL_PCT = 13.0

# Regla Julian (2026-04-14): si el precio actual esta >50% arriba de la
# proyeccion de la linea, esa linea "quedo atras" — el rally la dejo obsoleta.
# Aplica al tier LONG (diagonal del rally post-bear): ej. GOOGL 2008-2025
# proyecta $171 pero precio = $314 (+82%) => la linea real es una mas reciente.
LONG_MAX_ABOVE_PROJECTION_PCT = 80.0

# Regla Julian (2026-04-14 v4, CRITICA): la linea diagonal NO puede atravesar
# ningun cuerpo de vela.  Referencia visual: TSLA queda bien porque toca mechas
# sin cortar cuerpos; el resto queda mal porque la regresion minimiza error
# cuadratico sobre pivots y deja que la recta "flote" por el medio de velas
# que no son pivots.
#
# Constraint: para TODA barra k en [anchor1, N-1], la linea tiene que estar
# por debajo (o justo en) body_low[k] + NO_BODY_CROSS_TOL_PCT.  Si la linea
# queda arriba del body_low de aunque sea 1 vela, se descarta.  Tolerancia
# minima porque es visual: en log-scale una linea 0.5% arriba del cuerpo
# todavia no se percibe como "cortando", pero mas que eso ya se nota.
NO_BODY_CROSS_TOL_PCT = 1.0

# Regla Julian (2026-04-14, revisada): detectar lateralizacion reciente y trazar
# soporte horizontal como ZONA.  El approach anterior (ultimos 3 pivots) fallaba
# cuando la caida previa era aguda: los 3 pivots mas recientes incluian el tramo
# bajista (ej. MSFT $492 -> $464 -> $356), stdev enorme, no detectaba lateral
# aunque el precio YA estuviera lateralizando en la zona baja por 8-10 semanas.
#
# Nuevo approach: ventana de barras recientes (no pivots). Si en las ultimas
# SIDEWAYS_WINDOW_BARS el rango de lows es angosto Y hay >= N bars tocando el
# piso Y la tendencia de close es plana, marcamos horizontal al piso + banda.
SIDEWAYS_WINDOW_BARS        = 10    # ~2.5 meses weekly
SIDEWAYS_MAX_REL_STDEV      = 0.08  # stdev(lows)/mean(lows) < 8% — robusto vs
                                    # picos aislados que rompian max/min_low
SIDEWAYS_FLOOR_TOL_PCT      = 5.0   # bar "toca" piso si low dentro del 5%
SIDEWAYS_MIN_FLOOR_TOUCHES  = 2     # al menos 2 bars tocando
SIDEWAYS_MAX_FLOOR_DROP_PCT = -12.0 # running_min(fin)/running_min(inicio) - 1.
                                    # Si el piso sigue cediendo mas que esto,
                                    # es tendencia bajista, no lateralizacion.
                                    # Usar running-min (no slope de close) es
                                    # mas fiel a como Julian define "lateral":
                                    # el precio puede bajar dentro de la banda,
                                    # lo clave es que el PISO no haga nuevos LL.
SIDEWAYS_MAX_TREND_PCT_YR   = 100.0 # guard contra explosiones alcistas: si la
                                    # ventana tiene slope_yr > 100% no es
                                    # lateralizacion, es breakout.
# Regla Julian (2026-04-14 v3): piso y tope de la zona tienen que ser EXTREMOS
# reales — min(lows) y max(highs) de la ventana.  Razon: con "2do low mas bajo"
# una mecha aislada quedaba DEBAJO del piso, y la linea cortaba la vela por
# el medio.  Julian: "en NINGUN caso la linea deberia trazar por el medio de
# las velas".  Con min/max absolutos la banda envuelve completamente el rango
# visible de la ventana sin cortar ninguna mecha.

# Testing/broken bands (soporte)
_TESTING_TOL = 0.03     # +/-3% = testeando


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

def _pivot_lows(lows: list[float], win: int, min_fwd: int = 3) -> list[int]:
    """
    Detecta pivots bajos con ventana simetrica `win`.

    Para las ultimas barras (en [n-win, n-1]) se permite una ventana derecha
    asimetrica: la barra califica como pivot si es el minimo en
    `[i-win, n-1]` Y hay al menos `min_fwd` barras posteriores.  Sin esta
    flexibilizacion, el minimo reciente (candidato natural para anchor2)
    nunca califica como pivot y el algoritmo no lo considera.
    """
    n = len(lows)
    out: list[int] = []
    for i in range(win, n):
        right = min(i + win + 1, n)
        if right - i - 1 < min_fwd:
            continue
        window = lows[i - win: right]
        if lows[i] == min(window):
            out.append(i)
    return out


# ── Hard constraint: la linea no atraviesa cuerpos de velas ─────────────────

def _line_crosses_any_body(
    slope:        float,
    intercept:    float,
    log_body:     list[float],
    i0:           int,
    i1:           int,
    override_tol: Optional[float] = None,
) -> bool:
    """
    Julian (v4): rechaza la linea si `slope*k + intercept > log(body_low[k]) + tol`
    para ALGUNA barra k en [i0, i1] (inclusive).  override_tol permite usar
    una tolerancia adaptativa al slope en vez de la constante global.
    """
    body_tol = override_tol if override_tol is not None else math.log(1 + NO_BODY_CROSS_TOL_PCT / 100)
    for k in range(i0, i1 + 1):
        if slope * k + intercept > log_body[k] + body_tol:
            return True
    return False


# ── Best-line search en log-space ────────────────────────────────────────────

def _fit_trendline_log(
    lows:           list[float],
    body_lows:      list[float],
    pivots:         list[int],
    min_span:       int,
    tol_pct:        float,
    anchor1_range:  Optional[tuple[float, float]] = None,
    anchor2_min:    Optional[float] = None,
    max_proj_ratio: Optional[float] = None,
    n_total:        Optional[int] = None,
    min_touches:    int = MIN_TOUCHES,
    strict_wick:    bool = True,
    max_span:       Optional[int] = None,
    body_cross_tol: float = 0.006,
) -> Optional[dict]:
    """
    Busca la mejor trendline ASCENDENTE (slope > 0) de soporte.

    Regla Julian (2026-04-14):
      - `strict_wick=True` (default): un touch cuenta solo si la trendline pasa
         cerca de la MECHA (`lows[i]`) con tol.  Es el modo clasico de dibujo
         de trendlines — une las puntas de las sombras inferiores.
      - `strict_wick=False` (fallback): acepta tambien touches en el final del
         cuerpo (`body_lows[i]`).  Se usa solo si el modo estricto no encuentra
         ninguna linea valida ("de ser necesario", segun Julian).
      En ambos modos, si la linea queda por encima del body_low + tol cuenta
      como violation (cuerpo debajo de la trendline = ruptura real).
    """
    if len(pivots) < 2:
        return None

    log_tol  = math.log(1 + tol_pct / 100)
    log_wick = [math.log(v) if v > 0 else 0.0 for v in lows]
    log_body = [math.log(v) if v > 0 else 0.0 for v in body_lows]
    N        = n_total if n_total is not None else len(lows)
    last_px  = lows[-1]
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
            if slope <= 0:
                continue
            intercept = log_wick[i] - slope * i

            if any(slope * k + intercept > log_body[k] + body_cross_tol for k in range(i, len(lows))):
                continue

            if max_proj_ratio is not None:
                proj_last = math.exp(slope * (N - 1) + intercept)
                if proj_last > last_px * max_proj_ratio:
                    continue

            # Regla Julian (2026-04-14): si hay un pivot post-anchor2 con mecha
            # muy por encima de la linea proyectada, esta linea esta obsoleta.
            # Excepcion (2026-04-15): solo aplicar si el PRECIO ACTUAL esta
            # tambien muy arriba de la linea. Si el precio volvio cerca de la
            # linea, el pivot post-anchor fue un rally peak y el precio retracto
            # — la linea sigue siendo relevante (status BROKEN / TESTING).
            # Ej. MSFT 1130->1257: 1278 ($492) flota 32% arriba de la linea
            # ($373), pero el precio actual ($386) esta -8% de la linea ($421)
            # = la linea sigue vigente, no obsoleta.
            obsolete = False
            gap_thr = math.log(1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100)
            proj_last_val = math.exp(slope * (N - 1) + intercept)
            if last_px > proj_last_val * (1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100):
                for p in pivots:
                    if p <= j:
                        continue
                    if log_wick[p] - (slope * p + intercept) > gap_thr:
                        obsolete = True
                        break
            if obsolete:
                continue

            touches = 0
            violations = 0
            violations_post = 0   # violaciones DESPUES de anchor2
            touching: list[int] = []
            for p in pivots:
                # Retro-proyeccion: una trendline nace en anchor1, no aplica a
                # pivots previos.  Ej. MSFT 1130->1307: la linea retro-proyectada
                # queda por encima de body_lows de 2008-2020 y generaba 27
                # "violations" ficticias que hundian el score.
                if p < i:
                    continue
                trend_val = slope * p + intercept
                lo = log_wick[p]       # piso: la mecha
                hi = log_body[p]       # techo del rango de contacto: cuerpo
                if trend_val > hi + log_tol:
                    # linea pasa por encima del cuerpo — el close rompio por abajo
                    if p > j:
                        violations_post += 1
                    else:
                        violations += 1
                elif trend_val >= lo - log_tol:
                    # Regla Julian (2026-04-20): toque si la linea esta dentro de
                    # la zona de sombra [wick - tol, body + tol].  La linea puede
                    # estar "desde la base hasta la punta de mecha".
                    touches += 1
                    touching.append(p)
                # else: linea debajo de la mecha -> ni toca ni viola, OK

            if touches < min_touches:
                continue

            # Regla Julian (2026-04-15): si existe un pivot p en (j-WINDOW, j)
            # cuyo wick es MAS BAJO que el de anchor2 AND queda flotando muy
            # arriba de la linea, la linea deberia haber anclado en ese pivot
            # en lugar de en j. Ej. MSFT 1130->1307 ($356) pasa a $308 en 1257
            # ($344 < $356): 1257 es un low deeper, la linea correcta ancla ahi
            # (1130->1257). Sin este filtro gana 1130->1307 por span aunque
            # salte un pivot clave.
            DEEPER_LOW_WINDOW = min(60, max(10, int(span * 0.25)))
            DEEPER_LOW_GAP = log_tol * (2 + span / 80)
            skip_deeper_low = False
            for p in pivots:
                if p >= j or p <= j - DEEPER_LOW_WINDOW or p < i:
                    continue
                if lows[p] < lows[j] and log_wick[p] - (slope * p + intercept) > DEEPER_LOW_GAP:
                    skip_deeper_low = True
                    break
            if skip_deeper_low:
                continue

            # Regla Julian (2026-04-16): si existe un pivot POSTERIOR a anchor2
            # cuyo low es MENOR que el de anchor2, la tesis de "minimos crecientes"
            # se rompio — la linea queda flotando en el aire sin tocar el low real.
            # Ej. MCD: anchor2 2023-10 ($245.73) pero 2024-07 hizo $243.53 (mas
            # bajo). La linea proyecta $260 ahi, flotando 6.6% arriba del pivot.
            # La linea correcta deberia anclar en ese low posterior.
            skip_post_deeper = False
            for p in pivots:
                if p <= j:
                    continue
                if lows[p] < lows[j] * 0.995:
                    skip_post_deeper = True
                    break
            if skip_post_deeper:
                continue

            # Violaciones post-anchor2 son el "break" natural de la linea — no
            # invalidan su validez historica, solo marcan que dejo de servir.
            # Pesan menos (-2) que las que ocurren dentro del rango activo (-10).
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
    lows:       list[float],
    body_lows:  list[float],
    piv_lists:  list[list[int]],
    **kwargs,
) -> Optional[dict]:
    """
    Regla Julian: las lineas deben unir PUNTAS de mechas formando cadenas de
    "minimos cada vez mas altos"; el cuerpo solo "de ser necesario".

    Recibe *varias* listas de pivots (distintos windows) y prueba cada una con
    3 estrategias, quedandose con el best score global:
      1. Regresion sobre higher-low chain (el approach visual de Julian).
      2. Linea exacta entre 2 anchors, strict_wick.
      3. Linea exacta flexible (wick OR body).

    Prioridad absoluta: 3+ toques.  Si no existe ninguna recta valida de 3+,
    se reintenta con min_touches=2 como fallback.  El resultado incluye
    'fallback': True cuando se uso el respaldo de 2 puntos.
    """
    # _fit_trendline_log no acepta apply_obsolete (solo aplica a regresion)
    exact_kwargs = {k: v for k, v in kwargs.items() if k != 'apply_obsolete'}

    best: Optional[dict] = None
    def keep(cand: Optional[dict]) -> None:
        nonlocal best
        if cand is None:
            return
        if best is None or cand['score'] > best['score']:
            best = cand

    # Paso 1+2: competencia entre recta exacta y regresion.  Ambas se evaluan
    # y gana la de mayor score.  Antes era secuencial (exacta primero, regresion
    # solo como fallback), pero en rallies empinados la regresion OLS captura
    # cadenas largas de higher lows que la recta exacta no alcanza.
    for piv in piv_lists:
        if len(piv) < MIN_TOUCHES:
            continue
        keep(_fit_trendline_log(lows, body_lows, piv, strict_wick=True,  **exact_kwargs))
        keep(_fit_trendline_log(lows, body_lows, piv, strict_wick=False, **exact_kwargs))
        keep(_fit_regression_log(lows, body_lows, piv, **kwargs))

    if best is not None:
        best['fallback'] = False
        return best

    # Paso 3: fallback a 2 toques — solo si no hubo ninguna de 3+
    fallback_exact  = {**exact_kwargs, 'min_touches': 2}
    for piv in piv_lists:
        if len(piv) < 2:
            continue
        keep(_fit_trendline_log(lows, body_lows, piv, strict_wick=True,  **fallback_exact))
        keep(_fit_trendline_log(lows, body_lows, piv, strict_wick=False, **fallback_exact))

    if best is not None:
        best['fallback'] = True
    return best


def _rising_chain(pivots: list[int], lows: list[float], start_k: int) -> list[int]:
    """
    Dado un indice `start_k` en la lista ordenada `pivots`, construye greedy
    la cadena de higher lows mas larga que arranca en `pivots[start_k]`:
    agrega el siguiente pivot si su `low` es estrictamente mayor al ultimo
    incluido.
    """
    chain = [pivots[start_k]]
    for p in pivots[start_k + 1:]:
        if lows[p] > lows[chain[-1]]:
            chain.append(p)
    return chain


def _fit_regression_log(
    lows:           list[float],
    body_lows:      list[float],
    pivots:         list[int],
    min_span:       int,
    tol_pct:        float,
    anchor1_range:  Optional[tuple[float, float]] = None,
    anchor2_min:    Optional[float] = None,
    max_proj_ratio: Optional[float] = None,
    n_total:        Optional[int] = None,
    min_touches:    int = MIN_TOUCHES,
    apply_obsolete: bool = True,
    max_span:       Optional[int] = None,
    body_cross_tol: float = 0.006,
) -> Optional[dict]:
    """
    Busca la mejor trendline por regresion lineal sobre cadenas de higher lows.

    Una "cadena" es una subsecuencia de pivots (en orden cronologico) con
    mechas estrictamente crecientes — justo lo que Julian llama "minimos cada
    vez mas altos".  La linea es la que minimiza error cuadratico en log-space
    sobre la cadena.  Todos los miembros de la cadena deben quedar dentro de
    `REGRESSION_TOL_PCT` de la recta (asi descartamos cadenas "torcidas" que
    no son rectas reales).
    """
    if len(pivots) < min_touches:
        return None

    reg_tol  = math.log(1 + REGRESSION_TOL_PCT / 100)
    viol_tol = math.log(1 + tol_pct / 100)
    obs_gap  = math.log(1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100)
    log_wick = [math.log(v) if v > 0 else 0.0 for v in lows]
    log_body = [math.log(v) if v > 0 else 0.0 for v in body_lows]
    N        = n_total if n_total is not None else len(lows)
    last_px  = lows[-1]
    best: Optional[dict] = None

    for start_k in range(len(pivots) - min_touches + 1):
        chain = _rising_chain(pivots, lows, start_k)
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

        # Regresion lineal en log-space sobre la cadena
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
        if slope <= 0:
            continue
        intercept_reg = mean_y - slope * mean_x

        # Todos los miembros de la cadena dentro de REGRESSION_TOL
        chain_ok = True
        for p in chain:
            if abs(log_wick[p] - (slope * p + intercept_reg)) > reg_tol:
                chain_ok = False
                break
        if not chain_ok:
            continue

        # Intercept pasa por la mecha del anchor1.
        intercept = log_wick[i0] - slope * i0

        if any(slope * k + intercept > log_body[k] + body_cross_tol for k in range(i0, len(lows))):
            continue

        # Regla Julian (2026-04-15): si la regresion proyecta demasiado alto
        # respecto al precio actual, la linea no es la que Julian dibuja.
        # Ej. MSFT 4-chain (1130->1235) proyecta $648 vs last=$386 (+68%);
        # Julian marca una linea de pendiente mas suave que termina cerca del
        # precio actual.  `max_proj_ratio=1.5` = rechaza si proyeccion > 150%
        # de last_px.  Cadenas muy empinadas caen; el rally-suave-largo gana.
        if max_proj_ratio is not None:
            proj_last = math.exp(slope * (N - 1) + intercept)
            if proj_last > last_px * max_proj_ratio:
                continue

        # Regla obsolete (solo relevante para long estructural): si hay un pivot
        # posterior a la cadena con low >30% arriba de la proyeccion, la linea
        # quedo desactualizada.  No se aplica a mid/short porque son lineas de
        # rallies cortos donde que el precio se vaya muy arriba es habitual.
        # Excepcion (2026-04-15): solo aplicar si el PRECIO ACTUAL sigue muy
        # arriba de la linea (mismo criterio que en _fit_trendline_log).
        if apply_obsolete:
            proj_last_val = math.exp(slope * (N - 1) + intercept)
            if last_px > proj_last_val * (1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100):
                obsolete = any(
                    log_wick[p] - (slope * p + intercept) > obs_gap
                    for p in pivots if p > i1
                )
                if obsolete:
                    continue

        # Violations: solo pivots en el rango [i0, +∞) Y que NO esten en la
        # cadena (los miembros de la cadena ya pasaron el chain_ok por reg_tol;
        # la regresion puede caer marginalmente por encima del body porque
        # minimiza error cuadratico — no es "ruptura", es el fit medio).
        # Retro-proyectar a pivots viejos (p < i0) tampoco es fallo real: una
        # trendline nace en i0, no aplica a la historia previa.
        chain_set = set(chain)
        violations = 0       # en [i0, i1]
        violations_post = 0  # post-i1
        for p in pivots:
            if p < i0 or p in chain_set:
                continue
            if slope * p + intercept > log_body[p] + viol_tol:
                if p > i1:
                    violations_post += 1
                else:
                    violations += 1

        # Mismo filtro "deeper low missed" que en _fit_trendline_log: si hay
        # un pivot p en (i1-WINDOW, i1) con wick mas bajo que anchor2 y flotando
        # arriba de la regresion, la cadena deberia haber extendido hasta p.
        reg_span = i1 - i0
        DEEPER_LOW_WINDOW = min(60, max(10, int(reg_span * 0.25)))
        DEEPER_LOW_GAP = math.log(1 + PRICE_TOL_PCT / 100) * (2 + reg_span / 80)
        skip_deeper_low = False
        for p in pivots:
            if p >= i1 or p <= i1 - DEEPER_LOW_WINDOW or p < i0:
                continue
            if lows[p] < lows[i1] and log_wick[p] - (slope * p + intercept) > DEEPER_LOW_GAP:
                skip_deeper_low = True
                break
        if skip_deeper_low:
            continue

        # Regla Julian (2026-04-16): pivot posterior con low menor que el ultimo
        # miembro de la cadena invalida la tesis de "minimos crecientes".
        # Ej. MCD: cadena termina en 2023-10 ($245.73), pero 2024-07 hizo
        # $243.53 — la linea flota en el aire sin tocar ese low real.
        skip_post_deeper = False
        for p in pivots:
            if p <= i1:
                continue
            if lows[p] < lows[i1] * 0.995:
                skip_post_deeper = True
                break
        if skip_post_deeper:
            continue

        touches = len(chain)
        span    = i1 - i0
        # Violaciones post-anchor2 son el "break" natural: solo restan -2,
        # las que caen dentro del rango activo siguen pesando -10.
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
    lows:      list[float],
    body_lows: list[float],
    highs:     list[float],
    closes:    list[float],
    n:         int,
    tf:        str,
) -> Optional[dict]:
    """
    Detecta lateralizacion reciente y traza un soporte horizontal + zona.

    Regla Julian (2026-04-14 v2): "tras una subida o caida, el precio se frena
    en una zona".  Miramos una VENTANA de SIDEWAYS_WINDOW_BARS barras recientes
    (no los ultimos K pivots — eso fallaba cuando la caida reciente era aguda
    y los ultimos swing lows eran de tramos muy distintos del rally/crash
    previo).

    Criterios:
      1. range_pct = max(lows)/min(lows) - 1 < SIDEWAYS_MAX_RANGE_PCT
      2. >= SIDEWAYS_MIN_FLOOR_TOUCHES bars con low dentro del SIDEWAYS_FLOOR_TOL_PCT
         del min (multiples toques al piso, no una sola mecha)
      3. slope de log(close) anualizado < SIDEWAYS_MAX_TREND_PCT_YR en valor abs
         (tendencia plana — "por mas que hay leve inclinacion al alza, lateral")

    Devuelve pseudo-trendline con slope=0.  Campo extra `zone_top` marca el
    borde superior de la zona (frontend renderiza como banda, no linea).
    """
    window = min(SIDEWAYS_WINDOW_BARS, n)
    if window < 6:
        return None

    start = n - window
    recent_lows   = lows[start:]
    recent_highs  = highs[start:]
    recent_closes = closes[start:]
    if min(recent_lows) <= 0:
        return None

    # 1) Dispersion baja: stdev/mean de lows.  Resistente a mechas aisladas
    #    que romperian el max/min_low (ej. PLTR tenia una semana $149 arriba
    #    de la zona $126-$141 que, con criterio max/min, desqualificaba la
    #    lateralizacion real).
    mean_low = sum(recent_lows) / len(recent_lows)
    var_low  = sum((v - mean_low) ** 2 for v in recent_lows) / len(recent_lows)
    stdev_low = var_low ** 0.5
    if mean_low <= 0 or stdev_low / mean_low > SIDEWAYS_MAX_REL_STDEV:
        return None

    # 2) Piso = min absoluto de la ventana.  Regla Julian (v3): la linea NUNCA
    #    puede atravesar una vela por el medio.  Con min(lows) ninguna mecha
    #    queda debajo del piso.
    floor = min(recent_lows)

    # 3) Multiples toques al piso (dentro del 5%)
    floor_tol = SIDEWAYS_FLOOR_TOL_PCT / 100
    touches_idxs = [start + k for k, v in enumerate(recent_lows)
                    if v / floor - 1 <= floor_tol]
    if len(touches_idxs) < SIDEWAYS_MIN_FLOOR_TOUCHES:
        return None

    # 4) Piso no sigue cediendo — running_min drop <= SIDEWAYS_MAX_FLOOR_DROP_PCT.
    #    Julian: "el precio se frena y no hace minimos mas bajos".  TSLA hace
    #    LL semana a semana (running_min -17%) — no es lateral.  ORCL hace
    #    bajada dentro de banda pero el piso se mantiene (~-7%) — si es.
    running_min = recent_lows[0]
    for v in recent_lows[1:]:
        if v < running_min:
            running_min = v
    floor_drop_pct = (running_min / recent_lows[0] - 1) * 100
    if floor_drop_pct < SIDEWAYS_MAX_FLOOR_DROP_PCT:
        return None

    # 5) Guard contra breakout alcista — si el precio vuela > N%/yr la ventana
    #    es un lanzamiento, no lateralizacion (aunque stdev de lows parezca
    #    bajo por compression inicial).
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
                if slope_pct_yr > SIDEWAYS_MAX_TREND_PCT_YR:
                    return None

    # Tope = max absoluto de highs en la ventana.  Regla Julian (v3): la linea
    # superior tampoco puede cortar velas — con max(highs) ninguna mecha queda
    # arriba del tope.  La banda envuelve todo el rango visible de la ventana.
    zone_top = max(recent_highs)

    return {
        'slope':         0.0,
        'intercept':     math.log(floor),
        'anchors':       (touches_idxs[0], touches_idxs[-1]),
        'touches':       len(touches_idxs),
        'violations':    0,
        'span':          touches_idxs[-1] - touches_idxs[0],
        'score':         len(touches_idxs) * 4.0,
        'touching_idxs': list(touches_idxs),
        'zone_top':      zone_top,
        'kind':          'horizontal',
    }


def _slope_annual_pct(slope_per_bar: float, tf: str) -> float:
    bars_per_year = {'W': 52, 'D': 252, 'M': 12}.get(tf, 252)
    return (math.exp(slope_per_bar * bars_per_year) - 1) * 100


def _tier_is_invalidated_by_trend(tl: dict, rows: list[dict]) -> bool:
    """
    Regla Julian (2026-04-14): si el precio reciente viene bajando y estamos
    cerca de la trendline (distance_pct < 5%), el "soporte" ya no es soporte
    porque el mercado cambio de direccion y se lo esta comiendo.

    Se evalua la pendiente de log(close) de las ultimas INVALIDATE_RECENT_BARS
    barras por regresion lineal; si es negativa Y la proyeccion actual esta a
    menos de INVALIDATE_MAX_DIST_PCT, se descarta el tier.
    """
    n = len(rows)
    last_close   = float(rows[-1]['close'])
    current_val  = math.exp(tl['slope'] * (n - 1) + tl['intercept'])
    distance_pct = (last_close / current_val - 1) * 100

    # La regla aplica SOLO cuando el precio ya esta DEBAJO de la linea y a
    # menos de INVALIDATE_MAX_DIST_PCT de distancia: ahi el status 'BROKEN' se
    # confirma si la pendiente reciente tambien baja.  Si el precio esta arriba
    # de la linea (incluso testeando desde arriba con slope negativo), la linea
    # todavia no se rompio — mostrarla como soporte valido.
    if distance_pct >= 0 or distance_pct <= -INVALIDATE_MAX_DIST_PCT:
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
    return slope_recent < 0


# ── Dominant-low rescue ─────────────────────────────────────────────────────

DOMINANT_LOW_RATIO = 0.80  # argmin < 2do_min * 0.80 → pivot "dominante"


def _try_dominant_low_rescue(
    lows:          list[float],
    body_lows:     list[float],
    pivots_all:    list[int],
    min_span:      int,
    max_span:      int,
    anchor1_range: tuple[float, float],
    anchor2_min:   float,
    n_total:       int,
    tol_pct:       float,
) -> Optional[dict]:
    """
    Rescate para tickers donde el minimo absoluto es un pivot claramente
    dominante (>=20% por debajo del 2do minimo) — tipico de rallies post-IPO
    o post-bear fuerte (OKLO, APP).  La linea exacta desde ese fondo hasta
    un anchor2 reciente no suele tener 3 pivots colineares porque la suba
    intermedia sale disparada; aceptamos 2 toques cuando el anclaje en ese
    minimo dominante es obvio.
    """
    if len(pivots_all) < 2:
        return None
    pivots_all = sorted(set(pivots_all))
    piv_sorted = sorted(pivots_all, key=lambda p: lows[p])
    imin = piv_sorted[0]
    second_low = lows[piv_sorted[1]]
    if second_low <= 0 or lows[imin] >= second_low * DOMINANT_LOW_RATIO:
        return None

    N = n_total
    f1 = imin / max(N - 1, 1)
    if not (anchor1_range[0] <= f1 <= anchor1_range[1]):
        return None

    log_lo_imin = math.log(lows[imin])
    log_body    = [math.log(v) if v > 0 else 0.0 for v in body_lows]
    log_wick    = [math.log(v) if v > 0 else 0.0 for v in lows]
    log_tol     = math.log(1 + tol_pct / 100)
    obs_gap     = math.log(1 + OBSOLETE_POST_ANCHOR_GAP_PCT / 100)

    best: Optional[dict] = None
    for p2 in pivots_all:
        if p2 <= imin:
            continue
        f2 = p2 / max(N - 1, 1)
        if f2 < anchor2_min:
            continue
        span = p2 - imin
        if span < min_span or span > max_span:
            continue
        slope = (math.log(lows[p2]) - log_lo_imin) / span
        if slope <= 0:
            continue
        intercept = log_lo_imin - slope * imin

        if _line_crosses_any_body(slope, intercept, log_body, imin, p2):
            continue

        obsolete = False
        for p in pivots_all:
            if p <= p2:
                continue
            if log_wick[p] - (slope * p + intercept) > obs_gap:
                obsolete = True
                break
        if obsolete:
            continue

        touches = 0
        violations = 0
        touching: list[int] = []
        for p in pivots_all:
            trend = slope * p + intercept
            lo = log_wick[p]
            hi = log_body[p]
            if trend > hi + log_tol:
                violations += 1
            elif trend >= lo - log_tol:
                touches += 1
                touching.append(p)

        score = touches * 4.0 - violations * 10.0 + span * 0.03
        if best is None or score > best['score']:
            best = dict(
                slope=slope, intercept=intercept,
                anchors=(imin, p2),
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
    Arma el dict de respuesta de una trendline:
      {
        status, anchor1, anchor2, line_points,
        current_value, distance_pct, slope_annual_pct, touches, violations
      }
    """
    n = len(rows)
    slope = tl['slope']
    i0, i1 = tl['anchors']
    lows = [float(r['low']) for r in rows]

    # Intercept pasa por la mecha del anchor1.
    # El fitting ya garantizo que no cruza ningun body_low.
    intercept = math.log(lows[i0]) - slope * i0

    line_points = []
    for x in range(i0, n):
        y = math.exp(slope * x + intercept)
        line_points.append({
            'fecha': rows[x]['fecha'].isoformat(),
            'value': round(y, 4),
        })

    # current_value = proyeccion de la linea en la ULTIMA barra disponible
    # (aunque la linea visible se corte antes); necesario para distance_pct.
    current_value = math.exp(slope * (n - 1) + intercept)
    price = float(rows[-1]['close'])
    distance_pct = (price / current_value - 1) * 100

    if distance_pct > _TESTING_TOL * 100:
        status = 'ACTIVE'
    elif distance_pct < -_TESTING_TOL * 100:
        status = 'BROKEN'
    else:
        status = 'TESTING'

    # Campos opcionales: kind ('horizontal'|'ascending') + zone_top (borde
    # superior de la banda para render como zona).  Los tiers diagonales no
    # setean `kind`; el frontend asume 'ascending' por default.
    out = {
        'status': status,
        'anchor1': {
            'fecha': rows[i0]['fecha'].isoformat(),
            'value': round(lows[i0], 4),
        },
        'anchor2': {
            'fecha': rows[i1]['fecha'].isoformat(),
            'value': round(lows[i1], 4),
        },
        'line_points':      line_points,
        'current_value':    round(current_value, 4),
        'distance_pct':     round(distance_pct, 2),
        'slope_annual_pct': round(_slope_annual_pct(slope, tf), 2),
        'touches':          tl['touches'],
        'violations':       tl['violations'],
        'kind':             tl.get('kind', 'ascending'),
        'fallback':         tl.get('fallback', False),
    }
    touching = tl.get('touching_idxs', [])
    out['touch_points'] = [
        {'fecha': rows[idx]['fecha'].isoformat(), 'value': round(lows[idx], 4)}
        for idx in touching if idx < n
    ]
    if 'zone_top' in tl:
        out['zone_top'] = round(tl['zone_top'], 4)
    return out


# ── Main ─────────────────────────────────────────────────────────────────────

def get_dynamic_supports(symbol: str, fecha: Optional[date] = None,
                         tf: Optional[str] = None) -> dict:
    """
    Devuelve 3 soportes dinamicos (long/mid/short) sobre el historico semanal.
    Fallback a diario si no hay suficientes barras semanales.

    Si se pasa `tf` ('W' o 'D'), fuerza ese timeframe sin fallback.

    Retorna siempre la estructura:
      {
        symbol, timeframe_used, bars_of_data, price,
        long:  tier | None,
        mid:   tier | None,
        short: tier | None,
      }
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

    lows      = [float(r['low']) for r in rows]
    body_lows = [min(float(r['open']), float(r['close'])) for r in rows]
    n = len(rows)
    price = float(rows[-1]['close'])

    # Window adaptativo (igual que el PDF aprobado por Julian)
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

    piv_long  = _pivot_lows(lows, win_long_px)
    piv_mid   = _pivot_lows(lows, win_mid_px)
    piv_short = _pivot_lows(lows, 3)

    # ── long (verde): diagonal del rally post-bear ───────────────────────────
    # Regla Julian: "las tendencias existen, una subida, una lateralizacion,
    # una caida..." — el tier long traza el soporte de la SUBIDA ACTUAL (rally
    # post-bear market), no un soporte estructural de hace 20 anios.  Por eso
    # anchor1_range comienza en 0.30 (no 0.0) y filtramos con distance_pct: si
    # la linea quedo >50% por debajo del precio, es un rally vigente mas fuerte
    # y debemos buscar uno mas reciente.
    # max_span evita que el long cruce bear markets viejos: el rally vigente
    # raramente supera los ~5 anios (260 barras semanales).  Ej. MSFT: sin
    # este limite, la linea 2015-2025 ganaba por span, ignorando el rally
    # 2023-2025 que es el que Julian marca.  Para tickers jovenes (PLTR 290w)
    # permitimos hasta 90% del historico — aun no cruzan un bear market largo.
    bars_per_year_tf = {'W': 52, 'D': 252, 'M': 12}.get(tf, 252)
    long_max_span = min(20 * bars_per_year_tf, int(n * 0.90))
    # piv_combined: union de piv_long + piv_mid. Necesario para capturar
    # lineas exactas donde los 3 touches vienen de listas distintas (ej. MSFT:
    # 2022-10-31 y 2026-03-23 estan en piv_long, pero 2023-01-02 solo en piv_mid).
    piv_combined = sorted(set(piv_long + piv_mid))

    # Regla Julian (2026-04-15): anchor1 del long = "rally start" = el pivot
    # mas antiguo en el rango reciente tal que TODOS los pivots posteriores
    # tienen low >= su low. Es el inicio del rally vigente (el precio nunca
    # rompio por debajo desde entonces). Evita que la linea ancle en fondos
    # de rallies anteriores ya terminados (ej. MSFT 2018-12 $94 -> rally
    # termino en 2022-10, ya no es el inicio del rally actual).
    # Para historias cortas (<400 bars, ~IPOs recientes) el fondo estructural
    # puede estar muy al inicio del historico — bajar el piso a 0.05.
    anchor1_lo_frac = 0.05 if n < long_max_span * 1.2 else 0.10
    anchor1_lo_idx = max(int(anchor1_lo_frac * (n - 1)), n - long_max_span)
    anchor1_hi_idx = int(0.98 * (n - 1))
    long_a2_min = 0.70 if n < 2000 else 0.85
    rally_candidates = []
    for k, p in enumerate(piv_combined):
        if not (anchor1_lo_idx <= p <= anchor1_hi_idx):
            continue
        later_lows = [lows[q] for q in piv_combined[k+1:]]
        if not later_lows or min(later_lows) >= lows[p]:
            rally_candidates.append(p)
    # Primer intento: fit normal, anchor1 libre.
    long_tl = _try_fit(
        lows, body_lows, [piv_long, piv_mid, piv_combined],
        min_span=span_mid, tol_pct=PRICE_TOL_PCT,
        anchor1_range=(anchor1_lo_frac, 0.98),
        anchor2_min=long_a2_min,
        max_span=long_max_span,
        max_proj_ratio=1.5,
        n_total=n, apply_obsolete=True,
    )

    # Segundo intento: forzar anchor1 = rally_start_idx (fondo del rally).
    # Si existe un fit que ancle en el fondo estructural del rally vigente,
    # preferirlo aunque pierda puntos por vp (precio testeando la linea).
    # Aplica un bonus para que compita con fits posteriores que evitan el
    # fondo y por ende marcan una pendiente mas chata.
    for rally_start_idx in rally_candidates:
        piv_long_r     = [p for p in piv_long     if p >= rally_start_idx]
        piv_mid_r      = [p for p in piv_mid      if p >= rally_start_idx]
        piv_combined_r = [p for p in piv_combined if p >= rally_start_idx]
        f1_lock = rally_start_idx / (n - 1) if n > 1 else 0.0
        anchor1_range_lock = (max(0.0, f1_lock - 0.002), min(1.0, f1_lock + 0.002))
        long_tl_locked = _try_fit(
            lows, body_lows, [piv_long_r, piv_mid_r, piv_combined_r],
            min_span=span_mid, tol_pct=PRICE_TOL_PCT,
            anchor1_range=anchor1_range_lock,
            anchor2_min=long_a2_min,
            max_span=long_max_span,
            max_proj_ratio=1.5,
            n_total=n, apply_obsolete=True,
        )
        if long_tl_locked is not None:
            long_tl = long_tl_locked
            break

    # Dominant-low rescue: si el minimo absoluto es un pivot >=20% debajo del
    # 2do minimo (rally post-IPO / post-bear fuerte), forzar esa ancla aunque
    # sea linea de 2 toques.  Solo reemplaza el fit actual si el rescue ancla
    # SIGNIFICATIVAMENTE antes y mas abajo — asi no toca tickers donde el fit
    # ya parte cerca del fondo.
    rescue_long = _try_dominant_low_rescue(
        lows, body_lows, sorted(set(piv_long + piv_mid)),
        min_span=span_mid, max_span=long_max_span,
        anchor1_range=(anchor1_lo_frac, 0.98), anchor2_min=long_a2_min,
        n_total=n, tol_pct=PRICE_TOL_PCT,
    )
    if rescue_long is not None:
        if long_tl is None:
            long_tl = rescue_long
        else:
            cur_i0 = long_tl['anchors'][0]
            r_i0   = rescue_long['anchors'][0]
            if r_i0 < cur_i0 - 20 and lows[r_i0] < lows[cur_i0] * 0.80:
                long_tl = rescue_long

    # ── mid (amarillo): diagonal del rally mas reciente ──────────────────────
    # Regla Julian (2026-04-21): el mid es un soporte ascendente de mediano plazo
    # — conecta lows recientes con pendiente suave.  NO requiere que anchor2 sea
    # el ultimo pivot; puede anclar en lows de hace meses con el precio ya lejos
    # arriba (como el chart de Julian en JNJ: a1=ene-2025, a2=abr-2025, precio
    # 50% arriba).  anchor2_min relajado a 0.90 para capturar estos casos.
    if long_tl is not None:
        long_i1 = long_tl['anchors'][1]
        if long_i1 > n * 0.90:
            mid_a1_lo = max(0.70, 1.0 - 500 / max(n, 1))
        else:
            mid_a1_lo = max(0.75, (long_i1 + (n - 1 - long_i1) * 0.3) / (n - 1))
    else:
        mid_a1_lo = 0.75
    mid_tl = _try_fit(
        lows, body_lows, [piv_mid, piv_short],
        min_span=span_short, tol_pct=PRICE_TOL_PCT,
        anchor1_range=(mid_a1_lo, 0.98),
        anchor2_min=0.90,
        n_total=n, apply_obsolete=False,
    )

    # ── short (cyan): horizontal si el precio lateraliza ─────────────────────
    # Regla Julian: tras subir y corregir, el precio se frena en una zona sin
    # hacer minimos mas bajos — ej. ORCL $135, MSFT $360, PLTR $130.
    # Approach: ventana de SIDEWAYS_WINDOW_BARS (~10 weekly), no pivots — asi
    # captura la consolidacion actual aunque los pivots previos sean del bajon.
    closes = [float(r['close']) for r in rows]
    highs  = [float(r['high'])  for r in rows]
    short_tl = _detect_sideways_horizontal(lows, body_lows, highs, closes, n, tf)

    # ── Invalidaciones ───────────────────────────────────────────────────────
    # - Tier long: si distance_pct > LONG_MAX_ABOVE_PROJECTION_PCT, la linea
    #   "quedo atras" — el rally la dejo obsoleta (ej. GOOGL 2008-2025 con
    #   precio 82% arriba).
    if long_tl is not None:
        cur = math.exp(long_tl['slope'] * (n - 1) + long_tl['intercept'])
        dist_pct = (price / cur - 1) * 100
        if dist_pct > LONG_MAX_ABOVE_PROJECTION_PCT:
            long_tl = None

    # - Diagonales: invalidar si el precio cambio de direccion cerca del soporte
    #   (Regla Phase 1 v2, aplicada cuando |distance| < 5%).  NO se aplica al
    #   tier short (horizontal): por definicion el horizontal es "precio se
    #   frena en la zona"; si testea el piso con slope negativo queremos
    #   justamente SHOWRLO para que el usuario vea "cuidado con este piso".
    # Regla Julian (2026-04-15): el tier long es estructural — si el precio lo
    # esta testeando desde arriba con slope reciente negativo, es justamente
    # lo que queremos mostrar ('red zone').  Dejar que _build_tier decida
    # ACTIVE / TESTING / BROKEN y que el usuario vea la linea.  Mid sigue
    # invalidandose porque es una diagonal tactica de corto plazo.
    # Regla Julian (2026-04-21): NO invalidar mid por tendencia reciente.
    # El usuario quiere ver la trendline de soporte incluso cuando el precio
    # la esta testeando / rompiendo — igual que el long.

    # Regla Julian (2026-04-15): una sola diagonal ascendente dominante.
    # Si mid comparte anchor1 con long (dentro de 8 bars por distinto pivot
    # window), es la misma "familia" de lineas — dropear mid para evitar
    # redundancia visual. Mid solo vale la pena si es un sub-rally reciente
    # con anchor1 CLARAMENTE posterior al del long (ej. GOOGL 2025-04 sobre
    # el rally long 2022-2025 — anchors distintos).
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
    res = get_dynamic_supports(sym)
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
    }, indent=2))
