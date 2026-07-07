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
import re
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

# ── Caché para dynamic-resistances ────────────────────────────────────────────

_dynres_cache: dict = {}         # symbol → {'data': dict, 'ts': float}
_dynres_lock = threading.Lock()
_DYNRES_TTL  = 3600              # 1 hora

# ── Caché para channel-breakdown ──────────────────────────────────────────────

_chbd_cache: dict = {}           # symbol → {'data': dict, 'ts': float}
_chbd_lock = threading.Lock()
_CHBD_TTL  = 3600                # 1 hora

# ── Caché para sr-v2 ──────────────────────────────────────────────────────────

_srv2_cache: dict = {}           # symbol → {'data': dict, 'ts': float}
_srv2_lock = threading.Lock()
_SRV2_TTL  = 3600                # 1 hora

# ── Caché para tiered-sr ──────────────────────────────────────────────────────

_tiered_cache: dict = {}         # symbol → {'data': dict, 'ts': float}
_tiered_lock = threading.Lock()
_TIERED_TTL  = 3600              # 1 hora

# ── Caché para ut-bot ─────────────────────────────────────────────────────────

_utbot_cache: dict = {}          # (symbol, sensitivity, atr_period) → {'data': dict, 'ts': float}
_utbot_lock = threading.Lock()
_UTBOT_TTL  = 3600               # 1 hora

# ── Caché para pivots ─────────────────────────────────────────────────────────

_pivots_cache: dict = {}         # "symbol_tf" → {'data': dict, 'ts': float}
_pivots_lock = threading.Lock()
_PIVOTS_TTL  = 3600              # 1 hora

# ── Caché para elliott ────────────────────────────────────────────────────────

_elliott_cache: dict = {}        # symbol → {'data': dict, 'ts': float}
_elliott_lock = threading.Lock()
_ELLIOTT_TTL  = 1800             # 30 minutos

# ── Caché para accelerated-trendlines ────────────────────────────────────────

_accel_cache: dict = {}          # "symbol_tf" → {'data': dict, 'ts': float}
_accel_lock = threading.Lock()
_ACCEL_TTL  = 3600               # 1 hora

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

_BCRYPT_ROUNDS = 10

def _hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


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
            # Migración idempotente: columnas de señales por usuario
            for col, ddl in [
                ('user_id',          'INT NULL'),
                ('accion_id',        'INT NULL'),
                ('signal_code',      'VARCHAR(40) NULL'),
                ('signal_direction', 'VARCHAR(10) NULL'),
            ]:
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'notification'
                      AND COLUMN_NAME = %s
                """, [col])
                if cur.fetchone()['cnt'] == 0:
                    cur.execute(f"ALTER TABLE notification ADD COLUMN {col} {ddl}")
                    print(f' * Columna notification.{col} creada')
            # Índice compuesto para filtrar por user rápido
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'notification'
                  AND INDEX_NAME = 'idx_notif_user_created'
            """)
            if cur.fetchone()['cnt'] == 0:
                cur.execute("CREATE INDEX idx_notif_user_created ON notification (user_id, created_at)")
                print(' * Índice notification.idx_notif_user_created creado')
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


def _ensure_watchlist_table():
    """Watchlist por usuario (idempotente)."""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlist (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    user_id       INT           NOT NULL,
                    accion_id     INT           NOT NULL,
                    qty           DECIMAL(20,6) NULL,
                    avg_buy_price DECIMAL(20,6) NULL,
                    stop_loss     DECIMAL(20,6) NULL,
                    take_profit   DECIMAL(20,6) NULL,
                    note          VARCHAR(500)  NULL,
                    added_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_user_accion (user_id, accion_id),
                    INDEX idx_user (user_id),
                    CONSTRAINT fk_uw_user   FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_uw_accion FOREIGN KEY (accion_id) REFERENCES accion(id) ON DELETE CASCADE
                )
            """)
            for col in ('stop_loss', 'take_profit'):
                cur.execute(f"""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = 'user_watchlist' AND column_name = '{col}'
                """)
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE user_watchlist ADD COLUMN {col} DECIMAL(20,6) NULL AFTER avg_buy_price")
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = DATABASE() AND table_name = 'user_watchlist' AND column_name = 'telegram_alerts'
            """)
            if not cur.fetchone():
                cur.execute("ALTER TABLE user_watchlist ADD COLUMN telegram_alerts TINYINT(1) NOT NULL DEFAULT 0")
                print(' * Columna user_watchlist.telegram_alerts creada')
        conn.commit()
    finally:
        conn.close()


def _ensure_trades_table():
    """Log de movimientos (compras/ventas) por usuario. Idempotente."""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_trades (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    user_id     INT           NOT NULL,
                    accion_id   INT           NOT NULL,
                    qty         DECIMAL(20,6) NOT NULL,
                    buy_price   DECIMAL(20,6) NOT NULL,
                    buy_date    DATE          NOT NULL,
                    sell_price  DECIMAL(20,6) NULL,
                    sell_date   DATE          NULL,
                    fee         DECIMAL(20,6) NOT NULL DEFAULT 0,
                    note        VARCHAR(500)  NULL,
                    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ut_user (user_id),
                    INDEX idx_ut_user_accion (user_id, accion_id),
                    CONSTRAINT fk_ut_user   FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_ut_accion FOREIGN KEY (accion_id) REFERENCES accion(id) ON DELETE CASCADE
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _ensure_price_levels_table():
    """Niveles de precio dibujados por usuario sobre un gráfico (idempotente)."""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_price_levels (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_id    INT           NOT NULL,
                    accion_id  INT           NOT NULL,
                    price      DECIMAL(20,6) NOT NULL,
                    kind       VARCHAR(20)   NOT NULL DEFAULT 'support',
                    label      VARCHAR(120)  NULL,
                    created_at TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_upl_user_accion (user_id, accion_id),
                    CONSTRAINT fk_upl_user   FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_upl_accion FOREIGN KEY (accion_id) REFERENCES accion(id) ON DELETE CASCADE
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _ensure_trendlines_table():
    """Trendlines (N puntos, N>=2) dibujadas por usuario. Idempotente.

    Columnas `t1/p1/t2/p2` = primero/último punto (para índice + back-compat).
    `points_json` contiene el polyline completo [{t,p}, ...] cuando N>2;
    cuando N=2 puede ser NULL (se reconstruye desde t1/p1/t2/p2)."""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_trendlines (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    user_id     INT           NOT NULL,
                    accion_id   INT           NOT NULL,
                    t1          VARCHAR(10)   NOT NULL,
                    p1          DECIMAL(20,6) NOT NULL,
                    t2          VARCHAR(10)   NOT NULL,
                    p2          DECIMAL(20,6) NOT NULL,
                    points_json TEXT          NULL,
                    kind        VARCHAR(20)   NOT NULL DEFAULT 'support',
                    label       VARCHAR(120)  NULL,
                    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_utl_user_accion (user_id, accion_id),
                    CONSTRAINT fk_utl_user   FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,
                    CONSTRAINT fk_utl_accion FOREIGN KEY (accion_id) REFERENCES accion(id) ON DELETE CASCADE
                )
            """)
            # ALTER idempotente para filas viejas (rama N=2 previa): agrega
            # points_json si no existe. MySQL <8.0.29 no tiene IF NOT EXISTS
            # en ADD COLUMN, así que probamos y tragamos el error si ya está.
            try:
                cur.execute("ALTER TABLE user_trendlines ADD COLUMN points_json TEXT NULL AFTER p2")
            except Exception:
                pass
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
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, investor_profile FROM users WHERE username = %s",
                (username,),
            )
            user = cur.fetchone()
    if not user or not _check_pw(password, user['password_hash']):
        return jsonify({'error': 'Credenciales incorrectas'}), 401
    if user['password_hash'].startswith('$2b$12$'):
        new_hash = _hash_pw(password)
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                            (new_hash, user['id']))
            conn.commit()
    token = _make_token(user['id'], user['username'])
    return jsonify({
        'token': token,
        'username': user['username'],
        'investor_profile': user.get('investor_profile'),
    })


@app.route('/api/auth/me', methods=['GET'])
@login_required
def auth_me():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, investor_profile FROM users WHERE id = %s",
                (request.user['sub'],),
            )
            row = cur.fetchone() or {}
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
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET investor_profile = %s WHERE id = %s",
                (profile, request.user['sub']),
            )
        conn.commit()
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
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", (request.user['sub'],))
            user = cur.fetchone()
            if not user or not _check_pw(current, user['password_hash']):
                return jsonify({'error': 'Contraseña actual incorrecta'}), 401
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                        (_hash_pw(new_pw), request.user['sub']))
        conn.commit()
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


# ── DB connection pool ─────────────────────────────────────────────────────────

import queue as _queue

_pool = _queue.Queue(maxsize=0)
_POOL_MAX = 8

class _PooledConn:
    """Context manager that returns connections to pool instead of closing."""
    __slots__ = ('conn', '_returned')

    def __init__(self, conn):
        self.conn = conn
        self._returned = False

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._return()

    def close(self):
        self._return()

    def _return(self):
        if self._returned:
            return
        self._returned = True
        try:
            self.conn.ping(reconnect=True)
            _pool.put_nowait(self.conn)
        except Exception:
            try:
                self.conn.close()
            except Exception:
                pass

def _conn():
    try:
        conn = _pool.get_nowait()
        conn.ping(reconnect=True)
        return _PooledConn(conn)
    except (_queue.Empty, Exception):
        return _PooledConn(pymysql.connect(**MYSQL_CONFIG))


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
    search_up = search.upper().strip()
    s_order      = "(CASE WHEN UPPER(simbolo) = %s THEN 0 WHEN UPPER(simbolo) LIKE %s THEN 1 ELSE 2 END), simbolo" if search else "ABS(pct_cambio) DESC, simbolo"
    s_order_full = "(CASE WHEN UPPER(a.simbolo) = %s THEN 0 WHEN UPPER(a.simbolo) LIKE %s THEN 1 ELSE 2 END), a.simbolo" if search else "ABS(pct_cambio) DESC, a.simbolo"
    opt_order    = [search_up, f"{search_up}%"] if search else []

    s_clause   = "AND (UPPER(a.simbolo) LIKE %s OR LOWER(a.nombre) LIKE %s)" if search else ""
    opt_search = [f"%{search_up}%", f"%{search.lower().strip()}%"] if search else []

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

    # ── Staleness detection (solo para timeframe D) ──
    stale = False
    last_date = None
    if tf == 'D' and rows:
        last_date = rows[-1]['fecha']          # ya es str, sorted ASC
        try:
            ld = datetime.date.fromisoformat(last_date)
            today = datetime.date.today()
            # Contar días de negociación (lun-vie) entre last_date y hoy
            bdays = 0
            d = ld + datetime.timedelta(days=1)
            while d <= today:
                if d.weekday() < 5:            # 0=lun … 4=vie
                    bdays += 1
                d += datetime.timedelta(days=1)
            stale = bdays > 1
        except Exception:
            pass

    return _jresp({
        'accion_id': accion_id, 'simbolo': simbolo, 'tf': tf,
        'candles': rows, 'stale': stale, 'last_date': last_date,
    })


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
    tf = request.args.get('tf')

    cache_key = f"{symbol}_{tf or 'auto'}"
    with _dynsup_lock:
        entry = _dynsup_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _DYNSUP_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.dynamic_supports import get_dynamic_supports
        result = get_dynamic_supports(symbol, datetime.date.today(), tf=tf)
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _dynsup_lock:
        _dynsup_cache[cache_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/pivots ──────────────────────────────────────────────────
#
# Devuelve pivot lows y pivot highs detectados sobre el OHLCV del simbolo.
# Son los mismos pivots que usa el algoritmo de soportes/resistencias dinamicas.

@app.route('/api/assets/<int:accion_id>/pivots')
def get_pivots_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']
    tf = (request.args.get('tf') or 'W').strip().upper()
    if tf not in ('D', 'W'):
        tf = 'W'

    cache_key = f"{symbol}_{tf}"
    with _pivots_lock:
        entry = _pivots_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _PIVOTS_TTL:
            return _jresp(entry['data'])

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT fecha, open, high, low, close
                       FROM ohlcv_extended
                       WHERE simbolo = %s AND timeframe = %s
                       ORDER BY fecha ASC""",
                    (symbol, tf),
                )
                rows = cur.fetchall()

        if not rows or len(rows) < 20:
            result = {'symbol': symbol, 'tf': tf, 'pivot_lows': [], 'pivot_highs': []}
        else:
            from strategies.dynamic_supports import _pivot_lows, PIVOT_WIN_W, PIVOT_WIN_W_SML
            from strategies.dynamic_resistances import _pivot_highs

            lows  = [float(r['low'])  for r in rows]
            highs = [float(r['high']) for r in rows]
            base_win = PIVOT_WIN_W if len(rows) >= 400 else PIVOT_WIN_W_SML
            win = int(base_win * 2.5) if tf == 'D' else base_win

            low_idxs  = _pivot_lows(lows, win)
            high_idxs = _pivot_highs(highs, win)

            pivot_lows = [
                {'fecha': str(rows[i]['fecha']), 'value': round(lows[i], 4)}
                for i in low_idxs
            ]
            pivot_highs = [
                {'fecha': str(rows[i]['fecha']), 'value': round(highs[i], 4)}
                for i in high_idxs
            ]
            result = {
                'symbol': symbol,
                'tf': tf,
                'pivot_lows': pivot_lows,
                'pivot_highs': pivot_highs,
            }
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _pivots_lock:
        _pivots_cache[cache_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/dynamic-resistances ──────────────────────────────────────
#
# Resistencias dinamicas descendentes (espejo de dynamic-supports). Devuelve 3
# tiers: long / mid / short para pintar overlays rojo/naranja/magenta.

@app.route('/api/assets/<int:accion_id>/dynamic-resistances')
def get_dynamic_resistances_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    tf_arg = (request.args.get('tf') or '').strip().upper()
    tf = tf_arg if tf_arg in ('D', 'W') else None
    cache_key = f'{symbol}::{tf or "auto"}'

    with _dynres_lock:
        entry = _dynres_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _DYNRES_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.dynamic_resistances import get_dynamic_resistances
        result = get_dynamic_resistances(symbol, datetime.date.today(), tf=tf)
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _dynres_lock:
        _dynres_cache[cache_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/tiered-sr ─────────────────────────────────────────────────
#
# Soportes y resistencias con clasificacion behavioral:
#   historical  — estructural, semanal
#   accelerated — diagonal empinada, diario (cuando hay aceleracion)
#   tactical    — horizontal (lateralizacion)

@app.route('/api/assets/<int:accion_id>/tiered-sr')
def get_tiered_sr_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _tiered_lock:
        entry = _tiered_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _TIERED_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.tiered_sr import get_tiered_sr
        result = get_tiered_sr(symbol, datetime.date.today())
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _tiered_lock:
        _tiered_cache[symbol] = {'data': result, 'ts': time.time()}

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


# ── /api/assets/<id>/channel-breakdown ───────────────────────────────────────
#
# Analiza ruptura de canal: 3 escenarios post-breakdown (Julian).
# Escenario 1: bounce + retest,  2: piso nuevo,  3: breakdown → sell.

@app.route('/api/assets/<int:accion_id>/channel-breakdown')
def get_channel_breakdown_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _chbd_lock:
        entry = _chbd_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _CHBD_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.channel_breakdown import analyze_channel_breakdown
        result = analyze_channel_breakdown(symbol, datetime.date.today())
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _chbd_lock:
        _chbd_cache[symbol] = {'data': result, 'ts': time.time()}

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


# ── /api/assets/<id>/backfill ─────────────────────────────────────────────────
#
# Trigger on-demand para descargar histórico OHLCV de un ticker desde Yahoo.
# Restringido al usuario "albano" (admin). Corre los 3 timeframes (D/W/M)
# sincrono — tarda ~5-15s dependiendo de la cobertura disponible en Yahoo.

@app.route('/api/assets/<int:accion_id>/backfill', methods=['POST'])
@login_required
def backfill_asset(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT simbolo FROM accion WHERE id=%s', [accion_id])
            row = cur.fetchone()
    if not row:
        return _jresp({'error': 'asset not found'}, 404)
    symbol = row['simbolo']

    from scripts.backfill_history import backfill_symbol, ensure_table
    ensure_table()
    out = {}
    for tf in ('D', 'W', 'M'):
        try:
            out[tf] = backfill_symbol(symbol, tf)
        except Exception as e:
            out[tf] = {'error': str(e)}
    # Invalidar caches por simbolo — datos nuevos deben recomputar estrategias.
    for cache, lock in (
        (_ltsupp_cache, _ltsupp_lock),
        (_hzones_cache, _hzones_lock),
        (_channel_cache, _channel_lock),
        (_dynsup_cache,  _dynsup_lock),
        (_utbot_cache,   _utbot_lock),
        (_chbd_cache,    _chbd_lock),
    ):
        with lock:
            for k in list(cache.keys()):
                if k == symbol or (isinstance(k, tuple) and k and k[0] == symbol):
                    cache.pop(k, None)

    # After ohlcv backfill, also update price_history
    from data.data_loader import fetch_price_history, save_asset_prices
    try:
        ph_rows = fetch_price_history(symbol, start_date=datetime.date.today() - datetime.timedelta(days=10))
        if ph_rows:
            save_asset_prices(ph_rows)
            out['price_history'] = {'rows': len(ph_rows)}
    except Exception as e:
        out['price_history'] = {'error': str(e)}

    # Sync valorhistoricoaccion so dashboard price also updates
    try:
        from scripts.sync_price_tables import sync
        sync(full=False)
        out['sync'] = 'ok'
    except Exception as e2:
        out['sync'] = {'error': str(e2)}

    return _jresp({'symbol': symbol, 'results': out})


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
    user_id = request.user['sub']

    # Se ven las notifs globales (user_id NULL) + las propias del usuario.
    params = [user_id]
    where  = '(n.user_id IS NULL OR n.user_id = %s)'
    if kind:
        where += ' AND n.kind = %s'
        params.append(kind)
    params.append(limit)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT n.id, n.batch_run_id, n.kind, n.title, n.body, n.data_json,
                       n.created_at, n.read_at,
                       n.user_id, n.accion_id, n.signal_code, n.signal_direction,
                       a.simbolo AS accion_simbolo
                FROM notification n
                LEFT JOIN accion a ON a.id = n.accion_id
                WHERE {where}
                ORDER BY n.created_at DESC
                LIMIT %s
            """, params)
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
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            # Sólo permite marcar como leída si es global o propia del user
            cur.execute("""
                UPDATE notification SET read_at = NOW()
                WHERE id = %s
                  AND read_at IS NULL
                  AND (user_id IS NULL OR user_id = %s)
            """, [notif_id, user_id])
        conn.commit()
    return _jresp({'ok': True})


@app.route('/api/notifications/unread-count')
@login_required
def get_unread_count():
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS n FROM notification
                WHERE read_at IS NULL
                  AND (user_id IS NULL OR user_id = %s)
            """, [user_id])
            n = cur.fetchone()['n']
    return _jresp({'unread': n})


# ── Watchlist por usuario ─────────────────────────────────────────────────────

def _watchlist_serialize_row(r: dict) -> dict:
    """Calcula campos derivados (P&L, valor corriente, pct día/semana) y tipa decimales."""
    precio      = float(r['precio'])           if r.get('precio')           is not None else None
    precio_prev = float(r['precio_prev'])      if r.get('precio_prev')      is not None else None
    precio_week = float(r['precio_week_ago']) if r.get('precio_week_ago') is not None else None
    qty         = float(r['qty'])              if r.get('qty')              is not None else None
    avg         = float(r['avg_buy_price'])    if r.get('avg_buy_price')    is not None else None

    pct_dia    = round((precio / precio_prev - 1) * 100, 2) if (precio and precio_prev) else None
    pct_semana = round((precio / precio_week - 1) * 100, 2) if (precio and precio_week) else None

    valor_corriente = round(qty * precio, 2) if (qty is not None and precio is not None) else None
    ganancia_abs    = round((precio - avg) * qty, 2)        if (qty is not None and avg is not None and precio is not None) else None
    ganancia_pct    = round((precio / avg - 1) * 100, 2)    if (avg and precio) else None

    sl = float(r['stop_loss'])   if r.get('stop_loss')   is not None else None
    tp = float(r['take_profit']) if r.get('take_profit') is not None else None

    return {
        'id':                r['id'],
        'accion_id':         r['accion_id'],
        'simbolo':           r['simbolo'],
        'nombre':            r['nombre'],
        'mercado':           r['mercado'],
        'qty':               qty,
        'avg_buy_price':     avg,
        'stop_loss':         sl,
        'take_profit':       tp,
        'note':              r.get('note'),
        'precio':            precio,
        'pct_cambio_dia':    pct_dia,
        'pct_cambio_semana': pct_semana,
        'valor_corriente':   valor_corriente,
        'ganancia_abs':      ganancia_abs,
        'ganancia_pct':      ganancia_pct,
        'added_at':          str(r['added_at']) if r.get('added_at') else None,
    }


@app.route('/api/watchlist', methods=['GET'])
@login_required
def get_watchlist():
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT uw.id, uw.accion_id, uw.qty, uw.avg_buy_price, uw.stop_loss, uw.take_profit, uw.note, uw.added_at,
                       a.simbolo, a.nombre, m.descripcion AS mercado,
                       (SELECT v.precio_cierre FROM valorhistoricoaccion v
                        WHERE v.accion_id = uw.accion_id
                        ORDER BY v.fecha DESC LIMIT 1) AS precio,
                       (SELECT v.precio_cierre FROM valorhistoricoaccion v
                        WHERE v.accion_id = uw.accion_id
                        ORDER BY v.fecha DESC LIMIT 1 OFFSET 1) AS precio_prev,
                       (SELECT v.precio_cierre FROM valorhistoricoaccion v
                        WHERE v.accion_id = uw.accion_id
                        ORDER BY v.fecha DESC LIMIT 1 OFFSET 5) AS precio_week_ago
                FROM user_watchlist uw
                JOIN accion a  ON a.id = uw.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE uw.user_id = %s
                ORDER BY uw.added_at DESC
            """, [user_id])
            rows = cur.fetchall()
    return _jresp({'items': [_watchlist_serialize_row(r) for r in rows]})


@app.route('/api/watchlist', methods=['POST'])
@login_required
def add_watchlist():
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}

    try:
        accion_id = int(body.get('accion_id'))
    except (TypeError, ValueError):
        return _jresp({'error': 'accion_id requerido y numérico'}, 400)

    def _parse_num(key):
        v = body.get(key)
        if v is None or v == '':
            return None
        try:
            f = float(v)
            if f < 0:
                return False  # señal de inválido
            return f
        except (TypeError, ValueError):
            return False

    qty = _parse_num('qty')
    avg = _parse_num('avg_buy_price')
    sl  = _parse_num('stop_loss')
    tp  = _parse_num('take_profit')
    if qty is False or avg is False or sl is False or tp is False:
        return _jresp({'error': 'qty, avg_buy_price, stop_loss y take_profit deben ser numéricos no negativos'}, 400)

    note = (body.get('note') or '').strip() or None
    if note and len(note) > 500:
        note = note[:500]

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM accion WHERE id = %s", [accion_id])
            if not cur.fetchone():
                return _jresp({'error': 'accion_id no existe'}, 404)
            cur.execute(
                "SELECT id FROM user_watchlist WHERE user_id = %s AND accion_id = %s",
                [user_id, accion_id],
            )
            if cur.fetchone():
                return _jresp({'error': 'Ya está en la watchlist'}, 409)
            cur.execute("""
                INSERT INTO user_watchlist (user_id, accion_id, qty, avg_buy_price, stop_loss, take_profit, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, [user_id, accion_id, qty, avg, sl, tp, note])
            new_id = cur.lastrowid
        conn.commit()
    return _jresp({'ok': True, 'id': new_id}, 201)


@app.route('/api/watchlist/<int:item_id>', methods=['PATCH'])
@login_required
def update_watchlist(item_id: int):
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}

    updates = []
    params  = []

    if 'qty' in body:
        v = body['qty']
        if v is None or v == '':
            updates.append('qty = NULL')
        else:
            try:
                f = float(v)
                if f < 0:
                    return _jresp({'error': 'qty no puede ser negativa'}, 400)
                updates.append('qty = %s')
                params.append(f)
            except (TypeError, ValueError):
                return _jresp({'error': 'qty debe ser numérica'}, 400)

    if 'avg_buy_price' in body:
        v = body['avg_buy_price']
        if v is None or v == '':
            updates.append('avg_buy_price = NULL')
        else:
            try:
                f = float(v)
                if f < 0:
                    return _jresp({'error': 'avg_buy_price no puede ser negativo'}, 400)
                updates.append('avg_buy_price = %s')
                params.append(f)
            except (TypeError, ValueError):
                return _jresp({'error': 'avg_buy_price debe ser numérico'}, 400)

    for col in ('stop_loss', 'take_profit'):
        if col in body:
            v = body[col]
            if v is None or v == '':
                updates.append(f'{col} = NULL')
            else:
                try:
                    f = float(v)
                    if f < 0:
                        return _jresp({'error': f'{col} no puede ser negativo'}, 400)
                    updates.append(f'{col} = %s')
                    params.append(f)
                except (TypeError, ValueError):
                    return _jresp({'error': f'{col} debe ser numérico'}, 400)

    if 'note' in body:
        note = (body.get('note') or '').strip() or None
        if note and len(note) > 500:
            note = note[:500]
        updates.append('note = %s')
        params.append(note)

    if not updates:
        return _jresp({'error': 'Nada para actualizar'}, 400)

    params.extend([item_id, user_id])
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE user_watchlist SET {', '.join(updates)} WHERE id = %s AND user_id = %s",
                params,
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
        conn.commit()
    return _jresp({'ok': True})


@app.route('/api/watchlist/<int:item_id>', methods=['DELETE'])
@login_required
def delete_watchlist(item_id: int):
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_watchlist WHERE id = %s AND user_id = %s",
                [item_id, user_id],
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
        conn.commit()
    return _jresp({'ok': True})


@app.route('/api/assets/<int:accion_id>/signals')
@login_required
def get_asset_signals(accion_id: int):
    """Notificaciones de estrategia para un ticker específico (últimos 30 días)."""
    user_id = request.user['sub']
    limit = min(int(request.args.get('limit', 30)), 100)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT n.id, n.kind, n.title, n.body, n.signal_code, n.signal_direction,
                       n.created_at, n.read_at
                FROM notification n
                WHERE n.accion_id = %s
                  AND (n.user_id IS NULL OR n.user_id = %s)
                  AND n.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                ORDER BY n.created_at DESC
                LIMIT %s
            """, [accion_id, user_id, limit])
            rows = cur.fetchall()
            cur.execute("""
                SELECT telegram_alerts FROM user_watchlist
                WHERE user_id = %s AND accion_id = %s
            """, [user_id, accion_id])
            wl = cur.fetchone()
    telegram_on = bool(wl['telegram_alerts']) if wl else False
    in_watchlist = wl is not None
    return _jresp({'items': rows, 'telegram_alerts': telegram_on, 'in_watchlist': in_watchlist})


@app.route('/api/assets/<int:accion_id>/telegram-alert', methods=['POST'])
@login_required
def toggle_telegram_alert(accion_id: int):
    """Activa/desactiva alertas Telegram para un ticker en la watchlist."""
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get('enabled', False))
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM user_watchlist WHERE user_id = %s AND accion_id = %s",
                [user_id, accion_id],
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "INSERT INTO user_watchlist (user_id, accion_id, telegram_alerts) VALUES (%s, %s, %s)",
                    [user_id, accion_id, int(enabled)],
                )
            else:
                cur.execute(
                    "UPDATE user_watchlist SET telegram_alerts = %s WHERE id = %s",
                    [int(enabled), row['id']],
                )
        conn.commit()
    return _jresp({'ok': True, 'telegram_alerts': enabled})


# ── Log de movimientos (trades) por usuario ───────────────────────────────────

def _trade_serialize(r: dict) -> dict:
    qty   = float(r['qty'])        if r.get('qty')        is not None else None
    bp    = float(r['buy_price'])  if r.get('buy_price')  is not None else None
    sp    = float(r['sell_price']) if r.get('sell_price') is not None else None
    fee   = float(r['fee'])        if r.get('fee')        is not None else 0.0
    gross = ((sp - bp) * qty) if (sp is not None and bp is not None and qty is not None) else None
    net   = (gross - fee) if gross is not None else None
    pct   = ((sp / bp - 1) * 100) if (sp is not None and bp) else None
    return {
        'id':          r['id'],
        'accion_id':   r['accion_id'],
        'simbolo':     r.get('simbolo'),
        'nombre':      r.get('nombre'),
        'mercado':     r.get('mercado'),
        'qty':         qty,
        'buy_price':   bp,
        'buy_date':    str(r['buy_date'])  if r.get('buy_date')  else None,
        'sell_price':  sp,
        'sell_date':   str(r['sell_date']) if r.get('sell_date') else None,
        'fee':         fee,
        'note':        r.get('note'),
        'gross_pnl':   round(gross, 2) if gross is not None else None,
        'net_pnl':     round(net,   2) if net   is not None else None,
        'pct':         round(pct,   2) if pct   is not None else None,
        'created_at':  str(r['created_at']) if r.get('created_at') else None,
    }


def _parse_trade_body(body: dict, partial: bool = False):
    """Valida el body de un trade. Devuelve (fields_dict, error_resp_or_None)."""
    fields: dict = {}

    if 'accion_id' in body or not partial:
        try:
            fields['accion_id'] = int(body.get('accion_id'))
        except (TypeError, ValueError):
            return None, _jresp({'error': 'accion_id requerido y numérico'}, 400)

    def _num(key, required=False, allow_null=False):
        if key not in body:
            if required and not partial:
                return None, _jresp({'error': f'{key} requerido'}, 400)
            return '__skip__', None
        v = body.get(key)
        if v is None or v == '':
            if allow_null:
                return None, None
            if required and not partial:
                return None, _jresp({'error': f'{key} requerido'}, 400)
            return None, None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None, _jresp({'error': f'{key} debe ser numérico'}, 400)
        if f < 0:
            return None, _jresp({'error': f'{key} no puede ser negativo'}, 400)
        return f, None

    for key, required, allow_null in [
        ('qty',        True,  False),
        ('buy_price',  True,  False),
        ('sell_price', False, True),
        ('fee',        False, False),
    ]:
        val, err = _num(key, required=required, allow_null=allow_null)
        if err:
            return None, err
        if val == '__skip__':
            continue
        fields[key] = val

    def _date(key, required=False, allow_null=False):
        if key not in body:
            if required and not partial:
                return '__missing__'
            return '__skip__'
        v = body.get(key)
        if v is None or v == '':
            if allow_null:
                return None
            if required and not partial:
                return '__missing__'
            return None
        try:
            return datetime.datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
        except ValueError:
            return '__invalid__'

    for key, required, allow_null in [
        ('buy_date',  True,  False),
        ('sell_date', False, True),
    ]:
        d = _date(key, required=required, allow_null=allow_null)
        if d == '__missing__':
            return None, _jresp({'error': f'{key} requerido (formato YYYY-MM-DD)'}, 400)
        if d == '__invalid__':
            return None, _jresp({'error': f'{key} inválido (formato YYYY-MM-DD)'}, 400)
        if d == '__skip__':
            continue
        fields[key] = d

    if 'note' in body:
        note = (body.get('note') or '').strip() or None
        if note and len(note) > 500:
            note = note[:500]
        fields['note'] = note

    if 'fee' not in fields and not partial:
        fields['fee'] = 0.0

    # sell_price y sell_date van de la mano — si hay uno debe haber otro
    sp_present = 'sell_price' in fields and fields['sell_price'] is not None
    sd_present = 'sell_date'  in fields and fields['sell_date']  is not None
    if sp_present != sd_present and not partial:
        return None, _jresp({'error': 'sell_price y sell_date deben ir juntos'}, 400)

    return fields, None


@app.route('/api/trades', methods=['GET'])
@login_required
def get_trades():
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ut.id, ut.accion_id, ut.qty, ut.buy_price, ut.buy_date,
                       ut.sell_price, ut.sell_date, ut.fee, ut.note, ut.created_at,
                       a.simbolo, a.nombre, m.descripcion AS mercado
                FROM user_trades ut
                JOIN accion a  ON a.id = ut.accion_id
                JOIN mercado m ON m.id = a.mercado_id
                WHERE ut.user_id = %s
                ORDER BY ut.buy_date DESC, ut.id DESC
            """, [user_id])
            rows = cur.fetchall()
    return _jresp({'items': [_trade_serialize(r) for r in rows]})


@app.route('/api/trades', methods=['POST'])
@login_required
def add_trade():
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    fields, err = _parse_trade_body(body, partial=False)
    if err:
        return err
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM accion WHERE id = %s", [fields['accion_id']])
            if not cur.fetchone():
                return _jresp({'error': 'accion_id no existe'}, 404)
            cur.execute("""
                INSERT INTO user_trades (user_id, accion_id, qty, buy_price, buy_date,
                                         sell_price, sell_date, fee, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [
                user_id,
                fields['accion_id'],
                fields['qty'],
                fields['buy_price'],
                fields['buy_date'],
                fields.get('sell_price'),
                fields.get('sell_date'),
                fields.get('fee', 0.0),
                fields.get('note'),
            ])
            new_id = cur.lastrowid
        conn.commit()
    return _jresp({'ok': True, 'id': new_id}, 201)


@app.route('/api/trades/<int:trade_id>', methods=['PATCH'])
@login_required
def update_trade(trade_id: int):
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    fields, err = _parse_trade_body(body, partial=True)
    if err:
        return err
    # accion_id no se puede modificar tras creado
    fields.pop('accion_id', None)
    if not fields:
        return _jresp({'error': 'Nada para actualizar'}, 400)

    sets, params = [], []
    for k, v in fields.items():
        sets.append(f'{k} = %s')
        params.append(v)
    params.extend([trade_id, user_id])

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE user_trades SET {', '.join(sets)} WHERE id = %s AND user_id = %s",
                params,
            )
            if cur.rowcount == 0:
                # rowcount puede ser 0 si no cambió nada — verificamos existencia
                cur.execute(
                    "SELECT id FROM user_trades WHERE id = %s AND user_id = %s",
                    [trade_id, user_id],
                )
                if not cur.fetchone():
                    return _jresp({'error': 'No encontrado'}, 404)
        conn.commit()
    return _jresp({'ok': True})


@app.route('/api/trades/<int:trade_id>', methods=['DELETE'])
@login_required
def delete_trade(trade_id: int):
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_trades WHERE id = %s AND user_id = %s",
                [trade_id, user_id],
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
        conn.commit()
    return _jresp({'ok': True})


# ── Niveles dibujados por el usuario sobre el chart ───────────────────────────

_PRICE_LEVEL_KINDS = {'support', 'resistance', 'target', 'note'}


def _price_level_serialize(r: dict) -> dict:
    return {
        'id':         r['id'],
        'accion_id':  r['accion_id'],
        'price':      float(r['price']) if r['price'] is not None else None,
        'kind':       r['kind'],
        'label':      r.get('label'),
        'created_at': str(r['created_at']) if r.get('created_at') else None,
    }


@app.route('/api/price-levels', methods=['GET'])
@login_required
def get_price_levels():
    user_id = request.user['sub']
    try:
        accion_id = int(request.args.get('accion_id') or 0)
    except ValueError:
        return _jresp({'error': 'accion_id inválido'}, 400)
    if accion_id <= 0:
        return _jresp({'error': 'accion_id requerido'}, 400)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, accion_id, price, kind, label, created_at
                FROM user_price_levels
                WHERE user_id = %s AND accion_id = %s
                ORDER BY price DESC
            """, [user_id, accion_id])
            rows = cur.fetchall() or []
    return _jresp({'items': [_price_level_serialize(r) for r in rows]})


@app.route('/api/price-levels', methods=['POST'])
@login_required
def create_price_level():
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    try:
        accion_id = int(body.get('accion_id') or 0)
        price     = float(body.get('price'))
    except (TypeError, ValueError):
        return _jresp({'error': 'accion_id y price requeridos'}, 400)
    if accion_id <= 0 or price <= 0:
        return _jresp({'error': 'accion_id y price deben ser > 0'}, 400)
    kind  = (body.get('kind') or 'support').strip().lower()
    if kind not in _PRICE_LEVEL_KINDS:
        return _jresp({'error': f'kind debe ser uno de: {sorted(_PRICE_LEVEL_KINDS)}'}, 400)
    label = (body.get('label') or None)
    if label and len(label) > 120:
        label = label[:120]
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM accion WHERE id = %s", [accion_id])
            if not cur.fetchone():
                return _jresp({'error': 'accion no existe'}, 404)
            cur.execute("""
                INSERT INTO user_price_levels (user_id, accion_id, price, kind, label)
                VALUES (%s, %s, %s, %s, %s)
            """, [user_id, accion_id, price, kind, label])
            new_id = cur.lastrowid
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, accion_id, price, kind, label, created_at
                FROM user_price_levels WHERE id = %s
            """, [new_id])
            row = cur.fetchone()
    return _jresp({'item': _price_level_serialize(row)}, 201)


@app.route('/api/price-levels/<int:level_id>', methods=['PATCH'])
@login_required
def update_price_level(level_id: int):
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    updates, params = [], []
    if 'price' in body:
        try:
            p = float(body['price'])
            if p <= 0:
                return _jresp({'error': 'price debe ser > 0'}, 400)
            updates.append('price = %s'); params.append(p)
        except (TypeError, ValueError):
            return _jresp({'error': 'price inválido'}, 400)
    if 'kind' in body:
        k = (body.get('kind') or '').strip().lower()
        if k not in _PRICE_LEVEL_KINDS:
            return _jresp({'error': f'kind debe ser uno de: {sorted(_PRICE_LEVEL_KINDS)}'}, 400)
        updates.append('kind = %s'); params.append(k)
    if 'label' in body:
        lbl = body.get('label')
        if lbl is not None and len(lbl) > 120:
            lbl = lbl[:120]
        updates.append('label = %s'); params.append(lbl)
    if not updates:
        return _jresp({'error': 'nada para actualizar'}, 400)
    params.extend([level_id, user_id])
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE user_price_levels SET {', '.join(updates)} WHERE id = %s AND user_id = %s",
                params,
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
            cur.execute("""
                SELECT id, accion_id, price, kind, label, created_at
                FROM user_price_levels WHERE id = %s
            """, [level_id])
            row = cur.fetchone()
        conn.commit()
    return _jresp({'item': _price_level_serialize(row)})


@app.route('/api/price-levels/<int:level_id>', methods=['DELETE'])
@login_required
def delete_price_level(level_id: int):
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_price_levels WHERE id = %s AND user_id = %s",
                [level_id, user_id],
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
        conn.commit()
    return _jresp({'ok': True})


# ── Trendlines (2 puntos) ─────────────────────────────────────────────────────

_TRENDLINE_KINDS = {'support', 'resistance', 'target', 'note'}

_TRENDLINE_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _trendline_serialize(r: dict) -> dict:
    # Reconstruye points[]: si hay points_json usarlo; si no, fallback al par t1/p1-t2/p2.
    points = None
    raw = r.get('points_json')
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(p, dict) for p in parsed):
                points = [{'t': str(p.get('t')), 'p': float(p.get('p'))} for p in parsed
                          if p.get('t') and p.get('p') is not None]
        except Exception:
            points = None
    if points is None:
        points = [
            {'t': r['t1'], 'p': float(r['p1']) if r['p1'] is not None else 0.0},
            {'t': r['t2'], 'p': float(r['p2']) if r['p2'] is not None else 0.0},
        ]
    return {
        'id':         r['id'],
        'accion_id':  r['accion_id'],
        'points':     points,
        'kind':       r['kind'],
        'label':      r.get('label'),
        'created_at': str(r['created_at']) if r.get('created_at') else None,
    }


@app.route('/api/trendlines', methods=['GET'])
@login_required
def get_trendlines():
    user_id = request.user['sub']
    try:
        accion_id = int(request.args.get('accion_id') or 0)
    except ValueError:
        return _jresp({'error': 'accion_id inválido'}, 400)
    if accion_id <= 0:
        return _jresp({'error': 'accion_id requerido'}, 400)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, accion_id, t1, p1, t2, p2, points_json, kind, label, created_at
                FROM user_trendlines
                WHERE user_id = %s AND accion_id = %s
                ORDER BY created_at DESC
            """, [user_id, accion_id])
            rows = cur.fetchall() or []
    return _jresp({'items': [_trendline_serialize(r) for r in rows]})


@app.route('/api/trendlines', methods=['POST'])
@login_required
def create_trendline():
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    try:
        accion_id = int(body.get('accion_id') or 0)
    except (TypeError, ValueError):
        return _jresp({'error': 'accion_id requerido'}, 400)
    if accion_id <= 0:
        return _jresp({'error': 'accion_id debe ser > 0'}, 400)

    # Nuevo formato: { points: [{t,p}, {t,p}, ...] } con N>=2.
    # Formato legacy (2 puntos): { t1, p1, t2, p2 } — se acepta por compat.
    raw_points = body.get('points')
    points: list[dict] = []
    if isinstance(raw_points, list) and raw_points:
        for pt in raw_points:
            if not isinstance(pt, dict):
                return _jresp({'error': 'points debe ser lista de {t, p}'}, 400)
            t = (pt.get('t') or '').strip()
            try:
                p = float(pt.get('p'))
            except (TypeError, ValueError):
                return _jresp({'error': 'p inválido en points'}, 400)
            if not _TRENDLINE_DATE_RE.match(t):
                return _jresp({'error': 't debe ser YYYY-MM-DD en points'}, 400)
            if p <= 0:
                return _jresp({'error': 'p debe ser > 0 en points'}, 400)
            points.append({'t': t, 'p': p})
    else:
        # legacy 2-point payload
        try:
            p1 = float(body.get('p1'))
            p2 = float(body.get('p2'))
        except (TypeError, ValueError):
            return _jresp({'error': 'points[] (o t1,p1,t2,p2) requerido'}, 400)
        t1 = (body.get('t1') or '').strip()
        t2 = (body.get('t2') or '').strip()
        if not _TRENDLINE_DATE_RE.match(t1) or not _TRENDLINE_DATE_RE.match(t2):
            return _jresp({'error': 't1 y t2 deben ser YYYY-MM-DD'}, 400)
        if p1 <= 0 or p2 <= 0:
            return _jresp({'error': 'p1 y p2 deben ser > 0'}, 400)
        points = [{'t': t1, 'p': p1}, {'t': t2, 'p': p2}]

    if len(points) < 2:
        return _jresp({'error': 'se requieren al menos 2 puntos'}, 400)
    # Orden cronológico + deduplicación por fecha (último gana)
    points.sort(key=lambda x: x['t'])
    dedup: dict[str, dict] = {}
    for pt in points:
        dedup[pt['t']] = pt
    points = list(dedup.values())
    if len(points) < 2:
        return _jresp({'error': 'se requieren al menos 2 fechas distintas'}, 400)

    kind = (body.get('kind') or 'support').strip().lower()
    if kind not in _TRENDLINE_KINDS:
        return _jresp({'error': f'kind debe ser uno de: {sorted(_TRENDLINE_KINDS)}'}, 400)
    label = body.get('label') or None
    if label and len(label) > 120:
        label = label[:120]

    first, last = points[0], points[-1]
    points_json = json.dumps(points) if len(points) > 2 else None

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM accion WHERE id = %s", [accion_id])
            if not cur.fetchone():
                return _jresp({'error': 'accion no existe'}, 404)
            cur.execute("""
                INSERT INTO user_trendlines (user_id, accion_id, t1, p1, t2, p2, points_json, kind, label)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [user_id, accion_id, first['t'], first['p'], last['t'], last['p'],
                  points_json, kind, label])
            new_id = cur.lastrowid
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, accion_id, t1, p1, t2, p2, points_json, kind, label, created_at
                FROM user_trendlines WHERE id = %s
            """, [new_id])
            row = cur.fetchone()
    return _jresp({'item': _trendline_serialize(row)}, 201)


@app.route('/api/trendlines/<int:line_id>', methods=['PATCH'])
@login_required
def update_trendline(line_id: int):
    user_id = request.user['sub']
    body = request.get_json(silent=True) or {}
    updates, params = [], []
    if 'kind' in body:
        k = (body.get('kind') or '').strip().lower()
        if k not in _TRENDLINE_KINDS:
            return _jresp({'error': f'kind debe ser uno de: {sorted(_TRENDLINE_KINDS)}'}, 400)
        updates.append('kind = %s'); params.append(k)
    if 'label' in body:
        lbl = body.get('label')
        if lbl is not None and len(lbl) > 120:
            lbl = lbl[:120]
        updates.append('label = %s'); params.append(lbl)
    if not updates:
        return _jresp({'error': 'nada para actualizar'}, 400)
    params.extend([line_id, user_id])
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE user_trendlines SET {', '.join(updates)} WHERE id = %s AND user_id = %s",
                params,
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
            cur.execute("""
                SELECT id, accion_id, t1, p1, t2, p2, points_json, kind, label, created_at
                FROM user_trendlines WHERE id = %s
            """, [line_id])
            row = cur.fetchone()
        conn.commit()
    return _jresp({'item': _trendline_serialize(row)})


@app.route('/api/trendlines/<int:line_id>', methods=['DELETE'])
@login_required
def delete_trendline(line_id: int):
    user_id = request.user['sub']
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_trendlines WHERE id = %s AND user_id = %s",
                [line_id, user_id],
            )
            if cur.rowcount == 0:
                return _jresp({'error': 'No encontrado'}, 404)
        conn.commit()
    return _jresp({'ok': True})


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
def _ensure_crypto_alerts_table():
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS crypto_alerts (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    user_id     INT           NOT NULL,
                    coin_id     VARCHAR(30)   NOT NULL,
                    direction   VARCHAR(10)   NOT NULL DEFAULT 'below',
                    target_price DECIMAL(20,6) NOT NULL,
                    label       VARCHAR(120)  NULL,
                    active      TINYINT(1)    NOT NULL DEFAULT 1,
                    triggered_at DATETIME     NULL,
                    created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ca_user (user_id),
                    INDEX idx_ca_active (active, coin_id),
                    CONSTRAINT fk_ca_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()

try:
    _ensure_users_table()
    _ensure_batch_tables()
    _ensure_watchlist_table()
    _ensure_trades_table()
    _ensure_price_levels_table()
    _ensure_trendlines_table()
    _ensure_crypto_alerts_table()
except Exception as _bootstrap_err:
    print(f' * WARN bootstrap migrations: {_bootstrap_err}')


# ── Entry point ────────────────────────────────────────────────────────────────

# ── /api/assets/<id>/sr-v2 ────────────────────────────────────────────────────
#
# Motor V2 de soportes y resistencias: horizontales (zonas), diagonales
# (estructurales + aceleración), scoring 0-100, estados, explicaciones.

@app.route('/api/assets/<int:accion_id>/sr-v2')
def get_sr_v2_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']

    with _srv2_lock:
        entry = _srv2_cache.get(symbol)
        if entry and (time.time() - entry['ts']) < _SRV2_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.sr_engine_v2 import calculate_sr
        result = calculate_sr(symbol, timeframe='W', fecha=datetime.date.today())
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _srv2_lock:
        _srv2_cache[symbol] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/assets/<id>/events — Eventos probabilísticos ────────────────────────

@app.route('/api/assets/<int:accion_id>/events')
def get_asset_events(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()
    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']
    fecha_str = request.args.get('fecha', '')
    if fecha_str:
        fecha = datetime.datetime.strptime(fecha_str, '%Y-%m-%d').date()
    else:
        fecha = datetime.date.today()

    try:
        from ml.probability_engine import analyze_event_probability
        from db.connection import get_conn as _ml_conn
        conn2 = _ml_conn()
        try:
            with conn2.cursor() as cur:
                cur.execute("""
                    SELECT event_type, event_detail, event_strength, fecha
                    FROM ml_events WHERE symbol=%s AND fecha=%s
                    ORDER BY event_strength DESC
                """, (symbol, fecha))
                events = cur.fetchall()
        finally:
            conn2.close()

        results = []
        for ev in events:
            prob = analyze_event_probability(symbol, fecha, ev['event_type'])
            results.append({
                'event_type':     ev['event_type'],
                'event_detail':   ev.get('event_detail'),
                'event_strength': float(ev['event_strength']) if ev.get('event_strength') else 0,
                'prob_up_5d':     round(prob.prob_up_5d, 3),
                'prob_up_10d':    round(prob.prob_up_10d, 3),
                'expected_ret_5d':  round(prob.expected_ret_5d, 4),
                'expected_ret_10d': round(prob.expected_ret_10d, 4),
                'confidence':     round(prob.confidence, 3),
                'n_total':        prob.n_total,
                'n_sector':       prob.n_sector,
                'n_similar':      prob.n_similar,
                'global_win_rate':  round(prob.global_win_rate_5d, 3),
                'sector_win_rate':  round(prob.sector_win_rate_5d, 3),
                'similar_win_rate': round(prob.similar_win_rate_5d, 3),
                'sector':         prob.sector,
                'top_analogues':  prob.top_analogues[:5],
            })
        return _jresp({'symbol': symbol, 'fecha': str(fecha), 'events': results})
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)


# ── /api/assets/<id>/elliott ──────────────────────────────────────────────────
#
# Análisis de Ondas de Elliott sobre un activo individual.

@app.route('/api/assets/<int:accion_id>/elliott')
def get_elliott(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']
    tf_arg = (request.args.get('tf') or '').strip().upper()
    tf = tf_arg if tf_arg in ('D', 'W') else 'D'
    cache_key = f'{symbol}::{tf}'

    with _elliott_lock:
        entry = _elliott_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _ELLIOTT_TTL:
            return _jresp(entry['data'])

    try:
        from strategies.elliott import analyze_elliott
        result = analyze_elliott(symbol, datetime.date.today(), tf=tf)
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _elliott_lock:
        _elliott_cache[cache_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/scan/elliott ────────────────────────────────────────────────────────
#
# Scan masivo de Elliott sobre el universo activo.  Devuelve resumen por activo.

_elliott_scan_cache: dict = {}
_elliott_scan_lock = threading.Lock()
_ELLIOTT_SCAN_TTL = 1800

@app.route('/api/scan/elliott')
def scan_elliott():
    market = request.args.get('market', 'USA')
    tf_arg = (request.args.get('tf') or '').strip().upper()
    tf = tf_arg if tf_arg in ('D', 'W') else 'D'
    scan_key = f'{market}::{tf}'

    with _elliott_scan_lock:
        entry = _elliott_scan_cache.get(scan_key)
        if entry and (time.time() - entry['ts']) < _ELLIOTT_SCAN_TTL:
            return _jresp(entry['data'])

    with _conn() as conn:
        with conn.cursor() as cur:
            if market == 'BYMA':
                cur.execute(
                    "SELECT id, simbolo, nombre FROM accion WHERE activo = 1 AND simbolo LIKE '%%.BA' ORDER BY simbolo"
                )
            else:
                cur.execute(
                    "SELECT id, simbolo, nombre FROM accion WHERE activo = 1 AND simbolo NOT LIKE '%%.BA' ORDER BY simbolo"
                )
            assets = cur.fetchall()

    from strategies.elliott import analyze_elliott
    items = []
    fecha = datetime.date.today()

    for asset in assets:
        try:
            res = analyze_elliott(asset['simbolo'], fecha, tf=tf)
            if res.get('signal') in ('BUY', 'SELL') and res.get('rules_valid'):
                items.append({
                    'accion_id': asset['id'],
                    'simbolo': asset['simbolo'],
                    'nombre': asset['nombre'],
                    'signal': res['signal'],
                    'current_wave': res['current_wave'],
                    'current_wave_label': res.get('current_wave_label', ''),
                    'confidence': res['confidence'],
                    'direction': res.get('direction', ''),
                    'price': res.get('price', 0),
                })
        except Exception:
            pass

    items.sort(key=lambda x: (-x['confidence'], x['simbolo']))
    result = {'items': items, 'fecha': str(fecha), 'market': market, 'timeframe': tf}

    with _elliott_scan_lock:
        _elliott_scan_cache[scan_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


# ── /api/trends/sma200-weekly ─────────────────────────────────────────────────
#
# Tendencia de largo plazo de todos los activos con >=201 barras semanales.
# Calcula SMA200 semanal y clasifica: ALCISTA (precio > SMA200) / BAJISTA.

import threading as _threading_trends

_sma200w_cache: dict | None = None
_sma200w_cache_ts: float = 0.0
_sma200w_lock = _threading_trends.Lock()
_SMA200W_TTL = 3600


@app.route('/api/trends/sma200-weekly')
@login_required
def trends_sma200_weekly():
    global _sma200w_cache, _sma200w_cache_ts

    with _sma200w_lock:
        if _sma200w_cache and (time.time() - _sma200w_cache_ts) < _SMA200W_TTL:
            return _jresp(_sma200w_cache)

    min_bars = 201
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT simbolo FROM ohlcv_extended
                WHERE timeframe = 'W'
                GROUP BY simbolo
                HAVING COUNT(*) >= %s
                ORDER BY simbolo
            """, (min_bars,))
            symbols = [r['simbolo'] for r in cur.fetchall()]

    items = []
    for symbol in symbols:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT close FROM ohlcv_extended
                           WHERE simbolo = %s AND timeframe = 'W'
                           ORDER BY fecha DESC LIMIT 200""",
                        (symbol,),
                    )
                    rows = cur.fetchall()
                    if len(rows) < 200:
                        continue
                    closes = [float(r['close']) for r in reversed(rows)]
                    sma200 = sum(closes) / 200
                    price = closes[-1]
                    dist_pct = round((price / sma200 - 1) * 100, 2)

                    cur.execute(
                        "SELECT id, nombre FROM accion WHERE simbolo = %s LIMIT 1",
                        (symbol,),
                    )
                    asset = cur.fetchone()

            items.append({
                'simbolo':     symbol,
                'nombre':      asset['nombre'] if asset else symbol,
                'accion_id':   asset['id'] if asset else None,
                'price':       round(price, 2),
                'sma200':      round(sma200, 2),
                'distance_pct': dist_pct,
                'trend':       'ALCISTA' if price > sma200 else 'BAJISTA',
            })
        except Exception:
            continue

    items.sort(key=lambda x: x['distance_pct'], reverse=True)
    result = {
        'items': items,
        'fecha': str(datetime.date.today()),
        'total': len(items),
        'alcistas': sum(1 for i in items if i['trend'] == 'ALCISTA'),
        'bajistas': sum(1 for i in items if i['trend'] == 'BAJISTA'),
    }

    with _sma200w_lock:
        _sma200w_cache = result
        _sma200w_cache_ts = time.time()

    return _jresp(result)


# ═══════════════════════════════════════════════════════════════════════════════
# BONOS ARGENTINOS
# ═══════════════════════════════════════════════════════════════════════════════

_bonds_cache: dict | None = None
_bonds_cache_ts: float = 0.0
_bonds_lock = threading.Lock()
_BONDS_TTL = 600


def _ensure_bonds_tables():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()


try:
    _ensure_bonds_tables()
except Exception:
    pass


@app.route('/api/bonds/dashboard')
def bonds_dashboard():
    global _bonds_cache, _bonds_cache_ts
    with _bonds_lock:
        if _bonds_cache and (time.time() - _bonds_cache_ts) < _BONDS_TTL:
            return _jresp(_bonds_cache)

    from strategies.bonds_ar import BONDS as BOND_DEFS, ALL_BOND_SYMBOLS, PAIRS, analyze_bond, calc_zscore_signal, calc_spread_signal
    from scripts.byma_bonds_fetch import fetch_byma_bonds, _best_usd_price

    raw = fetch_byma_bonds()
    bonds_out = []
    tir_map = {}

    conn = _conn()
    try:
        for sym in ALL_BOND_SYMBOLS:
            best = _best_usd_price(raw, sym)
            if not best:
                continue

            analysis = analyze_bond(sym, best['price'], datetime.date.today())
            if not analysis:
                continue

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tir FROM bonds_tir_history WHERE symbol = %s ORDER BY fecha DESC LIMIT 60",
                    (sym,),
                )
                tir_hist = [float(r['tir']) for r in cur.fetchall()]

            zscore_data = calc_zscore_signal(analysis['tir'], tir_hist)
            analysis.update(zscore_data)
            tir_map[sym] = analysis['tir']
            bonds_out.append(analysis)

        spreads = []
        for al_sym, gd_sym in PAIRS:
            if al_sym not in tir_map or gd_sym not in tir_map:
                continue
            spread_bps = round((tir_map[al_sym] - tir_map[gd_sym]) * 100, 1)

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.tir AS al_tir, g.tir AS gd_tir
                    FROM bonds_tir_history a
                    JOIN bonds_tir_history g ON a.fecha = g.fecha AND g.symbol = %s
                    WHERE a.symbol = %s ORDER BY a.fecha DESC LIMIT 60
                """, (gd_sym, al_sym))
                spread_hist = [round((float(r['al_tir']) - float(r['gd_tir'])) * 100, 1) for r in cur.fetchall()]

            sp_signal = calc_spread_signal(spread_bps, spread_hist)
            spreads.append({'al': al_sym, 'gd': gd_sym, 'spread_bps': spread_bps, **sp_signal})
    finally:
        conn.close()

    result = {
        'bonds': bonds_out,
        'spreads': spreads,
        'fecha': str(datetime.date.today()),
    }

    with _bonds_lock:
        _bonds_cache = result
        _bonds_cache_ts = time.time()

    return _jresp(result)


@app.route('/api/bonds/<symbol>/history')
def bonds_history(symbol: str):
    symbol = symbol.upper()
    days = int(request.args.get('days', 90))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.fecha, p.price_usd, p.price_ars, p.bid_usd, p.ask_usd, p.volume,
                       t.tir, t.paridad, t.duration_mod, t.z_score, t.`signal`
                FROM bonds_price_history p
                LEFT JOIN bonds_tir_history t ON p.symbol = t.symbol AND p.fecha = t.fecha
                WHERE p.symbol = %s
                ORDER BY p.fecha DESC
                LIMIT %s
            """, (symbol, days))
            rows = cur.fetchall()
    finally:
        conn.close()

    return _jresp({
        'symbol': symbol,
        'history': [{k: (str(v) if isinstance(v, (datetime.date, datetime.datetime)) else
                         float(v) if hasattr(v, 'as_integer_ratio') else v)
                     for k, v in r.items()} for r in rows],
    })


@app.route('/api/bonds/curve')
def bonds_curve():
    from strategies.bonds_ar import BONDS as BOND_DEFS, ALL_BOND_SYMBOLS, analyze_bond
    from scripts.byma_bonds_fetch import fetch_byma_bonds, _best_usd_price

    raw = fetch_byma_bonds()
    points = []
    for sym in ALL_BOND_SYMBOLS:
        best = _best_usd_price(raw, sym)
        if not best:
            continue
        analysis = analyze_bond(sym, best['price'], datetime.date.today())
        if not analysis or analysis.get('tir') is None:
            continue
        points.append({
            'symbol': sym,
            'law': BOND_DEFS[sym]['law'],
            'maturity': BOND_DEFS[sym]['maturity'].isoformat(),
            'tir': analysis['tir'],
            'paridad': analysis.get('paridad'),
            'duration_mod': analysis.get('duration_mod'),
        })

    points.sort(key=lambda x: x['maturity'])
    return _jresp({'curve': points, 'fecha': str(datetime.date.today())})


@app.route('/api/bonds/spreads')
def bonds_spreads():
    from strategies.bonds_ar import PAIRS
    days = int(request.args.get('days', 90))

    conn = _conn()
    try:
        result = []
        for al_sym, gd_sym in PAIRS:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.fecha, a.tir AS al_tir, g.tir AS gd_tir
                    FROM bonds_tir_history a
                    JOIN bonds_tir_history g ON a.fecha = g.fecha AND g.symbol = %s
                    WHERE a.symbol = %s
                    ORDER BY a.fecha DESC
                    LIMIT %s
                """, (gd_sym, al_sym, days))
                rows = cur.fetchall()

            history = [{
                'fecha': str(r['fecha']),
                'al_tir': float(r['al_tir']),
                'gd_tir': float(r['gd_tir']),
                'spread_bps': round((float(r['al_tir']) - float(r['gd_tir'])) * 100, 1),
            } for r in rows]

            result.append({'al': al_sym, 'gd': gd_sym, 'history': history})
    finally:
        conn.close()

    return _jresp({'pairs': result})


# ── Screener: generic scan infrastructure ──────────────────────────────────────

_screener_cache: dict = {}       # key → {market → {data, ts}}
_screener_running: dict = {}     # key → set of markets running
_screener_lock = threading.Lock()


def _get_scan_assets(market: str) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            if market == 'BYMA':
                cur.execute(
                    "SELECT id, simbolo, nombre FROM accion WHERE activo = 1 AND simbolo LIKE '%%.BA' ORDER BY simbolo"
                )
            elif market == 'USA':
                cur.execute(
                    "SELECT id, simbolo, nombre FROM accion WHERE activo = 1 AND simbolo NOT LIKE '%%.BA' ORDER BY simbolo"
                )
            else:
                cur.execute(
                    "SELECT id, simbolo, nombre FROM accion WHERE activo = 1 ORDER BY simbolo"
                )
            return cur.fetchall()


def _scan_endpoint_generic(strategy_key: str, ttl: int, compute_fn):
    market = request.args.get('market', 'USA')

    with _screener_lock:
        cache = _screener_cache.setdefault(strategy_key, {})
        running = _screener_running.setdefault(strategy_key, set())

        entry = cache.get(market)
        if entry and (time.time() - entry['ts']) < ttl:
            return _jresp({**entry['data'], 'cached': True, 'status': 'ready'})

        if market in running:
            return _jresp({'status': 'computing', 'market': market})

        running.add(market)

    def _bg():
        try:
            result = compute_fn(market)
            with _screener_lock:
                cache[market] = {'data': result, 'ts': time.time()}
                running.discard(market)
        except Exception as e:
            print(f' * ERROR scan {strategy_key} ({market}): {e}')
            import traceback; traceback.print_exc()
            with _screener_lock:
                running.discard(market)

    threading.Thread(target=_bg, daemon=True).start()
    return _jresp({'status': 'computing', 'market': market})


# ── /api/scan/sr-breakout ────────────────────────────────────────────────────

@app.route('/api/scan/sr-breakout')
def scan_sr_breakout():
    def compute(market):
        from scripts.sr_breakout_alert import scan as sr_scan, _get_symbols
        all_symbols = _get_symbols()
        if market == 'BYMA':
            symbols = [s for s in all_symbols if s.endswith('.BA')]
        elif market == 'USA':
            symbols = [s for s in all_symbols if not s.endswith('.BA')]
        else:
            symbols = all_symbols

        res_broke, res_touched, sup_bounced, sup_touched, lateralized = sr_scan(symbols)

        all_syms = set()
        for lst in [res_broke, res_touched, sup_bounced, sup_touched, lateralized]:
            for item in lst:
                all_syms.add(item['symbol'])

        sym_info = {}
        if all_syms:
            with _conn() as conn:
                with conn.cursor() as cur:
                    fmt = ','.join(['%s'] * len(all_syms))
                    cur.execute(
                        f"SELECT id, simbolo, nombre FROM accion WHERE simbolo IN ({fmt})",
                        list(all_syms)
                    )
                    for r in cur.fetchall():
                        sym_info[r['simbolo']] = {'accion_id': r['id'], 'nombre': r['nombre']}

        def enrich(lst):
            for item in lst:
                info = sym_info.get(item['symbol'], {})
                item['accion_id'] = info.get('accion_id')
                item['nombre'] = info.get('nombre', '')
            return lst

        return {
            'res_broke': enrich(res_broke),
            'res_touched': enrich(res_touched),
            'sup_bounced': enrich(sup_bounced),
            'sup_touched': enrich(sup_touched),
            'lateralized': enrich(lateralized),
            'fecha': str(datetime.date.today()),
            'market': market,
        }

    return _scan_endpoint_generic('sr_breakout', 1800, compute)


# ── /api/scan/channels ───────────────────────────────────────────────────────

@app.route('/api/scan/channels')
def scan_channels():
    def compute(market):
        assets = _get_scan_assets(market)
        from strategies.channel_detection import detect_channels_multi
        items = []
        fecha = datetime.date.today()

        for idx, asset in enumerate(assets):
            if idx % 50 == 0:
                print(f'  channel scan {idx}/{len(assets)}...')
            try:
                channels = detect_channels_multi(asset['simbolo'], fecha)
                if not channels:
                    continue
                for ch in channels:
                    if ch.get('stale'):
                        continue
                    if ch['decision'] in ('NEAR_SUPPORT', 'NEAR_RESISTANCE',
                                          'BELOW_SUPPORT', 'ABOVE_RESISTANCE'):
                        items.append({
                            'accion_id':        asset['id'],
                            'simbolo':          asset['simbolo'],
                            'nombre':           asset['nombre'],
                            'horizon':          ch.get('horizon', ''),
                            'channel_type':     ch['channel_type'],
                            'decision':         ch['decision'],
                            'signal':           ch.get('signal', 'HOLD'),
                            'position':         ch['position'],
                            'upper_now':        ch['upper_now'],
                            'lower_now':        ch['lower_now'],
                            'price':            ch.get('last_close', 0),
                            'reading':          ch['reading'],
                            'bounce_confirmed': ch.get('bounce_confirmed', False),
                            'slope_annual_pct': ch.get('slope_annual_pct', 0),
                        })
            except Exception:
                pass

        items.sort(key=lambda x: (
            0 if x.get('bounce_confirmed') else 1,
            0 if x['signal'] == 'BUY' else (1 if x['signal'] == 'SELL' else 2),
            x['simbolo'],
        ))
        return {'items': items, 'fecha': str(fecha), 'market': market}

    return _scan_endpoint_generic('channels', 1800, compute)


# ── /api/scan/historical-lows ────────────────────────────────────────────────

@app.route('/api/scan/historical-lows')
def scan_historical_lows():
    def compute(market):
        assets = _get_scan_assets(market)
        symbols = [a['simbolo'] for a in assets]
        id_map = {a['simbolo']: a for a in assets}

        from strategies.historical_lows import run_universe
        all_results = run_universe(symbols)

        items = []
        for r in all_results:
            if r.get('setup_state') == 'NO_SIGNAL':
                continue
            info = id_map.get(r['simbolo'], {})
            items.append({
                'accion_id':        info.get('id'),
                'simbolo':          r['simbolo'],
                'nombre':           info.get('nombre', ''),
                'price':            r['price'],
                'low_52w':          r['low_52w'],
                'distance_52w_pct': r.get('distance_52w_pct'),
                'setup_state':      r['setup_state'],
                'decision':         r['decision'],
                'reading':          r['reading'],
                'is_all_time_low':  r.get('is_all_time_low', False),
                'rsi14':            r.get('rsi14'),
            })

        items.sort(key=lambda x: x.get('distance_52w_pct') or 999)
        return {'items': items, 'fecha': str(datetime.date.today()), 'market': market}

    return _scan_endpoint_generic('historical_lows', 1800, compute)


# ── /api/scan/historical-highs ───────────────────────────────────────────────

@app.route('/api/scan/historical-highs')
def scan_historical_highs():
    def compute(market):
        assets = _get_scan_assets(market)
        symbols = [a['simbolo'] for a in assets]
        id_map = {a['simbolo']: a for a in assets}

        from strategies.historical_highs import run_universe
        all_results = run_universe(symbols)

        items = []
        for r in all_results:
            if r.get('setup_state') == 'NO_SIGNAL':
                continue
            info = id_map.get(r['simbolo'], {})
            items.append({
                'accion_id':        info.get('id'),
                'simbolo':          r['simbolo'],
                'nombre':           info.get('nombre', ''),
                'price':            r['price'],
                'high_52w':         r.get('high_52w'),
                'distance_52w_pct': r.get('distance_52w_pct'),
                'setup_state':      r['setup_state'],
                'decision':         r.get('decision', ''),
                'reading':          r.get('reading', ''),
                'is_all_time_high': r.get('is_all_time_high', False),
                'rsi14':            r.get('rsi14'),
            })

        items.sort(key=lambda x: abs(x.get('distance_52w_pct') or 999))
        return {'items': items, 'fecha': str(datetime.date.today()), 'market': market}

    return _scan_endpoint_generic('historical_highs', 1800, compute)


# ── Crypto prices ─────────────────────────────────────────────────────────────

_crypto_cache: dict = {}          # {'data': ..., 'ts': float}
_crypto_lock = threading.Lock()
_CRYPTO_TTL  = 120                # 2 minutos

@app.route('/api/crypto/prices')
def crypto_prices():
    import requests as _req

    now = time.time()
    with _crypto_lock:
        cached = _crypto_cache.get('data')
        if cached and now - _crypto_cache.get('ts', 0) < _CRYPTO_TTL:
            return jsonify(cached)

    try:
        url = 'https://api.coingecko.com/api/v3/coins/markets'
        params = {
            'vs_currency': 'usd',
            'ids': 'bitcoin,tether',
            'order': 'market_cap_desc',
            'sparkline': 'true',
            'price_change_percentage': '1h,24h,7d',
        }
        resp = _req.get(url, params=params, timeout=10)
        resp.raise_for_status()
        coins = resp.json()

        result = {'coins': [], 'ts': datetime.datetime.utcnow().isoformat() + 'Z'}
        for c in coins:
            result['coins'].append({
                'id':                  c['id'],
                'symbol':              c['symbol'].upper(),
                'name':                c['name'],
                'price':               c.get('current_price'),
                'market_cap':          c.get('market_cap'),
                'volume_24h':          c.get('total_volume'),
                'change_1h_pct':       c.get('price_change_percentage_1h_in_currency'),
                'change_24h_pct':      c.get('price_change_percentage_24h_in_currency'),
                'change_7d_pct':       c.get('price_change_percentage_7d_in_currency'),
                'high_24h':            c.get('high_24h'),
                'low_24h':             c.get('low_24h'),
                'ath':                 c.get('ath'),
                'ath_change_pct':      c.get('ath_change_percentage'),
                'sparkline':           c.get('sparkline_in_7d', {}).get('price', []),
                'last_updated':        c.get('last_updated'),
            })

        with _crypto_lock:
            _crypto_cache['data'] = result
            _crypto_cache['ts'] = now

        return jsonify(result)
    except Exception as exc:
        with _crypto_lock:
            cached = _crypto_cache.get('data')
        if cached:
            return jsonify(cached)
        return jsonify({'error': str(exc)}), 502


# ── Crypto alerts CRUD ─────────────────────────────────────────────────────────

@app.route('/api/crypto/alerts')
@login_required
def crypto_alerts_list():
    user_id = request.user['sub']
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, coin_id, direction, target_price, label, active, triggered_at, created_at
                FROM crypto_alerts WHERE user_id = %s ORDER BY created_at DESC
            """, (user_id,))
            rows = cur.fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        items.append({
            'id':           r['id'],
            'coin_id':      r['coin_id'],
            'direction':    r['direction'],
            'target_price': float(r['target_price']),
            'label':        r['label'],
            'active':       bool(r['active']),
            'triggered_at': r['triggered_at'].isoformat() if r['triggered_at'] else None,
            'created_at':   r['created_at'].isoformat() if r['created_at'] else None,
        })
    return jsonify({'alerts': items})


@app.route('/api/crypto/alerts', methods=['POST'])
@login_required
def crypto_alerts_create():
    user_id = request.user['sub']
    data = request.get_json(force=True)
    coin_id      = data.get('coin_id', 'bitcoin')
    direction    = data.get('direction', 'below')
    target_price = data.get('target_price')
    label        = data.get('label', '')

    if not target_price or float(target_price) <= 0:
        return jsonify({'error': 'target_price inválido'}), 400
    if direction not in ('below', 'above'):
        return jsonify({'error': 'direction debe ser below o above'}), 400
    if coin_id not in ('bitcoin', 'tether'):
        return jsonify({'error': 'coin_id inválido'}), 400

    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO crypto_alerts (user_id, coin_id, direction, target_price, label)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, coin_id, direction, float(target_price), label or None))
            new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    return jsonify({'ok': True, 'id': new_id})


@app.route('/api/crypto/alerts/<int:alert_id>', methods=['DELETE'])
@login_required
def crypto_alerts_delete(alert_id):
    user_id = request.user['sub']
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crypto_alerts WHERE id = %s AND user_id = %s", (alert_id, user_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


_crypto_ohlcv_cache: dict = {}      # coin_id → {'data': ..., 'ts': float, 'days': int}
_crypto_ohlcv_lock = threading.Lock()
_CRYPTO_OHLCV_TTL  = 300             # 5 minutos

@app.route('/api/crypto/<coin_id>/ohlcv')
def crypto_ohlcv(coin_id):
    import requests as _req

    allowed = {'bitcoin', 'tether'}
    if coin_id not in allowed:
        return jsonify({'error': 'Coin no soportada'}), 400

    days = int(request.args.get('days', 90))
    if days not in (1, 7, 14, 30, 90, 180, 365):
        days = 90

    cache_key = f'{coin_id}_{days}'
    now = time.time()
    with _crypto_ohlcv_lock:
        cached = _crypto_ohlcv_cache.get(cache_key)
        if cached and now - cached.get('ts', 0) < _CRYPTO_OHLCV_TTL:
            return jsonify(cached['data'])

    try:
        url = f'https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc'
        params = {'vs_currency': 'usd', 'days': days}
        resp = _req.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

        candles = []
        for row in raw:
            ts_ms, o, h, l, c = row
            dt = datetime.datetime.utcfromtimestamp(ts_ms / 1000)
            candles.append({
                'fecha':  dt.strftime('%Y-%m-%d'),
                'time':   dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'open':   o,
                'high':   h,
                'low':    l,
                'close':  c,
                'volume': 0,
            })

        result = {'coin_id': coin_id, 'days': days, 'candles': candles}

        with _crypto_ohlcv_lock:
            _crypto_ohlcv_cache[cache_key] = {'data': result, 'ts': now}

        return jsonify(result)
    except Exception as exc:
        with _crypto_ohlcv_lock:
            cached = _crypto_ohlcv_cache.get(cache_key)
        if cached:
            return jsonify(cached['data'])
        return jsonify({'error': str(exc)}), 502


# ── /api/assets/<id>/accelerated-trendlines ──────────────────────────────────
#
# Motor acelerado independiente: detecta soportes/resistencias con pendiente
# empinada (>=40%/yr) y régimen de aceleración/compresión.
# No reemplaza /dynamic-supports ni /dynamic-resistances.

@app.route('/api/assets/<int:accion_id>/accelerated-trendlines')
def get_accelerated_trendlines_endpoint(accion_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT simbolo FROM accion WHERE id = %s", [accion_id])
            row = cur.fetchone()

    if not row:
        return _jresp({'error': 'Asset not found'}, 404)

    symbol = row['simbolo']
    tf = (request.args.get('tf') or 'D').strip().upper()
    if tf not in ('D', 'W'):
        tf = 'D'

    cache_key = f"{symbol}_{tf}"
    with _accel_lock:
        entry = _accel_cache.get(cache_key)
        if entry and (time.time() - entry['ts']) < _ACCEL_TTL:
            return _jresp(entry['data'])

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT fecha, open, high, low, close, volume
                       FROM ohlcv_extended
                       WHERE simbolo = %s AND timeframe = %s
                       ORDER BY fecha ASC""",
                    (symbol, tf),
                )
                raw = cur.fetchall()

        if not raw:
            result = {
                'symbol': symbol, 'timeframe_used': tf, 'price': None,
                'support': None, 'resistance': None, 'regime': 'none',
                'meta': {'reason': f'No OHLCV data for {symbol}/{tf}'},
            }
            return _jresp(result)

        ohlcv_rows = [
            {'fecha': str(r['fecha']), 'open': float(r['open']),
             'high': float(r['high']), 'low': float(r['low']),
             'close': float(r['close']),
             'volume': int(r.get('volume', 0) or 0)}
            for r in raw
        ]
        price = ohlcv_rows[-1]['close']

        from strategies.accelerated_trendlines import detect_accelerated_trendlines
        accel = detect_accelerated_trendlines(ohlcv_rows, {'tf': tf})

        meta = {k: v for k, v in accel.get('meta', {}).items() if k != 'config'}

        result = {
            'symbol':         symbol,
            'timeframe_used': tf,
            'price':          price,
            'support':        accel['support'],
            'resistance':     accel['resistance'],
            'regime':         accel['regime'],
            'meta':           meta,
        }
    except Exception as e:
        return _jresp({'error': str(e), 'symbol': symbol}, 500)

    with _accel_lock:
        _accel_cache[cache_key] = {'data': result, 'ts': time.time()}

    return _jresp(result)


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
