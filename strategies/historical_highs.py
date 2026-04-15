"""
strategies.historical_highs — deteccion de maximos historicos (52 semanas / 2 anos).

Detecta cuando un activo se acerca o supera su maximo de 52 semanas o su maximo
absoluto dentro del historial disponible.

Umbral configurable: 20 % de distancia al maximo.

Estados:
    NO_SIGNAL        — precio > 20 % por debajo del maximo 52w
    NEAR_52W_HIGH    — precio dentro del 20 % del maximo 52w
    AT_52W_HIGH      — precio dentro del 5 % del maximo 52w
    NEW_52W_HIGH     — precio rompio por encima del maximo 52w anterior
"""
from __future__ import annotations

import sys
import os
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.utils import rsi, momentum_pct, sma

# ── Umbrales ──────────────────────────────────────────────────────────────────

_NEAR_PCT   = 20.0   # % para considerar "cercano" al maximo 52w
_AT_PCT     = 5.0    # % para considerar "en" el maximo 52w
_52W_BARS   = 252    # dias habiles en 52 semanas


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_ohlcv(symbol: str, fecha: date, n: int = 600) -> list[dict]:
    """Carga OHLCV diario desde price_history, ordenado ASC."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM price_history
                   WHERE simbolo = %s AND fecha <= %s
                   ORDER BY fecha DESC LIMIT %s""",
                (symbol, fecha, n),
            )
            rows = list(cur.fetchall())
        rows.reverse()
        return rows
    finally:
        conn.close()


# ── Analisis ──────────────────────────────────────────────────────────────────

def analyze_symbol(symbol: str, fecha: Optional[date] = None) -> Optional[dict]:
    """Analiza proximidad a maximos historicos para un simbolo.

    Retorna None si no hay suficiente historia (< 100 dias).
    """
    fecha = fecha or date.today()
    rows = _load_ohlcv(symbol, fecha, n=600)

    if len(rows) < 100:
        return None

    closes = [float(r['close']) for r in rows]
    highs  = [float(r['high']) for r in rows]
    price  = closes[-1]

    # ── Maximo 52 semanas (sobre los highs intradiarios) ─────────────────────
    window_52w = highs[-_52W_BARS:] if len(highs) >= _52W_BARS else highs
    high_52w = max(window_52w)

    # Fecha del maximo 52w
    offset = len(highs) - len(window_52w)
    high_52w_idx = offset + window_52w.index(high_52w)
    high_52w_date = rows[high_52w_idx]['fecha']
    high_52w_days_ago = len(rows) - 1 - high_52w_idx

    # ── Maximo absoluto (todo el historial) ──────────────────────────────────
    high_all = max(highs)
    high_all_idx = highs.index(high_all)
    high_all_date = rows[high_all_idx]['fecha']

    # ── Distancias (negativas = por debajo del maximo) ───────────────────────
    dist_52w = ((price / high_52w) - 1) * 100 if high_52w > 0 else None
    dist_all = ((price / high_all) - 1) * 100 if high_all > 0 else None

    # ── Clasificacion ────────────────────────────────────────────────────────
    is_new_high = (price >= high_52w * 0.999)  # precio = maximo o por encima

    if is_new_high:
        state = 'NEW_52W_HIGH'
    elif dist_52w is not None and abs(dist_52w) <= _AT_PCT:
        state = 'AT_52W_HIGH'
    elif dist_52w is not None and abs(dist_52w) <= _NEAR_PCT:
        state = 'NEAR_52W_HIGH'
    else:
        state = 'NO_SIGNAL'

    # ── Decision ─────────────────────────────────────────────────────────────
    if state in ('NEW_52W_HIGH', 'AT_52W_HIGH'):
        decision = 'ALERT'
        confidence = 'HIGH'
    elif state == 'NEAR_52W_HIGH':
        decision = 'WATCHLIST'
        confidence = 'MEDIUM'
    else:
        decision = 'NO_ACTION'
        confidence = 'LOW'

    # ── Indicadores de contexto ──────────────────────────────────────────────
    rsi_val  = rsi(closes, 14)
    mom20    = momentum_pct(closes, 20)
    sma200   = sma(closes, 200)

    # ── Es tambien maximo absoluto? ──────────────────────────────────────────
    is_all_time_high = (price >= high_all * 0.999)

    # ── Reading ──────────────────────────────────────────────────────────────
    if state == 'NEW_52W_HIGH':
        reading = f"{symbol} rompio su maximo de 52 semanas (${high_52w:.2f}). Precio actual ${price:.2f}."
    elif state == 'AT_52W_HIGH':
        reading = f"{symbol} a {abs(dist_52w):.1f}% de su maximo 52w (${high_52w:.2f}). Precio ${price:.2f}."
    elif state == 'NEAR_52W_HIGH':
        reading = f"{symbol} cerca de maximo 52w: {abs(dist_52w):.1f}% debajo de ${high_52w:.2f}."
    else:
        reading = f"{symbol} a {abs(dist_52w):.1f}% de su maximo 52w." if dist_52w else f"{symbol} sin senial."

    if is_all_time_high:
        reading += " MAXIMO HISTORICO ABSOLUTO."

    return {
        'fecha':              fecha,
        'simbolo':            symbol,
        'price':              round(price, 4),
        'high_52w':           round(high_52w, 4),
        'high_52w_date':      high_52w_date,
        'high_52w_days_ago':  high_52w_days_ago,
        'distance_52w_pct':   round(dist_52w, 3) if dist_52w is not None else None,
        'high_all':           round(high_all, 4),
        'high_all_date':      high_all_date,
        'distance_all_pct':   round(dist_all, 3) if dist_all is not None else None,
        'is_all_time_high':   is_all_time_high,
        'setup_state':        state,
        'decision':           decision,
        'confidence_level':   confidence,
        'reading':            reading,
        'rsi14':              rsi_val,
        'mom20':              mom20,
        'sma200':             round(sma200, 4) if sma200 else None,
    }


def run_universe(symbols: list[str], fecha: Optional[date] = None) -> list[dict]:
    """Corre el analisis para todos los simbolos. Retorna todos (con y sin senial)."""
    fecha = fecha or date.today()
    results = []
    for sym in symbols:
        r = analyze_symbol(sym, fecha)
        if r:
            results.append(r)
    return results


# ── Persistencia ──────────────────────────────────────────────────────────────

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS historical_high_signals (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    fecha               DATE           NOT NULL,
    simbolo             VARCHAR(20)    NOT NULL,
    price               DECIMAL(14,4),
    high_52w            DECIMAL(14,4),
    high_52w_date       DATE,
    high_52w_days_ago   INT,
    distance_52w_pct    DECIMAL(8,3),
    high_all            DECIMAL(14,4),
    high_all_date       DATE,
    distance_all_pct    DECIMAL(8,3),
    is_all_time_high    TINYINT(1)     DEFAULT 0,
    setup_state         VARCHAR(20),
    decision            VARCHAR(20),
    confidence_level    VARCHAR(10),
    reading             VARCHAR(500),
    rsi14               DECIMAL(6,2),
    mom20               DECIMAL(8,4),
    sma200              DECIMAL(14,4),
    created_at          TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_hh_fecha_sym (fecha, simbolo),
    INDEX idx_state (setup_state),
    INDEX idx_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_UPSERT_SQL = """
INSERT INTO historical_high_signals
    (fecha, simbolo, price, high_52w, high_52w_date, high_52w_days_ago,
     distance_52w_pct, high_all, high_all_date, distance_all_pct,
     is_all_time_high, setup_state, decision, confidence_level,
     reading, rsi14, mom20, sma200)
VALUES
    (%(fecha)s, %(simbolo)s, %(price)s, %(high_52w)s, %(high_52w_date)s,
     %(high_52w_days_ago)s, %(distance_52w_pct)s, %(high_all)s, %(high_all_date)s,
     %(distance_all_pct)s, %(is_all_time_high)s, %(setup_state)s, %(decision)s,
     %(confidence_level)s, %(reading)s, %(rsi14)s, %(mom20)s, %(sma200)s)
ON DUPLICATE KEY UPDATE
    price            = VALUES(price),
    high_52w         = VALUES(high_52w),
    high_52w_date    = VALUES(high_52w_date),
    high_52w_days_ago = VALUES(high_52w_days_ago),
    distance_52w_pct = VALUES(distance_52w_pct),
    high_all         = VALUES(high_all),
    high_all_date    = VALUES(high_all_date),
    distance_all_pct = VALUES(distance_all_pct),
    is_all_time_high = VALUES(is_all_time_high),
    setup_state      = VALUES(setup_state),
    decision         = VALUES(decision),
    confidence_level = VALUES(confidence_level),
    reading          = VALUES(reading),
    rsi14            = VALUES(rsi14),
    mom20            = VALUES(mom20),
    sma200           = VALUES(sma200)
"""


def ensure_table() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_ENSURE_TABLE_SQL)
    finally:
        conn.close()


def save_signals(results: list[dict]) -> int:
    """Persiste resultados en historical_high_signals (upsert)."""
    if not results:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for r in results:
                cur.execute(_UPSERT_SQL, r)
        conn.commit()
        return len(results)
    finally:
        conn.close()
