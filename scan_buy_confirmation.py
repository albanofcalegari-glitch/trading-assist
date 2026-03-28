"""
scan_buy_confirmation.py
─────────────────────────────────────────────────────────────────────────────
Escanea TODOS los activos activos en la BD y detecta cuáles cumplen la
condición BUY_CONFIRMATION (cruce WMA21/SMA30 + confirmación RSI).

Uso:
    python scan_buy_confirmation.py                 # todos los mercados
    python scan_buy_confirmation.py --market BYMA   # solo BYMA/CEDEARs
    python scan_buy_confirmation.py --market USA    # solo mercados US
    python scan_buy_confirmation.py --days 120      # más historia (default 90)
    python scan_buy_confirmation.py --only-fuerte   # solo señales FUERTE
"""
import sys, os, argparse, time
# Forzar UTF-8 en Windows para evitar UnicodeEncodeError en cp1252
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

import pymysql
import pandas as pd

import charts as ch

# ── Config BD (misma que queries.py) ─────────────────────────────────────────
BOLSA_CFG = dict(
    host='localhost', user='root', password='123456', db='bolsa',
    charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)

USA_MARKETS = ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')


def _conn():
    return pymysql.connect(**BOLSA_CFG)


# ── Fetch masivo ──────────────────────────────────────────────────────────────

def fetch_bulk(days: int, market: str | None) -> pd.DataFrame:
    """
    Una sola query: últimos `days` días de precios + RSI para todos los
    activos activos (precio_cierre > 0.5, datos en los últimos 7 días).
    Retorna DataFrame con columnas:
      accion_id, simbolo, nombre, mercado, fecha,
      open, high, low, close, volume, rsi14
    """
    if market == 'USA':
        ph       = ','.join(['%s'] * len(USA_MARKETS))
        m_clause = f"AND m.descripcion IN ({ph})"
        m_params = list(USA_MARKETS)
    elif market:
        m_clause = "AND m.descripcion = %s"
        m_params = [market]
    else:
        m_clause = ""
        m_params = []

    # Activos "activos": tienen dato en los últimos 7 días
    active_subq = """
        SELECT DISTINCT accion_id
        FROM valorhistoricoaccion
        WHERE fecha >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
          AND precio_cierre > 0.5
    """

    sql = f"""
        SELECT
            v.accion_id,
            a.simbolo,
            a.nombre,
            m.descripcion  AS mercado,
            v.fecha,
            v.precio_apertura  AS open,
            v.precio_max       AS high,
            v.precio_min       AS low,
            v.precio_cierre    AS close,
            v.volumen          AS volume,
            it.rsi14
        FROM valorhistoricoaccion v
        JOIN accion  a ON a.id = v.accion_id
        JOIN mercado m ON m.id = a.mercado_id
        LEFT JOIN indicadortecnico it
               ON it.accion_id = v.accion_id AND it.fecha = v.fecha
        WHERE v.accion_id IN ({active_subq})
          AND v.fecha >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
          AND v.precio_cierre > 0.5
          {m_clause}
        ORDER BY v.accion_id, v.fecha
    """
    params = [days] + m_params

    print(f"  Descargando datos ({days} días)...", end=' ', flush=True)
    t0 = time.time()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    print(f"{len(rows):,} filas en {time.time()-t0:.1f}s")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in ['open', 'high', 'low', 'close', 'volume', 'rsi14']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['fecha'] = df['fecha'].astype(str)
    return df


# ── Procesar un activo ────────────────────────────────────────────────────────

def process_asset(grp: pd.DataFrame) -> dict | None:
    """
    Recibe el sub-DataFrame de un activo (ya ordenado por fecha).
    Computa EMA20/SMA200 → S/R estático + dinámico → BUY_CONFIRMATION.
    Retorna dict con resultado o None si no hay señal.
    """
    grp = grp.reset_index(drop=True)

    # Mínimo de datos para WMA21 + SMA30
    if len(grp) < 30:
        return None

    # Calcular MAs adicionales (necesarias para get_dynamic_sr)
    grp['ema20']  = grp['close'].ewm(span=20, adjust=False).mean()
    grp['sma50']  = grp['close'].rolling(50).mean()
    grp['sma200'] = grp['close'].rolling(200, min_periods=80).mean()

    # S/R estático + dinámico
    sup, _res    = ch.get_support_resistance(grp)
    dyn_sup, _dr = ch.get_dynamic_sr(grp)

    # BUY_CONFIRMATION
    conf = ch.get_buy_confirmation(grp, sup, dyn_sup)

    if not conf['signals']:
        return None

    # Extraer info del activo (primera fila)
    meta = grp.iloc[0]
    last = grp.iloc[-1]

    return {
        'simbolo':       meta['simbolo'],
        'nombre':        (meta.get('nombre') or '')[:40],
        'mercado':       meta['mercado'],
        'precio':        float(last['close']),
        'activo':        conf['activo'],
        'fuerza':        conf['fuerza'],
        'motivo':        ' | '.join(conf['motivo']),
        'fecha_signal':  conf['fecha'],
        'cerca_soporte': conf['cerca_soporte'],
        'n_signals':     len(conf['signals']),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Escanea BUY_CONFIRMATION en todos los activos')
    parser.add_argument('--market',      default=None,  help='BYMA | USA | NASDAQ | NYSE | … (default: todos)')
    parser.add_argument('--cedear',      action='store_true',  help='Alias rápido para --market BYMA')
    parser.add_argument('--days',        type=int, default=90, help='Días de historia (default: 90)')
    parser.add_argument('--only-fuerte', action='store_true',  help='Mostrar solo señales FUERTE')
    parser.add_argument('--only-active', action='store_true',  help='Mostrar solo señales activas (WMA>SMA)')
    args = parser.parse_args()

    if args.cedear:
        args.market = 'BYMA'

    print()
    print('=' * 70)
    print('  SCAN BUY_CONFIRMATION')
    print(f'  Mercado: {args.market or "Todos"}  |  Historia: {args.days} días')
    print('=' * 70)

    # 1. Bulk fetch
    df_all = fetch_bulk(args.days, args.market)
    if df_all.empty:
        print("Sin datos.")
        return

    activos = df_all['accion_id'].nunique()
    print(f"  Activos a procesar: {activos:,}")

    # 2. Procesar por activo
    t0 = time.time()
    results = []
    errores = 0

    groups = df_all.groupby('accion_id', sort=False)
    for i, (aid, grp) in enumerate(groups, 1):
        if i % 100 == 0 or i == activos:
            pct = i / activos * 100
            print(f"\r  Procesando {i:>4}/{activos}  ({pct:.0f}%)  señales: {len(results)}", end='', flush=True)
        try:
            r = process_asset(grp)
            if r:
                results.append(r)
        except Exception as e:
            errores += 1

    elapsed = time.time() - t0
    print(f"\r  Procesando {activos}/{activos}  (100%)  señales: {len(results)}  — {elapsed:.1f}s")

    if errores:
        print(f"  Errores (ignorados): {errores}")

    if not results:
        print("\n  No se encontraron señales BUY_CONFIRMATION.")
        return

    # 3. Filtros opcionales
    if args.only_active:
        results = [r for r in results if r['activo']]
    if args.only_fuerte:
        results = [r for r in results if r['fuerza'] == 'FUERTE']

    # 4. Ordenar: activo + FUERTE primero, luego por fecha_señal desc
    def _date_neg(s):
        # Convierte 'YYYY-MM-DD' a entero negativo para ordenar descendente
        try:
            y, m, d = map(int, (s or '0000-01-01').split('-'))
            return -(y * 10000 + m * 100 + d)
        except Exception:
            return 0

    _fuerza_ord = {'FUERTE': 0, 'MEDIA': 1}
    results.sort(key=lambda r: (
        0 if r['activo'] else 1,
        _fuerza_ord.get(r['fuerza'] or '', 2),
        _date_neg(r['fecha_signal']),
    ))

    # 5. Imprimir tabla
    print()
    print('=' * 70)
    print(f"  RESULTADOS: {len(results)} senales encontradas")
    print('=' * 70)

    # Separar activas / inactivas
    activas   = [r for r in results if r['activo']]
    inactivas = [r for r in results if not r['activo']]

    def _print_section(title, rows):
        if not rows:
            return
        sep = '-' * (50 - min(len(title), 48))
        print(f"\n-- {title} ({len(rows)}) {sep}")
        print(f"  {'Simbolo':<8}  {'Mercado':<12}  {'Fuerza':<8}  {'Fecha':<12}  {'Motivo'}")
        print('  ' + '-' * 65)
        for r in rows:
            soporte_tag = '[S]' if r['cerca_soporte'] else '   '
            print(
                f"  {r['simbolo']:<8}  {r['mercado']:<12}  "
                f"{(r['fuerza'] or '-'):<8}  {(r['fecha_signal'] or '-'):<12}  "
                f"{soporte_tag}  {r['motivo']}"
            )

    _print_section("SENALES ACTIVAS  (WMA21 > SMA30 hoy)", activas)
    _print_section("Senales historicas (cruce ya revertido)", inactivas)

    # Resumen
    n_fuerte = sum(1 for r in results if r['fuerza'] == 'FUERTE')
    n_media  = sum(1 for r in results if r['fuerza'] == 'MEDIA')
    print()
    print('=' * 70)
    print(f"  Total: {len(results)}  |  Activas: {len(activas)}  |  "
          f"FUERTE: {n_fuerte}  |  MEDIA: {n_media}")
    print('=' * 70)
    print()


if __name__ == '__main__':
    main()
