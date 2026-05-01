"""
ml/dataset.py — orquestador del build de ml_signals.

Para cada (símbolo, fecha de business day) en un rango:
  1. invoca strategies.trend_pullback.analyze_symbol() para generar la "señal"
  2. si la señal cumple el filtro (decisión != NO_ACTION o setup interesante),
     extrae features con ml.features.extract_features
  3. computa labels forward con ml.labels.compute_labels
  4. upsert en la tabla ml_signals (UNIQUE: symbol+fecha+strategy+variant)

Uso:
  .venv/Scripts/python.exe -m ml.dataset --start 2025-12-01 --end 2026-02-01 \\
                                          --symbols AAPL,GOOGL,MSFT,NVDA,JPM
  .venv/Scripts/python.exe -m ml.dataset --full
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from db.connection import get_conn
from ml.features import extract_features
from ml.labels import compute_labels
from ml.migrations import ensure_schema
from strategies.trend_pullback import analyze_symbol


# ── Defaults para corrida acotada de validación ──────────────────────────────

DEFAULT_VALIDATION_SYMBOLS = ['AAPL', 'GOOGL', 'MSFT', 'NVDA', 'JPM']
DEFAULT_VALIDATION_START = date(2025, 12, 1)
DEFAULT_VALIDATION_END   = date(2026, 2, 28)

# Cuando se corre --full sobre todo el universo
FULL_START = date(2025, 4, 1)   # market_context_daily empieza 2025-03-31
FULL_END   = date(2026, 3, 15)  # 10 días buffer antes del max de price_history

# Setups que SI persistimos (filtrar NO_SETUP/TREND_BROKEN para no inflar el dataset
# con filas inservibles; igualmente quedan accesibles si los queremos en Fase 2)
INTERESTING_SETUPS = {'PULLBACK_VALID', 'PULLBACK_FORMING', 'TREND_HEALTHY'}

STRATEGY_NAME = 'trend_pullback'


# ── Trading days helper ──────────────────────────────────────────────────────

def _trading_days(cur, start: date, end: date) -> list[date]:
    """
    Devuelve fechas distintas con barras en price_history dentro del rango.
    Usa el calendario real de la BD (evita listar weekends/holidays a mano).
    """
    cur.execute(
        """SELECT DISTINCT fecha FROM price_history
           WHERE fecha BETWEEN %s AND %s
           ORDER BY fecha""",
        (start, end),
    )
    return [r['fecha'] for r in cur.fetchall()]


# ── Universo ─────────────────────────────────────────────────────────────────

def _universe_symbols() -> list[str]:
    try:
        from config import UNIVERSE  # type: ignore
        return list(UNIVERSE)
    except Exception:
        return DEFAULT_VALIDATION_SYMBOLS


# ── Upsert ───────────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO ml_signals (
    symbol, fecha, strategy, variant, signal_score,
    price, volume_ratio, gap_pct, range_position,
    rsi_14, adx_14, dist_sma200, ret_5d, ret_20d, rs_vs_spy,
    atr14_rel, vs_52w_high, rs_sector, pullback_score,
    dist_to_support, dist_to_resistance,
    has_dyn_short, dyn_short_dist_pct, dist_to_ath_pct,
    has_res_long, res_long_dist_pct,
    has_res_mid, res_mid_dist_pct, res_mid_slope,
    has_res_short, res_short_dist_pct,
    market_regime, vix_percentile, spy_return_20d,
    return_1d, return_5d, return_10d, max_drawdown_5d, label_5d_strong
) VALUES (
    %(symbol)s, %(fecha)s, %(strategy)s, %(variant)s, %(signal_score)s,
    %(price)s, %(volume_ratio)s, %(gap_pct)s, %(range_position)s,
    %(rsi_14)s, %(adx_14)s, %(dist_sma200)s, %(ret_5d)s, %(ret_20d)s, %(rs_vs_spy)s,
    %(atr14_rel)s, %(vs_52w_high)s, %(rs_sector)s, %(pullback_score)s,
    %(dist_to_support)s, %(dist_to_resistance)s,
    %(has_dyn_short)s, %(dyn_short_dist_pct)s, %(dist_to_ath_pct)s,
    %(has_res_long)s, %(res_long_dist_pct)s,
    %(has_res_mid)s, %(res_mid_dist_pct)s, %(res_mid_slope)s,
    %(has_res_short)s, %(res_short_dist_pct)s,
    %(market_regime)s, %(vix_percentile)s, %(spy_return_20d)s,
    %(return_1d)s, %(return_5d)s, %(return_10d)s, %(max_drawdown_5d)s, %(label_5d_strong)s
)
ON DUPLICATE KEY UPDATE
    signal_score=VALUES(signal_score),
    price=VALUES(price), volume_ratio=VALUES(volume_ratio),
    gap_pct=VALUES(gap_pct), range_position=VALUES(range_position),
    rsi_14=VALUES(rsi_14), adx_14=VALUES(adx_14), dist_sma200=VALUES(dist_sma200),
    ret_5d=VALUES(ret_5d), ret_20d=VALUES(ret_20d), rs_vs_spy=VALUES(rs_vs_spy),
    atr14_rel=VALUES(atr14_rel), vs_52w_high=VALUES(vs_52w_high),
    rs_sector=VALUES(rs_sector), pullback_score=VALUES(pullback_score),
    dist_to_support=VALUES(dist_to_support), dist_to_resistance=VALUES(dist_to_resistance),
    has_dyn_short=VALUES(has_dyn_short),
    dyn_short_dist_pct=VALUES(dyn_short_dist_pct),
    dist_to_ath_pct=VALUES(dist_to_ath_pct),
    has_res_long=VALUES(has_res_long),
    res_long_dist_pct=VALUES(res_long_dist_pct),
    has_res_mid=VALUES(has_res_mid),
    res_mid_dist_pct=VALUES(res_mid_dist_pct),
    res_mid_slope=VALUES(res_mid_slope),
    has_res_short=VALUES(has_res_short),
    res_short_dist_pct=VALUES(res_short_dist_pct),
    market_regime=VALUES(market_regime), vix_percentile=VALUES(vix_percentile),
    spy_return_20d=VALUES(spy_return_20d),
    return_1d=VALUES(return_1d), return_5d=VALUES(return_5d), return_10d=VALUES(return_10d),
    max_drawdown_5d=VALUES(max_drawdown_5d), label_5d_strong=VALUES(label_5d_strong)
"""


def _upsert(cur, row: dict) -> None:
    cur.execute(_UPSERT_SQL, row)


# ── Build core ───────────────────────────────────────────────────────────────

def build_dataset(
    symbols: Iterable[str],
    start: date,
    end: date,
    verbose: bool = True,
) -> dict:
    """
    Recorre (símbolo, fecha) y persiste filas a ml_signals.
    Devuelve un dict con stats: filas insertadas, skips, etc.
    """
    ensure_schema()

    stats = {
        'analyzed':       0,
        'skipped_setup':  0,   # señal NO_SETUP/TREND_BROKEN → no la guardamos
        'skipped_nodata': 0,   # analyze_symbol devolvió None
        'skipped_feat':   0,   # extract_features devolvió None
        'inserted':       0,
        'with_label':     0,   # filas que tienen label_5d_strong (no NULL)
    }

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tdays = _trading_days(cur, start, end)
            if verbose:
                print(f'[ ] {len(tdays)} trading days en {start} → {end}')
                print(f'[ ] {len(list(symbols))} símbolos')

            stats['errors'] = 0
            t0 = time.time()
            for sym in symbols:
                try:
                    for d in tdays:
                        stats['analyzed'] += 1
                        sig = analyze_symbol(sym, d)
                        if sig is None:
                            stats['skipped_nodata'] += 1
                            continue
                        setup = sig.get('setup_state', 'NO_SETUP')
                        if setup not in INTERESTING_SETUPS:
                            stats['skipped_setup'] += 1
                            continue

                        feats = extract_features(cur, sym, d)
                        if feats is None:
                            stats['skipped_feat'] += 1
                            continue

                        labs = compute_labels(cur, sym, d)

                        row = {
                            'symbol':       sym,
                            'fecha':        d,
                            'strategy':     STRATEGY_NAME,
                            'variant':      setup,                       # subtipo de la señal
                            'signal_score': float(sig['trend_score']),
                            'pullback_score': float(sig['pullback_score']),
                            **feats,
                            **labs,
                        }
                        _upsert(cur, row)
                        stats['inserted'] += 1
                        if labs['label_5d_strong'] is not None:
                            stats['with_label'] += 1
                except Exception as e:
                    stats['errors'] += 1
                    if verbose:
                        print(f'  · {sym:6} ERROR — {type(e).__name__}: {e}')
                    continue

                if verbose:
                    elapsed = time.time() - t0
                    rate = stats['analyzed'] / elapsed if elapsed > 0 else 0
                    print(f'  · {sym:6} hecho — analyzed={stats["analyzed"]} '
                          f'inserted={stats["inserted"]} errs={stats["errors"]} ({rate:.1f}/s)')
    finally:
        conn.close()
    return stats


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    except Exception:
        pass

    p = argparse.ArgumentParser(description='Build ml_signals dataset (Track A)')
    p.add_argument('--start', type=_parse_date, default=DEFAULT_VALIDATION_START)
    p.add_argument('--end',   type=_parse_date, default=DEFAULT_VALIDATION_END)
    p.add_argument('--symbols', type=str, default=','.join(DEFAULT_VALIDATION_SYMBOLS),
                   help='lista CSV de símbolos; ignorado si --full')
    p.add_argument('--full', action='store_true',
                   help='usa UNIVERSE completo y rango FULL_START..FULL_END')
    args = p.parse_args()

    if args.full:
        symbols = _universe_symbols()
        start, end = FULL_START, FULL_END
    else:
        symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
        start, end = args.start, args.end

    print(f'[#] build_dataset symbols={len(symbols)} {start} → {end}')
    t0 = time.time()
    stats = build_dataset(symbols, start, end)
    elapsed = time.time() - t0

    print('\n=== STATS ===')
    for k, v in stats.items():
        print(f'  {k:18}= {v}')
    print(f'  elapsed_seconds   = {elapsed:.1f}')


if __name__ == '__main__':
    main()
