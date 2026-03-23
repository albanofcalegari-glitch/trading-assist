"""
queries.py — Consultas contra la BD 'bolsa' para el dashboard trading-assist

FIX: pd.read_sql con DictCursor de PyMySQL retorna nombres de columna como datos.
     Todas las queries que retornan DataFrame usan cursor.fetchall() + pd.DataFrame().
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pymysql
import pandas as pd

BOLSA_CFG = dict(
    host='localhost', user='root', password='123456', db='bolsa',
    charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)

USA_MARKETS = ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')

# Prioridad de mercado para deduplicación: menor número = mayor prioridad (USA > BYMA)
_MARKET_PRIORITY = """
    CASE m.descripcion
        WHEN 'NASDAQ'        THEN 1
        WHEN 'NYSE'          THEN 2
        WHEN 'NYSE_AMERICAN' THEN 3
        WHEN 'NYSE_ARCA'     THEN 4
        WHEN 'CBOE_BZX'      THEN 5
        WHEN 'BYMA'          THEN 6
        ELSE                      7
    END
"""


def _conn():
    return pymysql.connect(**BOLSA_CFG)


def _last_two_dates(cur):
    cur.execute("SELECT MAX(fecha) FROM valorhistoricoaccion")
    last = cur.fetchone()['MAX(fecha)']
    cur.execute("SELECT MAX(fecha) FROM valorhistoricoaccion WHERE fecha < %s", [last])
    prev = cur.fetchone()['MAX(fecha)']
    return last, prev


# ── Top movers ────────────────────────────────────────────────────────────────

def get_top_movers(segment: str, direction: str, n: int = 5) -> list[dict]:
    if segment == 'BYMA':
        market_clause = "AND m.descripcion = 'BYMA'"
    else:
        placeholders  = ','.join(['%s'] * len(USA_MARKETS))
        market_clause = f"AND m.descripcion IN ({placeholders})"

    order = "DESC" if direction == 'up' else "ASC"

    with _conn() as conn:
        with conn.cursor() as cur:
            last, prev = _last_two_dates(cur)
            params = [last, prev]
            if segment != 'BYMA':
                params.extend(USA_MARKETS)
            params.append(n)

            cur.execute(f"""
                SELECT a.simbolo, a.nombre,
                       v1.precio_cierre AS precio,
                       ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2) AS pct_cambio
                FROM valorhistoricoaccion v1
                JOIN valorhistoricoaccion v2
                  ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                JOIN accion a ON a.id = v1.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE v1.fecha = %s
                  AND v1.precio_cierre > 0.5
                  AND v2.precio_cierre > 0.5
                  {market_clause}
                ORDER BY pct_cambio {order}
                LIMIT %s
            """, params)
            return cur.fetchall()


# ── Tabla de activos ──────────────────────────────────────────────────────────

def get_asset_table(
    market: str | None = None,
    search: str | None = None,
    page: int = 0,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """
    Deduplicación por símbolo:
      - market=None  ("Todos"): ROW_NUMBER() PARTITION BY simbolo → retiene solo la
        fila con mayor prioridad de mercado (NASDAQ/NYSE/... > BYMA). Un símbolo que
        exista en ambos mercados aparece UNA SOLA VEZ (versión USA).
      - market='USA': filtra directo por m.descripcion IN USA_MARKETS, sin dedup.
      - market='BYMA': filtra directo, sin dedup (muestra todas las especies locales).
      - market=otro valor: filtra por ese mercado exacto.
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            last, prev = _last_two_dates(cur)
            opt_search = [f"%{search}%", f"%{search}%"] if search else []
            s_clause   = "AND (a.simbolo LIKE %s OR a.nombre LIKE %s)" if search else ""

            # ── Modo "Todos": deduplicar por símbolo, prioridad USA > BYMA ──────
            if not market:
                base_params = [last, prev] + opt_search

                cur.execute(f"""
                    SELECT COUNT(*) AS n FROM (
                        SELECT a.simbolo,
                               ROW_NUMBER() OVER (
                                   PARTITION BY a.simbolo
                                   ORDER BY {_MARKET_PRIORITY}
                               ) AS _rn
                        FROM valorhistoricoaccion v1
                        JOIN valorhistoricoaccion v2
                          ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                        JOIN accion a ON a.id = v1.accion_id
                        JOIN mercado m ON m.id = a.mercado_id
                        WHERE v1.fecha = %s
                          AND v1.precio_cierre > 0.5
                          AND v2.precio_cierre > 0.5
                          {s_clause}
                    ) _sub WHERE _rn = 1
                """, base_params)
                total = cur.fetchone()['n']

                cur.execute(f"""
                    SELECT accion_id, simbolo, nombre, mercado, precio, pct_cambio
                    FROM (
                        SELECT a.id AS accion_id, a.simbolo, a.nombre,
                               m.descripcion AS mercado,
                               v1.precio_cierre AS precio,
                               ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2)
                                   AS pct_cambio,
                               ROW_NUMBER() OVER (
                                   PARTITION BY a.simbolo
                                   ORDER BY {_MARKET_PRIORITY}
                               ) AS _rn
                        FROM valorhistoricoaccion v1
                        JOIN valorhistoricoaccion v2
                          ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                        JOIN accion a ON a.id = v1.accion_id
                        JOIN mercado m ON m.id = a.mercado_id
                        WHERE v1.fecha = %s
                          AND v1.precio_cierre > 0.5
                          AND v2.precio_cierre > 0.5
                          {s_clause}
                    ) _sub
                    WHERE _rn = 1
                    ORDER BY ABS(pct_cambio) DESC, simbolo
                    LIMIT %s OFFSET %s
                """, base_params + [page_size, page * page_size])
                return cur.fetchall(), total

            # ── Modo con filtro explícito de mercado ──────────────────────────
            if market == 'USA':
                ph        = ','.join(['%s'] * len(USA_MARKETS))
                m_clause  = f"AND m.descripcion IN ({ph})"
                opt_market = list(USA_MARKETS)
            else:
                m_clause   = "AND m.descripcion = %s"
                opt_market = [market]

            base_params = [last, prev] + opt_market + opt_search

            cur.execute(f"""
                SELECT COUNT(*) AS n
                FROM valorhistoricoaccion v1
                JOIN valorhistoricoaccion v2
                  ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                JOIN accion a ON a.id = v1.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE v1.fecha = %s
                  AND v1.precio_cierre > 0.5
                  AND v2.precio_cierre > 0.5
                  {m_clause} {s_clause}
            """, [prev, last] + opt_market + opt_search)
            total = cur.fetchone()['n']

            cur.execute(f"""
                SELECT a.id AS accion_id, a.simbolo, a.nombre,
                       m.descripcion AS mercado,
                       v1.precio_cierre AS precio,
                       ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2) AS pct_cambio
                FROM valorhistoricoaccion v1
                JOIN valorhistoricoaccion v2
                  ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                JOIN accion a ON a.id = v1.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE v1.fecha = %s
                  AND v1.precio_cierre > 0.5
                  AND v2.precio_cierre > 0.5
                  {m_clause} {s_clause}
                ORDER BY ABS(v1.precio_cierre / v2.precio_cierre - 1) DESC, a.simbolo
                LIMIT %s OFFSET %s
            """, [prev, last] + opt_market + opt_search + [page_size, page * page_size])
            return cur.fetchall(), total


def get_available_markets() -> list[str]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT descripcion FROM mercado ORDER BY descripcion")
            return [r['descripcion'] for r in cur.fetchall()]


def get_accion_info(accion_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.simbolo, a.nombre,
                       m.descripcion AS mercado, a.sector_etf
                FROM accion a
                JOIN mercado m ON m.id = a.mercado_id
                WHERE a.id = %s
            """, [accion_id])
            return cur.fetchone()


# ── Detalle de activo ─────────────────────────────────────────────────────────

def get_asset_prices(accion_id: int, days: int = 400) -> pd.DataFrame:
    """
    OHLCV + SMA50. EMA20 y SMA200 calculados en Python.

    USA cursor.fetchall() + pd.DataFrame() en lugar de pd.read_sql()
    para evitar el bug de DictCursor que retorna nombres de columna como datos.
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT v.fecha,
                       v.precio_apertura AS open,
                       v.precio_max      AS high,
                       v.precio_min      AS low,
                       v.precio_cierre   AS close,
                       v.volumen         AS volume,
                       it.sma50
                FROM valorhistoricoaccion v
                LEFT JOIN indicadortecnico it
                  ON it.accion_id = v.accion_id AND it.fecha = v.fecha
                WHERE v.accion_id = %s
                ORDER BY v.fecha DESC
                LIMIT %s
            """, [accion_id, days])
            rows = cur.fetchall()

    if not rows:
        return pd.DataFrame(columns=['fecha','open','high','low','close','volume',
                                      'sma50','ema20','sma200'])

    df = pd.DataFrame(rows)
    df = df.sort_values('fecha').reset_index(drop=True)

    for col in ['open', 'high', 'low', 'close', 'volume', 'sma50']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    df['sma200'] = df['close'].rolling(200, min_periods=100).mean()

    # Convertir fecha a string 'YYYY-MM-DD' para que Plotly la interprete bien
    df['fecha'] = df['fecha'].astype(str)

    return df


def get_asset_indicators(accion_id: int, days: int = 365) -> pd.DataFrame:
    """RSI, mom_12_1, rs_sector, momentum_20d desde indicadorTecnico."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha, rsi14, mom_12_1, rs_sector, momentum_20d
                FROM indicadortecnico
                WHERE accion_id = %s
                  AND mom_12_1 IS NOT NULL
                ORDER BY fecha DESC
                LIMIT %s
            """, [accion_id, days])
            rows = cur.fetchall()

    if not rows:
        return pd.DataFrame(columns=['fecha','rsi14','mom_12_1','rs_sector','momentum_20d'])

    df = pd.DataFrame(rows)
    df = df.sort_values('fecha').reset_index(drop=True)

    for col in ['rsi14', 'mom_12_1', 'rs_sector', 'momentum_20d']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['fecha'] = df['fecha'].astype(str)

    return df
