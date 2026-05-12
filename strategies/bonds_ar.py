"""
bonds_ar.py — Bonos soberanos argentinos: definiciones, TIR, señales
====================================================================
Reestructuración Guzmán 2020.  Cupones step-up, amortización escalonada.
Pagan 9-ene y 9-jul.  Convención 30/360.

Funciones públicas:
  BONDS                         dict con la ficha de cada bono
  get_remaining_cashflows()     flujos futuros por VN 100
  calc_accrued_interest()       intereses corridos 30/360
  calc_tir()                    TIR anualizada (Newton-Raphson)
  calc_modified_duration()      duración modificada
  calc_paridad()                paridad = precio / VR
  analyze_all()                 dashboard completo con Z-scores y señales
"""

from datetime import date, timedelta
from typing import Optional
import math

# ── helpers 30/360 ────────────────────────────────────────────────────────────

def _days360(d1: date, d2: date) -> int:
    y1, m1, day1 = d1.year, d1.month, min(d1.day, 30)
    y2, m2, day2 = d2.year, d2.month, d2.day
    if day2 == 31 and day1 >= 30:
        day2 = 30
    return 360 * (y2 - y1) + 30 * (m2 - m1) + (day2 - day1)


def _yearfrac360(d1: date, d2: date) -> float:
    return _days360(d1, d2) / 360.0

# ── fechas de pago ────────────────────────────────────────────────────────────

def _payment_dates(start_year: int, end_date: date) -> list[date]:
    dates = []
    for y in range(start_year, end_date.year + 1):
        for m in (1, 7):
            d = date(y, m, 9)
            if d <= end_date:
                dates.append(d)
    return sorted(dates)

# ── definiciones de bonos ─────────────────────────────────────────────────────
# coupon_schedule: [(desde, hasta, tasa_anual), ...]
# amort_schedule:  [(fecha, pct_del_original), ...]  pct sumando 100

def _build_amort(start: date, end: date, pct: float, freq_months: int = 6) -> list[tuple]:
    result = []
    d = start
    while d <= end:
        result.append((d, pct))
        if freq_months == 6:
            m = d.month + 6
            y = d.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            d = date(y, m, d.day)
        else:
            d = date(d.year + 1, d.month, d.day)
    return result


BONDS = {
    'AL29': {
        'name': 'Bonar USD 1% 2029',
        'law': 'ARG', 'currency': 'USD',
        'maturity': date(2029, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4), date(2029, 7, 9), 0.01),
        ],
        'amort_schedule': _build_amort(date(2025, 1, 9), date(2029, 7, 9), 10.0),
        'pair': 'GD29',
        'byma_symbol': 'AL29D',
    },
    'GD29': {
        'name': 'Global USD 1% 2029',
        'law': 'NY', 'currency': 'USD',
        'maturity': date(2029, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4), date(2029, 7, 9), 0.01),
        ],
        'amort_schedule': _build_amort(date(2025, 1, 9), date(2029, 7, 9), 10.0),
        'pair': 'AL29',
        'byma_symbol': 'GD29D',
    },
    'AL30': {
        'name': 'Bonar USD Step-Up 2030',
        'law': 'ARG', 'currency': 'USD',
        'maturity': date(2030, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2023, 7, 9), 0.005),
            (date(2023, 7, 9),  date(2027, 7, 9), 0.0075),
            (date(2027, 7, 9),  date(2030, 7, 9), 0.0175),
        ],
        'amort_schedule': [(date(2024, 7, 9), 4.0)] + _build_amort(date(2025, 1, 9), date(2030, 7, 9), 8.0),
        'pair': 'GD30',
        'byma_symbol': 'AL30D',
    },
    'GD30': {
        'name': 'Global USD Step-Up 2030',
        'law': 'NY', 'currency': 'USD',
        'maturity': date(2030, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2023, 7, 9), 0.005),
            (date(2023, 7, 9),  date(2027, 7, 9), 0.0075),
            (date(2027, 7, 9),  date(2030, 7, 9), 0.0175),
        ],
        'amort_schedule': [(date(2024, 7, 9), 4.0)] + _build_amort(date(2025, 1, 9), date(2030, 7, 9), 8.0),
        'pair': 'AL30',
        'byma_symbol': 'GD30D',
    },
    'AL35': {
        'name': 'Bonar USD Step-Up 2035',
        'law': 'ARG', 'currency': 'USD',
        'maturity': date(2035, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.02),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.03625),
            (date(2023, 7, 9),  date(2035, 7, 9), 0.04125),
        ],
        'amort_schedule': _build_amort(date(2031, 1, 9), date(2035, 7, 9), 10.0),
        'pair': 'GD35',
        'byma_symbol': 'AL35D',
    },
    'GD35': {
        'name': 'Global USD Step-Up 2035',
        'law': 'NY', 'currency': 'USD',
        'maturity': date(2035, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.02),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.03625),
            (date(2023, 7, 9),  date(2035, 7, 9), 0.04125),
        ],
        'amort_schedule': _build_amort(date(2031, 1, 9), date(2035, 7, 9), 10.0),
        'pair': 'AL35',
        'byma_symbol': 'GD35D',
    },
    'AE38': {
        'name': 'Bonar USD Step-Up 2038',
        'law': 'ARG', 'currency': 'USD',
        'maturity': date(2038, 1, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.02),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.03875),
            (date(2023, 7, 9),  date(2024, 7, 9), 0.0425),
            (date(2024, 7, 9),  date(2038, 1, 9), 0.05),
        ],
        'amort_schedule': _build_amort(date(2027, 7, 9), date(2038, 1, 9), 4.545),
        'pair': 'GD38',
        'byma_symbol': 'AE38D',
    },
    'GD38': {
        'name': 'Global USD Step-Up 2038',
        'law': 'NY', 'currency': 'USD',
        'maturity': date(2038, 1, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.02),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.03875),
            (date(2023, 7, 9),  date(2024, 7, 9), 0.0425),
            (date(2024, 7, 9),  date(2038, 1, 9), 0.05),
        ],
        'amort_schedule': _build_amort(date(2027, 7, 9), date(2038, 1, 9), 4.545),
        'pair': 'AE38',
        'byma_symbol': 'GD38D',
    },
    'AL41': {
        'name': 'Bonar USD Step-Up 2041',
        'law': 'ARG', 'currency': 'USD',
        'maturity': date(2041, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.005),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.0175),
            (date(2023, 7, 9),  date(2041, 7, 9), 0.035),
        ],
        'amort_schedule': _build_amort(date(2028, 1, 9), date(2041, 7, 9), 3.571),
        'pair': 'GD41',
        'byma_symbol': 'AL41D',
    },
    'GD41': {
        'name': 'Global USD Step-Up 2041',
        'law': 'NY', 'currency': 'USD',
        'maturity': date(2041, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.005),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.0175),
            (date(2023, 7, 9),  date(2041, 7, 9), 0.035),
        ],
        'amort_schedule': _build_amort(date(2028, 1, 9), date(2041, 7, 9), 3.571),
        'pair': 'AL41',
        'byma_symbol': 'GD41D',
    },
    'GD46': {
        'name': 'Global USD Step-Up 2046',
        'law': 'NY', 'currency': 'USD',
        'maturity': date(2046, 7, 9),
        'issue_date': date(2020, 9, 4),
        'coupon_schedule': [
            (date(2020, 9, 4),  date(2021, 7, 9), 0.00125),
            (date(2021, 7, 9),  date(2022, 7, 9), 0.005),
            (date(2022, 7, 9),  date(2023, 7, 9), 0.0175),
            (date(2023, 7, 9),  date(2027, 7, 9), 0.025),
            (date(2027, 7, 9),  date(2029, 7, 9), 0.035),
            (date(2029, 7, 9),  date(2046, 7, 9), 0.04875),
        ],
        'amort_schedule': _build_amort(date(2025, 1, 9), date(2046, 7, 9), 2.273),
        'pair': None,
        'byma_symbol': 'GD46D',
    },
}

ALL_BOND_SYMBOLS = sorted(BONDS.keys())

PAIRS = [
    ('AL29', 'GD29'),
    ('AL30', 'GD30'),
    ('AL35', 'GD35'),
    ('AE38', 'GD38'),
    ('AL41', 'GD41'),
]

# ── Valor Residual ────────────────────────────────────────────────────────────

def get_valor_residual(symbol: str, as_of: date) -> float:
    bond = BONDS[symbol]
    amortized = sum(pct for d, pct in bond['amort_schedule'] if d <= as_of)
    return max(0.0, 100.0 - amortized)


# ── Tasa cupón vigente ────────────────────────────────────────────────────────

def _coupon_rate_at(symbol: str, d: date) -> float:
    for start, end, rate in BONDS[symbol]['coupon_schedule']:
        if start <= d < end or (d == end and d == BONDS[symbol]['maturity']):
            return rate
    return BONDS[symbol]['coupon_schedule'][-1][2]


# ── Flujos de caja remanentes ─────────────────────────────────────────────────

def get_remaining_cashflows(symbol: str, settle_date: date) -> list[dict]:
    bond = BONDS[symbol]
    pay_dates = _payment_dates(2021, bond['maturity'])

    amort_map = {}
    for d, pct in bond['amort_schedule']:
        amort_map[d] = pct

    vr = 100.0
    flows = []
    for pd in pay_dates:
        if pd <= settle_date:
            if pd in amort_map:
                vr -= amort_map[pd]
            continue

        rate = _coupon_rate_at(symbol, pd)
        interest = vr * rate / 2.0

        amort_pct = amort_map.get(pd, 0.0)
        amort_amount = amort_pct  # pct of original 100

        flows.append({
            'date': pd,
            'interest': round(interest, 6),
            'amortization': round(amort_amount, 6),
            'total': round(interest + amort_amount, 6),
            'vr_before': round(vr, 6),
        })

        vr -= amort_pct

    return flows


# ── Intereses corridos (30/360) ───────────────────────────────────────────────

def calc_accrued_interest(symbol: str, settle_date: date) -> float:
    bond = BONDS[symbol]
    pay_dates = _payment_dates(2021, bond['maturity'])

    prev_pay = bond['issue_date']
    for pd in pay_dates:
        if pd > settle_date:
            break
        prev_pay = pd

    next_pay = None
    for pd in pay_dates:
        if pd > settle_date:
            next_pay = pd
            break

    if next_pay is None:
        return 0.0

    vr = get_valor_residual(symbol, settle_date)
    rate = _coupon_rate_at(symbol, next_pay)
    coupon_full = vr * rate / 2.0

    days_period = _days360(prev_pay, next_pay)
    days_accrued = _days360(prev_pay, settle_date)

    if days_period <= 0:
        return 0.0

    return coupon_full * days_accrued / days_period


# ── TIR (Newton-Raphson) ─────────────────────────────────────────────────────

def calc_tir(
    price_dirty: float,
    cashflows: list[dict],
    settle_date: date,
    guess: float = 0.08,
    tol: float = 1e-8,
    max_iter: int = 200,
) -> Optional[float]:
    if not cashflows or price_dirty <= 0:
        return None

    def pv(y: float) -> float:
        total = 0.0
        for cf in cashflows:
            t = _yearfrac360(settle_date, cf['date'])
            if t <= 0:
                continue
            total += cf['total'] / (1 + y) ** t
        return total

    def dpv(y: float) -> float:
        total = 0.0
        for cf in cashflows:
            t = _yearfrac360(settle_date, cf['date'])
            if t <= 0:
                continue
            total -= t * cf['total'] / (1 + y) ** (t + 1)
        return total

    y = guess
    for _ in range(max_iter):
        f = pv(y) - price_dirty
        df = dpv(y)
        if abs(df) < 1e-14:
            break
        y_new = y - f / df
        if y_new <= -0.99:
            y_new = y / 2
        if abs(y_new - y) < tol:
            return round(y_new, 6)
        y = y_new

    return round(y, 6)


# ── Duración Modificada ──────────────────────────────────────────────────────

def calc_modified_duration(
    price_dirty: float,
    cashflows: list[dict],
    settle_date: date,
    tir: float,
) -> Optional[float]:
    if tir is None or price_dirty <= 0:
        return None

    weighted_sum = 0.0
    pv_sum = 0.0
    for cf in cashflows:
        t = _yearfrac360(settle_date, cf['date'])
        if t <= 0:
            continue
        disc = cf['total'] / (1 + tir) ** t
        weighted_sum += t * disc
        pv_sum += disc

    if pv_sum <= 0:
        return None

    macaulay = weighted_sum / pv_sum
    return round(macaulay / (1 + tir), 4)


# ── Paridad ──────────────────────────────────────────────────────────────────

def calc_paridad(price_clean: float, symbol: str, settle_date: date) -> Optional[float]:
    vr = get_valor_residual(symbol, settle_date)
    if vr <= 0:
        return None
    return round(price_clean / vr * 100, 2)


# ── Análisis completo de un bono ─────────────────────────────────────────────

def analyze_bond(symbol: str, price_usd: float, settle_date: Optional[date] = None) -> Optional[dict]:
    if symbol not in BONDS or price_usd <= 0:
        return None

    settle = settle_date or date.today()
    bond = BONDS[symbol]

    cashflows = get_remaining_cashflows(symbol, settle)
    if not cashflows:
        return None

    accrued = calc_accrued_interest(symbol, settle)
    price_dirty = price_usd + accrued
    vr = get_valor_residual(symbol, settle)
    paridad = calc_paridad(price_usd, symbol, settle)

    tir = calc_tir(price_dirty, cashflows, settle)
    duration = calc_modified_duration(price_dirty, cashflows, settle, tir) if tir else None

    return {
        'symbol': symbol,
        'name': bond['name'],
        'law': bond['law'],
        'maturity': bond['maturity'].isoformat(),
        'price_clean': round(price_usd, 4),
        'price_dirty': round(price_dirty, 4),
        'accrued_interest': round(accrued, 4),
        'valor_residual': round(vr, 2),
        'paridad': paridad,
        'tir': round(tir * 100, 2) if tir else None,
        'duration_mod': duration,
        'pair': bond['pair'],
        'cashflows_count': len(cashflows),
        'next_payment': cashflows[0]['date'].isoformat() if cashflows else None,
        'next_payment_total': cashflows[0]['total'] if cashflows else None,
    }


# ── Z-score + señal ──────────────────────────────────────────────────────────

Z_BUY_THRESHOLD = 1.5
Z_SELL_THRESHOLD = -1.5

def calc_zscore_signal(current_tir: float, tir_history: list[float]) -> dict:
    if len(tir_history) < 10:
        return {'z_score': None, 'signal': 'NEUTRAL', 'avg_tir': None, 'std_tir': None}

    avg = sum(tir_history) / len(tir_history)
    variance = sum((x - avg) ** 2 for x in tir_history) / len(tir_history)
    std = math.sqrt(variance) if variance > 0 else 0.001

    z = (current_tir - avg) / std

    if z >= Z_BUY_THRESHOLD:
        signal = 'BUY'
    elif z <= Z_SELL_THRESHOLD:
        signal = 'SELL'
    else:
        signal = 'NEUTRAL'

    return {
        'z_score': round(z, 3),
        'signal': signal,
        'avg_tir': round(avg, 2),
        'std_tir': round(std, 4),
    }


def calc_spread_signal(spread_current: float, spread_history: list[float]) -> dict:
    if len(spread_history) < 10:
        return {'spread_z': None, 'spread_signal': 'NEUTRAL', 'avg_spread': None}

    avg = sum(spread_history) / len(spread_history)
    variance = sum((x - avg) ** 2 for x in spread_history) / len(spread_history)
    std = math.sqrt(variance) if variance > 0 else 0.001

    z = (spread_current - avg) / std

    if z >= 1.5:
        sig = 'AL_CHEAP'
    elif z <= -1.5:
        sig = 'GD_CHEAP'
    else:
        sig = 'NEUTRAL'

    return {
        'spread_z': round(z, 3),
        'spread_signal': sig,
        'avg_spread': round(avg, 2),
        'std_spread': round(std, 4),
    }
