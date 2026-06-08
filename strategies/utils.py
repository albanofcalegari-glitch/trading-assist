"""
utils.py — funciones matemáticas puras para indicadores técnicos
Sin dependencias de DB. Todo sobre listas de floats ordenadas ASC.
"""
import math
import statistics
from typing import Optional


def sma(prices: list[float], n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    return statistics.mean(prices[-n:])


def ema(prices: list[float], n: int) -> Optional[float]:
    """EMA estándar con factor k = 2/(n+1)."""
    if len(prices) < n:
        return None
    k = 2.0 / (n + 1)
    val = statistics.mean(prices[:n])
    for p in prices[n:]:
        val = p * k + val * (1 - k)
    return val


def rsi(prices: list[float], n: int = 14) -> Optional[float]:
    """Wilder's RSI. Necesita al menos n+1 precios."""
    if len(prices) < n + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_g = statistics.mean(gains[:n])
    avg_l = statistics.mean(losses[:n])
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n

    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def momentum_pct(prices: list[float], lookback: int) -> Optional[float]:
    """Retorno % de hace `lookback` días hasta hoy."""
    if len(prices) <= lookback:
        return None
    base = prices[-1 - lookback]
    if base == 0:
        return None
    return round((prices[-1] / base - 1) * 100, 4)


def vol_ratio(volumes: list[float], short: int = 5, long: int = 20) -> Optional[float]:
    """Ratio volumen promedio short / long. < 1 = corrección con volumen bajo."""
    if len(volumes) < long:
        return None
    avg_s = statistics.mean(volumes[-short:])
    avg_l = statistics.mean(volumes[-long:])
    if avg_l == 0:
        return None
    return round(avg_s / avg_l, 3)


def vs_peak(prices: list[float], lookback: int = 60) -> Optional[float]:
    """Distancia % desde el máximo de los últimos `lookback` días. Siempre <= 0."""
    window = prices[-lookback:] if len(prices) >= lookback else prices
    if not window:
        return None
    peak = max(window)
    if peak == 0:
        return None
    return round((prices[-1] / peak - 1) * 100, 4)


def touch_quality(
    rows: list[dict],
    touch_idx: int,
    zone_center: float,
    role: str,
    bounce_pct: float = 0.0,
    vol_lookback: int = 20,
) -> dict:
    """Calidad de un toque individual a un S/R (0-1).

    Sub-métricas:
      vol_score      (0.35) — volumen del bar vs promedio reciente
      body_score     (0.25) — tamaño de vela vs promedio ("paridad de vela")
      rejection_score(0.25) — cuánto rechazó el precio (close vs wick)
      bounce_score   (0.15) — rebote posterior (recibido del caller)
    """
    n = len(rows)
    start = max(0, touch_idx - vol_lookback)
    window = rows[start:touch_idx] if touch_idx > 0 else []

    r = rows[touch_idx]
    o, h, l, c = float(r['open']), float(r['high']), float(r['low']), float(r['close'])
    vol = float(r.get('volume', 0))

    # ── vol_score ──
    vols = [float(w.get('volume', 0)) for w in window]
    avg_vol = statistics.mean(vols) if vols else 0
    raw_vol_ratio = vol / avg_vol if avg_vol > 0 else 0
    vol_s = min(1.0, raw_vol_ratio / 3.0)

    # ── body_score ("paridad de vela") ──
    body = abs(c - o)
    bodies = [abs(float(w['close']) - float(w['open'])) for w in window]
    avg_body = statistics.mean(bodies) if bodies else 0
    raw_body_ratio = body / avg_body if avg_body > 0 else 0
    body_s = min(1.0, raw_body_ratio / 3.0)

    # ── rejection_score ──
    if role == 'support':
        wick_into = zone_center - l if l < zone_center else 0
        rejection = (c - l) / (zone_center - l) if (zone_center - l) > 0 else 0
    else:
        wick_into = h - zone_center if h > zone_center else 0
        rejection = (h - c) / (h - zone_center) if (h - zone_center) > 0 else 0
    rej_s = max(0.0, min(1.0, rejection))

    # ── bounce_score ──
    bounce_s = min(1.0, bounce_pct / 5.0) if bounce_pct > 0 else 0.0

    # ── guard: datos insuficientes → neutro ──
    if not window or avg_vol == 0:
        return {
            'quality': 0.5, 'vol_ratio': 0.0,
            'body_ratio': 0.0, 'rejection': round(rej_s, 3),
        }

    quality = vol_s * 0.35 + body_s * 0.25 + rej_s * 0.25 + bounce_s * 0.15
    return {
        'quality': round(quality, 3),
        'vol_ratio': round(raw_vol_ratio, 2),
        'body_ratio': round(raw_body_ratio, 2),
        'rejection': round(rej_s, 3),
    }


def higher_low(prices: list[float], lookback: int = 5) -> bool:
    """True si el precio actual está por encima del mínimo de los últimos `lookback` días."""
    if len(prices) < lookback + 1:
        return False
    recent_min = min(prices[-lookback - 1:-1])
    return prices[-1] > recent_min * 1.015   # al menos 1.5% por encima del mínimo
