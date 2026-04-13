"""
fetch_universe.py — Descarga la lista completa de tickers de NYSE, NASDAQ y BYMA

Fuentes:
    - NASDAQ: https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
    - NYSE/AMEX: https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt
    - BYMA: lista curada de Panel Líder + Panel General (sufijo .BA para Yahoo Finance)

Uso:
    python scripts/fetch_universe.py               # descarga y guarda en data/universe.txt
    python scripts/fetch_universe.py --dry-run      # muestra resumen sin guardar
    python scripts/fetch_universe.py --stats         # muestra estadísticas del archivo existente
"""

import argparse
import os
import sys
import requests
from pathlib import Path

# ── Rutas ────────────────────────────────────────────────────────────────────

ROOT_DIR     = Path(__file__).resolve().parent.parent
OUTPUT_FILE  = ROOT_DIR / 'data' / 'universe.txt'

# ── Cabeceras HTTP ───────────────────────────────────────────────────────────

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
}

# ── BYMA tickers (Panel Líder + Panel General principales) ──────────────────
# Estos no están en nasdaqtrader.com — se mantienen como lista curada.
# Usamos sufijo .BA para Yahoo Finance.

BYMA_TICKERS = [
    # Panel Líder
    'ALUA.BA', 'BBAR.BA', 'BMA.BA', 'BYMA.BA', 'CEPU.BA', 'COME.BA',
    'CRES.BA', 'CVH.BA', 'EDN.BA', 'GGAL.BA', 'HARG.BA', 'LOMA.BA',
    'MIRG.BA', 'PAMP.BA', 'SUPV.BA', 'TECO2.BA', 'TGNO4.BA', 'TGSU2.BA',
    'TRAN.BA', 'TXAR.BA', 'VALO.BA', 'YPFD.BA',
    # Panel General (más líquidos)
    'AGRO.BA', 'AUSO.BA', 'BOLT.BA', 'BPAT.BA', 'CAPX.BA', 'CARC.BA',
    'CECO2.BA', 'CELU.BA', 'CGPA2.BA', 'CTIO.BA', 'DGCU2.BA', 'DOME.BA',
    'DYCA.BA', 'FERR.BA', 'FIPL.BA', 'GAMI.BA', 'GARO.BA', 'GCDI.BA',
    'GCLA.BA', 'GRIM.BA', 'HAVA.BA', 'INTR.BA', 'INVJ.BA', 'IRSA.BA',
    'LONG.BA', 'METR.BA', 'MOLA.BA', 'MOLI.BA', 'MORI.BA', 'MTR.BA',
    'NOTO.BA', 'PATA.BA', 'POLL.BA', 'RICH.BA', 'RIGO.BA', 'ROSE.BA',
    'SAMI.BA', 'SEMI.BA',
]


# ── Fetch NASDAQ-listed tickers ──────────────────────────────────────────────

def fetch_nasdaq_tickers() -> list[str]:
    """
    Descarga tickers listados en NASDAQ desde nasdaqtrader.com.
    Filtra: test issues, ETFs, y símbolos con caracteres especiales.
    """
    url = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt'
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f'  [ERROR] No se pudo descargar nasdaqlisted.txt: {e}')
        return []

    tickers = []
    lines = resp.text.strip().split('\n')

    for line in lines[1:]:  # skip header
        if line.startswith('File Creation Time'):
            continue
        parts = line.split('|')
        if len(parts) < 7:
            continue

        symbol       = parts[0].strip()
        test_issue   = parts[3].strip()
        etf          = parts[6].strip()

        # Filtrar test issues y ETFs
        if test_issue == 'Y':
            continue
        if etf == 'Y':
            continue

        # Solo símbolos alfanuméricos (excluir warrants, units, etc.)
        if not symbol or not symbol.replace('.', '').isalnum():
            continue
        # Excluir símbolos con dígitos que indican clases especiales (ZXYZ1, etc.)
        # pero permitir BRK.A, BRK.B style
        if '$' in symbol or ' ' in symbol:
            continue

        tickers.append(symbol)

    return tickers


# ── Fetch NYSE/AMEX/ARCA tickers ────────────────────────────────────────────

def fetch_other_tickers() -> list[str]:
    """
    Descarga tickers listados en NYSE, AMEX, NYSE Arca desde nasdaqtrader.com.
    Filtra: test issues, ETFs, y símbolos con caracteres especiales.
    """
    url = 'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt'
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f'  [ERROR] No se pudo descargar otherlisted.txt: {e}')
        return []

    tickers = []
    lines = resp.text.strip().split('\n')

    for line in lines[1:]:  # skip header
        if line.startswith('File Creation Time'):
            continue
        parts = line.split('|')
        if len(parts) < 7:
            continue

        symbol     = parts[0].strip()  # ACT Symbol
        exchange   = parts[2].strip()   # N=NYSE, A=AMEX, P=ARCA, Z=BATS, V=IEXG
        etf        = parts[4].strip()
        test_issue = parts[6].strip()

        # Filtrar test issues y ETFs
        if test_issue == 'Y':
            continue
        if etf == 'Y':
            continue

        # Solo NYSE (N), AMEX (A), NYSE Arca (P)
        if exchange not in ('N', 'A', 'P'):
            continue

        # Solo símbolos limpios
        if not symbol or not symbol.replace('.', '').replace('-', '').isalnum():
            continue
        if '$' in symbol or ' ' in symbol:
            continue

        tickers.append(symbol)

    return tickers


# ── Merge y limpieza ─────────────────────────────────────────────────────────

def build_universe(include_byma: bool = True) -> tuple[list[str], dict]:
    """
    Construye el universo completo: NASDAQ + NYSE/AMEX + BYMA.
    Retorna (lista ordenada de tickers, stats dict).
    """
    print('  Descargando NASDAQ tickers...')
    nasdaq = fetch_nasdaq_tickers()
    print(f'    -> {len(nasdaq)} tickers NASDAQ')

    print('  Descargando NYSE/AMEX tickers...')
    other = fetch_other_tickers()
    print(f'    -> {len(other)} tickers NYSE/AMEX/ARCA')

    byma = list(BYMA_TICKERS) if include_byma else []
    print(f'  BYMA tickers: {len(byma)} (curados)')

    # Merge sin duplicados
    all_tickers = sorted(set(nasdaq) | set(other) | set(byma))

    stats = {
        'nasdaq':  len(nasdaq),
        'nyse':    len(other),
        'byma':    len(byma),
        'total':   len(all_tickers),
    }

    return all_tickers, stats


def save_universe(tickers: list[str]) -> None:
    """Guarda la lista de tickers en data/universe.txt, uno por línea."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('# trading-assist universe — generado por scripts/fetch_universe.py\n')
        f.write(f'# Total: {len(tickers)} tickers\n')
        f.write('# Fuentes: NASDAQ + NYSE/AMEX + BYMA\n')
        f.write('#\n')
        for t in tickers:
            f.write(t + '\n')
    print(f'\n  Guardado en {OUTPUT_FILE} ({len(tickers)} tickers)')


def load_existing() -> list[str]:
    """Carga la lista existente de universe.txt."""
    if not OUTPUT_FILE.exists():
        return []
    tickers = []
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            tickers.append(line)
    return tickers


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Descarga lista completa de tickers NYSE + NASDAQ + BYMA'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Muestra resumen sin guardar')
    parser.add_argument('--stats', action='store_true',
                        help='Muestra estadísticas del archivo existente')
    parser.add_argument('--no-byma', action='store_true',
                        help='Excluir tickers BYMA')
    args = parser.parse_args()

    if args.stats:
        existing = load_existing()
        if not existing:
            print('No hay archivo universe.txt existente.')
            return
        us = [t for t in existing if not t.endswith('.BA')]
        ar = [t for t in existing if t.endswith('.BA')]
        print(f'\n  universe.txt: {len(existing)} tickers')
        print(f'    US (NYSE+NASDAQ): {len(us)}')
        print(f'    BYMA (.BA):       {len(ar)}')
        return

    print()
    print('=' * 60)
    print('  fetch_universe — descargando lista completa de tickers')
    print('=' * 60)
    print()

    tickers, stats = build_universe(include_byma=not args.no_byma)

    print()
    print(f'  RESUMEN:')
    print(f'    NASDAQ:       {stats["nasdaq"]:>6,}')
    print(f'    NYSE/AMEX:    {stats["nyse"]:>6,}')
    print(f'    BYMA:         {stats["byma"]:>6,}')
    print(f'    Total único:  {stats["total"]:>6,}')

    if args.dry_run:
        print('\n  [DRY RUN] No se guardó ningún archivo.')
        # Mostrar muestra
        print(f'\n  Primeros 20: {", ".join(tickers[:20])}')
        print(f'  Últimos  20: {", ".join(tickers[-20:])}')
        return

    save_universe(tickers)
    print('\n  [OK] Listo. Ahora ejecutá:')
    print('    python scripts/load_history.py          # carga diaria completa')
    print('    python scripts/backfill_history.py      # backfill multi-timeframe')
    print()


if __name__ == '__main__':
    main()
