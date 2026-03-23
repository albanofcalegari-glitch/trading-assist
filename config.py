"""
trading-assist — configuración central
"""
import pymysql.cursors

# ── Base de datos ─────────────────────────────────────────────────────────────
MYSQL_CONFIG = dict(
    host='localhost',
    user='root',
    password='123456',
    db='trading_assist',
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)

# ── Universo de activos ───────────────────────────────────────────────────────
UNIVERSE = ['NVDA', 'MSFT', 'GOOGL', 'AAPL', 'MELI', 'VIST', 'JPM', 'DIS', 'PYPL', 'NU']

# Sector + ETF de referencia por símbolo
SECTOR_MAP = {
    'NVDA':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'MSFT':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'GOOGL': {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'AAPL':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'MELI':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'VIST':  {'sector': 'Energy',                 'benchmark': 'XLE'},
    'JPM':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'DIS':   {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'PYPL':  {'sector': 'Financials',             'benchmark': 'XLF'},
    'NU':    {'sector': 'Financials',             'benchmark': 'XLF'},
}

# ── Benchmarks ────────────────────────────────────────────────────────────────
MARKET_BENCHMARK   = 'SPY'
SECTOR_BENCHMARKS  = ['XLK', 'XLC', 'XLF', 'XLY', 'XLE']

# Todos los símbolos a fetchear (universo + benchmarks)
ALL_SYMBOLS = sorted(set(UNIVERSE) | {MARKET_BENCHMARK} | set(SECTOR_BENCHMARKS))

# ── Parámetros de datos ───────────────────────────────────────────────────────
HISTORY_YEARS = 2          # años de historia mínima
FETCH_TIMEOUT = 20         # segundos timeout HTTP
