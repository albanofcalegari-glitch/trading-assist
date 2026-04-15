"""
strategies.historical_lows — detección de mínimos históricos (52 semanas / 2 años).

Detecta cuando un activo se acerca o rompe su mínimo de 52 semanas o su mínimo
absoluto dentro del historial disponible (~2 años).

Estados:
    NO_SIGNAL        — precio > 5 % por encima del mínimo 52w
    NEAR_52W_LOW     — precio dentro del 5 % del mínimo 52w
    AT_52W_LOW       — precio dentro del 1.5 % del mínimo 52w (tocando)
    NEW_52W_LOW      — precio rompió por debajo del mínimo 52w anterior

Decisiones:
    ALERT            — AT_52W_LOW o NEW_52W_LOW → alerta inmediata
    WATCHLIST        — NEAR_52W_LOW → vigilar
    NO_ACTION        — NO_SIGNAL
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

_NEAR_PCT   = 5.0    # % para considerar "cercano" al mínimo 52w
_AT_PCT     = 1.5    # % para considerar "en" el mínimo 52w
_52W_BARS   = 252    # días hábiles en 52 semanas


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


# ── Análisis ──────────────────────────────────────────────────────────────────

def analyze_symbol(symbol: str, fecha: Optional[date] = None) -> Optional[dict]:
    """Analiza proximidad a mínimos históricos para un símbolo.

    Retorna None si no hay suficiente historia (< 100 días).
    """
    fecha = fecha or date.today()
    rows = _load_ohlcv(symbol, fecha, n=600)

    if len(rows) < 100:
        return None

    closes = [float(r['close']) for r in rows]
    lows   = [float(r['low']) for r in rows]
    price  = closes[-1]

    # ── Mínimo 52 semanas (sobre los lows intradiarios) ──────────────────────
    window_52w = lows[-_52W_BARS:] if len(lows) >= _52W_BARS else lows
    low_52w = min(window_52w)

    # Fecha del mínimo 52w
    offset = len(lows) - len(window_52w)
    low_52w_idx = offset + window_52w.index(low_52w)
    low_52w_date = rows[low_52w_idx]['fecha']
    low_52w_days_ago = len(rows) - 1 - low_52w_idx

    # ── Mínimo absoluto (todo el historial) ──────────────────────────────────
    low_all = min(lows)
    low_all_idx = lows.index(low_all)
    low_all_date = rows[low_all_idx]['fecha']

    # ── Distancias ───────────────────────────────────────────────────────────
    dist_52w = ((price / low_52w) - 1) * 100 if low_52w > 0 else None
    dist_all = ((price / low_all) - 1) * 100 if low_all > 0 else None

    # ── Clasificación ────────────────────────────────────────────────────────
    is_new_low = (price <= low_52w * 1.001)  # precio = mínimo o por debajo

    if is_new_low:
        state = 'NEW_52W_LOW'
    elif dist_52w is not None and dist_52w <= _AT_PCT:
        state = 'AT_52W_LOW'
    elif dist_52w is not None and dist_52w <= _NEAR_PCT:
        state = 'NEAR_52W_LOW'
    else:
        state = 'NO_SIGNAL'

    # ── Decisión ─────────────────────────────────────────────────────────────
    if state in ('NEW_52W_LOW', 'AT_52W_LOW'):
        decision = 'ALERT'
        confidence = 'HIGH'
    elif state == 'NEAR_52W_LOW':
        decision = 'WATCHLIST'
        confidence = 'MEDIUM'
    else:
        decision = 'NO_ACTION'
        confidence = 'LOW'

    # ── Indicadores de contexto ──────────────────────────────────────────────
    rsi_val  = rsi(closes, 14)
    mom20    = momentum_pct(closes, 20)
    sma200   = sma(closes, 200)

    # ── Es también mínimo absoluto? ──────────────────────────────────────────
    is_all_time_low = (price <= low_all * 1.001)

    # ── Reading ──────────────────────────────────────────────────────────────
    if state == 'NEW_52W_LOW':
        reading = f"{symbol} rompio su minimo de 52 semanas (${low_52w:.2f}). Precio actual ${price:.2f}."
    elif state == 'AT_52W_LOW':
        reading = f"{symbol} a {dist_52w:.1f}% de su minimo 52w (${low_52w:.2f}). Precio ${price:.2f}."
    elif state == 'NEAR_52W_LOW':
        reading = f"{symbol} cerca de minimo 52w: {dist_52w:.1f}% arriba de ${low_52w:.2f}."
    else:
        reading = f"{symbol} a {dist_52w:.1f}% de su minimo 52w." if dist_52w else f"{symbol} sin senial."

    if is_all_time_low:
        reading += " MINIMO HISTORICO ABSOLUTO."

    return {
        'fecha':              fecha,
        'simbolo':            symbol,
        'price':              round(price, 4),
        'low_52w':            round(low_52w, 4),
        'low_52w_date':       low_52w_date,
        'low_52w_days_ago':   low_52w_days_ago,
        'distance_52w_pct':   round(dist_52w, 3) if dist_52w is not None else None,
        'low_all':            round(low_all, 4),
        'low_all_date':       low_all_date,
        'distance_all_pct':   round(dist_all, 3) if dist_all is not None else None,
        'is_all_time_low':    is_all_time_low,
        'setup_state':        state,
        'decision':           decision,
        'confidence_level':   confidence,
        'reading':            reading,
        'rsi14':              rsi_val,
        'mom20':              mom20,
        'sma200':             round(sma200, 4) if sma200 else None,
    }


def run_universe(symbols: list[str], fecha: Optional[date] = None) -> list[dict]:
    """Corre el análisis para todos los símbolos. Retorna solo los que tienen señal."""
    fecha = fecha or date.today()
    results = []
    for sym in symbols:
        r = analyze_symbol(sym, fecha)
        if r:
            results.append(r)
    return results


# ── Persistencia ──────────────────────────────────────────────────────────────

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS historical_low_signals (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    fecha               DATE           NOT NULL,
    simbolo             VARCHAR(20)    NOT NULL,
    price               DECIMAL(14,4),
    low_52w             DECIMAL(14,4),
    low_52w_date        DATE,
    low_52w_days_ago    INT,
    distance_52w_pct    DECIMAL(8,3),
    low_all             DECIMAL(14,4),
    low_all_date        DATE,
    distance_all_pct    DECIMAL(8,3),
    is_all_time_low     TINYINT(1)     DEFAULT 0,
    setup_state         VARCHAR(20),
    decision            VARCHAR(20),
    confidence_level    VARCHAR(10),
    reading             VARCHAR(500),
    rsi14               DECIMAL(6,2),
    mom20               DECIMAL(8,4),
    sma200              DECIMAL(14,4),
    created_at          TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_hl_fecha_sym (fecha, simbolo),
    INDEX idx_state (setup_state),
    INDEX idx_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_UPSERT_SQL = """
INSERT INTO historical_low_signals
    (fecha, simbolo, price, low_52w, low_52w_date, low_52w_days_ago,
     distance_52w_pct, low_all, low_all_date, distance_all_pct,
     is_all_time_low, setup_state, decision, confidence_level,
     reading, rsi14, mom20, sma200)
VALUES
    (%(fecha)s, %(simbolo)s, %(price)s, %(low_52w)s, %(low_52w_date)s,
     %(low_52w_days_ago)s, %(distance_52w_pct)s, %(low_all)s, %(low_all_date)s,
     %(distance_all_pct)s, %(is_all_time_low)s, %(setup_state)s, %(decision)s,
     %(confidence_level)s, %(reading)s, %(rsi14)s, %(mom20)s, %(sma200)s)
ON DUPLICATE KEY UPDATE
    price            = VALUES(price),
    low_52w          = VALUES(low_52w),
    low_52w_date     = VALUES(low_52w_date),
    low_52w_days_ago = VALUES(low_52w_days_ago),
    distance_52w_pct = VALUES(distance_52w_pct),
    low_all          = VALUES(low_all),
    low_all_date     = VALUES(low_all_date),
    distance_all_pct = VALUES(distance_all_pct),
    is_all_time_low  = VALUES(is_all_time_low),
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
    """Persiste resultados en historical_low_signals (upsert)."""
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
