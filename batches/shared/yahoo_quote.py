"""
batches.shared.yahoo_quote — wrapper de Yahoo Finance v8 chart con prePost.

Devuelve datos intraday + premarket del día corriente, sin necesidad de yfinance.
Lo usan PremarketBatch (10:00 ART) y OpeningBatch (10:30 ART).

Endpoint:
    https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
        ?interval=5m&range=1d&includePrePost=true

Parsing:
    - meta.chartPreviousClose       → cierre del día anterior
    - meta.regularMarketPrice       → último precio (incluye RTH si está abierto)
    - meta.marketState              → PRE | REGULAR | POST | CLOSED
    - currentTradingPeriod.regular  → start/end (epoch sec) de la sesión RTH
    - timestamp[] + indicators.quote[0].close[] → barras 5m

Las barras se separan en pre (ts < regular_start) y reg (regular_start ≤ ts ≤ regular_end).
"""
from __future__ import annotations

import time
import requests
from typing import Any

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

_BASE_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
_TIMEOUT  = 15


def _pct(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or not prev:
        return None
    return (curr / prev - 1.0) * 100.0


def fetch_quote_with_prepost(symbol: str) -> dict | None:
    """
    Devuelve un dict normalizado con:
        symbol, market_state,
        prev_close,
        open_price            (open RTH del día, si ya hay)
        regular_market_price  (último precio RTH)
        premarket_price       (último precio premarket)
        premarket_pct         (%, vs prev_close)
        regular_pct           (%, vs prev_close)
        gap_pct               (open vs prev_close, %)
        last_price            (último precio disponible: RTH si hay, sino premarket)
        n_pre_bars, n_reg_bars

    Devuelve None si Yahoo no responde o el símbolo no existe.
    """
    url = _BASE_URL.format(symbol=symbol)
    params = {
        'interval':       '5m',
        'range':          '1d',
        'includePrePost': 'true',
    }
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f'  [yahoo_quote] {symbol}: {e}')
        return None

    try:
        result = data['chart']['result'][0]
    except (KeyError, IndexError, TypeError):
        return None

    meta = result.get('meta', {}) or {}
    prev_close = meta.get('chartPreviousClose')
    rmp        = meta.get('regularMarketPrice')
    state      = meta.get('marketState', 'CLOSED')

    # Período RTH del día
    regular_start = None
    regular_end   = None
    ctp = meta.get('currentTradingPeriod') or {}
    reg = ctp.get('regular') or {}
    regular_start = reg.get('start')
    regular_end   = reg.get('end')

    timestamps = result.get('timestamp') or []
    quote      = (result.get('indicators', {}).get('quote') or [{}])[0]
    closes     = quote.get('close') or []
    opens      = quote.get('open')  or []

    pre_bars: list[tuple[int, float]] = []
    reg_bars: list[tuple[int, float, float | None]] = []  # (ts, close, open)

    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        o = opens[i]  if i < len(opens)  else None
        if c is None:
            continue
        if regular_start is not None and ts < regular_start:
            pre_bars.append((ts, float(c)))
        elif regular_end is None or ts <= regular_end:
            reg_bars.append((ts, float(c), float(o) if o is not None else None))

    premarket_price = pre_bars[-1][1] if pre_bars else None
    open_price      = None
    last_reg_price  = None
    if reg_bars:
        # primer "open" no nulo
        for _ts, _c, _o in reg_bars:
            if _o is not None:
                open_price = _o
                break
        last_reg_price = reg_bars[-1][1]

    # Si Yahoo nos da regularMarketPrice más fresco, usalo como referencia RTH
    regular_market_price = float(rmp) if rmp is not None else last_reg_price

    last_price = regular_market_price if regular_market_price is not None else premarket_price

    return {
        'symbol':               symbol,
        'market_state':         state,
        'prev_close':           float(prev_close) if prev_close is not None else None,
        'open_price':           open_price,
        'regular_market_price': regular_market_price,
        'premarket_price':      premarket_price,
        'premarket_pct':        _pct(premarket_price,      prev_close),
        'regular_pct':          _pct(regular_market_price, prev_close),
        'gap_pct':              _pct(open_price,           prev_close),
        'last_price':           last_price,
        'n_pre_bars':           len(pre_bars),
        'n_reg_bars':           len(reg_bars),
    }


def fetch_quotes_batch(symbols: list[str], delay: float = 0.15) -> dict[str, dict]:
    """
    Trae quotes para una lista de símbolos secuencialmente.
    Devuelve {symbol: quote_dict} omitiendo los que fallaron.
    """
    out: dict[str, dict] = {}
    for sym in symbols:
        q = fetch_quote_with_prepost(sym)
        if q is not None:
            out[sym] = q
        if delay:
            time.sleep(delay)
    return out
