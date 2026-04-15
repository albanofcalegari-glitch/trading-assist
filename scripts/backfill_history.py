"""
backfill_history.py — Descarga histórico OHLCV extendido multi-timeframe

Tabla destino: trading_assist.ohlcv_extended
Columnas: simbolo, timeframe, fecha, open, high, low, close, volume

Objetivo de cobertura:
    D (diario):  hasta 20 años
    W (semanal): hasta 25 años
    M (mensual): máximo disponible (~30 años)

Uso:
    python scripts/backfill_history.py                        # universo completo D+W+M
    python scripts/backfill_history.py --symbol GOOGL         # solo GOOGL, todos los TF
    python scripts/backfill_history.py --symbol DIS --tf W    # DIS semanal
    python scripts/backfill_history.py --tf M                 # todos los símbolos, mensual
    python scripts/backfill_history.py --update               # solo actualizar faltantes
"""

import argparse
import sys
import os
import time
import requests
from datetime import datetime, timedelta, date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE, MARKET_BENCHMARK, SECTOR_BENCHMARKS
from db.connection import get_conn

# ── Cabeceras Yahoo Finance ───────────────────────────────────────────────────

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

_BASE_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'


def _yf_symbol(symbol: str) -> str:
    # Yahoo Finance usa guiones en lugar de puntos para sub-clases (PBR.A -> PBR-A, BRK.B -> BRK-B).
    return symbol.replace('.', '-')

# ── Configuración por timeframe ───────────────────────────────────────────────
# tf -> (intervalo Yahoo Finance, años de historia objetivo)

_TF_CONFIG = {
    'D': ('1d',  20),
    'W': ('1wk', 25),
    'M': ('1mo', 30),
}

_ALL_SYMBOLS = sorted(set(UNIVERSE) | {MARKET_BENCHMARK} | set(SECTOR_BENCHMARKS))

# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ohlcv_extended (
    simbolo    VARCHAR(20)          NOT NULL,
    timeframe  ENUM('D', 'W', 'M') NOT NULL,
    fecha      DATE                 NOT NULL,
    open       DECIMAL(14,4)        NOT NULL,
    high       DECIMAL(14,4)        NOT NULL,
    low        DECIMAL(14,4)        NOT NULL,
    close      DECIMAL(14,4)        NOT NULL,
    volume     BIGINT               NOT NULL DEFAULT 0,
    PRIMARY KEY (simbolo, timeframe, fecha),
    INDEX idx_sym_tf (simbolo, timeframe),
    INDEX idx_tf_fecha (timeframe, fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_table() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
        conn.commit()
    finally:
        conn.close()


# ── Fetch Yahoo Finance ───────────────────────────────────────────────────────

def _fetch(
    symbol:     str,
    yf_interval: str,
    years:      int,
    start_date: Optional[date] = None,
) -> list[dict]:
    """
    Descarga OHLCV de Yahoo Finance para el intervalo dado.
    Soporta '1d', '1wk', '1mo'.
    """
    if start_date:
        period1 = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    else:
        period1 = int((datetime.now() - timedelta(days=years * 365 + 30)).timestamp())

    period2 = int(datetime.now().timestamp())

    url = _BASE_URL.format(symbol=_yf_symbol(symbol))
    params = {
        'interval': yf_interval,
        'period1':  period1,
        'period2':  period2,
        'events':   'history',
    }

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        print(f'    [TIMEOUT] {symbol} ({yf_interval})')
        return []
    except Exception as e:
        print(f'    [ERROR]   {symbol} ({yf_interval}): {e}')
        return []

    try:
        result     = data['chart']['result'][0]
        timestamps = result['timestamp']
        q          = result['indicators']['quote'][0]
    except (KeyError, IndexError, TypeError):
        return []

    opens   = q.get('open',   [])
    highs   = q.get('high',   [])
    lows    = q.get('low',    [])
    closes  = q.get('close',  [])
    volumes = q.get('volume', [])

    rows = []
    for i, ts in enumerate(timestamps):
        try:
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            if None in (o, h, l, c):
                continue
            rows.append({
                'simbolo': symbol,
                'fecha':   datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d'),
                'open':    round(float(o), 4),
                'high':    round(float(h), 4),
                'low':     round(float(l), 4),
                'close':   round(float(c), 4),
                'volume':  int(volumes[i]) if volumes[i] is not None else 0,
            })
        except (TypeError, IndexError):
            continue

    return rows


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_last_date(symbol: str, tf: str) -> Optional[date]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(fecha) AS mx FROM ohlcv_extended WHERE simbolo=%s AND timeframe=%s",
                (symbol, tf),
            )
            row = cur.fetchone()
            return row['mx'] if row and row['mx'] else None
    finally:
        conn.close()


def _upsert(rows: list[dict], tf: str) -> tuple[int, int]:
    """
    Inserta o actualiza filas en ohlcv_extended.

    Retorna (inserted, updated).

    Técnica: MySQL ON DUPLICATE KEY UPDATE retorna rowcount=1 por INSERT
    y rowcount=2 por UPDATE. Tras executemany, el rowcount total es
    sum(1 * inserts + 2 * updates). Con total_rows = inserts + updates:
        updates  = rowcount_total - total_rows
        inserted = total_rows - updates
    """
    if not rows:
        return 0, 0

    sql = """
        INSERT INTO ohlcv_extended
               (simbolo, timeframe, fecha, open, high, low, close, volume)
        VALUES (%(simbolo)s, %(tf)s, %(fecha)s,
                %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
        ON DUPLICATE KEY UPDATE
            open   = VALUES(open),
            high   = VALUES(high),
            low    = VALUES(low),
            close  = VALUES(close),
            volume = VALUES(volume)
    """

    enriched = [{**r, 'tf': tf} for r in rows]
    conn = get_conn(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, enriched)
            rc = cur.rowcount   # 1*inserts + 2*updates
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    n        = len(rows)
    updated  = rc - n        # rows that already existed and were updated
    inserted = n - updated   # truly new rows
    # Clamp: en MySQL rowcount puede ser 0 si el UPDATE no cambia valores
    updated  = max(0, updated)
    inserted = max(0, inserted)
    return inserted, updated


# ── Backfill de un símbolo + timeframe ───────────────────────────────────────

def backfill_symbol(symbol: str, tf: str, update_only: bool = False) -> dict:
    """
    Descarga y persiste el histórico extendido para un símbolo y timeframe.

    update_only=True: solo actualiza si ya hay datos en DB; si no hay, salta.
    update_only=False: descarga el histórico completo si no hay datos, o
                       solo lo faltante si ya existe algo.

    Retorna dict con el log del resultado.
    """
    yf_interval, years = _TF_CONFIG[tf]

    last = _get_last_date(symbol, tf)

    if update_only and last is None:
        return {
            'symbol':  symbol, 'tf': tf, 'skipped': True,
            'reason':  'sin datos en DB — ejecutar sin --update primero',
        }

    start = None
    if last:
        start = last + timedelta(days=1)
        if start > date.today():
            return {
                'symbol':    symbol, 'tf': tf, 'skipped': True,
                'reason':    'ya actualizado',
                'last_date': str(last),
            }

    rows = _fetch(symbol, yf_interval, years, start_date=start)
    if not rows:
        return {
            'symbol':  symbol, 'tf': tf, 'skipped': True,
            'reason':  'sin datos de Yahoo Finance',
        }

    inserted, updated = _upsert(rows, tf)

    return {
        'symbol':     symbol,
        'tf':         tf,
        'skipped':    False,
        'first_date': rows[0]['fecha'],
        'last_date':  rows[-1]['fecha'],
        'bars_total': len(rows),
        'inserted':   inserted,
        'updated':    updated,
    }


# ── Formato de log ────────────────────────────────────────────────────────────

def _log(result: dict) -> None:
    sym = result['symbol']
    tf  = result['tf']

    if result['skipped']:
        reason = result.get('reason', '')
        if 'ya actualizado' in reason:
            print(f'  {sym:8s} [{tf}]  ya actualizado  (hasta {result.get("last_date", "?")})')
        elif 'sin datos en DB' in reason:
            print(f'  {sym:8s} [{tf}]  SKIP — {reason}')
        else:
            print(f'  {sym:8s} [{tf}]  sin datos Yahoo Finance')
        return

    print(
        f'  {sym:8s} [{tf}]  '
        f'{result["first_date"]} -> {result["last_date"]}  '
        f'barras={result["bars_total"]:5d}  '
        f'insertadas={result["inserted"]:5d}  '
        f'actualizadas={result["updated"]:4d}'
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Backfill histórico OHLCV extendido multi-timeframe'
    )
    parser.add_argument('--symbol', type=str, default=None,
                        help='Símbolo específico (ej. GOOGL). Sin esto procesa todo el universo.')
    parser.add_argument('--tf', type=str, default=None, choices=['D', 'W', 'M'],
                        help='Timeframe: D=diario, W=semanal, M=mensual. Sin esto: D+W+M.')
    parser.add_argument('--full', action='store_true',
                        help='Backfill completo — descarga todo el historico disponible (default)')
    parser.add_argument('--update', action='store_true',
                        help='Solo actualizar datos faltantes (requiere que ya haya datos en DB)')
    parser.add_argument('--delay', type=float, default=0.8,
                        help='Delay en segundos entre requests a Yahoo Finance (default: 0.8)')
    args = parser.parse_args()

    symbols    = [args.symbol.upper()] if args.symbol else _ALL_SYMBOLS
    timeframes = [args.tf] if args.tf else ['D', 'W', 'M']

    print()
    print('=' * 72)
    print(f'  backfill_history')
    print(f'  simbolos   : {", ".join(symbols)}')
    print(f'  timeframes : {", ".join(timeframes)}')
    print(f'  modo       : {"update (solo faltantes)" if args.update else "full backfill (hasta 20-30 años)"}')
    print(f'  delay      : {args.delay}s entre requests')
    print('=' * 72)

    ensure_table()
    print()

    total_inserted = 0
    total_updated  = 0
    total_bars     = 0

    for sym in symbols:
        for tf in timeframes:
            result = backfill_symbol(sym, tf, update_only=args.update)
            _log(result)

            if not result['skipped']:
                total_inserted += result['inserted']
                total_updated  += result['updated']
                total_bars     += result['bars_total']

            time.sleep(args.delay)

    print()
    print('=' * 72)
    print(
        f'  RESUMEN  '
        f'barras_totales={total_bars}  '
        f'insertadas={total_inserted}  '
        f'actualizadas={total_updated}'
    )
    print('=' * 72)
    print()


if __name__ == '__main__':
    main()
