"""
sector_regime — clasificación del régimen sectorial diario
Fuente: ETFs sectoriales (XLK, XLC, XLF, XLY, XLE)

Regímenes:
    STRONG   — momentum positivo + outperformance vs SPY
    WEAK     — momentum negativo + underperformance vs SPY
    NEUTRAL  — resto
"""
import statistics
from datetime import date
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn

# ── Parámetros ────────────────────────────────────────────────────────────────
MOM_SHORT_DAYS   = 20
MOM_LONG_DAYS    = 60
STRONG_MOM_MIN   =  4.0    # % mom60 mínimo para STRONG
WEAK_MOM_MAX     = -4.0    # % mom60 máximo para WEAK
RS_STRONG_MIN    =  1.03   # ratio sector/SPY 60d para confirmar STRONG
RS_WEAK_MAX      =  0.97   # ratio sector/SPY 60d para confirmar WEAK
HIGH_LOOKBACK    = 252      # días para calcular drawdown desde máximo


# ─────────────────────────────────────────────────────────────────────────────
# Cálculos
# ─────────────────────────────────────────────────────────────────────────────

def _momentum_pct(prices: list[float], lookback: int) -> Optional[float]:
    if len(prices) <= lookback:
        return None
    return (prices[-1] / prices[-1 - lookback] - 1) * 100


def _drawdown_from_high(prices: list[float], lookback: int = HIGH_LOOKBACK) -> Optional[float]:
    """% de caída desde el máximo del período."""
    window = prices[-lookback:] if len(prices) >= lookback else prices
    if not window:
        return None
    peak = max(window)
    if peak == 0:
        return None
    return (prices[-1] / peak - 1) * 100


def _relative_strength(sector_prices: list[float], spy_prices: list[float], lookback: int) -> Optional[float]:
    """
    RS = retorno_sector_60d / retorno_spy_60d expresado como ratio.
    > 1.0 → sector outperforma. < 1.0 → underperforma.
    """
    if len(sector_prices) <= lookback or len(spy_prices) <= lookback:
        return None
    sec_ret = sector_prices[-1] / sector_prices[-1 - lookback]
    spy_ret = spy_prices[-1] / spy_prices[-1 - lookback]
    if spy_ret == 0:
        return None
    return round(sec_ret / spy_ret, 4)


def classify_sector_regime(
    sector_closes: list[float],
    spy_closes:    list[float],
) -> dict:
    """
    Clasifica el régimen de un sector dado sus cierres y los de SPY.

    Returns dict con: regime, mom20, mom60, drawdown_52w, rs_vs_spy
    """
    mom20       = _momentum_pct(sector_closes, MOM_SHORT_DAYS)
    mom60       = _momentum_pct(sector_closes, MOM_LONG_DAYS)
    drawdown    = _drawdown_from_high(sector_closes, HIGH_LOOKBACK)
    rs_vs_spy   = _relative_strength(sector_closes, spy_closes, MOM_LONG_DAYS)

    # ── Clasificación ─────────────────────────────────────────────────────────
    regime = 'NEUTRAL'

    if (
        mom60 is not None and mom60 > STRONG_MOM_MIN
        and rs_vs_spy is not None and rs_vs_spy >= RS_STRONG_MIN
    ):
        regime = 'STRONG'
    elif (
        mom60 is not None and mom60 < WEAK_MOM_MAX
        and rs_vs_spy is not None and rs_vs_spy <= RS_WEAK_MAX
    ):
        regime = 'WEAK'

    return {
        'regime':       regime,
        'mom20':        round(mom20,    4) if mom20    is not None else None,
        'mom60':        round(mom60,    4) if mom60    is not None else None,
        'drawdown_52w': round(drawdown, 4) if drawdown is not None else None,
        'rs_vs_spy':    rs_vs_spy,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

_SECTOR_ETF_MAP = {
    'XLK': 'Technology',
    'XLC': 'Communication Services',
    'XLF': 'Financials',
    'XLY': 'Consumer Discretionary',
    'XLE': 'Energy',
}


def _load_closes_by_symbol(table: str, symbol: str) -> list[tuple[date, float]]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT fecha, close FROM {table} WHERE simbolo=%s ORDER BY fecha ASC",
                (symbol,)
            )
            return [(row['fecha'], float(row['close'])) for row in cur.fetchall()]
    finally:
        conn.close()


def _save_sector_context(rows: list[dict]) -> None:
    if not rows:
        return
    sql = """
        INSERT INTO sector_context_daily
            (fecha, sector, simbolo, regime, mom20, mom60, drawdown_52w, rs_vs_spy)
        VALUES
            (%(fecha)s, %(sector)s, %(simbolo)s, %(regime)s,
             %(mom20)s, %(mom60)s, %(drawdown_52w)s, %(rs_vs_spy)s)
        ON DUPLICATE KEY UPDATE
            simbolo=VALUES(simbolo), regime=VALUES(regime),
            mom20=VALUES(mom20),     mom60=VALUES(mom60),
            drawdown_52w=VALUES(drawdown_52w), rs_vs_spy=VALUES(rs_vs_spy)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Runner principal
# ─────────────────────────────────────────────────────────────────────────────

def run_sector_regime(
    sector_benchmarks: list[str],
    from_date: Optional[date] = None,
    to_date:   Optional[date] = None,
) -> dict[str, list[dict]]:
    """
    Calcula y guarda el régimen sectorial para cada ETF y cada fecha disponible.

    Args:
        sector_benchmarks: lista de ETFs (ej. ['XLK','XLC','XLF','XLY','XLE'])
        from_date: fecha de inicio del cálculo
        to_date:   fecha de fin del cálculo

    Returns:
        dict {etf_symbol: [row_por_fecha]}
    """
    # Cargar SPY como referencia
    spy_series = _load_closes_by_symbol('market_index', 'SPY')
    if not spy_series:
        print("[ERROR] No hay datos de SPY en market_index. Correr load_history primero.")
        return {}

    spy_by_date = {d: c for d, c in spy_series}
    spy_dates   = sorted(spy_by_date.keys())

    to_date   = to_date   or date.today()
    from_date = from_date or spy_dates[0]

    all_results: dict[str, list[dict]] = {}

    for etf in sector_benchmarks:
        sector_name = _SECTOR_ETF_MAP.get(etf, etf)
        sector_series = _load_closes_by_symbol('sector_index', etf)

        if not sector_series:
            print(f"  [WARN] Sin datos para {etf} en sector_index")
            continue

        # Alinear series por fecha
        sector_by_date = {d: c for d, c in sector_series}
        common_dates   = sorted(set(spy_by_date) & set(sector_by_date))

        # Acumular cierres en orden
        spy_buf    = []
        sector_buf = []
        results    = []

        min_history = MOM_LONG_DAYS + 10

        for d in common_dates:
            spy_buf.append(spy_by_date[d])
            sector_buf.append(sector_by_date[d])

            if d < from_date or d > to_date:
                continue
            if len(sector_buf) < min_history:
                continue

            ctx = classify_sector_regime(sector_buf, spy_buf)
            row = {
                'fecha':   d,
                'sector':  sector_name,
                'simbolo': etf,
                **ctx,
            }
            results.append(row)

        _save_sector_context(results)
        all_results[etf] = results
        print(f"  sector_regime [{etf} / {sector_name}]: {len(results)} fechas guardadas")

    return all_results


def get_latest_sector_regimes(benchmarks: list[str]) -> dict[str, dict]:
    """
    Devuelve el último régimen guardado para cada sector.
    Returns: {etf_symbol: row_dict}
    """
    conn = get_conn()
    results = {}
    try:
        for etf in benchmarks:
            sector_name = _SECTOR_ETF_MAP.get(etf, etf)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM sector_context_daily
                       WHERE sector=%s ORDER BY fecha DESC LIMIT 1""",
                    (sector_name,)
                )
                row = cur.fetchone()
                if row:
                    results[etf] = row
    finally:
        conn.close()
    return results
