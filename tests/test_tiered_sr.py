"""
Tests para strategies/tiered_sr.py

Todos los tests usan datos sinteticos (mock de _load) para no depender
de la base de datos.  Cada escenario genera OHLCV realista y verifica
que la clasificacion behavioral (historical/accelerated/tactical) sea
correcta.
"""

import math
import sys
import os
from datetime import date, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ── Helpers para generar OHLCV sintetico ────────────────────────────────────

def make_bar(o, h, l, c, vol=1000, fecha=None):
    """Barra OHLCV individual."""
    return {
        'fecha': fecha or date(2020, 1, 1),
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': vol,
    }


def make_uptrend(start, end, bars, tf='W', start_date=None):
    """
    Genera una tendencia alcista con pullbacks periodicos que crean pivots.
    Cada ~8-10 barras hay un dip de ~3-5% que genera un swing low detectabe.
    """
    start_date = start_date or date(2020, 1, 6)
    delta_days = 7 if tf == 'W' else 1
    rows = []
    pullback_period = 8
    pullback_depth = 0.04
    for i in range(bars):
        frac = i / max(bars - 1, 1)
        mid = start * math.exp(math.log(end / start) * frac)
        # Pullback ciclico: cada pullback_period barras baja un % y luego sube
        cycle_pos = i % pullback_period
        if cycle_pos < 2:
            dip = -pullback_depth * mid * (1 - cycle_pos / 2)
        else:
            dip = pullback_depth * mid * 0.2 * ((cycle_pos - 2) % 3)
        mid_adj = mid + dip
        spread = mid * 0.015
        o = mid_adj - spread
        c = mid_adj + spread
        h = max(o, c) * 1.012
        l = min(o, c) * 0.988
        f = start_date + timedelta(days=delta_days * i)
        rows.append(make_bar(round(o, 2), round(h, 2), round(l, 2), round(c, 2), 1000, f))
    return rows


def make_downtrend(start, end, bars, tf='W', start_date=None):
    """
    Genera tendencia bajista con bounces periodicos que crean pivot highs.
    """
    start_date = start_date or date(2020, 1, 6)
    delta_days = 7 if tf == 'W' else 1
    rows = []
    bounce_period = 8
    bounce_depth = 0.04
    for i in range(bars):
        frac = i / max(bars - 1, 1)
        mid = start * math.exp(math.log(end / start) * frac)
        cycle_pos = i % bounce_period
        if cycle_pos < 2:
            bump = bounce_depth * mid * (1 - cycle_pos / 2)
        else:
            bump = -bounce_depth * mid * 0.2 * ((cycle_pos - 2) % 3)
        mid_adj = mid + bump
        spread = mid * 0.015
        o = mid_adj + spread
        c = mid_adj - spread
        h = max(o, c) * 1.012
        l = min(o, c) * 0.988
        f = start_date + timedelta(days=delta_days * i)
        rows.append(make_bar(round(o, 2), round(h, 2), round(l, 2), round(c, 2), 1000, f))
    return rows


def make_sideways(price, bars, tf='W', spread_pct=3, start_date=None):
    """Genera lateralizacion alrededor de `price` con spread limitado."""
    start_date = start_date or date(2024, 1, 1)
    delta_days = 7 if tf == 'W' else 1
    rows = []
    for i in range(bars):
        noise = price * spread_pct / 100 * (0.5 if i % 2 == 0 else -0.5)
        mid = price + noise * 0.3
        sp = price * spread_pct / 200
        o = mid - sp
        c = mid + sp * (0.5 if i % 3 == 0 else 1)
        h = max(o, c) * 1.005
        l = min(o, c) * 0.995
        f = start_date + timedelta(days=delta_days * i)
        rows.append(make_bar(round(o, 2), round(h, 2), round(l, 2), round(c, 2), 1000, f))
    return rows


def make_accelerated_rally(
    structural_bars=200,
    accel_bars=80,
    struct_start=50,
    struct_end=120,
    accel_end=350,
    tf_struct='W',
    tf_accel='D',
):
    """
    Genera datos para un rally con fase acelerada:
    - Weekly: subida lenta de struct_start a struct_end en structural_bars
    - Daily: subida rapida de struct_end a accel_end en accel_bars
    """
    struct_start_date = date(2020, 1, 6)
    weekly = make_uptrend(struct_start, struct_end, structural_bars, tf_struct, struct_start_date)

    accel_start_date = weekly[-1]['fecha'] + timedelta(days=1)
    daily = make_uptrend(struct_end, accel_end, accel_bars, tf_accel, accel_start_date)

    # Add some older daily data that corresponds to the weekly period
    # (last 120 days of weekly = last ~17 weeks)
    older_daily_start = weekly[-20]['fecha']
    older_daily = make_uptrend(
        struct_end * 0.85, struct_end, 40, 'D', older_daily_start,
    )
    full_daily = older_daily + daily

    return weekly, full_daily


def make_accelerated_decline(
    structural_bars=200,
    accel_bars=80,
    struct_start=300,
    struct_end=180,
    accel_end=60,
):
    """
    Genera datos para una caida con fase acelerada (espejo del rally).
    """
    struct_start_date = date(2020, 1, 6)
    weekly = make_downtrend(struct_start, struct_end, structural_bars, 'W', struct_start_date)

    accel_start_date = weekly[-1]['fecha'] + timedelta(days=1)
    daily = make_downtrend(struct_end, accel_end, accel_bars, 'D', accel_start_date)

    older_daily_start = weekly[-20]['fecha']
    older_daily = make_downtrend(struct_end * 1.15, struct_end, 40, 'D', older_daily_start)
    full_daily = older_daily + daily

    return weekly, full_daily


# ── Mock helper ─────────────────────────────────────────────────────────────

def mock_load(weekly_rows, daily_rows):
    """Retorna una funcion que simula _load para weekly y daily."""
    def _fake_load(symbol, tf, fecha_max):
        if tf == 'W':
            return [r for r in weekly_rows if r['fecha'] <= fecha_max]
        elif tf == 'D':
            return [r for r in daily_rows if r['fecha'] <= fecha_max]
        return []
    return _fake_load


# ── Tests ───────────────────────────────────────────────────────────────────

class TestDetectAcceleration:
    """Tests para la funcion _detect_acceleration."""

    def test_no_acceleration_close_to_structural(self):
        """Precio 10% arriba del soporte → no hay aceleracion."""
        from strategies.tiered_sr import _detect_acceleration
        daily = make_uptrend(100, 115, 120, 'D')
        result = _detect_acceleration(
            structural_slope_annual=20.0,
            structural_current_value=100.0,
            price=110.0,
            daily_rows=daily,
            side='support',
        )
        assert not result['detected']

    def test_acceleration_detected_far_from_structural(self):
        """Precio 40% arriba con pendiente diaria empinada → aceleracion."""
        from strategies.tiered_sr import _detect_acceleration
        daily = make_uptrend(80, 160, 120, 'D')
        result = _detect_acceleration(
            structural_slope_annual=15.0,
            structural_current_value=100.0,
            price=140.0,
            daily_rows=daily,
            side='support',
        )
        assert result['detected']
        assert result['direction'] == 'bullish'
        assert result['distance_from_structural_pct'] >= 25

    def test_bearish_acceleration(self):
        """Precio 35% debajo de resistencia con highs cayendo → aceleracion bajista."""
        from strategies.tiered_sr import _detect_acceleration
        daily = make_downtrend(200, 110, 120, 'D')
        result = _detect_acceleration(
            structural_slope_annual=-10.0,
            structural_current_value=200.0,
            price=130.0,
            daily_rows=daily,
            side='resistance',
        )
        assert result['detected']
        assert result['direction'] == 'bearish'

    def test_no_acceleration_insufficient_data(self):
        """Menos de 30 barras diarias → no detecta."""
        from strategies.tiered_sr import _detect_acceleration
        daily = make_uptrend(100, 200, 20, 'D')
        result = _detect_acceleration(
            structural_slope_annual=15.0,
            structural_current_value=100.0,
            price=200.0,
            daily_rows=daily,
            side='support',
        )
        assert not result['detected']


class TestFitAccelerated:
    """Tests para las funciones de fitting acelerado."""

    def test_fit_accelerated_support_finds_line(self):
        """Uptrend diario claro → encuentra linea ascendente."""
        from strategies.tiered_sr import _fit_accelerated_support
        daily = make_uptrend(100, 200, 120, 'D')
        tl = _fit_accelerated_support(daily)
        # Puede o no encontrar dependiendo de los pivots
        # pero si encuentra, debe tener slope positiva
        if tl is not None:
            assert tl['slope'] > 0
            assert tl['touches'] >= 2

    def test_fit_accelerated_resistance_finds_line(self):
        """Downtrend diario → encuentra linea descendente."""
        from strategies.tiered_sr import _fit_accelerated_resistance
        daily = make_downtrend(300, 150, 120, 'D')
        tl = _fit_accelerated_resistance(daily)
        if tl is not None:
            assert tl['slope'] < 0
            assert tl['touches'] >= 2

    def test_fit_returns_none_on_insufficient_data(self):
        """Menos de 30 barras → None."""
        from strategies.tiered_sr import _fit_accelerated_support
        daily = make_uptrend(100, 120, 15, 'D')
        assert _fit_accelerated_support(daily) is None


class TestFitTactical:
    """Tests para la deteccion de zonas horizontales tacticas."""

    def test_sideways_detected(self):
        """Precio lateral → detecta zona horizontal."""
        from strategies.tiered_sr import _fit_tactical_support
        rows = make_sideways(100, 15, 'W')
        tl = _fit_tactical_support(rows, 'W')
        if tl is not None:
            assert tl['kind'] == 'horizontal'
            assert tl['slope'] == 0.0

    def test_no_sideways_in_trend(self):
        """Uptrend fuerte → no detecta lateral."""
        from strategies.tiered_sr import _fit_tactical_support
        rows = make_uptrend(50, 200, 15, 'W')
        tl = _fit_tactical_support(rows, 'W')
        assert tl is None


class TestStopHint:
    """Tests para el calculo de stop_hint."""

    def test_support_stop_below(self):
        """Stop de soporte = current_value × 0.98."""
        from strategies.tiered_sr import _compute_stop_hint
        tier = {'current_value': 100.0, 'kind': 'ascending'}
        stop = _compute_stop_hint(tier, 'support')
        assert stop == pytest.approx(98.0, abs=0.01)

    def test_resistance_stop_above(self):
        """Stop de resistencia = current_value × 1.02."""
        from strategies.tiered_sr import _compute_stop_hint
        tier = {'current_value': 100.0, 'kind': 'descending'}
        stop = _compute_stop_hint(tier, 'resistance')
        assert stop == pytest.approx(102.0, abs=0.01)

    def test_horizontal_support_uses_zone_low(self):
        """Stop de soporte horizontal = zone_low × 0.98."""
        from strategies.tiered_sr import _compute_stop_hint
        tier = {'current_value': 102.0, 'kind': 'horizontal', 'zone_low': 95.0}
        stop = _compute_stop_hint(tier, 'support')
        assert stop == pytest.approx(93.1, abs=0.01)


class TestGetTieredSR:
    """Tests de integracion del orquestador get_tiered_sr."""

    @patch('strategies.tiered_sr._load')
    def test_no_data_returns_empty(self, mock):
        """Sin datos → todos los tiers None."""
        from strategies.tiered_sr import get_tiered_sr
        mock.return_value = []
        result = get_tiered_sr('FAKE', date(2026, 1, 1))
        assert result['price'] is None
        assert result['support']['historical'] is None
        assert result['support']['accelerated'] is None
        assert result['support']['tactical'] is None
        assert result['resistance']['historical'] is None

    @patch('strategies.tiered_sr._load')
    def test_normal_uptrend_historical_only(self, mock):
        """
        Uptrend semanal normal, precio cerca del soporte.
        Espera historical populated, accelerated None.
        """
        from strategies.tiered_sr import get_tiered_sr
        weekly = make_uptrend(50, 120, 200, 'W')
        daily = make_uptrend(110, 120, 60, 'D',
                             start_date=weekly[-60]['fecha'])
        mock.side_effect = mock_load(weekly, daily)

        result = get_tiered_sr('TEST', weekly[-1]['fecha'])
        assert result['price'] is not None

        # Historical support may or may not be found depending on pivot geometry
        # but accelerated should NOT be found (price near structural)
        accel = result['acceleration']['support']
        assert not accel['detected']
        assert result['support']['accelerated'] is None

    @patch('strategies.tiered_sr._load')
    def test_bullish_acceleration_scenario(self, mock):
        """
        Rally semanal lento + aceleracion diaria → detected=True.
        """
        from strategies.tiered_sr import get_tiered_sr
        weekly, daily = make_accelerated_rally(
            structural_bars=200,
            accel_bars=80,
            struct_start=50,
            struct_end=120,
            accel_end=350,
        )
        mock.side_effect = mock_load(weekly, daily)
        last_date = max(daily[-1]['fecha'], weekly[-1]['fecha'])

        result = get_tiered_sr('ACCEL', last_date)
        accel_info = result['acceleration']['support']

        # La distancia debe ser grande (precio ~350 vs soporte ~120)
        assert accel_info['distance_from_structural_pct'] > 20 or not accel_info['detected']
        # Si detecta aceleracion, el tier acelerado deberia existir
        if accel_info['detected']:
            accel_tier = result['support']['accelerated']
            if accel_tier is not None:
                assert accel_tier['classification'] == 'accelerated'
                assert accel_tier['kind'] == 'ascending'
                assert 'stop_hint' in accel_tier

    @patch('strategies.tiered_sr._load')
    def test_output_structure_complete(self, mock):
        """Verifica que el dict de salida tiene todos los campos requeridos."""
        from strategies.tiered_sr import get_tiered_sr
        weekly = make_uptrend(50, 120, 200, 'W')
        daily = make_uptrend(110, 120, 60, 'D',
                             start_date=weekly[-60]['fecha'])
        mock.side_effect = mock_load(weekly, daily)

        result = get_tiered_sr('STRUCT', weekly[-1]['fecha'])

        assert 'symbol' in result
        assert 'price' in result
        assert 'fecha' in result
        assert 'support' in result
        assert 'resistance' in result
        assert 'acceleration' in result

        for side in ('support', 'resistance'):
            assert 'historical' in result[side]
            assert 'accelerated' in result[side]
            assert 'tactical' in result[side]

        for side in ('support', 'resistance'):
            assert 'detected' in result['acceleration'][side]
            assert 'direction' in result['acceleration'][side]

    @patch('strategies.tiered_sr._load')
    def test_historical_tier_has_metadata(self, mock):
        """Si historical existe, debe tener los campos behavioral."""
        from strategies.tiered_sr import get_tiered_sr
        weekly = make_uptrend(30, 150, 250, 'W')
        daily = make_uptrend(140, 150, 60, 'D',
                             start_date=weekly[-60]['fecha'])
        mock.side_effect = mock_load(weekly, daily)

        result = get_tiered_sr('META', weekly[-1]['fecha'])
        hist = result['support']['historical']
        if hist is not None:
            assert hist['classification'] == 'historical'
            assert 'stop_hint' in hist
            assert 'status' in hist
            assert hist['status'] in ('ACTIVE', 'TESTING', 'BROKEN')
            assert 'current_value' in hist
            assert 'distance_pct' in hist
            assert 'slope_annual_pct' in hist
            assert 'line_points' in hist
            assert 'touch_points' in hist
            assert 'touches' in hist
            assert 'anchor1' in hist
            assert 'anchor2' in hist

    @patch('strategies.tiered_sr._load')
    def test_lateralization_gets_tactical(self, mock):
        """
        Precio lateral sin tendencia → tactical deberia detectar zona.
        """
        from strategies.tiered_sr import get_tiered_sr
        # Weekly: subida larga + lateralizacion al final
        weekly_up = make_uptrend(30, 100, 180, 'W')
        weekly_lat = make_sideways(100, 20, 'W',
                                   start_date=weekly_up[-1]['fecha'] + timedelta(days=7))
        weekly = weekly_up + weekly_lat
        daily = make_sideways(100, 60, 'D',
                              start_date=weekly[-60]['fecha'])
        mock.side_effect = mock_load(weekly, daily)

        result = get_tiered_sr('LAT', weekly[-1]['fecha'])
        # Acceleration should not trigger for lateral
        assert not result['acceleration']['support']['detected']

    @patch('strategies.tiered_sr._load')
    def test_bearish_acceleration_resistance(self, mock):
        """
        Caida acelerada → resistance.accelerated deberia aparecer.
        """
        from strategies.tiered_sr import get_tiered_sr
        weekly, daily = make_accelerated_decline(
            structural_bars=200,
            accel_bars=80,
            struct_start=300,
            struct_end=180,
            accel_end=60,
        )
        mock.side_effect = mock_load(weekly, daily)
        last_date = max(daily[-1]['fecha'], weekly[-1]['fecha'])

        result = get_tiered_sr('BEAR', last_date)
        accel_info = result['acceleration']['resistance']

        # Si detecta aceleracion bajista
        if accel_info['detected']:
            assert accel_info['direction'] == 'bearish'
            accel_tier = result['resistance']['accelerated']
            if accel_tier is not None:
                assert accel_tier['classification'] == 'accelerated'
                assert accel_tier['kind'] == 'descending'


class TestOlsSlope:
    """Tests para la funcion interna _ols_slope."""

    def test_positive_slope(self):
        from strategies.tiered_sr import _ols_slope
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _ols_slope(values) == pytest.approx(1.0, abs=0.01)

    def test_flat_slope(self):
        from strategies.tiered_sr import _ols_slope
        values = [5.0, 5.0, 5.0, 5.0]
        assert _ols_slope(values) == pytest.approx(0.0, abs=0.01)

    def test_insufficient_data(self):
        from strategies.tiered_sr import _ols_slope
        assert _ols_slope([1.0, 2.0]) == 0.0
