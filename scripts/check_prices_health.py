"""
check_prices_health.py — Verifica si las tablas de precios están actualizadas.

Uso:
    python scripts/check_prices_health.py              # resumen rápido
    python scripts/check_prices_health.py --detail      # detalle por tabla y timeframe
    python scripts/check_prices_health.py --symbols AAPL GOOGL PLTR  # solo estos

Exit codes:
    0 = todo actualizado (≤1 día hábil de atraso)
    1 = atraso detectado (≥2 días hábiles)
    2 = error de conexión
"""

import argparse
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn


def _biz_days_behind(last_date, today):
    if not last_date:
        return 999
    count = 0
    d = last_date + timedelta(days=1)
    while d <= today:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def check(detail=False, symbols=None):
    today = date.today()
    issues = []

    try:
        conn = get_conn()
    except Exception as e:
        print(f'[ERROR] No se pudo conectar a la DB: {e}')
        return 2

    try:
        with conn.cursor() as cur:
            print(f'=== Price Health Check — {today} ===\n')

            # 1. Tablas principales: max fecha global
            tables = [
                ('price_history', 'Precios diarios (universo)', 'simbolo'),
                ('market_index', 'Índice de mercado (SPY)', 'simbolo'),
                ('valorhistoricoaccion', 'Frontend (API legacy)', 'accion_id'),
            ]
            for table, desc, sym_col in tables:
                cur.execute(f"SELECT MAX(fecha) AS mx, COUNT(DISTINCT {sym_col}) AS nsym FROM {table}")
                row = cur.fetchone()
                mx = row['mx']
                nsym = row['nsym'] or 0
                behind = _biz_days_behind(mx, today)
                status = 'OK' if behind <= 1 else f'ATRASO {behind}d'
                if behind > 1:
                    issues.append(f'{table}: {mx} ({behind} días hábiles atrás)')
                print(f'  {desc:40s}  última={mx}  símbolos={nsym:>5d}  [{status}]')

            print()

            # 2. ohlcv_extended por timeframe
            for tf in ['D', 'W', 'M']:
                cur.execute(
                    "SELECT MAX(fecha) AS mx, COUNT(DISTINCT simbolo) AS nsym "
                    "FROM ohlcv_extended WHERE timeframe = %s", (tf,)
                )
                row = cur.fetchone()
                mx = row['mx']
                nsym = row['nsym'] or 0
                behind = _biz_days_behind(mx, today) if tf == 'D' else 0
                status = 'OK' if behind <= 1 else f'ATRASO {behind}d'
                if tf == 'D' and behind > 1:
                    issues.append(f'ohlcv_extended/{tf}: {mx} ({behind} días hábiles atrás)')
                print(f'  ohlcv_extended/{tf:1s}                         última={mx}  símbolos={nsym:>5d}  [{status}]')

            print()

            # 3. Sync check: price_history vs valorhistoricoaccion
            cur.execute("SELECT MAX(fecha) AS mx FROM price_history")
            ph_mx = cur.fetchone()['mx']
            cur.execute("SELECT MAX(fecha) AS mx FROM valorhistoricoaccion")
            vh_mx = cur.fetchone()['mx']
            if ph_mx and vh_mx:
                if vh_mx < ph_mx:
                    delta = (ph_mx - vh_mx).days
                    issues.append(f'valorhistoricoaccion ({vh_mx}) atrás de price_history ({ph_mx}) por {delta}d')
                    print(f'  SYNC: valorhistoricoaccion DESINCRONIZADA ({vh_mx} vs {ph_mx})')
                else:
                    print(f'  SYNC: OK (ambas hasta {ph_mx})')

            # 4. Detalle por símbolo si se pide
            if detail or symbols:
                print()
                target = symbols or ['SPY', 'AAPL', 'GOOGL', 'PLTR', 'NVDA', 'MSFT', 'TSLA', 'META', 'AMZN', 'NU']
                print(f'  {"Símbolo":<10s} {"price_history":>15s} {"ohlcv_ext/D":>15s} {"ohlcv_ext/W":>15s} {"valorhist":>15s}')
                print(f'  {"-"*10:<10s} {"-"*15:>15s} {"-"*15:>15s} {"-"*15:>15s} {"-"*15:>15s}')

                for sym in target:
                    cur.execute("SELECT MAX(fecha) AS mx FROM price_history WHERE simbolo = %s", (sym,))
                    ph = cur.fetchone()['mx']

                    cur.execute(
                        "SELECT MAX(fecha) AS mx FROM ohlcv_extended WHERE simbolo = %s AND timeframe = 'D'",
                        (sym,)
                    )
                    od = cur.fetchone()['mx']

                    cur.execute(
                        "SELECT MAX(fecha) AS mx FROM ohlcv_extended WHERE simbolo = %s AND timeframe = 'W'",
                        (sym,)
                    )
                    ow = cur.fetchone()['mx']

                    cur.execute(
                        """SELECT MAX(v.fecha) AS mx
                           FROM valorhistoricoaccion v
                           JOIN accion a ON a.id = v.accion_id
                           WHERE a.simbolo = %s""",
                        (sym,)
                    )
                    vh = cur.fetchone()['mx']

                    print(f'  {sym:<10s} {str(ph or "-"):>15s} {str(od or "-"):>15s} {str(ow or "-"):>15s} {str(vh or "-"):>15s}')

            # 5. Último batch_run exitoso de update
            print()
            try:
                cur.execute("""
                    SELECT started_at, finished_at, status
                    FROM batch_run
                    WHERE batch_name IN ('closing', 'opening')
                    ORDER BY id DESC LIMIT 3
                """)
                runs = cur.fetchall()
                if runs:
                    print('  Últimos batch_run:')
                    for r in runs:
                        print(f'    {r["started_at"]}  {r["status"]:>6s}  (fin: {r["finished_at"]})')
            except Exception:
                pass

    finally:
        conn.close()

    print()
    if issues:
        print(f'RESULTADO: {len(issues)} PROBLEMAS')
        for issue in issues:
            print(f'  - {issue}')
        return 1
    else:
        print('RESULTADO: TODO ACTUALIZADO')
        return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Verificar estado de tablas de precios')
    parser.add_argument('--detail', action='store_true', help='Mostrar detalle por símbolo')
    parser.add_argument('--symbols', nargs='+', default=None, help='Verificar estos símbolos')
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else None
    code = check(detail=args.detail, symbols=symbols)
    sys.exit(code)
