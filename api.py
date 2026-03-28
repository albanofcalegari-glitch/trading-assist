"""
api.py — REST API Flask para el frontend React de Trading Assist

Uso:
  python api.py              # corre en :8000
  python api.py --port 8001

Endpoints:
  GET /api/markets
  GET /api/movers?market=USA&direction=up&n=5
  GET /api/assets?market=USA&search=AAPL&page=0&limit=50
  GET /api/assets/<id>
  GET /api/assets/<id>/ohlcv?days=400
  GET /api/assets/<id>/indicators?days=365
  GET /api/scan/wma-cross?market=USA&top=5
"""

import sys
import argparse
import datetime
import decimal
import json
import os
import threading
import time

import pymysql
import pymysql.cursors

# ── Caché en memoria para el scan WMA (evita 300s por request) ─────────────────

_scan_cache:    dict  = {}       # key → {'data': ..., 'ts': float}
_scan_running:  set   = set()    # markets cuyo scan está en curso
_scan_lock = threading.Lock()
_SCAN_TTL  = 600                 # 10 minutos

# ── Optionals ──────────────────────────────────────────────────────────────────
try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
except ImportError:
    print("Instalar: pip install flask flask-cors")
    sys.exit(1)

try:
    import numpy as np
    import pandas as pd
    HAS_NP = True
except ImportError:
    HAS_NP = False

# ── Config ─────────────────────────────────────────────────────────────────────

MYSQL_CONFIG = dict(
    host='localhost', user='root', password='123456',
    db='bolsa', charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)

USA_MARKETS = ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')

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

app = Flask(__name__)
CORS(app)


# ── JSON serializer (Decimal, date) ────────────────────────────────────────────

class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (datetime.date, datetime.datetime)):
            return str(o)
        return super().default(o)

app.json_encoder = _Enc


def _jresp(data, status=200):
    return app.response_class(
        response=json.dumps(data, cls=_Enc),
        status=status,
        mimetype='application/json',
    )


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _conn():
    return pymysql.connect(**MYSQL_CONFIG)


def _last_two_dates(cur):
    cur.execute("SELECT MAX(fecha) FROM valorhistoricoaccion")
    last = cur.fetchone()['MAX(fecha)']
    cur.execute("SELECT MAX(fecha) FROM valorhistoricoaccion WHERE fecha < %s", [last])
    prev = cur.fetchone()['MAX(fecha)']
    return last, prev


def _last_date_market(cur, mkt: str):
    cur.execute("""
        SELECT MAX(v.fecha) AS f
        FROM valorhistoricoaccion v
        JOIN accion a ON a.id = v.accion_id
        JOIN mercado m ON m.id = a.mercado_id
        WHERE m.descripcion = %s
    """, [mkt])
    return cur.fetchone()['f']


# ── /api/markets ───────────────────────────────────────────────────────────────

@app.route('/api/markets')
def get_markets():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, descripcion AS name FROM mercado ORDER BY descripcion")
            return _jresp(cur.fetchall())


# ── /api/movers ────────────────────────────────────────────────────────────────

@app.route('/api/movers')
def get_movers():
    market    = request.args.get('market', 'USA')
    direction = request.args.get('direction', 'up')
    n         = int(request.args.get('n', 5))
    order     = 'DESC' if direction == 'up' else 'ASC'

    with _conn() as conn:
        with conn.cursor() as cur:
            if market == 'BYMA':
                last = _last_date_market(cur, 'BYMA')
                cur.execute("SELECT MAX(fecha) FROM valorhistoricoaccion WHERE fecha < %s", [last])
                prev = cur.fetchone()['MAX(fecha)']
                mkt_clause = "AND m.descripcion = 'BYMA'"
                params = [last, prev, n]
            else:
                last, prev = _last_two_dates(cur)
                ph = ','.join(['%s'] * len(USA_MARKETS))
                mkt_clause = f"AND m.descripcion IN ({ph})"
                params = [last, prev] + list(USA_MARKETS) + [n]

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
                  AND v1.precio_cierre > 0.5 AND v2.precio_cierre > 0.5
                  {mkt_clause}
                ORDER BY pct_cambio {order}
                LIMIT %s
            """, params)
            rows = cur.fetchall()

    return _jresp({'market': market, 'direction': direction, 'items': rows})


# ── /api/assets ────────────────────────────────────────────────────────────────

@app.route('/api/assets')
def get_assets():
    market    = request.args.get('market', '')   # '' | 'USA' | 'BYMA'
    search    = request.args.get('search', '')
    page      = int(request.args.get('page', 0))
    limit     = int(request.args.get('limit', 50))

    s_clause   = "AND (a.simbolo LIKE %s OR a.nombre LIKE %s)" if search else ""
    opt_search = [f"%{search}%", f"%{search}%"] if search else []

    with _conn() as conn:
        with conn.cursor() as cur:
            last, prev = _last_two_dates(cur)

            # ── Todos (dedup) ──────────────────────────────────────────────────
            if not market:
                base = [last, prev] + opt_search
                cur.execute(f"""
                    SELECT COUNT(*) AS n FROM (
                        SELECT a.simbolo,
                               ROW_NUMBER() OVER (
                                   PARTITION BY a.simbolo ORDER BY {_MARKET_PRIORITY}
                               ) AS rn
                        FROM valorhistoricoaccion v1
                        JOIN valorhistoricoaccion v2
                          ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                        JOIN accion a ON a.id = v1.accion_id
                        JOIN mercado m ON m.id = a.mercado_id
                        WHERE v1.fecha = %s AND v1.precio_cierre > 0.5
                          AND v2.precio_cierre > 0.5 {s_clause}
                    ) _s WHERE rn = 1
                """, base)
                total = cur.fetchone()['n']

                cur.execute(f"""
                    SELECT accion_id, simbolo, nombre, mercado, precio, pct_cambio, volumen
                    FROM (
                        SELECT a.id AS accion_id, a.simbolo, a.nombre,
                               m.descripcion AS mercado,
                               v1.precio_cierre  AS precio,
                               v1.volumen,
                               ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2) AS pct_cambio,
                               ROW_NUMBER() OVER (
                                   PARTITION BY a.simbolo ORDER BY {_MARKET_PRIORITY}
                               ) AS rn
                        FROM valorhistoricoaccion v1
                        JOIN valorhistoricoaccion v2
                          ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                        JOIN accion a ON a.id = v1.accion_id
                        JOIN mercado m ON m.id = a.mercado_id
                        WHERE v1.fecha = %s AND v1.precio_cierre > 0.5
                          AND v2.precio_cierre > 0.5 {s_clause}
                    ) _s WHERE rn = 1
                    ORDER BY ABS(pct_cambio) DESC, simbolo
                    LIMIT %s OFFSET %s
                """, base + [limit, page * limit])
                rows = cur.fetchall()

            else:
                # ── USA o BYMA ─────────────────────────────────────────────────
                if market == 'USA':
                    ph = ','.join(['%s'] * len(USA_MARKETS))
                    m_clause = f"AND m.descripcion IN ({ph})"
                    opt_mkt  = list(USA_MARKETS)
                else:
                    m_clause = "AND m.descripcion = %s"
                    opt_mkt  = [market]

                base = [prev, last] + opt_mkt + opt_search
                cur.execute(f"""
                    SELECT COUNT(*) AS n
                    FROM valorhistoricoaccion v1
                    JOIN valorhistoricoaccion v2
                      ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                    JOIN accion a ON a.id = v1.accion_id
                    JOIN mercado m ON m.id = a.mercado_id
                    WHERE v1.fecha = %s AND v1.precio_cierre > 0.5
                      AND v2.precio_cierre > 0.5 {m_clause} {s_clause}
                """, base)
                total = cur.fetchone()['n']

                cur.execute(f"""
                    SELECT a.id AS accion_id, a.simbolo, a.nombre,
                           m.descripcion AS mercado,
                           v1.precio_cierre  AS precio,
                           v1.volumen,
                           ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2) AS pct_cambio
                    FROM valorhistoricoaccion v1
                    JOIN valorhistoricoaccion v2
                      ON v1.accion_id = v2.accion_id AND v2.fecha = %s
                    JOIN accion a ON a.id = v1.accion_id
                    JOIN mercado m ON m.id = a.mercado_id
                    WHERE v1.fecha = %s AND v1.precio_cierre > 0.5
                      AND v2.precio_cierre > 0.5 {m_clause} {s_clause}
                    ORDER BY ABS(pct_cambio) DESC, simbolo
                    LIMIT %s OFFSET %s
                """, [prev, last] + opt_mkt + opt_search + [limit, page * limit])
                rows = cur.fetchall()

    return _jresp({
        'items': rows,
        'total': total,
        'page':  page,
        'limit': limit,
        'pages': max(1, -(-total // limit)),
    })


# ── /api/assets/<id> ───────────────────────────────────────────────────────────

@app.route('/api/assets/<int:accion_id>')
def get_asset(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.simbolo, a.nombre, m.descripcion AS mercado
                FROM accion a
                JOIN mercado m ON m.id = a.mercado_id
                WHERE a.id = %s
            """, [accion_id])
            info = cur.fetchone()
            if not info:
                return _jresp({'error': 'Not found'}, 404)

            last, prev = _last_two_dates(cur)
            cur.execute("""
                SELECT v1.precio_cierre AS precio, v1.volumen,
                       ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2) AS pct_cambio
                FROM valorhistoricoaccion v1
                LEFT JOIN valorhistoricoaccion v2
                  ON v2.accion_id = v1.accion_id AND v2.fecha = %s
                WHERE v1.accion_id = %s AND v1.fecha = %s
            """, [prev, accion_id, last])
            price_row = cur.fetchone() or {}

    return _jresp({**info, **price_row, 'fecha': str(last)})


# ── /api/assets/<id>/ohlcv ─────────────────────────────────────────────────────

@app.route('/api/assets/<int:accion_id>/ohlcv')
def get_ohlcv(accion_id: int):
    days = int(request.args.get('days', 400))
    cutoff = datetime.date.today() - datetime.timedelta(days=days)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha,
                       COALESCE(precio_apertura, precio_cierre) AS open,
                       COALESCE(precio_max, precio_cierre)      AS high,
                       COALESCE(precio_min, precio_cierre)      AS low,
                       precio_cierre AS close, volumen AS volume
                FROM valorhistoricoaccion
                WHERE accion_id = %s AND fecha >= %s
                ORDER BY fecha ASC
            """, [accion_id, cutoff])
            rows = cur.fetchall()

    # Serializar fechas
    for r in rows:
        r['fecha'] = str(r['fecha'])

    return _jresp({'accion_id': accion_id, 'candles': rows})


# ── /api/assets/<id>/indicators ───────────────────────────────────────────────

@app.route('/api/assets/<int:accion_id>/indicators')
def get_indicators(accion_id: int):
    days = int(request.args.get('days', 365))
    cutoff = datetime.date.today() - datetime.timedelta(days=days)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha, sma50, rsi14,
                       atr14_rel, dist_sma200_pct,
                       momentum_5d, momentum_20d,
                       volume_ratio_5d, volume_ratio_20d
                FROM indicadortecnico
                WHERE accion_id = %s AND fecha >= %s
                ORDER BY fecha ASC
            """, [accion_id, cutoff])
            rows = cur.fetchall()

    for r in rows:
        r['fecha'] = str(r['fecha'])

    return _jresp({'accion_id': accion_id, 'indicators': rows})


# ── /api/scan/wma-cross ────────────────────────────────────────────────────────

def _nearest_resistance(highs, current_price: float, window: int = 5):
    """Pivot high más cercano POR ENCIMA del precio actual."""
    pivots = []
    for i in range(window, len(highs) - window):
        h = float(highs[i])
        if h <= current_price:
            continue
        left_ok  = all(float(highs[j]) <= h for j in range(i - window, i))
        right_ok = all(float(highs[j]) <= h for j in range(i + 1, i + window + 1))
        if left_ok and right_ok:
            pivots.append(h)
    return min(pivots) if pivots else None


def _execute_scan(market: str) -> dict:
    """Lógica real del scan WMA. Guarda resultado en caché y retorna el dict completo."""
    GAP_THRESHOLD  = 0.005
    MIN_UPSIDE_PCT = 15.0
    MIN_BARS       = 35
    MIN_VOL_USA    = 200_000
    MIN_VOL_AR     = 5_000

    with _conn() as conn:
        with conn.cursor() as cur:
            if market == 'BYMA':
                last = _last_date_market(cur, 'BYMA')
                mkt_clause  = "AND m.descripcion = 'BYMA'"
                cedear_join = ""
            elif market == 'USA':
                cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion")
                last = cur.fetchone()['f']
                mkt_clause  = "AND m.descripcion IN ('NASDAQ','NYSE','NYSE_AMERICAN','NYSE_ARCA','CBOE_BZX')"
                cedear_join = "INNER JOIN cedear c ON c.accion_id = a.id"
            else:
                cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion")
                last = cur.fetchone()['f']
                mkt_clause  = ""
                cedear_join = "INNER JOIN cedear c ON c.accion_id = a.id"

            cutoff = last - datetime.timedelta(days=55)

            cur.execute(f"""
                SELECT v.accion_id, a.simbolo, a.nombre, m.descripcion AS mercado,
                       v.volumen AS vol_today
                FROM valorhistoricoaccion v
                JOIN accion a ON a.id = v.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                {cedear_join}
                WHERE v.fecha = %s AND v.precio_cierre >= 1.0 {mkt_clause}
            """, [last])
            active = {r['accion_id']: r for r in cur.fetchall()}

            cur.execute(f"""
                SELECT v.accion_id, v.fecha, v.precio_cierre AS close,
                       COALESCE(v.precio_max, v.precio_cierre) AS high,
                       it.rsi14,
                       it.dist_sma200_pct
                FROM valorhistoricoaccion v
                LEFT JOIN indicadortecnico it
                       ON it.accion_id = v.accion_id AND it.fecha = v.fecha
                JOIN accion a ON a.id = v.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                {cedear_join}
                WHERE v.fecha >= %s AND v.precio_cierre >= 1.0 {mkt_clause}
                ORDER BY v.accion_id, v.fecha
            """, [cutoff])
            rows = cur.fetchall()

    if not rows:
        result = {'setup': [], 'cross': [], 'fecha': str(last)}
        with _scan_lock:
            _scan_cache[market] = {'data': result, 'ts': time.time()}
        return result

    df = pd.DataFrame(rows)
    setup_list, cross_list = [], []

    def _wma(closes, n, offset=0):
        end = len(closes) - offset
        start = end - n
        if start < 0 or end <= 0:
            return np.nan
        w = np.arange(1, n + 1, dtype=float)
        return float(np.dot(closes[start:end], w) / w.sum())

    for aid, grp in df.groupby('accion_id'):
        if aid not in active:
            continue
        grp = grp.sort_values('fecha').reset_index(drop=True)
        if len(grp) < MIN_BARS:
            continue

        info    = active[aid]
        mercado = info['mercado']
        vol     = int(info.get('vol_today') or 0)
        if vol < (MIN_VOL_AR if mercado == 'BYMA' else MIN_VOL_USA):
            continue

        closes = grp['close'].astype(float).values
        price  = closes[-1]
        w6_0 = _wma(closes, 6, 0);  w6_1 = _wma(closes, 6, 1)
        w30_0 = _wma(closes, 30, 0); w30_1 = _wma(closes, 30, 1)

        if any(np.isnan(x) for x in [w6_0, w6_1, w30_0, w30_1]):
            continue

        try:    trend_up = float(grp['dist_sma200_pct'].iloc[-1]) >= 0
        except: trend_up = False

        # Filtros swing: RSI < 50 y upside a resistencia >= MIN_UPSIDE_PCT
        try:
            rsi = float(grp['rsi14'].iloc[-1])
        except (TypeError, ValueError):
            rsi = None

        highs = grp['high'].astype(float).values
        resistance = _nearest_resistance(highs, price)
        upside_pct = ((resistance - price) / price * 100) if resistance else None

        swing_ok = (
            rsi is not None and rsi < 50
            and upside_pct is not None and upside_pct >= MIN_UPSIDE_PCT
        )

        base = dict(accion_id=int(aid), simbolo=info['simbolo'],
                    nombre=info['nombre'][:35], mercado=mercado,
                    precio=round(price, 2), wma6=round(w6_0, 4),
                    wma30=round(w30_0, 4), vol=vol, trend_up=trend_up,
                    rsi=round(rsi, 1) if rsi is not None else None,
                    upside_pct=round(upside_pct, 1) if upside_pct is not None else None,
                    resistance=round(resistance, 2) if resistance is not None else None)

        if w6_1 < w30_1 and w6_0 > w30_0:
            if not swing_ok:
                continue
            cross_list.append({**base, 'tipo': 'CROSS_SWING_BUY',
                'gap_pct': round((w6_0 - w30_0) / max(w30_0, 1e-9) * 100, 3)})
            continue

        gap_now  = (w30_0 - w6_0) / max(w30_0, 1e-9)
        gap_prev = (w30_1 - w6_1) / max(w30_1, 1e-9)
        if (w6_0 < w30_0 and gap_now < GAP_THRESHOLD
                and gap_now < gap_prev and w6_0 > w6_1 and price >= closes[-2]
                and swing_ok):
            setup_list.append({**base, 'tipo': 'SETUP_SWING',
                'gap_pct': round(gap_now * 100, 3),
                'slope': round((w6_0 - w6_1) / max(w6_1, 1e-9), 6)})

    def _dedup(lst):
        prio = {'NASDAQ': 0, 'NYSE': 1, 'NYSE_AMERICAN': 2, 'NYSE_ARCA': 3, 'CBOE_BZX': 4, 'BYMA': 10}
        seen = {}
        for r in lst:
            sym, p = r['simbolo'], prio.get(r['mercado'], 99)
            if sym not in seen or p < prio.get(seen[sym]['mercado'], 99):
                seen[sym] = r
        return list(seen.values())

    setup_list = sorted(_dedup(setup_list), key=lambda r: (r['gap_pct'], -r.get('slope', 0)))
    cross_list = sorted(_dedup(cross_list), key=lambda r: (0 if r['trend_up'] else 1, -r['vol']))

    result = {'setup': setup_list, 'cross': cross_list, 'fecha': str(last)}
    with _scan_lock:
        _scan_cache[market] = {'data': result, 'ts': time.time()}
        _scan_running.discard(market)
    return result


# ── /api/market-context ────────────────────────────────────────────────────────

@app.route('/api/market-context')
def get_market_context():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha, vix_level, vix_percentile_1y,
                       spy_return_5d, spy_return_20d,
                       yield_10y, market_regime
                FROM indicadormercado
                ORDER BY fecha DESC
                LIMIT 1
            """)
            row = cur.fetchone()
    if not row:
        return _jresp({'error': 'no data'}, 404)
    row['fecha'] = str(row['fecha'])
    return _jresp(row)


@app.route('/api/scan/wma-cross')
def scan_wma_cross():
    if not HAS_NP:
        return _jresp({'error': 'numpy/pandas not available'}, 503)

    market = request.args.get('market', 'USA')
    top    = int(request.args.get('top', 10))
    trend  = request.args.get('trend', 'false').lower() == 'true'

    with _scan_lock:
        cached = _scan_cache.get(market)
        if cached and (time.time() - cached['ts']) < _SCAN_TTL:
            data  = cached['data']
            setup = [r for r in data['setup'] if not trend or r['trend_up']][:top]
            cross = [r for r in data['cross'] if not trend or r['trend_up']][:top]
            return _jresp({'setup': setup, 'cross': cross,
                           'fecha': data['fecha'], 'market': market,
                           'cached': True, 'status': 'ready'})

        if market in _scan_running:
            return _jresp({'status': 'computing', 'market': market,
                           'setup': [], 'cross': [], 'fecha': ''})

        _scan_running.add(market)

    def _bg():
        try:
            _execute_scan(market)
        except Exception as e:
            print(f' * ERROR scan ({market}): {e}')
            with _scan_lock:
                _scan_running.discard(market)

    threading.Thread(target=_bg, daemon=True).start()
    return _jresp({'status': 'computing', 'market': market,
                   'setup': [], 'cross': [], 'fecha': ''})


# ── Pre-calentado del caché en background ─────────────────────────────────────

def _warm_cache():
    """Ejecuta el scan en background al arrancar para que el primer request sea rápido."""
    import time as _time
    _time.sleep(3)   # esperar a que Flask esté listo
    try:
        print(' * Precalentando caché WMA scan USA...')
        _execute_scan('USA')
        print(' * Caché WMA listo.')
    except Exception as e:
        print(f' * WARN precalentado: {e}')


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', type=str, default='127.0.0.1')
    parser.add_argument('--no-warm', action='store_true',
                        help='Omitir pre-calentado del caché')
    args = parser.parse_args()

    if not args.no_warm and HAS_NP:
        t = threading.Thread(target=_warm_cache, daemon=True)
        t.start()

    print(f'API running on http://{args.host}:{args.port}')
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
