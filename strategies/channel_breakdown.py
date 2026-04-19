"""
channel_breakdown.py — Estrategia de ruptura de canal (Julian, 2026-04-16)

Caso: un activo rompe el soporte de un canal (ej. DUOL rompiendo canal ascendente).
Una vez que el precio cae por debajo del canal, se analiza el comportamiento
posterior en las zonas de soporte horizontales debajo del canal roto.

3 escenarios post-ruptura:

  SCENARIO_1 — BOUNCE_RETEST:
    Precio cae a una zona de soporte, rebota, retestea la zona desde arriba.
    Entrada en el retest, SL = piso de la zona (~6%).

  SCENARIO_2 — NEW_FLOOR:
    Precio forma un piso nuevo (lateraliza), retrocede dentro de ese rango
    y vuelve a rebotar.  Entrada en el rebote, SL = piso del rango (~6%).

  SCENARIO_3 — BREAKDOWN:
    Precio rompe la zona de soporte decisivamente. VENDER / no entrar.

Uso:
    from strategies.channel_breakdown import analyze_channel_breakdown
    result = analyze_channel_breakdown('DUOL')
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.channel_detection import detect_channels_multi


# ── Constantes ──────────────────────────────────────────────────────────────

LOOKBACK_BARS       = 60      # barras semanales para buscar zonas post-ruptura
ZONE_CLUSTER_TOL    = 0.04    # 4% tolerancia para agrupar lows en zona
ZONE_MIN_TOUCHES    = 2       # minimo toques al piso para formar zona
ZONE_FLOOR_TOL_PCT  = 5.0     # low dentro del 5% del piso = "toca"
BOUNCE_MIN_PCT      = 4.0     # rebote minimo para considerar bounce valido
RETEST_TOL_PCT      = 3.0     # precio dentro del 3% de zone_high = retest
BREAKDOWN_PCT       = 4.0     # close >4% debajo de zone_low = breakdown
SL_BUFFER_PCT       = 1.0     # SL = zone_low - 1% de margen
SIDEWAYS_MAX_STDEV  = 0.06    # stdev/mean < 6% = lateralizacion
SIDEWAYS_MIN_BARS   = 5       # minimo barras para considerar piso formado
MAX_SL_PCT          = 8.0     # maximo SL permitido (si >8% no es setup limpio)


# ── Carga de datos ──────────────────────────────────────────────────────────

def _load_weekly(symbol: str, fecha_max: date) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = 'W' AND fecha <= %s
                   ORDER BY fecha ASC""",
                (symbol, fecha_max),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _load_daily(symbol: str, fecha_max: date, limit: int = 300) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM price_history
                   WHERE simbolo = %s AND fecha <= %s
                   ORDER BY fecha DESC LIMIT %s""",
                (symbol, fecha_max, limit),
            )
            rows = cur.fetchall()
        rows.reverse()
        return rows
    finally:
        conn.close()


# ── Deteccion de ruptura de canal ───────────────────────────────────────────

def _find_broken_channel(symbol: str, fecha: date) -> Optional[dict]:
    """
    Busca un canal cuyo soporte fue roto (position < 0 = BELOW_SUPPORT).
    Prioriza el horizonte mas largo (long > medium > short).
    """
    channels = detect_channels_multi(symbol, fecha)
    if not channels:
        return None

    for ch in channels:
        if ch.get('position', 1) < 0:
            return ch

    return None


# ── Deteccion de zonas de soporte post-ruptura ──────────────────────────────

def _find_support_zones_post_break(
    rows: list[dict],
    channel_lower_now: float,
) -> list[dict]:
    """
    Busca zonas de soporte DEBAJO del canal roto, formadas por clusters
    de lows en las barras recientes.
    """
    n = len(rows)
    if n < 10:
        return []

    lows   = [float(r['low'])   for r in rows]
    highs  = [float(r['high'])  for r in rows]
    closes = [float(r['close']) for r in rows]

    start = max(0, n - LOOKBACK_BARS)
    recent_lows = []
    for i in range(start, n):
        if lows[i] < channel_lower_now:
            recent_lows.append((i, lows[i]))

    if len(recent_lows) < 2:
        return []

    sorted_by_price = sorted(recent_lows, key=lambda x: x[1])
    clusters: list[list[tuple[int, float]]] = []
    for item in sorted_by_price:
        placed = False
        for cluster in clusters:
            center = sum(p for _, p in cluster) / len(cluster)
            if abs(item[1] / center - 1) <= ZONE_CLUSTER_TOL:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    zones = []
    for cluster in clusters:
        if len(cluster) < ZONE_MIN_TOUCHES:
            continue
        floor = min(p for _, p in cluster)
        ceil  = max(p for _, p in cluster)
        zone_low  = floor * (1 - ZONE_FLOOR_TOL_PCT / 200)
        zone_high = ceil  * (1 + ZONE_FLOOR_TOL_PCT / 200)

        touch_idxs = [i for i, p in cluster]
        first_touch = min(touch_idxs)
        last_touch  = max(touch_idxs)

        max_bounce = 0
        for idx, _ in cluster:
            future_highs = highs[idx + 1: min(idx + 16, n)]
            if future_highs:
                bounce = (max(future_highs) / floor - 1) * 100
                max_bounce = max(max_bounce, bounce)

        zones.append({
            'zone_low':      round(zone_low, 2),
            'zone_high':     round(zone_high, 2),
            'floor':         round(floor, 2),
            'ceiling':       round(ceil, 2),
            'touches':       len(cluster),
            'first_touch':   rows[first_touch]['fecha'].isoformat(),
            'last_touch':    rows[last_touch]['fecha'].isoformat(),
            'max_bounce_pct': round(max_bounce, 2),
        })

    zones.sort(key=lambda z: z['floor'], reverse=True)
    return zones


# ── Clasificacion de escenario ──────────────────────────────────────────────

def _classify_scenario(
    rows:  list[dict],
    zone:  dict,
) -> dict:
    """
    Clasifica el estado actual respecto a una zona de soporte post-ruptura.

    Retorna scenario + detalles de entrada/SL.
    """
    n = len(rows)
    price  = float(rows[-1]['close'])
    lows   = [float(r['low'])   for r in rows]
    highs  = [float(r['high'])  for r in rows]
    closes = [float(r['close']) for r in rows]

    zone_low  = zone['zone_low']
    zone_high = zone['zone_high']
    floor     = zone['floor']

    # SL = piso de la zona - buffer
    sl_price = floor * (1 - SL_BUFFER_PCT / 100)
    sl_pct   = (price / sl_price - 1) * 100 if sl_price > 0 else 0

    # ── SCENARIO 3: BREAKDOWN ───────────────────────────────────────────────
    # Precio cierra decisivamente debajo de la zona
    if price < zone_low * (1 - BREAKDOWN_PCT / 100):
        return {
            'scenario': 'BREAKDOWN',
            'scenario_num': 3,
            'signal': 'SELL',
            'description': (
                f'Precio rompió zona de soporte ${zone_low:.2f}-${zone_high:.2f} '
                f'decisivamente. VENDER / no entrar.'
            ),
            'entry': None,
            'sl': None,
            'sl_pct': None,
            'zone': zone,
        }

    # Detectar lateralizacion reciente (NEW_FLOOR)
    window = min(LOOKBACK_BARS, n)
    start = n - window
    window_lows = lows[start:]
    if len(window_lows) >= SIDEWAYS_MIN_BARS:
        mean_low = sum(window_lows) / len(window_lows)
        var_low  = sum((v - mean_low) ** 2 for v in window_lows) / len(window_lows)
        stdev_low = var_low ** 0.5
        is_sideways = mean_low > 0 and stdev_low / mean_low < SIDEWAYS_MAX_STDEV
    else:
        is_sideways = False

    # ¿Precio esta en/cerca de la zona? (retest o holding)
    in_zone = zone_low <= price <= zone_high * 1.02
    near_zone = abs(price / zone_high - 1) <= RETEST_TOL_PCT / 100

    # ¿Hubo bounce previo desde esta zona?
    had_bounce = zone['max_bounce_pct'] >= BOUNCE_MIN_PCT

    # ── SCENARIO 2: NEW_FLOOR ──────────────────────────────────────────────
    if is_sideways and (in_zone or near_zone) and zone['touches'] >= 2:
        entry_price = zone_high
        return {
            'scenario': 'NEW_FLOOR',
            'scenario_num': 2,
            'signal': 'BUY' if in_zone else 'WAIT',
            'description': (
                f'Precio formó piso nuevo en zona ${zone_low:.2f}-${zone_high:.2f} '
                f'({zone["touches"]} toques). Retrocede y rebota dentro del rango. '
                f'SL en ${sl_price:.2f} ({sl_pct:.1f}%).'
            ),
            'entry': round(entry_price, 2),
            'sl': round(sl_price, 2),
            'sl_pct': round(sl_pct, 1),
            'zone': zone,
        }

    # ── SCENARIO 1: BOUNCE_RETEST ──────────────────────────────────────────
    if had_bounce and (in_zone or near_zone):
        entry_price = zone_high
        return {
            'scenario': 'BOUNCE_RETEST',
            'scenario_num': 1,
            'signal': 'BUY' if in_zone else 'WAIT',
            'description': (
                f'Precio rebotó desde ${floor:.2f} (rebote {zone["max_bounce_pct"]:.1f}%) '
                f'y retestea zona ${zone_low:.2f}-${zone_high:.2f}. '
                f'Entrada en retest, SL en ${sl_price:.2f} ({sl_pct:.1f}%).'
            ),
            'entry': round(entry_price, 2),
            'sl': round(sl_price, 2),
            'sl_pct': round(sl_pct, 1),
            'zone': zone,
        }

    # ── Precio sobre la zona, esperando retest ─────────────────────────────
    if price > zone_high:
        return {
            'scenario': 'ABOVE_ZONE',
            'scenario_num': 0,
            'signal': 'WAIT',
            'description': (
                f'Precio sobre zona ${zone_low:.2f}-${zone_high:.2f}. '
                f'Esperar retest para posible entrada.'
            ),
            'entry': round(zone_high, 2),
            'sl': round(sl_price, 2),
            'sl_pct': round(sl_pct, 1),
            'zone': zone,
        }

    # ── Precio debajo de la zona pero sin breakdown claro ──────────────────
    return {
        'scenario': 'BELOW_ZONE',
        'scenario_num': 0,
        'signal': 'WAIT',
        'description': (
            f'Precio debajo de zona ${zone_low:.2f}-${zone_high:.2f} '
            f'pero sin ruptura decisiva. Monitorear.'
        ),
        'entry': None,
        'sl': round(sl_price, 2),
        'sl_pct': round(sl_pct, 1),
        'zone': zone,
    }


# ── Funcion principal ──────────────────────────────────────────────────────

def analyze_channel_breakdown(
    symbol: str,
    fecha: Optional[date] = None,
) -> dict:
    """
    Analiza si un activo presenta setup de channel breakdown (Julian).

    Retorna:
      {
        symbol, fecha, has_breakdown, channel, scenario,
        zones, best_scenario, reading
      }
    """
    fecha = fecha or date.today()

    # 1. Buscar canal roto
    channel = _find_broken_channel(symbol, fecha)

    if channel is None:
        channels = detect_channels_multi(symbol, fecha)
        near_support = None
        for ch in channels:
            pos = ch.get('position', 0.5)
            if 0 <= pos <= 0.15:
                near_support = ch
                break

        return {
            'symbol':         symbol,
            'fecha':          str(fecha),
            'has_breakdown':  False,
            'channel':        near_support,
            'near_support':   near_support is not None,
            'zones':          [],
            'best_scenario':  None,
            'reading':        (
                f'{symbol}: sin ruptura de canal detectada.'
                + (f' Precio cerca del soporte del canal ({near_support["decision"]}).'
                   if near_support else '')
            ),
        }

    # 2. Cargar data (weekly preferido, fallback a daily)
    rows = _load_weekly(symbol, fecha)
    if not rows or len(rows) < 20:
        rows = _load_daily(symbol, fecha, limit=500)
    if not rows or len(rows) < 20:
        return {
            'symbol':        symbol,
            'fecha':         str(fecha),
            'has_breakdown': True,
            'channel':       channel,
            'zones':         [],
            'best_scenario': None,
            'reading':       f'{symbol}: canal roto pero datos insuficientes para analizar zonas.',
        }

    # 3. Detectar zonas de soporte post-ruptura
    channel_lower = channel['lower_now']
    zones = _find_support_zones_post_break(rows, channel_lower)

    if not zones:
        price = float(rows[-1]['close'])
        return {
            'symbol':        symbol,
            'fecha':         str(fecha),
            'has_breakdown': True,
            'channel':       channel,
            'price':         round(price, 2),
            'zones':         [],
            'best_scenario': {
                'scenario': 'BREAKDOWN',
                'scenario_num': 3,
                'signal': 'SELL',
                'description': (
                    f'{symbol} rompió canal {channel["channel_type"].lower()} '
                    f'(soporte ${channel_lower:.2f}) sin zona de soporte clara debajo. '
                    f'VENDER / no entrar.'
                ),
                'entry': None,
                'sl': None,
                'sl_pct': None,
                'zone': None,
            },
            'reading': (
                f'{symbol}: ruptura de canal {channel["channel_type"].lower()} '
                f'sin soporte visible. Señal de venta.'
            ),
        }

    # 4. Clasificar escenario para cada zona, elegir la mejor
    scenarios = []
    for z in zones:
        sc = _classify_scenario(rows, z)
        if sc['sl_pct'] is not None and sc['sl_pct'] > MAX_SL_PCT:
            sc['signal'] = 'SKIP'
            sc['description'] += f' SL demasiado amplio (>{MAX_SL_PCT}%).'
        scenarios.append(sc)

    # Prioridad: BUY > WAIT > SELL > SKIP
    signal_priority = {'BUY': 4, 'WAIT': 3, 'SELL': 2, 'SKIP': 1}
    best = max(scenarios, key=lambda s: (
        signal_priority.get(s['signal'], 0),
        -(s.get('sl_pct') or 99),
    ))

    price = float(rows[-1]['close'])

    # Generar reading
    if best['scenario'] == 'BOUNCE_RETEST':
        reading = (
            f'{symbol}: ruptura de canal {channel["channel_type"].lower()}. '
            f'Escenario 1 — rebote + retest en zona ${best["zone"]["floor"]:.2f}. '
            f'{"Entrada activa" if best["signal"] == "BUY" else "Esperar retest"}. '
            f'SL ${best["sl"]:.2f} ({best["sl_pct"]:.1f}%).'
        )
    elif best['scenario'] == 'NEW_FLOOR':
        reading = (
            f'{symbol}: ruptura de canal {channel["channel_type"].lower()}. '
            f'Escenario 2 — piso nuevo formado en ${best["zone"]["floor"]:.2f}. '
            f'{"Entrada activa" if best["signal"] == "BUY" else "Esperar confirmación"}. '
            f'SL ${best["sl"]:.2f} ({best["sl_pct"]:.1f}%).'
        )
    elif best['scenario'] == 'BREAKDOWN':
        reading = (
            f'{symbol}: ruptura de canal {channel["channel_type"].lower()}. '
            f'Escenario 3 — VENDER. Soporte roto sin recuperación.'
        )
    else:
        reading = (
            f'{symbol}: ruptura de canal {channel["channel_type"].lower()}. '
            f'Monitorear zonas de soporte. Precio ${price:.2f}.'
        )

    return {
        'symbol':        symbol,
        'fecha':         str(fecha),
        'has_breakdown': True,
        'channel':       channel,
        'price':         round(price, 2),
        'channel_lower': round(channel_lower, 2),
        'zones':         zones,
        'scenarios':     scenarios,
        'best_scenario': best,
        'reading':       reading,
    }


# ── Batch: correr sobre lista de simbolos ───────────────────────────────────

def scan_breakdowns(
    symbols: list[str],
    fecha: Optional[date] = None,
) -> list[dict]:
    """Escanea una lista de simbolos buscando channel breakdowns activos."""
    fecha = fecha or date.today()
    results = []
    for sym in symbols:
        try:
            r = analyze_channel_breakdown(sym, fecha)
            if r['has_breakdown']:
                results.append(r)
        except Exception as e:
            print(f'  [ERROR] {sym}: {e}')
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import json
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ['DUOL']
    for sym in symbols:
        print(f'\n{"="*60}')
        print(f'  {sym}')
        print(f'{"="*60}')
        r = analyze_channel_breakdown(sym)
        print(f'  Breakdown: {r["has_breakdown"]}')
        if r.get('channel'):
            ch = r['channel']
            print(f'  Canal: {ch["channel_type"]} | Lower: ${ch["lower_now"]} | Upper: ${ch["upper_now"]}')
            print(f'  Position: {ch.get("position", "?")}')
        if r.get('zones'):
            print(f'  Zonas de soporte ({len(r["zones"])}):')
            for z in r['zones']:
                print(f'    ${z["floor"]:.2f} - ${z["ceiling"]:.2f} ({z["touches"]} toques, rebote {z["max_bounce_pct"]:.1f}%)')
        if r.get('best_scenario'):
            sc = r['best_scenario']
            print(f'  >>> Escenario: {sc["scenario"]} ({sc["signal"]})')
            print(f'      {sc["description"]}')
        print(f'  Reading: {r["reading"]}')
