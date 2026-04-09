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

# Alias — todos los módulos importan desde acá
DB_CONFIG = MYSQL_CONFIG

# ── Universo de activos ───────────────────────────────────────────────────────
# 203 símbolos validados contra la BD de prod (>=252 barras disponibles).
# Incluye S&P 100 + NASDAQ-100 esenciales + sectoriales clave + LATAM (GGAL,
# BMA, CRESY, EDN, PAM, TGS, YPF, MELI, NU, VIST).
# Excluidos por falta de data en la BD: BRK-B, MMC, WBA.
UNIVERSE = [
    'A', 'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'ADP', 'ADSK', 'AEP', 'AIG',
    'ALL', 'AMAT', 'AMD', 'AMGN', 'AMZN', 'ANET', 'AON', 'APD', 'APH', 'AVGO',
    'AXP', 'BA', 'BABA', 'BAC', 'BIDU', 'BIIB', 'BKNG', 'BLK', 'BMA', 'BMY',
    'BSX', 'BX', 'C', 'CARR', 'CAT', 'CB', 'CDNS', 'CI', 'CL', 'CME',
    'CMI', 'COP', 'COST', 'CRESY', 'CRM', 'CSCO', 'CSX', 'CTAS', 'CTSH', 'CVX',
    'D', 'DE', 'DHR', 'DIS', 'DLR', 'DLTR', 'DOW', 'DUK', 'DXCM', 'ECL',
    'EDN', 'ELV', 'EMR', 'EOG', 'EQIX', 'ETN', 'EW', 'EXC', 'F', 'FAST',
    'FCX', 'FDX', 'FIS', 'FTNT', 'GD', 'GE', 'GGAL', 'GILD', 'GIS', 'GLW',
    'GOOG', 'GOOGL', 'GS', 'HCA', 'HD', 'HON', 'HRL', 'HSY', 'HUM', 'IBM',
    'ICE', 'IDXX', 'INTC', 'INTU', 'ISRG', 'ITW', 'JD', 'JNJ', 'JPM', 'KHC',
    'KKR', 'KLAC', 'KMB', 'KMI', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'LRCX',
    'MA', 'MAR', 'MCD', 'MCHP', 'MCK', 'MDLZ', 'MDT', 'MELI', 'MET', 'META',
    'MMM', 'MNST', 'MO', 'MPC', 'MRK', 'MRNA', 'MS', 'MSFT', 'MSI', 'NDAQ',
    'NEE', 'NEM', 'NFLX', 'NIO', 'NOW', 'NSC', 'NU', 'NVDA', 'NXPI', 'ORCL',
    'ORLY', 'OXY', 'PAM', 'PAYX', 'PCAR', 'PCG', 'PDD', 'PEP', 'PFE', 'PG',
    'PLD', 'PM', 'PNC', 'PRU', 'PSA', 'PSX', 'PYPL', 'QCOM', 'REGN', 'ROP',
    'ROST', 'RTX', 'SBUX', 'SCHW', 'SHW', 'SLB', 'SNPS', 'SO', 'SPG', 'SPGI',
    'SRE', 'SYK', 'T', 'TEL', 'TER', 'TFC', 'TGS', 'TGT', 'TJX', 'TMO',
    'TRV', 'TSLA', 'TT', 'TXN', 'UNH', 'UNP', 'UPS', 'URI', 'USB', 'V',
    'VIST', 'VLO', 'VRTX', 'VZ', 'WBD', 'WELL', 'WFC', 'WM', 'WMT', 'XEL',
    'XOM', 'YPF', 'YUM', 'ZTS',
]

# Sector + ETF de referencia por símbolo.
# Símbolos NO listados acá heredan sector='NEUTRAL' en la lógica de
# `strategies/trend_pullback.py:context_alignment` (degradación graceful).
SECTOR_MAP = {
    # Technology (XLK)
    'AAPL':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'MSFT':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'NVDA':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'AVGO':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'ORCL':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'CRM':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'CSCO':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'ACN':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'AMD':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'ADBE':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'INTC':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'INTU':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'IBM':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'TXN':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'QCOM':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'AMAT':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'NOW':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'ANET':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'LRCX':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'KLAC':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'CDNS':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'SNPS':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'MCHP':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'NXPI':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'ADSK':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'FTNT':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'ADP':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'PAYX':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'CTSH':  {'sector': 'Technology',             'benchmark': 'XLK'},
    'APH':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'TEL':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'TER':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'GLW':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'MSI':   {'sector': 'Technology',             'benchmark': 'XLK'},
    'FIS':   {'sector': 'Technology',             'benchmark': 'XLK'},
    # Communication Services (XLC)
    'GOOGL': {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'GOOG':  {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'META':  {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'NFLX':  {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'DIS':   {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'WBD':   {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'T':     {'sector': 'Communication Services', 'benchmark': 'XLC'},
    'VZ':    {'sector': 'Communication Services', 'benchmark': 'XLC'},
    # Financials (XLF)
    'JPM':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'BAC':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'WFC':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'C':     {'sector': 'Financials',             'benchmark': 'XLF'},
    'GS':    {'sector': 'Financials',             'benchmark': 'XLF'},
    'MS':    {'sector': 'Financials',             'benchmark': 'XLF'},
    'AXP':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'BLK':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'SCHW':  {'sector': 'Financials',             'benchmark': 'XLF'},
    'SPGI':  {'sector': 'Financials',             'benchmark': 'XLF'},
    'CME':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'ICE':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'NDAQ':  {'sector': 'Financials',             'benchmark': 'XLF'},
    'PNC':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'USB':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'TFC':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'BX':    {'sector': 'Financials',             'benchmark': 'XLF'},
    'KKR':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'CB':    {'sector': 'Financials',             'benchmark': 'XLF'},
    'AIG':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'ALL':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'TRV':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'MET':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'PRU':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'AON':   {'sector': 'Financials',             'benchmark': 'XLF'},
    'V':     {'sector': 'Financials',             'benchmark': 'XLF'},
    'MA':    {'sector': 'Financials',             'benchmark': 'XLF'},
    'PYPL':  {'sector': 'Financials',             'benchmark': 'XLF'},
    'NU':    {'sector': 'Financials',             'benchmark': 'XLF'},
    'GGAL':  {'sector': 'Financials',             'benchmark': 'XLF'},
    'BMA':   {'sector': 'Financials',             'benchmark': 'XLF'},
    # Consumer Discretionary (XLY)
    'AMZN':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'TSLA':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'HD':    {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'LOW':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'MCD':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'SBUX':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'NKE':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'BKNG':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'MAR':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'TJX':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'ROST':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'DLTR':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'ORLY':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'YUM':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'F':     {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'MELI':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'BABA':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'JD':    {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'PDD':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'NIO':   {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    'BIDU':  {'sector': 'Consumer Discretionary', 'benchmark': 'XLY'},
    # Energy (XLE)
    'XOM':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'CVX':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'COP':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'EOG':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'SLB':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'MPC':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'PSX':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'VLO':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'OXY':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'KMI':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'VIST':  {'sector': 'Energy',                 'benchmark': 'XLE'},
    'YPF':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'PAM':   {'sector': 'Energy',                 'benchmark': 'XLE'},
    'TGS':   {'sector': 'Energy',                 'benchmark': 'XLE'},
}

# ── Benchmarks ────────────────────────────────────────────────────────────────
MARKET_BENCHMARK   = 'SPY'
SECTOR_BENCHMARKS  = ['XLK', 'XLC', 'XLF', 'XLY', 'XLE']

# Todos los símbolos a fetchear (universo + benchmarks)
ALL_SYMBOLS = sorted(set(UNIVERSE) | {MARKET_BENCHMARK} | set(SECTOR_BENCHMARKS))

# ── Parámetros de datos ───────────────────────────────────────────────────────
HISTORY_YEARS = 2          # años de historia mínima
FETCH_TIMEOUT = 20         # segundos timeout HTTP
