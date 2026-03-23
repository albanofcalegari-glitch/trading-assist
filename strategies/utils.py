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


def higher_low(prices: list[float], lookback: int = 5) -> bool:
    """True si el precio actual está por encima del mínimo de los últimos `lookback` días."""
    if len(prices) < lookback + 1:
        return False
    recent_min = min(prices[-lookback - 1:-1])
    return prices[-1] > recent_min * 1.015   # al menos 1.5% por encima del mínimo
