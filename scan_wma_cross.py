"""
scan_wma_cross.py — Escanea el universo buscando:
  1. BUY_EARLY_SWING : WMA6 por cruzar WMA30 (brecha < 0.5%, cerrándose, pendiente alcista)
  2. BUY_SWING_RECENT: WMA6 cruzó WMA30 hace <= CROSS_LOOKBACK barras

Uso:
  python scan_wma_cross.py                    -> USA + BYMA, top 40
  python scan_wma_cross.py --market USA       -> solo USA
  python scan_wma_cross.py --market BYMA      -> solo BYMA
  python scan_wma_cross.py --trend            -> solo alcistas (precio > SMA200)
"""
import sys, os, argparse, datetime, time
sys.path.insert(0, os.path.dirname(__file__))
import pymysql
import numpy as np
import pandas as pd

MYSQL_CONFIG = dict(
    host='localhost', user='root', password='123456', db='bolsa',
    charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)

GAP_THRESHOLD  = 0.005   # 0.5% — brecha máxima para BUY_EARLY
CROSS_LOOKBACK = 3       # barras recientes para considerar cruce "reciente"
MIN_BARS       = 35      # necesitamos >= 30 barras para WMA30 + 3 barras de look-back + margen
PRICE_MIN      = 1.0

_W6   = np.arange(1,  7, dtype=float); _W6S  = _W6.sum()   # 21
_W30  = np.arange(1, 31, dtype=float); _W30S = _W30.sum()  # 465


def _wma(closes: np.ndarray, n: int, offset: int = 0) -> float:
    """WMA(n) sobre closes[-(n+offset) : len-offset] (offset=0 = barra más reciente)."""
    end   = len(closes) - offset
    start = end - n
    if start < 0 or end <= 0:
        return np.nan
    x = closes[start:end]
    w = np.arange(1, n + 1, dtype=float)
    return float(np.dot(x, w) / w.sum())


def scan(market_filter: str | None = None, top_n: int = 50) -> pd.DataFrame:
    conn = pymysql.connect(**MYSQL_CONFIG)
    results = []

    try:
        with conn.cursor() as cur:

            # Última fecha por mercado (BYMA puede ser distinta a USA)
            if market_filter == 'BYMA':
                cur.execute("""
                    SELECT MAX(v.fecha) AS f
                    FROM valorhistoricoaccion v
                    JOIN accion a ON a.id = v.accion_id
                    JOIN mercado m ON m.id = a.mercado_id
                    WHERE m.descripcion = 'BYMA'
                """)
            else:
                cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion")
            last_date = cur.fetchone()['f']
            print(f"  Fecha de referencia : {last_date}")

            # Filtro de mercado
            if market_filter == 'USA':
                mkt_clause = "AND m.descripcion IN ('NASDAQ','NYSE','NYSE_AMERICAN','NYSE_ARCA','CBOE_BZX')"
            elif market_filter == 'BYMA':
                mkt_clause = "AND m.descripcion = 'BYMA'"
            else:
                mkt_clause = ""

            # Activos con datos en la última sesión
            cur.execute(f"""
                SELECT v.accion_id, a.simbolo, a.nombre, m.descripcion AS mercado
                FROM valorhistoricoaccion v
                JOIN accion a ON a.id = v.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE v.fecha = %s AND v.precio_cierre >= %s {mkt_clause}
            """, [last_date, PRICE_MIN])
            active = {r['accion_id']: r for r in cur.fetchall()}
            print(f"  Stocks activos      : {len(active)}")

            # Precio histórico — últimos ~55 días calendario (cubre >=35 barras de trading)
            cutoff = last_date - datetime.timedelta(days=55)
            print("  Cargando precios...")
            cur.execute(f"""
                SELECT v.accion_id, v.fecha,
                       v.precio_cierre  AS close,
                       it.dist_sma200_pct
                FROM valorhistoricoaccion v
                LEFT JOIN indicadortecnico it
                       ON it.accion_id = v.accion_id AND it.fecha = v.fecha
                JOIN accion a ON a.id = v.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE v.fecha >= %s
                  AND v.precio_cierre >= %s
                  {mkt_clause}
                ORDER BY v.accion_id, v.fecha
            """, [cutoff, PRICE_MIN])
            rows = cur.fetchall()

    finally:
        conn.close()

    if not rows:
        print("  Sin datos.")
        return pd.DataFrame()

    df_all = pd.DataFrame(rows)
    print(f"  Filas cargadas      : {len(df_all)}")
    print("  Calculando WMA6/WMA30...")

    t0 = time.time()
    for accion_id, grp in df_all.groupby('accion_id'):
        if accion_id not in active:
            continue
        grp = grp.sort_values('fecha').reset_index(drop=True)
        if len(grp) < MIN_BARS:
            continue

        closes = grp['close'].astype(float).values

        # WMA6 y WMA30 para las últimas CROSS_LOOKBACK+1 barras
        # offset=0 → barra actual, offset=k → k barras atrás
        w6  = [_wma(closes, 6,  k) for k in range(CROSS_LOOKBACK + 1)]
        w30 = [_wma(closes, 30, k) for k in range(CROSS_LOOKBACK + 1)]

        if any(np.isnan(x) for x in w6 + w30):
            continue

        price     = closes[-1]
        price_pre = closes[-2] if len(closes) > 1 else price

        # Tendencia: dist_sma200_pct del último bar
        try:
            dist200  = float(grp['dist_sma200_pct'].iloc[-1])
            trend_up = dist200 >= 0
        except (TypeError, ValueError):
            trend_up = False

        info = active[accion_id]

        # ── Cruce reciente: WMA6 cruzó WMA30 hacia arriba en los últimos k barras ──
        # offset=0 es el bar más reciente; offset=1 es 1 barra atrás, etc.
        # Cruce en barra N-k: w6[k] > w30[k]  y  w6[k+1] < w30[k+1]
        cross_bar = None
        for k in range(CROSS_LOOKBACK):
            if w6[k] > w30[k] and w6[k + 1] < w30[k + 1]:
                cross_bar = k   # 0 = cruzó hoy, 1 = ayer, etc.
                break

        if cross_bar is not None:
            results.append({
                'tipo':       'BUY_SWING_RECENT',
                'simbolo':    info['simbolo'],
                'nombre':     info['nombre'][:40],
                'mercado':    info['mercado'],
                'precio':     round(price, 2),
                'wma6':       round(w6[0], 4),
                'wma30':      round(w30[0], 4),
                'gap_pct':    round((w6[0] - w30[0]) / max(w30[0], 1e-9) * 100, 3),
                'barras':     cross_bar,
                'tendencia':  'SI' if trend_up else 'NO',
            })
            continue

        # ── BUY_EARLY_SWING: WMA6 < WMA30, brecha cerrándose ─────────────────
        gap_now  = (w30[0] - w6[0]) / max(w30[0], 1e-9)
        gap_prev = (w30[1] - w6[1]) / max(w30[1], 1e-9)

        if (w6[0] < w30[0]            # no cruzó aún
                and gap_now  < GAP_THRESHOLD   # brecha < 0.5%
                and gap_now  < gap_prev        # brecha cerrándose
                and w6[0]    > w6[1]           # WMA6 pendiente alcista
                and price    >= price_pre):    # precio confirma

            results.append({
                'tipo':       'BUY_EARLY_SWING',
                'simbolo':    info['simbolo'],
                'nombre':     info['nombre'][:40],
                'mercado':    info['mercado'],
                'precio':     round(price, 2),
                'wma6':       round(w6[0], 4),
                'wma30':      round(w30[0], 4),
                'gap_pct':    round(gap_now * 100, 3),
                'barras':     0,
                'tendencia':  'SI' if trend_up else 'NO',
            })

    t1 = time.time()
    print(f"  Tiempo calculo      : {t1 - t0:.1f}s")
    print(f"  Candidatos          : {len(results)}")

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    # Ordenar: cruces recientes primero (barras asc), luego early (gap asc)
    out['_s'] = out.apply(
        lambda r: (0 if r['tipo'] == 'BUY_SWING_RECENT' else 1,
                   r['barras'], abs(r['gap_pct'])), axis=1)
    return (out.sort_values('_s').drop(columns='_s')
              .reset_index(drop=True).head(top_n))


# ─────────────────────────────────────────────────────────────────────────────
def _print_results(df: pd.DataFrame) -> None:
    if df.empty:
        print("\n  Sin resultados.\n")
        return

    recent = df[df['tipo'] == 'BUY_SWING_RECENT']
    early  = df[df['tipo'] == 'BUY_EARLY_SWING']

    HDR_R = f"  {'SIMBOLO':<10} {'MERCADO':<14} {'PRECIO':>8} {'WMA6':>9} " \
            f"{'WMA30':>9} {'GAP%':>7} {'BARRAS':>7} {'TEND':>5}  NOMBRE"
    HDR_E = f"  {'SIMBOLO':<10} {'MERCADO':<14} {'PRECIO':>8} {'WMA6':>9} " \
            f"{'WMA30':>9} {'GAP%':>7} {'TEND':>5}  NOMBRE"
    SEP   = "  " + "-" * 100

    if not recent.empty:
        print(f"\n{'='*72}")
        print(f"  BUY_SWING_RECENT — cruzaron hace <=3 barras  ({len(recent)} casos)")
        print(f"{'='*72}")
        print(HDR_R); print(SEP)
        for _, r in recent.iterrows():
            print(f"  {r['simbolo']:<10} {r['mercado']:<14} {r['precio']:>8.2f} "
                  f"{r['wma6']:>9.4f} {r['wma30']:>9.4f} {r['gap_pct']:>7.3f} "
                  f"{r['barras']:>7}    {r['tendencia']:>4}  {r['nombre']}")

    if not early.empty:
        print(f"\n{'='*72}")
        print(f"  BUY_EARLY_SWING — por cruzar  ({len(early)} casos)")
        print(f"{'='*72}")
        print(HDR_E); print(SEP)
        for _, r in early.sort_values('gap_pct').iterrows():
            print(f"  {r['simbolo']:<10} {r['mercado']:<14} {r['precio']:>8.2f} "
                  f"{r['wma6']:>9.4f} {r['wma30']:>9.4f} {r['gap_pct']:>7.3f} "
                  f"  {r['tendencia']:>4}  {r['nombre']}")

    print(f"\n  Total: {len(recent)} cruces recientes + {len(early)} por cruzar\n")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--market', choices=['USA', 'BYMA', 'ALL'], default='ALL')
    p.add_argument('--top',    type=int, default=40)
    p.add_argument('--trend',  action='store_true', help='Solo tendencia alcista (precio > SMA200)')
    args = p.parse_args()

    mkt = None if args.market == 'ALL' else args.market
    print(f"\n=== Scan WMA6/WMA30 crossover | mercado={args.market} ===\n")

    df = scan(market_filter=mkt, top_n=args.top * 3)

    if args.trend and not df.empty:
        df = df[df['tendencia'] == 'SI'].head(args.top)

    _print_results(df)
