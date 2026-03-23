"""
data_loader — descarga y persistencia de precios OHLCV
Fuente: Yahoo Finance API v8 (directa, sin yfinance)
"""
import time
import requests
from datetime import datetime, timedelta, date
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import FETCH_TIMEOUT, HISTORY_YEARS
from db.connection import get_conn

# ── Cabeceras necesarias para Yahoo Finance ───────────────────────────────────
_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

_BASE_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'


# ─────────────────────────────────────────────────────────────────────────────
# Fetch desde Yahoo Finance
# ─────────────────────────────────────────────────────────────────────────────

def fetch_price_history(
    symbol: str,
    years: int = HISTORY_YEARS,
    start_date: Optional[date] = None,
) -> list[dict]:
    """
    Descarga precios OHLCV diarios de Yahoo Finance.

    Args:
        symbol:     ticker (ej. 'NVDA', 'SPY')
        years:      años de historia si no se especifica start_date
        start_date: fecha de inicio opcional (para updates incrementales)

    Returns:
        lista de dicts con keys: simbolo, fecha, open, high, low, close, volume
        Ordenada por fecha ascendente.
    """
    if start_date:
        period1 = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    else:
        period1 = int((datetime.now() - timedelta(days=years * 365 + 10)).timestamp())

    period2 = int(datetime.now().timestamp())

    url = _BASE_URL.format(symbol=symbol)
    params = {
        'interval':  '1d',
        'period1':   period1,
        'period2':   period2,
        'events':    'history',
    }

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [ERROR] {symbol}: {e}")
        return []

    try:
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        ohlcv      = result['indicators']['quote'][0]
    except (KeyError, IndexError, TypeError):
        print(f"  [WARN]  {symbol}: respuesta vacía o inesperada")
        return []

    opens   = ohlcv.get('open',   [])
    highs   = ohlcv.get('high',   [])
    lows    = ohlcv.get('low',    [])
    closes  = ohlcv.get('close',  [])
    volumes = ohlcv.get('volume', [])

    rows = []
    for i, ts in enumerate(timestamps):
        try:
            o = opens[i];  h = highs[i];  l = lows[i];  c = closes[i]
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


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia en DB
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_prices(conn, table: str, rows: list[dict]) -> int:
    """INSERT ... ON DUPLICATE KEY UPDATE sobre una tabla de precios."""
    if not rows:
        return 0
    sql = f"""
        INSERT INTO {table} (simbolo, fecha, open, high, low, close, volume)
        VALUES (%(simbolo)s, %(fecha)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
        ON DUPLICATE KEY UPDATE
            open=VALUES(open), high=VALUES(high), low=VALUES(low),
            close=VALUES(close), volume=VALUES(volume)
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def save_market_index(rows: list[dict]) -> int:
    """Guarda precios de SPY en market_index."""
    conn = get_conn()
    try:
        return _upsert_prices(conn, 'market_index', rows)
    finally:
        conn.close()


def save_sector_index(rows: list[dict], sector: str) -> int:
    """Guarda precios de un ETF sectorial en sector_index."""
    conn = get_conn()
    try:
        enriched = [{**r, 'sector': sector} for r in rows]
        if not enriched:
            return 0
        sql = """
            INSERT INTO sector_index (simbolo, sector, fecha, open, high, low, close, volume)
            VALUES (%(simbolo)s, %(sector)s, %(fecha)s, %(open)s, %(high)s,
                    %(low)s, %(close)s, %(volume)s)
            ON DUPLICATE KEY UPDATE
                open=VALUES(open), high=VALUES(high), low=VALUES(low),
                close=VALUES(close), volume=VALUES(volume),
                sector=VALUES(sector)
        """
        with conn.cursor() as cur:
            cur.executemany(sql, enriched)
        return len(enriched)
    finally:
        conn.close()


def save_asset_prices(rows: list[dict]) -> int:
    """Guarda precios de un activo del universo en price_history."""
    conn = get_conn()
    try:
        return _upsert_prices(conn, 'price_history', rows)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de lectura
# ─────────────────────────────────────────────────────────────────────────────

def get_last_date(table: str, symbol: str) -> Optional[date]:
    """Retorna la última fecha disponible en DB para un símbolo."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MAX(fecha) AS mx FROM {table} WHERE simbolo=%s",
                (symbol,)
            )
            row = cur.fetchone()
            return row['mx'] if row and row['mx'] else None
    finally:
        conn.close()


def load_closes(table: str, symbol: str, n: int = 300) -> list[float]:
    """
    Devuelve los últimos N cierres de un símbolo ordenados ASC.
    Útil para cálculos de indicadores.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT close FROM {table}
                    WHERE simbolo=%s ORDER BY fecha DESC LIMIT %s""",
                (symbol, n)
            )
            rows = cur.fetchall()
        return [float(r['close']) for r in reversed(rows)]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Update incremental diario
# ─────────────────────────────────────────────────────────────────────────────

def update_prices_daily(
    universe: list[str],
    market_benchmark: str,
    sector_benchmarks: list[str],
    sector_map: dict,
    delay: float = 0.5,
) -> None:
    """
    Actualiza precios en DB descargando solo desde la última fecha disponible.
    Cubre: universo, benchmark de mercado y ETFs sectoriales.
    """
    all_symbols = sorted(set(universe) | {market_benchmark} | set(sector_benchmarks))

    print(f"\n=== update_prices_daily — {len(all_symbols)} símbolos ===\n")
    for sym in all_symbols:
        # Determinar tabla destino y si es sector/mercado
        if sym == market_benchmark:
            table = 'market_index'
        elif sym in sector_benchmarks:
            table = 'sector_index'
        else:
            table = 'price_history'

        last = get_last_date(table, sym)
        if last:
            start = last + timedelta(days=1)
            if start > date.today():
                print(f"  {sym:6s} → ya actualizado ({last})")
                continue
        else:
            start = None  # descarga completa

        rows = fetch_price_history(sym, start_date=start)
        if not rows:
            print(f"  {sym:6s} → sin datos nuevos")
            time.sleep(delay)
            continue

        if sym == market_benchmark:
            n = save_market_index(rows)
        elif sym in sector_benchmarks:
            # buscar el nombre del sector para este ETF
            sector_name = next(
                (v['sector'] for v in sector_map.values() if v['benchmark'] == sym),
                sym
            )
            n = save_sector_index(rows, sector_name)
        else:
            n = save_asset_prices(rows)

        print(f"  {sym:6s} → {n} filas guardadas (desde {rows[0]['fecha']})")
        time.sleep(delay)

    print("\nDone.\n")
