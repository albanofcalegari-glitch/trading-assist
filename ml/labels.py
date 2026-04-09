"""
ml/labels.py — labels forward para el dataset ml_signals.

Para una (symbol, fecha) calcula:
  - return_1d, return_5d, return_10d   (close-to-close fwd)
  - max_drawdown_5d                    (mínimo intra-ventana 5d vs price_t0)
  - label_5d_strong                    (return_5d > 3% AND max_drawdown_5d > -2%)

Fuente: tabla `price_history` (que ya usa la estrategia trend_pullback).
NUNCA usa datos > fecha+10 para no leak. Si no hay 10 días de futuro
disponibles devuelve None en los campos correspondientes.
"""
from __future__ import annotations
from datetime import date
from typing import Optional

from db.connection import get_conn


# ── Umbrales del label principal ─────────────────────────────────────────────
# Definición acordada con el user (Fase 1):
#   label_5d_strong = 1  ⟺  return_5d > +3%  AND  max_drawdown_5d > -2%
LABEL_RET_THR  = 0.03
LABEL_DD_THR   = -0.02


def _load_forward_bars(cur, symbol: str, fecha: date, n: int = 12) -> list[dict]:
    """Trae las primeras n barras estrictamente posteriores a fecha (no incluye t0)."""
    cur.execute(
        """SELECT fecha, open, high, low, close
           FROM price_history
           WHERE simbolo = %s AND fecha > %s
           ORDER BY fecha ASC
           LIMIT %s""",
        (symbol, fecha, n),
    )
    return cur.fetchall()


def _load_close_at(cur, symbol: str, fecha: date) -> Optional[float]:
    """Close del día t0 (la fecha de la señal). Si no hay barra ese día devuelve None."""
    cur.execute(
        "SELECT close FROM price_history WHERE simbolo=%s AND fecha=%s",
        (symbol, fecha),
    )
    row = cur.fetchone()
    return float(row['close']) if row else None


def compute_labels(cur, symbol: str, fecha: date) -> dict:
    """
    Calcula labels forward para (symbol, fecha). Usa el cursor que se le pase
    para no reabrir conexión por fila.

    Returns dict siempre con todas las claves; valores None si la ventana
    forward es insuficiente.
    """
    out = {
        'return_1d':       None,
        'return_5d':       None,
        'return_10d':      None,
        'max_drawdown_5d': None,
        'label_5d_strong': None,
    }

    p0 = _load_close_at(cur, symbol, fecha)
    if p0 is None or p0 <= 0:
        return out

    bars = _load_forward_bars(cur, symbol, fecha, n=12)
    if not bars:
        return out

    closes = [float(b['close']) for b in bars]
    lows   = [float(b['low'])   for b in bars]

    if len(closes) >= 1:
        out['return_1d']  = round(closes[0] / p0 - 1, 6)
    if len(closes) >= 5:
        out['return_5d']  = round(closes[4] / p0 - 1, 6)
        # Max drawdown intra-ventana 5d: mínimo de los lows en t+1..t+5 vs p0
        dd = min(l / p0 - 1 for l in lows[:5])
        out['max_drawdown_5d'] = round(dd, 6)
    if len(closes) >= 10:
        out['return_10d'] = round(closes[9] / p0 - 1, 6)

    # Label binario solo si tenemos retorno 5d y drawdown 5d
    if out['return_5d'] is not None and out['max_drawdown_5d'] is not None:
        is_strong = (out['return_5d'] > LABEL_RET_THR and
                     out['max_drawdown_5d'] > LABEL_DD_THR)
        out['label_5d_strong'] = 1 if is_strong else 0

    return out


# ── Standalone smoke test ────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for sym in ('AAPL', 'NVDA', 'JPM'):
                for d in (date(2025, 6, 16), date(2025, 12, 1), date(2026, 1, 5)):
                    r = compute_labels(cur, sym, d)
                    print(f'{sym} {d}: {r}')
    finally:
        conn.close()
