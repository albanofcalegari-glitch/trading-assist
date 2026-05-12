"""
byma_bonds_fetch.py — Fetch precios de bonos soberanos desde BYMA Open Data
=============================================================================
API pública, sin auth: open.bymadata.com.ar

Uso:
    python scripts/byma_bonds_fetch.py              # fetch + persist + calcular TIR
    python scripts/byma_bonds_fetch.py --dry-run     # solo mostrar sin guardar
"""

import argparse
import json
import ssl
import sys
import os
import urllib.request
import urllib.error
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.bonds_ar import (
    BONDS, ALL_BOND_SYMBOLS, analyze_bond,
    calc_zscore_signal,
)

BYMA_URL = 'https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/public-bonds'

HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

BYMA_TO_BOND = {}
for sym, bond in BONDS.items():
    BYMA_TO_BOND[bond['byma_symbol']] = sym

_CREATE_PRICE_TABLE = """
CREATE TABLE IF NOT EXISTS bonds_price_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    fecha DATE NOT NULL,
    price_usd DECIMAL(10,4),
    price_ars DECIMAL(14,2),
    bid_usd DECIMAL(10,4),
    ask_usd DECIMAL(10,4),
    volume BIGINT DEFAULT 0,
    UNIQUE KEY uq_sym_fecha (symbol, fecha),
    INDEX idx_symbol (symbol),
    INDEX idx_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_CREATE_TIR_TABLE = """
CREATE TABLE IF NOT EXISTS bonds_tir_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    fecha DATE NOT NULL,
    tir DECIMAL(8,4) NOT NULL,
    paridad DECIMAL(8,4),
    duration_mod DECIMAL(8,4),
    accrued_interest DECIMAL(8,4),
    z_score DECIMAL(6,3),
    `signal` VARCHAR(20),
    UNIQUE KEY uq_sym_fecha (symbol, fecha),
    INDEX idx_symbol (symbol),
    INDEX idx_signal (`signal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_tables():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_PRICE_TABLE)
            cur.execute(_CREATE_TIR_TABLE)
        conn.commit()
    finally:
        conn.close()


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(
            urllib.request.Request('https://open.bymadata.com.ar', method='HEAD'),
            timeout=5, context=ctx,
        )
        return ctx
    except Exception:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


def fetch_byma_bonds() -> list[dict]:
    body = json.dumps({"T2": True, "T1": True, "T0": True}).encode()
    req = urllib.request.Request(BYMA_URL, data=body, headers=HEADERS, method='POST')

    try:
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f'  [ERROR] BYMA API: {e}')
        return []

    if not isinstance(data, list):
        data = data.get('data', []) if isinstance(data, dict) else []

    results = []
    for item in data:
        byma_sym = item.get('symbol', '').strip()
        if byma_sym not in BYMA_TO_BOND:
            continue

        bond_sym = BYMA_TO_BOND[byma_sym]
        ccy = (item.get('denominationCcy') or '').upper()

        price = (
            item.get('closingPrice')
            or item.get('previousSettlementPrice')
            or item.get('settlementPrice')
        )
        if not price:
            continue

        price = float(price)

        bid = float(item['bidPrice']) if item.get('bidPrice') else None
        ask = float(item['offerPrice']) if item.get('offerPrice') else None
        vol = int(item.get('volume') or item.get('tradeVolume') or 0)
        settle_type = item.get('settlementType', '')

        results.append({
            'bond_symbol': bond_sym,
            'byma_symbol': byma_sym,
            'currency': ccy,
            'price': price,
            'bid': bid,
            'ask': ask,
            'volume': vol,
            'settlement': settle_type,
        })

    return results


def _best_usd_price(results: list[dict], bond_sym: str) -> Optional[dict]:
    candidates = [r for r in results if r['bond_symbol'] == bond_sym]
    usd = [r for r in candidates if r['currency'] in ('USD', 'EXT', '')]
    if usd:
        return usd[0]
    return candidates[0] if candidates else None


def _get_tir_history(symbol: str, days: int = 60) -> list[float]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tir FROM bonds_tir_history WHERE symbol = %s ORDER BY fecha DESC LIMIT %s",
                (symbol, days),
            )
            return [float(r['tir']) for r in cur.fetchall()]
    finally:
        conn.close()


def persist_prices(results: list[dict], fecha: date):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for bond_sym in ALL_BOND_SYMBOLS:
                best = _best_usd_price(results, bond_sym)
                if not best:
                    continue

                ars_candidates = [r for r in results if r['bond_symbol'] == bond_sym and r['currency'] == 'ARS']
                price_ars = ars_candidates[0]['price'] if ars_candidates else None

                cur.execute("""
                    INSERT INTO bonds_price_history (symbol, fecha, price_usd, price_ars, bid_usd, ask_usd, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        price_usd = VALUES(price_usd),
                        price_ars = VALUES(price_ars),
                        bid_usd = VALUES(bid_usd),
                        ask_usd = VALUES(ask_usd),
                        volume = VALUES(volume)
                """, (bond_sym, fecha, best['price'], price_ars, best.get('bid'), best.get('ask'), best['volume']))

        conn.commit()
    finally:
        conn.close()


def persist_tir(analyses: list[dict], fecha: date):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for a in analyses:
                if a.get('tir') is None:
                    continue
                cur.execute("""
                    INSERT INTO bonds_tir_history (symbol, fecha, tir, paridad, duration_mod, accrued_interest, z_score, `signal`)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        tir = VALUES(tir),
                        paridad = VALUES(paridad),
                        duration_mod = VALUES(duration_mod),
                        accrued_interest = VALUES(accrued_interest),
                        z_score = VALUES(z_score),
                        `signal` = VALUES(`signal`)
                """, (
                    a['symbol'], fecha,
                    a['tir'], a.get('paridad'), a.get('duration_mod'), a.get('accrued_interest'),
                    a.get('z_score'), a.get('signal'),
                ))
        conn.commit()
    finally:
        conn.close()


def run(dry_run: bool = False):
    print()
    print('=' * 60)
    print('  BYMA Bonds Fetch')
    print(f'  Fecha: {date.today()}')
    print(f'  Modo:  {"DRY-RUN" if dry_run else "PERSIST"}')
    print('=' * 60)
    print()

    if not dry_run:
        ensure_tables()

    results = fetch_byma_bonds()
    if not results:
        print('  [WARN] No se obtuvieron datos de BYMA')
        return []

    print(f'  Datos recibidos: {len(results)} registros de bonos')
    print()

    analyses = []
    for sym in ALL_BOND_SYMBOLS:
        best = _best_usd_price(results, sym)
        if not best:
            print(f'  {sym:6s}  SIN DATOS')
            continue

        analysis = analyze_bond(sym, best['price'], date.today())
        if not analysis:
            print(f'  {sym:6s}  ERROR en análisis')
            continue

        tir_hist = _get_tir_history(sym) if not dry_run else []
        zscore_data = calc_zscore_signal(analysis['tir'], tir_hist)
        analysis.update(zscore_data)

        analyses.append(analysis)

        signal_str = {
            'BUY': '🟢 COMPRAR',
            'SELL': '🔴 VENDER',
            'NEUTRAL': '⚪ ---',
        }.get(analysis.get('signal', 'NEUTRAL'), '⚪ ---')

        z_str = f"Z={analysis.get('z_score', '?'):>+6}" if analysis.get('z_score') is not None else 'Z=  N/A'

        print(
            f'  {sym:6s} [{BONDS[sym]["law"]:3s}]  '
            f'USD {best["price"]:>7.2f}  '
            f'TIR {analysis["tir"]:>5.2f}%  '
            f'Par {analysis["paridad"]:>6.2f}%  '
            f'DM {analysis.get("duration_mod", 0):>5.2f}  '
            f'{z_str}  {signal_str}'
        )

    if not dry_run and analyses:
        persist_prices(results, date.today())
        persist_tir(analyses, date.today())
        print(f'\n  Persistidos {len(analyses)} bonos en DB')

    print()
    print('=' * 60)
    return analyses


def main():
    parser = argparse.ArgumentParser(description='Fetch BYMA bond prices')
    parser.add_argument('--dry-run', action='store_true', help='Solo mostrar, no guardar')
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
