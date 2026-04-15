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
import functools
import json
import os
import threading
import time

import bcrypt
import jwt
import pymysql
import pymysql.cursors

# ── Caché en memoria para el scan WMA (evita 300s por request) ─────────────────

_scan_cache:    dict  = {}       # key → {'data': ..., 'ts': float}
_scan_running:  set   = set()    # markets cuyo scan está en curso
_scan_lock = threading.Lock()
_SCAN_TTL  = 600                 # 10 minutos

# ── Caché para longterm-support (cálculo O(n²) puede tardar 30-60s) ────────────

_ltsupp_cache: dict = {}         # (symbol, horizon) → {'data': dict, 'ts': float}
_ltsupp_lock = threading.Lock()
_LTSUPP_TTL  = 3600              # 1 hora

# ── Caché para horizontal-zones ───────────────────────────────────────────────

_hzones_cache: dict = {}         # symbol → {'data': dict, 'ts': float}
_hzones_lock = threading.Lock()
_HZONES_TTL  = 3600              # 1 hora

# ── Caché para channel-detection ──────────────────────────────────────────────

_channel_cache: dict = {}        # symbol → {'data': dict, 'ts': float}
_channel_lock = threading.Lock()
_CHANNEL_TTL  = 3600             # 1 hora

# ── Caché para dynamic-supports ───────────────────────────────────────────────

_dynsup_cache: dict = {}         # symbol → {'data': dict, 'ts': float}
_dynsup_lock = threading.Lock()
_DYNSUP_TTL  = 3600              # 1 hora

# ── Caché para ut-bot ─────────────────────────────────────────────────────────

_utbot_cache: dict = {}          # (symbol, sensitivity, atr_period) → {'data': dict, 'ts': float}
_utbot_lock = threading.Lock()
_UTBOT_TTL  = 3600               # 1 hora

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
    db='trading_assist', charset='utf8mb4',
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

JWT_SECRET = os.environ.get('JWT_SECRET', 'tr4d1ng-4ss1st-s3cr3t-k3y-2026')
JWT_EXP_HOURS = 24


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _check_pw(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _make_token(user_id: int, username: str) -> str:
    payload = {
        # PyJWT >= 2.10 exige que 'sub' sea string. Casteamos al firmar y
        # revertimos a int al decodificar (ver _decode_token), de modo que los
        # consumidores que esperan int siguen funcionando.
        'sub': str(user_id),
        'user': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXP_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def _decode_token(token: str):
    payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    sub = payload.get('sub')
    if isinstance(sub, str) and sub.isdigit():
        payload['sub'] = int(sub)
    return payload


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Token requerido'}), 401
        try:
            payload = _decode_token(auth[7:])
            request.user = payload
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expirado'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401
        return f(*args, **kwargs)
    return wrapper


VALID_INVESTOR_PROFILES = ('conservador', 'moderado', 'agresivo')


def _ensure_batch_tables():
    """Tablas para el sistema de batches/notificaciones (idempotente)."""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS batch_run (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    batch_name   VARCHAR(50) NOT NULL,
                    started_at   DATETIME    NOT NULL,
                    finished_at  DATETIME    NULL,
                    status       VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
                    payload_json LONGTEXT    NULL,
                    error        TEXT        NULL,
                    INDEX idx_batch_started (batch_name, started_at)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS notification (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    batch_run_id INT          NULL,
                    kind         VARCHAR(40)  NOT NULL,
                    title        VARCHAR(255) NOT NULL,
                    body         TEXT         NOT NULL,
                    data_json    LONGTEXT     NULL,
                    created_at   DATETIME     NOT NULL,
                    read_at      DATETIME     NULL,
                    INDEX idx_notif_created (created_at),
                    INDEX idx_notif_kind    (kind)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rotation_state (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    week_end        DATE         NOT NULL,
                    action          VARCHAR(20)  NOT NULL,
                    symbol          VARCHAR(20)  NULL,
                    prev_symbol     VARCHAR(20)  NULL,
                    score           DECIMAL(10,4) NULL,
                    equity          DECIMAL(14,2) NULL,
                    spy_equity      DECIMAL(14,2) NULL,
                    note            TEXT         NULL,
                    UNIQUE KEY uq_rotation_week (week_end)
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _ensure_users_table():
    """Crea la tabla users si no existe e inserta usuarios iniciales."""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            if cur.fetchone()['cnt'] == 0:
                pw = _hash_pw('12345678')
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", ('albano', pw))
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", ('julian', pw))
                print(' * Usuarios iniciales creados: albano, julian')

            # Migración idempotente: agregar columna investor_profile si no existe
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'users'
                  AND COLUMN_NAME = 'investor_profile'
            """)
            if cur.fetchone()['cnt'] == 0:
                cur.execute("ALTER TABLE users ADD COLUMN investor_profile VARCHAR(20) NULL")
                print(' * Columna users.investor_profile creada')
        conn.commit()
    finally:
        conn.close()


# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    body = request.get_json(silent=True) or {}
    username = (body.get('username') or '').strip().lower()
    password = body.get('password') or ''
    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, investor_profile FROM users WHERE username = %s",
                (username,),
            )
            user = cur.fetchone()
    finally:
        conn.close()
    if not user or not _check_pw(password, user['password_hash']):
        return jsonify({'error': 'Credenciales incorrectas'}), 401
    token = _make_token(user['id'], user['username'])
    return jsonify({
        'token': token,
        'username': user['username'],
        'investor_profile': user.get('investor_profile'),
    })


@app.route('/api/auth/me', methods=['GET'])
@login_required
def auth_me():
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, investor_profile FROM users WHERE id = %s",
                (request.user['sub'],),
            )
            row = cur.fetchone() or {}
    finally:
        conn.close()
    return jsonify({
        'username': row.get('username') or request.user['user'],
        'investor_profile': row.get('investor_profile'),
    })


@app.route('/api/auth/profile', methods=['POST'])
@login_required
def auth_set_profile():
    body = request.get_json(silent=True) or {}
    profile = (body.get('profile') or '').strip().lower()
    if profile not in VALID_INVESTOR_PROFILES:
        return jsonify({
            'error': f'Perfil inválido. Debe ser uno de: {", ".join(VALID_INVESTOR_PROFILES)}'
        }), 400
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET investor_profile = %s WHERE id = %s",
                (profile, request.user['sub']),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'investor_profile': profile})


@app.route('/api/auth/change-password', methods=['POST'])
@login_required
def auth_change_password():
    body = request.get_json(silent=True) or {}
    current = body.get('current') or ''
    new_pw = body.get('new_password') or ''
    if not current or not new_pw:
        return jsonify({'error': 'Contraseña actual y nueva requeridas'}), 400
    if len(new_pw) < 6:
        return jsonify({'error': 'La nueva contraseña debe tener al menos 6 caracteres'}), 400
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", (request.user['sub'],))
            user = cur.fetchone()
            if not user or not _check_pw(current, user['password_hash']):
                return jsonify({'error': 'Contraseña actual incorrecta'}), 401
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                        (_hash_pw(new_pw), request.user['sub']))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'message': 'Contraseña actualizada'})


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


def _last_two_dates(cur, market: str | None = None):
    # Cuando se especifica un mercado, calculamos las 2 últimas fechas RESTRINGIDAS
    # a ese mercado. Esto es crítico para BYMA: el cron de USA puede haber corrido
    # antes que el de BYMA y la fecha global más reciente puede no existir en BYMA,
    # rompiendo el JOIN v1+v2.
    if market == 'BYMA':
        cur.execute("""
            SELECT v.fecha
            FROM valorhistoricoaccion v
            JOIN accion a  ON a.id = v.accion_id
            JOIN mercado m ON m.id = a.mercado_id
            WHERE m.descripcion = 'BYMA'
            GROUP BY v.fecha
            HAVING COUNT(*) >= 30
            ORDER BY v.fecha DESC LIMIT 2
        """)
        rows = cur.fetchall()
        if len(rows) >= 2:
            return rows[0]['fecha'], rows[1]['fecha']
    elif market == 'USA':
        ph = ','.join(['%s'] * len(USA_MARKETS))
        cur.execute(f"""
            SELECT v.fecha
            FROM valorhistoricoaccion v
            JOIN accion a  ON a.id = v.accion_id
            JOIN mercado m ON m.id = a.mercado_id
            WHERE m.descripcion IN ({ph})
            GROUP BY v.fecha
            HAVING COUNT(*) >= 5000
            ORDER BY v.fecha DESC LIMIT 2
        """, list(USA_MARKETS))
        rows = cur.fetchall()
        if len(rows) >= 2:
            return rows[0]['fecha'], rows[1]['fecha']

    # Default global: cobertura real (>= 5000 activos) para evitar updates parciales
    cur.execute("""
        SELECT fecha FROM valorhistoricoaccion
        GROUP BY fecha HAVING COUNT(*) >= 5000
        ORDER BY fecha DESC LIMIT 2
    """)
    rows = cur.fetchall()
    if len(rows) >= 2:
        return rows[0]['fecha'], rows[1]['fecha']
    # fallback al comportamiento anterior si no hay suficientes datos
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
    # Con búsqueda: símbolo exacto primero, luego prefijo, luego resto
    # Sin búsqueda: ordenar por mayor movimiento
    s_order      = "(CASE WHEN simbolo = %s THEN 0 WHEN simbolo LIKE %s THEN 1 ELSE 2 END), simbolo" if search else "ABS(pct_cambio) DESC, simbolo"
    s_order_full = "(CASE WHEN a.simbolo = %s THEN 0 WHEN a.simbolo LIKE %s THEN 1 ELSE 2 END), a.simbolo" if search else "ABS(pct_cambio) DESC, a.simbolo"
    opt_order    = [search.upper(), f"{search.upper()}%"] if search else []

    s_clause   = "AND (a.simbolo LIKE %s OR a.nombre LIKE %s)" if search else ""
    opt_search = [f"%{search}%", f"%{search}%"] if search else []

    with _conn() as conn:
        with conn.cursor() as cur:
            # Pasar market para que las fechas se calculen sobre ese mercado.
            # Sin esto, BYMA usa la última fecha global (que sólo tiene USA) y
            # el JOIN v1+v2 devuelve vacío.
            last, prev = _last_two_dates(cur, market or None)

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
                    ORDER BY {s_order}
                    LIMIT %s OFFSET %s
                """, base + opt_order + [limit, page * limit])
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
                    ORDER BY {s_order_full}
                    LIMIT %s OFFSET %s
                """, [prev, last] + opt_mkt + opt_search + opt_order + [limit, page * limit])
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

            # Detectar mercado del propio asset para no usar fecha global
            # (rompe BYMA cuando USA tiene un día más cargado).
            mkt_hint = 'BYMA' if info.get('mercado') == 'BYMA' else 'USA'
            last, prev = _last_two_dates(cur, mkt_hint)
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
                SELECT v.fecha,
                       COALESCE(ph.open,  v.precio_apertura, v.precio_cierre) AS open,
                       COALESCE(ph.high,  v.precio_max,
                           GREATEST(
                               COALESCE(ph.open,  v.precio_apertura, v.precio_cierre),
                               COALESCE(ph.close, v.precio_cierre)
                           )
                       ) AS high,
                       COALESCE(ph.low,   v.precio_min,
                           LEAST(
                               COALESCE(ph.open,  v.precio_apertura, v.precio_cierre),
                               COALESCE(ph.close, v.precio_cierre)
                           )
                       ) AS low,
                       COALESCE(ph.close, v.precio_cierre)  AS close,
                       COALESCE(ph.volume, v.volumen, 0)    AS volume
                FROM valorhistoricoaccion v
                JOIN accion a ON a.id = v.accion_id
                LEFT JOIN price_history ph
                       ON ph.simbolo = a.simbolo AND ph.fecha = v.fecha
                WHERE v.accion_id = %s AND v.fecha >= %s
                ORDER BY v.fecha ASC
            """, [accion_id, cutoff])
            rows = cur.fetchall()

    # Serializar fechas
    for r in rows:
        r['fecha'] = str(r['fecha'])

    return _jresp({'accion_id': accion_id, 'candles': rows})


# ── /api/assets/<id>/ohlcv-extended ───────────────────────────────────────────
# Sirve OHLCV desde ohlcv_extended (histórico completo: 20-30 años).
# ?tf=D  → diario   (hasta ~20 años según símbolo)
# ?tf=W  → semanal  (hasta ~25 años)
# ?tf=M  → mensual  (hasta ~30 años)

@app.route('/api/assets/<int:accion_id>/ohlcv-extended')
def get_ohlcv_extended(accion_id: int):
    tf = request.args.get('tf', 'D').upper()
    if tf not in ('D', 'W', 'M'):
        return _jresp({'error': 'tf must be D, W or M'}, 400)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    simbolo = row['simbolo']

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha,
                       open, high, low, close, volume
                FROM ohlcv_extended
                WHERE simbolo = %s AND timeframe = %s
                ORDER BY fecha ASC
            """, [simbolo, tf])
            rows = cur.fetchall()

    for r in rows:
        r['fecha'] = str(r['fecha'])

    return _jresp({'accion_id': accion_id, 'simbolo': simbolo, 'tf': tf, 'candles': rows})


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
#
# Devuelve VIX, SPY 5d/20d, T10Y y régimen con datos near-real-time.
# Estrategia:
#   1. yfinance live (^VIX, SPY, ^TNX) — cache de 90s en memoria.
#   2. DB (indicadormercado) — para vix_percentile_1y y market_regime,
#      que requieren histórico nuestro y se calculan en el batch diario.
#   3. Fallback puro a DB si Yahoo está caído.
#
# Response shape:
#   { fecha, vix_level, vix_percentile_1y, spy_return_5d, spy_return_20d,
#     yield_10y, market_regime, updated_at, source }
#
# updated_at = epoch unix segundos del último fetch live (None si fallback)
# source     = 'live' | 'db_fallback'

_MARKET_CTX_CACHE: dict | None = None
_MARKET_CTX_CACHE_TS: float    = 0.0
_MARKET_CTX_TTL                = 90  # segundos


def _fetch_live_market_context() -> dict:
    """Fetch directo a Yahoo. ~300-800ms p50. Sólo se llama si el cache expiró."""
    import yfinance as yf
    syms = yf.Tickers('^VIX SPY ^TNX')

    vix_info = syms.tickers['^VIX'].fast_info
    tnx_info = syms.tickers['^TNX'].fast_info

    # SPY 5d/20d returns: 1 sola request al history
    spy_hist = syms.tickers['SPY'].history(period='30d', interval='1d')
    closes   = spy_hist['Close'].tolist() if hasattr(spy_hist, 'empty') and not spy_hist.empty else []
    spy_5d   = (closes[-1] / closes[-6]  - 1) * 100 if len(closes) >= 6  else None
    spy_20d  = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else None

    return {
        'vix_level':     float(vix_info.last_price) if vix_info.last_price else None,
        'spy_return_5d': round(spy_5d, 2) if spy_5d is not None else None,
        'spy_return_20d': round(spy_20d, 2) if spy_20d is not None else None,
        # ^TNX viene en décimas de % (ej. 42.5 = 4.25%)
        'yield_10y':     round(float(tnx_info.last_price) / 10.0, 2) if tnx_info.last_price else None,
        'updated_at':    int(time.time()),
        'source':        'live',
    }


@app.route('/api/market-context')
def get_market_context():
    global _MARKET_CTX_CACHE, _MARKET_CTX_CACHE_TS
    now = time.time()

    # 1) DB → percentil VIX + market_regime + fecha del batch
    db_row = None
    try:
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
                db_row = cur.fetchone()
    except Exception as e:
        print(f'[market_context] db read failed: {e}')

    # 2) Live → con cache 90s
    if _MARKET_CTX_CACHE and (now - _MARKET_CTX_CACHE_TS) < _MARKET_CTX_TTL:
        live = _MARKET_CTX_CACHE
    else:
        try:
            live = _fetch_live_market_context()
            _MARKET_CTX_CACHE    = live
            _MARKET_CTX_CACHE_TS = now
        except Exception as e:
            print(f'[market_context] live fetch failed: {type(e).__name__}: {e}')
            # Fallback puro a DB
            if not db_row:
                return _jresp({'error': 'no data'}, 404)
            db_row['fecha']      = str(db_row['fecha'])
            db_row['updated_at'] = None
            db_row['source']     = 'db_fallback'
            return _jresp(db_row)

    # 3) Merge: live para precios, DB para regime/percentil/fecha
    out = {
        'fecha':             str(db_row['fecha']) if db_row else None,
        'vix_level':         live.get('vix_level'),
        'vix_percentile_1y': db_row.get('vix_percentile_1y') if db_row else None,
        'spy_return_5d':     live.get('spy_return_5d'),
        'spy_return_20d':    live.get('spy_return_20d'),
        'yield_10y':         live.get('yield_10y'),
        'market_regime':     db_row.get('market_regime') if db_row else None,
        'updated_at':        live.get('updated_at'),
        'source':            'live',
    }
    return _jresp(out)


# ── /api/assets/<id>/trend-pullback-signal ────────────────────────────────────
#
# Devuelve la última señal trend_pullback para un activo. Incluye gap_pct
# para que el frontend pueda aplicar el filtro GAP configurable por usuario.
# Tabla puede no existir todavía (primer deploy) → devolver null sin error.

@app.route('/api/assets/<int:accion_id>/trend-pullback-signal')
def get_trend_pullback_signal(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id=%s", [accion_id])
            row = cur.fetchone()
            if not row:
                return _jresp({'error': 'asset not found'}, 404)
            try:
                cur.execute("""
                    SELECT fecha, simbolo, trend_score, pullback_score, setup_state,
                           context_alignment, decision, confidence_level,
                           allow_trade, reading, price, gap_pct
                    FROM trend_pullback_signals
                    WHERE simbolo=%s
                    ORDER BY fecha DESC LIMIT 1
                """, [row['simbolo']])
                sig = cur.fetchone()
            except Exception:
                # Tabla no existe todavía
                return _jresp(None)
    if not sig:
        return _jresp(None)
    sig['fecha'] = str(sig['fecha'])
    return _jresp(sig)


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


# ── /api/assets/<id>/longterm-support ─────────────────────────────────────────
#
# Retorna la directriz de soporte estructural calculada sobre el histórico
# COMPLETO de ohlcv_extended (semanal o mensual según el horizonte).
# No depende del zoom ni de las velas visibles en el chart.
#
# Query params:
#   horizon = 'long_term' (default) | 'mid_term' | 'short_term'
#
# Requiere que backfill_history.py haya corrido previamente para el símbolo.

@app.route('/api/assets/<int:accion_id>/longterm-support')
def get_longterm_support_endpoint(accion_id: int):
    horizon = request.args.get('horizon', 'long_term')

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']
    cache_key = (symbol, horizon)

    # ── Devolver desde caché si está fresco ──────────────────────────────────
    with _ltsupp_lock:
        entry = _ltsupp_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _LTSUPP_TTL:
            return _jresp(entry['data'])

    # ── Calcular (puede tardar varios segundos) ───────────────────────────────
    try:
        from strategies.longterm_support import get_longterm_support
        result = get_longterm_support(symbol, datetime.date.today(), horizon=horizon)
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    if result is None:
        result = {
            'status':  'NO_DATA',
            'symbol':  symbol,
            'horizon': horizon,
            'message': 'Sin datos en ohlcv_extended. Ejecutar scripts/backfill_history.py',
            'line_points': [],
            'resistance_line_points': [],
        }

    with _ltsupp_lock:
        _ltsupp_cache[cache_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/dynamic-supports ─────────────────────────────────────────
#
# Soportes dinámicos ascendentes sobre el histórico semanal (log-space).
# Devuelve 3 tiers en un solo call:  long / mid / short.  Pensado para pintar
# tres overlays (verde/amarillo/cyan) en el PriceChart.

@app.route('/api/assets/<int:accion_id>/dynamic-supports')
def get_dynamic_supports_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _dynsup_lock:
        entry = _dynsup_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _DYNSUP_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.dynamic_supports import get_dynamic_supports
        result = get_dynamic_supports(symbol, datetime.date.today())
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _dynsup_lock:
        _dynsup_cache[symbol] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/ut-bot ───────────────────────────────────────────────────
#
# UT Bot trailing stop (variante QuantNomad) sobre cierre diario.
# Query params opcionales:
#   sensitivity (float, default 2.0)
#   atr_period  (int,   default 10)

@app.route('/api/assets/<int:accion_id>/ut-bot')
def get_ut_bot_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    try:
        sensitivity = float(request.args.get('sensitivity', 2.0))
        atr_period  = int(request.args.get('atr_period', 10))
    except (ValueError, TypeError):
        return _jresp({'error': 'Invalid sensitivity/atr_period'}, 400)

    key = (symbol, sensitivity, atr_period)
    with _utbot_lock:
        entry = _utbot_cache.get(key)
        if entry and (time.time() - entry['ts']) < _UTBOT_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.ut_bot import get_ut_bot
        result = get_ut_bot(symbol, datetime.date.today(), sensitivity, atr_period)
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _utbot_lock:
        _utbot_cache[key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/horizontal-zones ─────────────────────────────────────────
#
# Zonas horizontales de soporte y resistencia detectadas sobre ohlcv_extended
# semanal.  Retorna múltiples zonas para soporte y resistencia.

@app.route('/api/assets/<int:accion_id>/horizontal-zones')
def get_horizontal_zones(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _hzones_lock:
        entry = _hzones_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _HZONES_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.horizontal_zones import detect_horizontal_zones
        result = detect_horizontal_zones(symbol, datetime.date.today())
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _hzones_lock:
        _hzones_cache[symbol] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/channel ──────────────────────────────────────────────────
#
# Detección de canal paralelo (ascendente, descendente, horizontal) sobre datos
# semanales.  Retorna tipo, soporte/resistencia, posición dentro del canal,
# y datos de líneas para plotting.

@app.route('/api/assets/<int:accion_id>/channel')
def get_channel(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _channel_lock:
        entry = _channel_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _CHANNEL_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.channel_detection import detect_channels_multi
        channels = detect_channels_multi(symbol, datetime.date.today())
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    result = {'symbol': symbol, 'channels': channels}

    with _channel_lock:
        _channel_cache[symbol] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/historical-low-signal ────────────────────────────────────
#
# Devuelve la última señal de mínimos históricos para un activo.
# Tabla puede no existir todavía → devolver null sin error.

@app.route('/api/assets/<int:accion_id>/historical-low-signal')
def get_historical_low_signal(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id=%s", [accion_id])
            row = cur.fetchone()
            if not row:
                return _jresp({'error': 'asset not found'}, 404)
            try:
                cur.execute("""
                    SELECT fecha, simbolo, price, low_52w, low_52w_date,
                           low_52w_days_ago, distance_52w_pct,
                           low_all, low_all_date, distance_all_pct,
                           is_all_time_low, setup_state, decision,
                           confidence_level, reading, rsi14, mom20, sma200
                    FROM historical_low_signals
                    WHERE simbolo=%s
                    ORDER BY fecha DESC LIMIT 1
                """, [row['simbolo']])
                sig = cur.fetchone()
            except Exception:
                return _jresp(None)
    if not sig:
        return _jresp(None)
    sig['fecha'] = str(sig['fecha'])
    if sig.get('low_52w_date'):
        sig['low_52w_date'] = str(sig['low_52w_date'])
    if sig.get('low_all_date'):
        sig['low_all_date'] = str(sig['low_all_date'])
    for k in ('price', 'low_52w', 'distance_52w_pct', 'low_all',
              'distance_all_pct', 'rsi14', 'mom20', 'sma200'):
        if sig.get(k) is not None:
            sig[k] = float(sig[k])
    sig['is_all_time_low'] = bool(sig.get('is_all_time_low'))
    return _jresp(sig)


# ── /api/assets/<id>/historical-high-signal ───────────────────────────────────
#
# Devuelve la última señal de máximos históricos para un activo.
# Tabla puede no existir todavía → devolver null sin error.

@app.route('/api/assets/<int:accion_id>/historical-high-signal')
def get_historical_high_signal(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id=%s", [accion_id])
            row = cur.fetchone()
            if not row:
                return _jresp({'error': 'asset not found'}, 404)
            try:
                cur.execute("""
                    SELECT fecha, simbolo, price, high_52w, high_52w_date,
                           high_52w_days_ago, distance_52w_pct,
                           high_all, high_all_date, distance_all_pct,
                           is_all_time_high, setup_state, decision,
                           confidence_level, reading, rsi14, mom20, sma200
                    FROM historical_high_signals
                    WHERE simbolo=%s
                    ORDER BY fecha DESC LIMIT 1
                """, [row['simbolo']])
                sig = cur.fetchone()
            except Exception:
                return _jresp(None)
    if not sig:
        return _jresp(None)
    sig['fecha'] = str(sig['fecha'])
    if sig.get('high_52w_date'):
        sig['high_52w_date'] = str(sig['high_52w_date'])
    if sig.get('high_all_date'):
        sig['high_all_date'] = str(sig['high_all_date'])
    for k in ('price', 'high_52w', 'distance_52w_pct', 'high_all',
              'distance_all_pct', 'rsi14', 'mom20', 'sma200'):
        if sig.get(k) is not None:
            sig[k] = float(sig[k])
    sig['is_all_time_high'] = bool(sig.get('is_all_time_high'))
    return _jresp(sig)


# ── /api/assets/<id>/company-info ─────────────────────────────────────────────
#
# Información fundamental de la empresa: perfil, salud financiera, crecimiento,
# último balance.  Fuente: Yahoo Finance quoteSummary (sin API key).
# Cache en memoria con TTL 6h para no abusar del endpoint público.

_company_cache: dict = {}        # symbol → {'data': dict, 'ts': float}
_company_lock = threading.Lock()
_COMPANY_TTL  = 6 * 3600         # 6 horas

_YF_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
}

_YF_MODULES = (
    'summaryProfile,financialData,defaultKeyStatistics,'
    'earnings,incomeStatementHistory,price'
)


def _yf_quote_summary(symbol: str) -> dict | None:
    """Llama al endpoint público quoteSummary de Yahoo Finance."""
    import requests
    url = f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}'
    try:
        resp = requests.get(
            url,
            params={'modules': _YF_MODULES},
            headers=_YF_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        result = payload.get('quoteSummary', {}).get('result') or []
        return result[0] if result else None
    except Exception:
        return None


def _yf_num(node, key):
    """Yahoo devuelve {'raw': X, 'fmt': 'X%'} o números planos. Normaliza a float|None."""
    if node is None:
        return None
    val = node.get(key)
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get('raw')
    return val


def _build_company_info(symbol: str, raw: dict | None) -> dict:
    if not raw:
        return {'symbol': symbol, 'status': 'NO_DATA'}

    profile = raw.get('summaryProfile') or {}
    fin     = raw.get('financialData') or {}
    keys    = raw.get('defaultKeyStatistics') or {}
    earn    = raw.get('earnings') or {}
    income  = raw.get('incomeStatementHistory') or {}
    price_m = raw.get('price') or {}

    # Earnings yearly (último balance anual)
    yearly_chart = (earn.get('financialsChart') or {}).get('yearly') or []
    yearly = [
        {
            'year':    y.get('date'),
            'revenue': _yf_num(y, 'revenue'),
            'earnings': _yf_num(y, 'earnings'),
        }
        for y in yearly_chart
    ]

    # Income statements (últimos 4 balances)
    statements_raw = income.get('incomeStatementHistory') or []
    statements = []
    for s in statements_raw[:4]:
        statements.append({
            'end_date':         (s.get('endDate') or {}).get('fmt'),
            'total_revenue':    _yf_num(s, 'totalRevenue'),
            'gross_profit':     _yf_num(s, 'grossProfit'),
            'operating_income': _yf_num(s, 'operatingIncome'),
            'net_income':       _yf_num(s, 'netIncome'),
            'ebit':             _yf_num(s, 'ebit'),
        })

    # Health score heurístico simple (0–100)
    profit_margin = _yf_num(fin, 'profitMargins')
    roe           = _yf_num(fin, 'returnOnEquity')
    debt_eq       = _yf_num(fin, 'debtToEquity')
    current_ratio = _yf_num(fin, 'currentRatio')
    rev_growth    = _yf_num(fin, 'revenueGrowth')
    earn_growth   = _yf_num(fin, 'earningsGrowth')

    score = 0
    score_pts = 0
    def _bump(cond_pts, total_pts):
        nonlocal score, score_pts
        score += cond_pts
        score_pts += total_pts
    if profit_margin is not None:
        _bump(20 if profit_margin >= 0.10 else (10 if profit_margin > 0 else 0), 20)
    if roe is not None:
        _bump(20 if roe >= 0.15 else (10 if roe > 0 else 0), 20)
    if debt_eq is not None:
        # debtToEquity en yahoo viene en %, ej. 50 = 0.5x
        norm = debt_eq / 100 if debt_eq > 5 else debt_eq
        _bump(20 if norm < 1 else (10 if norm < 2 else 0), 20)
    if current_ratio is not None:
        _bump(20 if current_ratio >= 1.5 else (10 if current_ratio >= 1 else 0), 20)
    if rev_growth is not None:
        _bump(20 if rev_growth >= 0.10 else (10 if rev_growth > 0 else 0), 20)

    health_score = round(score / score_pts * 100) if score_pts else None
    if health_score is None:
        health_label = 'sin datos'
    elif health_score >= 70:
        health_label = 'sólida'
    elif health_score >= 45:
        health_label = 'aceptable'
    else:
        health_label = 'débil'

    return {
        'symbol': symbol,
        'status': 'OK',
        'profile': {
            'long_name':    price_m.get('longName') or profile.get('longBusinessSummary', '')[:80],
            'sector':       profile.get('sector'),
            'industry':     profile.get('industry'),
            'website':      profile.get('website'),
            'country':      profile.get('country'),
            'employees':    profile.get('fullTimeEmployees'),
            'description':  profile.get('longBusinessSummary'),
        },
        'health': {
            'score':         health_score,
            'label':         health_label,
            'profit_margin': profit_margin,
            'roe':           roe,
            'debt_to_equity': debt_eq,
            'current_ratio': current_ratio,
            'free_cashflow': _yf_num(fin, 'freeCashflow'),
            'total_cash':    _yf_num(fin, 'totalCash'),
            'total_debt':    _yf_num(fin, 'totalDebt'),
        },
        'growth': {
            'revenue_growth':  rev_growth,
            'earnings_growth': earn_growth,
        },
        'valuation': {
            'trailing_pe':  _yf_num(keys, 'trailingPE') or _yf_num(fin, 'trailingPE'),
            'forward_pe':   _yf_num(keys, 'forwardPE'),
            'peg_ratio':    _yf_num(keys, 'pegRatio'),
            'price_to_book': _yf_num(keys, 'priceToBook'),
            'market_cap':   _yf_num(price_m, 'marketCap'),
        },
        'analyst': {
            'recommendation':    fin.get('recommendationKey'),
            'target_mean_price': _yf_num(fin, 'targetMeanPrice'),
            'number_of_analysts': _yf_num(fin, 'numberOfAnalystOpinions'),
        },
        'earnings_yearly': yearly,
        'income_statements': statements,
    }


@app.route('/api/assets/<int:accion_id>/company-info')
def get_company_info(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()
    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _company_lock:
        entry = _company_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _COMPANY_TTL:
            return _jresp(entry['data'])

    raw  = _yf_quote_summary(symbol)
    data = _build_company_info(symbol, raw)

    with _company_lock:
        _company_cache[symbol] = {'data': data, 'ts': time.time()}

    return _jresp(data)


# ── /api/assets/<id>/fundamentals ─────────────────────────────────────────────
#
# Métricas financieras puras (separadas de company-info que es perfil + scoring).
# Foco: revenue/earnings TTM, márgenes, deuda, growth, valuación, dividendos,
# fechas próximas de earnings.  Cache 6h.

_fund_cache: dict = {}        # symbol → {'data': dict, 'ts': float}
_fund_lock  = threading.Lock()
_FUND_TTL   = 6 * 3600

_FUND_MODULES = (
    'financialData,defaultKeyStatistics,summaryDetail,price,calendarEvents'
)


def _yf_fundamentals(symbol: str) -> dict | None:
    """quoteSummary con módulos financieros + calendar."""
    import requests
    url = f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}'
    try:
        resp = requests.get(
            url,
            params={'modules': _FUND_MODULES},
            headers=_YF_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        result  = payload.get('quoteSummary', {}).get('result') or []
        return result[0] if result else None
    except Exception:
        return None


def _build_fundamentals(symbol: str, raw: dict | None) -> dict:
    base = {
        'symbol': symbol,
        'market_cap': None, 'currency': None,
        'revenue_ttm': None, 'gross_margin': None,
        'operating_margin': None, 'profit_margin': None,
        'net_income_ttm': None,
        'total_cash': None, 'total_debt': None, 'debt_to_equity': None,
        'revenue_growth_yoy': None, 'earnings_growth_yoy': None,
        'trailing_pe': None, 'forward_pe': None,
        'price_to_book': None, 'ev_to_ebitda': None,
        'dividend_yield': None, 'dividend_rate': None,
        'last_earnings_date': None, 'next_earnings_date': None,
        'updated_at': int(time.time()),
    }
    if not raw:
        return base

    fin     = raw.get('financialData')        or {}
    keys    = raw.get('defaultKeyStatistics') or {}
    summ    = raw.get('summaryDetail')        or {}
    price_m = raw.get('price')                or {}
    cal     = raw.get('calendarEvents')       or {}

    base['currency']    = price_m.get('currency')
    base['market_cap']  = _yf_num(price_m, 'marketCap') or _yf_num(summ, 'marketCap')
    base['revenue_ttm'] = _yf_num(fin, 'totalRevenue')
    base['gross_margin']     = _yf_num(fin, 'grossMargins')
    base['operating_margin'] = _yf_num(fin, 'operatingMargins')
    base['profit_margin']    = _yf_num(fin, 'profitMargins')
    base['net_income_ttm']   = _yf_num(keys, 'netIncomeToCommon')
    base['total_cash']       = _yf_num(fin, 'totalCash')
    base['total_debt']       = _yf_num(fin, 'totalDebt')

    debt_eq = _yf_num(fin, 'debtToEquity')
    if debt_eq is not None and debt_eq > 5:
        debt_eq = debt_eq / 100   # yahoo a veces lo da en %
    base['debt_to_equity'] = debt_eq

    base['revenue_growth_yoy']  = _yf_num(fin, 'revenueGrowth')
    base['earnings_growth_yoy'] = _yf_num(fin, 'earningsGrowth')

    base['trailing_pe']  = _yf_num(summ, 'trailingPE')  or _yf_num(keys, 'trailingPE')
    base['forward_pe']   = _yf_num(summ, 'forwardPE')   or _yf_num(keys, 'forwardPE')
    base['price_to_book'] = _yf_num(keys, 'priceToBook')
    base['ev_to_ebitda']  = _yf_num(keys, 'enterpriseToEbitda')

    base['dividend_yield'] = _yf_num(summ, 'dividendYield')
    base['dividend_rate']  = _yf_num(summ, 'dividendRate')

    # Fechas earnings
    earnings = cal.get('earnings') or {}
    earn_dates = earnings.get('earningsDate') or []
    if isinstance(earn_dates, list) and earn_dates:
        first = earn_dates[0]
        if isinstance(first, dict) and first.get('fmt'):
            base['next_earnings_date'] = first['fmt']
    last_earn = keys.get('lastFiscalYearEnd') or {}
    if isinstance(last_earn, dict) and last_earn.get('fmt'):
        base['last_earnings_date'] = last_earn['fmt']

    return base


@app.route('/api/assets/<int:accion_id>/fundamentals')
def get_fundamentals(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()
    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _fund_lock:
        entry = _fund_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _FUND_TTL:
            return _jresp(entry['data'])

    raw  = _yf_fundamentals(symbol)
    data = _build_fundamentals(symbol, raw)

    with _fund_lock:
        _fund_cache[symbol] = {'data': data, 'ts': time.time()}

    return _jresp(data)


# ── /api/notifications ────────────────────────────────────────────────────────
#
# Feed unificado de notificaciones generadas por los batches.
#  GET  /api/notifications?limit=50&kind=close
#  POST /api/notifications/<id>/read

@app.route('/api/notifications')
@login_required
def get_notifications():
    limit = min(int(request.args.get('limit', 50)), 200)
    kind  = request.args.get('kind', '').strip()

    with _conn() as conn:
        with conn.cursor() as cur:
            if kind:
                cur.execute("""
                    SELECT id, batch_run_id, kind, title, body, data_json, created_at, read_at
                    FROM notification
                    WHERE kind = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, [kind, limit])
            else:
                cur.execute("""
                    SELECT id, batch_run_id, kind, title, body, data_json, created_at, read_at
                    FROM notification
                    ORDER BY created_at DESC
                    LIMIT %s
                """, [limit])
            rows = cur.fetchall()

    # Parsear data_json para que el frontend reciba un objeto, no un string
    for r in rows:
        if r.get('data_json'):
            try:
                r['data'] = json.loads(r['data_json'])
            except Exception:
                r['data'] = None
        else:
            r['data'] = None
        r.pop('data_json', None)

    return _jresp({'items': rows})


@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notification SET read_at = NOW() WHERE id = %s AND read_at IS NULL",
                [notif_id],
            )
        conn.commit()
    return _jresp({'ok': True})


@app.route('/api/notifications/unread-count')
@login_required
def get_unread_count():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM notification WHERE read_at IS NULL")
            n = cur.fetchone()['n']
    return _jresp({'unread': n})


# ── Backtest: rotación semanal ────────────────────────────────────────────────

@app.route('/api/backtest/rotation')
@login_required
def get_backtest_rotation():
    """
    Backtest de la estrategia de rotación semanal vs SPY buy & hold.

    Query params (todos opcionales):
        start          ISO date (YYYY-MM-DD), default = end - 365 días
        end            ISO date, default = hoy
        capital        float, default 10000
        fee            float (ratio), default 0.0005
        max_universe   int, default 500 — top N por liquidez (perf)
        top_keep       int, default 10
        rotate_diff    float, default 15.0
        mode           'top1' | 'top3_equal', default 'top1'
        regime_filter  bool, default true (filtra cuando SPY < SMA200)
        min_price      float, default 10.0
        min_avg_vol    float, default 1_000_000

    Devuelve dict completo con config, period, history, equity_curve,
    metrics y summary. Pensado para alimentar /backtest/rotation en frontend.
    """
    from strategies.rotation import RotationBacktest, VALID_MODES

    def _qd(name):
        v = request.args.get(name)
        if not v:
            return None
        try:
            return datetime.datetime.strptime(v, '%Y-%m-%d').date()
        except ValueError:
            return None

    def _qf(name, default):
        v = request.args.get(name)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _qi(name, default):
        v = request.args.get(name)
        try:
            return int(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _qb(name, default):
        v = request.args.get(name)
        if v is None:
            return default
        return v.strip().lower() in ('1', 'true', 'yes', 'on', 't')

    mode = (request.args.get('mode') or 'top1').strip().lower()
    if mode not in VALID_MODES:
        return _jresp({'error': f'mode inválido. Válidos: {list(VALID_MODES)}'}, 400)

    bt = RotationBacktest(
        initial_capital=_qf('capital', 10000.0),
        fee_rate       =_qf('fee',     0.0005),
        top_keep       =_qi('top_keep', 10),
        rotate_diff    =_qf('rotate_diff', 15.0),
        max_universe   =_qi('max_universe', 500),
        mode           =mode,
        regime_filter  =_qb('regime_filter', True),
        min_price      =_qf('min_price', 10.0),
        min_avg_vol    =_qf('min_avg_vol', 1_000_000),
    )
    try:
        result = bt.run(_qd('start'), _qd('end'))
    except Exception as e:
        return _jresp({'error': str(e)}, 500)
    return _jresp(result)


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


# ── Bootstrap (corre al import del módulo, ej. bajo gunicorn) ─────────────────
# Las migraciones son idempotentes (CREATE TABLE IF NOT EXISTS / ALTER ... IF
# NOT COLUMN), así que es seguro ejecutarlas en cada arranque/worker.
try:
    _ensure_users_table()
    _ensure_batch_tables()
except Exception as _bootstrap_err:
    print(f' * WARN bootstrap migrations: {_bootstrap_err}')


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
