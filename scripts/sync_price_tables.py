"""
sync_price_tables.py — Sincroniza price_history -> valorhistoricoaccion

price_history se actualiza diariamente via cron (update_prices_cron.py).
valorhistoricoaccion es la tabla que usa la API del frontend.
Este script copia los datos nuevos de una a otra.

Uso:
    python scripts/sync_price_tables.py          # sync incremental
    python scripts/sync_price_tables.py --full    # rebuild completo (lento)

Diseñado para correr como cron después del update de precios.
"""

import argparse
import sys
import os
from datetime import date, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db.connection import get_conn


def log(msg):
    from datetime import datetime
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def sync(full=False):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Build symbol -> accion_id map (USA markets only: NASDAQ, NYSE, NYSE_AMERICAN, NYSE_ARCA, CBOE_BZX)
            cur.execute("""
                SELECT a.id AS accion_id, a.simbolo
                FROM accion a
                JOIN mercado m ON m.id = a.mercado_id
                WHERE m.descripcion IN ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')
            """)
            sym_to_id = {}
            for r in cur.fetchall():
                sym_to_id[r['simbolo']] = r['accion_id']

            log(f"Mapa simbolo->accion_id: {len(sym_to_id)} simbolos USA")

            if full:
                # Full rebuild: truncate and re-insert everything
                log("Modo FULL: sincronizando todo price_history -> valorhistoricoaccion")
                since = date(2020, 1, 1)
            else:
                # Incremental: only sync from the last date in valorhistoricoaccion
                cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion")
                last = cur.fetchone()['f']
                if last:
                    since = last - timedelta(days=1)  # overlap 1 day for safety
                else:
                    since = date(2020, 1, 1)
                log(f"Modo incremental: sincronizando desde {since}")

            # Get new data from price_history
            cur.execute("""
                SELECT simbolo, fecha, open, high, low, close, volume
                FROM price_history
                WHERE fecha >= %s
                ORDER BY simbolo, fecha
            """, (since,))
            rows = cur.fetchall()
            log(f"Filas a sincronizar: {len(rows)}")

            inserted = 0
            updated = 0
            skipped = 0

            for r in rows:
                accion_id = sym_to_id.get(r['simbolo'])
                if not accion_id:
                    skipped += 1
                    continue

                cur.execute("""
                    INSERT INTO valorhistoricoaccion
                        (accion_id, fecha, precio_apertura, precio_max, precio_min, precio_cierre, volumen)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        precio_apertura = VALUES(precio_apertura),
                        precio_max = VALUES(precio_max),
                        precio_min = VALUES(precio_min),
                        precio_cierre = VALUES(precio_cierre),
                        volumen = VALUES(volumen)
                """, (accion_id, r['fecha'], r['open'], r['high'], r['low'], r['close'], r['volume']))

                if cur.rowcount == 1:
                    inserted += 1
                elif cur.rowcount == 2:
                    updated += 1

            conn.commit()
            log(f"Sync OK: {inserted} insertadas, {updated} actualizadas, {skipped} sin accion_id")

            # Verify
            cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion")
            new_max = cur.fetchone()['f']
            cur.execute("SELECT MAX(fecha) AS f FROM price_history")
            ph_max = cur.fetchone()['f']
            log(f"valorhistoricoaccion ahora hasta: {new_max} (price_history: {ph_max})")

            if new_max == ph_max:
                log("OK - tablas sincronizadas")
            else:
                log(f"ATENCION: diferencia de fechas ({new_max} vs {ph_max})")

    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true', help='Rebuild completo')
    args = parser.parse_args()
    sync(full=args.full)
