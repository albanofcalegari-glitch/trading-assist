"""
init_db.py — crea base de datos y tablas
Ejecutar una sola vez al iniciar el proyecto.

Uso:
    python scripts/init_db.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pymysql
from config import MYSQL_CONFIG, SECTOR_MAP, UNIVERSE


SECTOR_NAMES = {
    'XLK': 'Technology',
    'XLC': 'Communication Services',
    'XLF': 'Financials',
    'XLY': 'Consumer Discretionary',
    'XLE': 'Energy',
}

ASSET_INFO = {
    'NVDA':  ('NVIDIA Corporation',          'Technology',             'Semiconductors',        'XLK'),
    'MSFT':  ('Microsoft Corporation',       'Technology',             'Software—Infrastructure','XLK'),
    'GOOGL': ('Alphabet Inc.',               'Communication Services', 'Internet Content',      'XLC'),
    'AAPL':  ('Apple Inc.',                  'Technology',             'Consumer Electronics',  'XLK'),
    'MELI':  ('MercadoLibre Inc.',           'Consumer Discretionary', 'Internet Retail',       'XLY'),
    'VIST':  ('Vista Energy S.A.B. de C.V.', 'Energy',                 'Oil & Gas E&P',         'XLE'),
    'JPM':   ('JPMorgan Chase & Co.',        'Financials',             'Banks—Diversified',     'XLF'),
    'DIS':   ('The Walt Disney Company',     'Communication Services', 'Entertainment',         'XLC'),
    'PYPL':  ('PayPal Holdings Inc.',        'Financials',             'Credit Services',       'XLF'),
    'NU':    ('Nu Holdings Ltd.',            'Financials',             'Credit Services',       'XLF'),
}


def create_database(root_config: dict) -> None:
    """Crea la base de datos si no existe."""
    cfg = {k: v for k, v in root_config.items() if k != 'db'}
    cfg.pop('cursorclass', None)
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS trading_assist "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        print("[OK] Base de datos 'trading_assist' lista")
    finally:
        conn.close()


def run_schema(conn) -> None:
    """Ejecuta el DDL desde schema.sql."""
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'schema.sql')
    with open(schema_path, encoding='utf-8') as f:
        raw = f.read()

    # Eliminar comentarios de línea, luego split por ';'
    lines_cleaned = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        lines_cleaned.append(line)

    cleaned = '\n'.join(lines_cleaned)

    statements = [
        s.strip()
        for s in cleaned.split(';')
        if s.strip()
    ]

    # Filtrar CREATE DATABASE y USE — ya ejecutados
    skip_prefixes = ('CREATE DATABASE', 'USE ')
    statements = [
        s for s in statements
        if not any(s.upper().startswith(p) for p in skip_prefixes)
    ]

    with conn.cursor() as cur:
        for stmt in statements:
            if stmt.strip():
                cur.execute(stmt)
    print(f"[OK] {len(statements)} tablas creadas/verificadas")


def seed_asset_master(conn) -> None:
    """Inserta los activos del universo en asset_master."""
    sql = """
        INSERT INTO asset_master (simbolo, nombre, sector, industria, benchmark_sector, activo)
        VALUES (%s, %s, %s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            nombre=VALUES(nombre), sector=VALUES(sector),
            industria=VALUES(industria), benchmark_sector=VALUES(benchmark_sector)
    """
    rows = [
        (sym, *info)
        for sym, info in ASSET_INFO.items()
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    print(f"[OK] {len(rows)} activos en asset_master")


def main():
    from config import MYSQL_CONFIG
    from db.connection import get_conn

    print("\n=== init_db — trading-assist ===\n")

    # 1. Crear DB (sin conectarse a ella todavía)
    create_database(MYSQL_CONFIG)

    # 2. Crear tablas
    conn = get_conn(autocommit=True)
    try:
        run_schema(conn)
        seed_asset_master(conn)
    finally:
        conn.close()

    print("\n[OK] Init completado. Ya podés correr scripts/load_history.py\n")


if __name__ == '__main__':
    main()
