"""
strategies.rotation — Backtest de estrategia de rotación semanal (V2).

Pregunta que responde:
    ¿Una rotación semanal hacia el(los) #1 del ranking, con guardarrieles de
    régimen y de churn, supera a SPY buy & hold?

Cambios V2 vs V1:
    - Filtro de régimen (configurable): si SPY < SMA200 → no abrir nuevas
      posiciones. Las existentes se mantienen sólo si siguen en top_keep.
    - Parámetros de churn (top_keep, rotate_diff) configurables, con defaults
      más estrictos (10 / 15.0).
    - Filtros de universo configurables (min_price, min_avg_vol).
    - Modos:
        * 'top1'        — 1 sola posición (lógica clásica).
        * 'top3_equal'  — 3 posiciones equally weighted, rotación por slot.
    - Snapshots de estado para construir la curva diaria de forma robusta.

Reglas (V2, configurables):
    1. Frecuencia: una decisión por semana (último día hábil de la semana ISO).
    2. Ejecución: open del siguiente día hábil (fallback close).
    3. Régimen: si SPY < SMA200 → no abrir, mantener sólo lo que siga fuerte.
    4. Top-K (k=1 o 3): el portfolio target son los top K del ranking; cada
       slot se rota cuando su símbolo cae fuera de top_keep, o cuando un
       candidato externo le saca >= rotate_diff puntos al peor slot.
    5. Comisión por trade (default 0.05%) en cada compra y cada venta.
    6. Filtros universo: precio > min_price y avg_vol_20d > min_avg_vol.
    7. Benchmark: SPY buy & hold con mismo capital inicial.

Output: dict JSON-serializable con `equity_curve`, `history`, `metrics`,
`summary`, `config`, `period`. Listo para alimentar /backtest/rotation.

CLI:
    python -m strategies.rotation                  # default: último año
    python -m strategies.rotation 2024-01-01
    python -m strategies.rotation 2024-01-01 2025-01-01 --mode top3_equal
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import os
from datetime import date, datetime, timedelta
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.shared.ranking_engine import (
    MIN_CANDLES,
    fetch_universe_history_range, fetch_spy_history_range,
    group_by_symbol, score_symbol_at,
    compute_return, compute_avg_volume, compute_sma,
)


# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_INITIAL_CAPITAL = 10_000.0
DEFAULT_FEE_RATE        = 0.0005    # 0.05% por trade

DEFAULT_TOP_KEEP        = 10        # actual debe estar en top N (V2: 10)
DEFAULT_ROTATE_DIFF     = 15.0      # gap mínimo de score para rotar (V2: 15)
DEFAULT_MAX_UNIVERSE    = 500
DEFAULT_MODE            = 'top1'    # 'top1' | 'top3_equal'
DEFAULT_REGIME_FILTER   = True
DEFAULT_MIN_PRICE       = 10.0      # más estricto que el filtro base (5)
DEFAULT_MIN_AVG_VOL     = 1_000_000 # más estricto que el base (500k)

WARMUP_DAYS             = 365
MAX_FORWARD_FILL        = 5
SMA_REGIME_WINDOW       = 200

VALID_MODES = ('top1', 'top3_equal')


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _to_date(x: Any) -> date | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        return datetime.strptime(x[:10], '%Y-%m-%d').date()
    return None


def _last_trading_day_per_iso_week(spy_dates: list[date],
                                   start: date, end: date) -> list[date]:
    """Devuelve el último día hábil de SPY en cada semana ISO dentro del rango."""
    weeks: dict[tuple[int, int], date] = {}
    for d in spy_dates:
        if d < start or d > end:
            continue
        iso = d.isocalendar()
        key = (iso[0], iso[1])
        if key not in weeks or d > weeks[key]:
            weeks[key] = d
    return sorted(weeks.values())


def _next_trading_day(spy_dates: list[date], after: date) -> date | None:
    for d in spy_dates:
        if d > after:
            return d
    return None


def _build_date_index(candles: list[dict]) -> dict[date, int]:
    return {_to_date(c['fecha']): i for i, c in enumerate(candles)}


def _open_at(candles: list[dict], date_idx: dict[date, int],
             target: date, sorted_dates: list[date]) -> tuple[float, date] | None:
    """Open en o después de `target`, fwd-fill hasta MAX_FORWARD_FILL días."""
    if target in date_idx:
        c = candles[date_idx[target]]
        return float(c['precio_apertura'] or c['precio_cierre'] or 0), target
    looked = 0
    for d in sorted_dates:
        if d <= target:
            continue
        looked += 1
        if looked > MAX_FORWARD_FILL:
            return None
        c = candles[date_idx[d]]
        return float(c['precio_apertura'] or c['precio_cierre'] or 0), d
    return None


def _close_at(candles: list[dict], date_idx: dict[date, int],
              target: date) -> float | None:
    """Close exacto en target o el último ≤ target."""
    if target in date_idx:
        c = candles[date_idx[target]]
        v = c['precio_cierre']
        return float(v) if v else None
    last: float | None = None
    for c in candles:
        d = _to_date(c['fecha'])
        if d > target:
            break
        if c['precio_cierre']:
            last = float(c['precio_cierre'])
    return last


def _prefilter_universe(grouped: dict[str, list[dict]],
                        max_universe: int,
                        min_price: float,
                        min_avg_vol: float) -> dict[str, list[dict]]:
    """
    Filtra universo:
      - ≥ MIN_CANDLES candles
      - precio último candle ≥ min_price
      - avg_volume_20d ≥ min_avg_vol
    Recorta a top max_universe por liquidez.
    """
    rated: list[tuple[str, float, list[dict]]] = []
    for sym, candles in grouped.items():
        if len(candles) < MIN_CANDLES:
            continue
        last_close = candles[-1].get('precio_cierre')
        if not last_close or float(last_close) < min_price:
            continue
        avg_vol = compute_avg_volume(candles, 20)
        if avg_vol is None or avg_vol < min_avg_vol:
            continue
        rated.append((sym, avg_vol, candles))
    rated.sort(key=lambda r: r[1], reverse=True)
    return {sym: candles for sym, _, candles in rated[:max_universe]}


def _dedupe_by_market(grouped: dict[str, list[dict]]) -> dict[str, list[dict]]:
    PRIORITY = {'NASDAQ': 0, 'NYSE': 1, 'NYSE_AMERICAN': 2, 'NYSE_ARCA': 3, 'CBOE_BZX': 4}
    out: dict[str, list[dict]] = {}
    for sym, candles in grouped.items():
        if sym in out:
            existing = out[sym][-1].get('mercado')
            new      = candles[-1].get('mercado')
            if PRIORITY.get(new, 99) < PRIORITY.get(existing, 99):
                out[sym] = candles
        else:
            out[sym] = candles
    return out


def _in_bull_regime(spy_rows: list[dict], idx: int,
                    window: int = SMA_REGIME_WINDOW) -> bool:
    """SPY close >= SMA200 → bull. Durante warmup asumimos bull (no penalizamos)."""
    if idx + 1 < window:
        return True
    sma = compute_sma(spy_rows[: idx + 1], window)
    if sma is None or sma <= 0:
        return True
    spy_close = float(spy_rows[idx].get('precio_cierre') or 0)
    if spy_close <= 0:
        return True
    return spy_close >= sma


# ─── Métricas ────────────────────────────────────────────────────────────────

def _compute_metrics(curve: list[dict], rotations: int,
                     start: date, end: date) -> dict:
    if len(curve) < 2:
        return {
            'total_return': 0, 'cagr': 0, 'max_drawdown': 0,
            'sharpe': 0, 'rotations_count': rotations,
        }
    initial = curve[0]['strat']
    final   = curve[-1]['strat']
    total_return = (final / initial - 1.0) if initial else 0.0

    days  = max((end - start).days, 1)
    years = days / 365.25
    cagr  = (final / initial) ** (1.0 / years) - 1.0 if years > 0 and initial > 0 else 0.0

    peak = curve[0]['strat']
    max_dd = 0.0
    for p in curve:
        s = p['strat']
        if s > peak:
            peak = s
        dd = (peak - s) / peak if peak else 0.0
        if dd > max_dd:
            max_dd = dd

    weekly_rets: list[float] = []
    for i in range(5, len(curve), 5):
        prev = curve[i - 5]['strat']
        curr = curve[i]['strat']
        if prev:
            weekly_rets.append(curr / prev - 1.0)
    if len(weekly_rets) >= 2:
        mean = sum(weekly_rets) / len(weekly_rets)
        var  = sum((r - mean) ** 2 for r in weekly_rets) / (len(weekly_rets) - 1)
        std  = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(52) if std > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        'total_return':    round(total_return, 4),
        'cagr':            round(cagr, 4),
        'max_drawdown':    round(max_dd, 4),
        'sharpe':          round(sharpe, 3),
        'rotations_count': rotations,
    }


# ─── Backtest ────────────────────────────────────────────────────────────────

class RotationBacktest:
    """Backtest de la estrategia de rotación semanal — V2."""

    def __init__(self,
                 initial_capital: float = DEFAULT_INITIAL_CAPITAL,
                 fee_rate:        float = DEFAULT_FEE_RATE,
                 top_keep:        int   = DEFAULT_TOP_KEEP,
                 rotate_diff:     float = DEFAULT_ROTATE_DIFF,
                 max_universe:    int   = DEFAULT_MAX_UNIVERSE,
                 mode:            str   = DEFAULT_MODE,
                 regime_filter:   bool  = DEFAULT_REGIME_FILTER,
                 min_price:       float = DEFAULT_MIN_PRICE,
                 min_avg_vol:     float = DEFAULT_MIN_AVG_VOL):
        if mode not in VALID_MODES:
            raise ValueError(f'mode inválido: {mode}. Válidos: {VALID_MODES}')
        self.initial_capital = initial_capital
        self.fee_rate        = fee_rate
        self.top_keep        = top_keep
        self.rotate_diff     = rotate_diff
        self.max_universe    = max_universe
        self.mode            = mode
        self.regime_filter   = regime_filter
        self.min_price       = min_price
        self.min_avg_vol     = min_avg_vol
        self.k               = 1 if mode == 'top1' else 3

    # ─── Public entrypoint ───────────────────────────────────────────────────

    def run(self,
            start: date | None = None,
            end:   date | None = None) -> dict:
        end   = end   or date.today()
        start = start or (end - timedelta(days=365))

        # 1. Bulk fetch con warmup
        fetch_from = start - timedelta(days=WARMUP_DAYS)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                rows     = fetch_universe_history_range(cur, fetch_from, end)
                spy_rows = fetch_spy_history_range(cur, fetch_from, end)
        finally:
            conn.close()

        for r in rows:     r['fecha'] = _to_date(r['fecha'])
        for r in spy_rows: r['fecha'] = _to_date(r['fecha'])

        if not spy_rows:
            return self._empty_result(start, end, 'no SPY data')

        # 2. Agrupar + dedup + pre-filtrar universo
        grouped  = _dedupe_by_market(group_by_symbol(rows))
        universe = _prefilter_universe(
            grouped, self.max_universe, self.min_price, self.min_avg_vol)
        if not universe:
            return self._empty_result(start, end, 'empty universe after filter')

        date_idx_map:     dict[str, dict[date, int]] = {}
        sorted_dates_map: dict[str, list[date]]      = {}
        for sym, candles in universe.items():
            date_idx_map[sym]     = _build_date_index(candles)
            sorted_dates_map[sym] = sorted(date_idx_map[sym].keys())

        # 3. Calendario
        spy_dates = [r['fecha'] for r in spy_rows]
        spy_close_by_date = {r['fecha']: float(r['precio_cierre'])
                             for r in spy_rows if r['precio_cierre']}
        spy_dates_in_range = [d for d in spy_dates if start <= d <= end]
        if not spy_dates_in_range:
            return self._empty_result(start, end, 'no SPY trading days in range')

        decision_days   = _last_trading_day_per_iso_week(spy_dates, start, end)
        spy_idx_by_date = {d: i for i, d in enumerate(spy_dates)}

        # 4. Estado inicial: K slots vacíos, capital repartido
        slots:         list[dict | None] = [None] * self.k
        cash_per_slot: list[float]       = [self.initial_capital / self.k] * self.k

        history:       list[dict] = []
        rotations                 = 0

        # Snapshots para curva diaria. effective_from = primer día del rango.
        state_history: list[dict] = [{
            'effective_from': spy_dates_in_range[0],
            'slots': [None] * self.k,
            'cash':  [self.initial_capital / self.k] * self.k,
        }]

        # 5. Loop semanal
        for decision_day in decision_days:
            spy_i = spy_idx_by_date.get(decision_day)
            if spy_i is None or spy_i < 21:
                history.append(self._row(
                    decision_day, 'SKIP', self._held_str(slots),
                    self._mark_total(slots, cash_per_slot, universe,
                                     date_idx_map, decision_day),
                    reason='warmup insuficiente'))
                continue

            spy_ret_20d_now = compute_return(spy_rows[: spy_i + 1], 20)
            bull = (not self.regime_filter) or _in_bull_regime(spy_rows, spy_i)

            ranking = self._rank_universe(
                universe, date_idx_map, decision_day, spy_ret_20d_now)
            if not ranking:
                history.append(self._row(
                    decision_day, 'SKIP', self._held_str(slots),
                    self._mark_total(slots, cash_per_slot, universe,
                                     date_idx_map, decision_day),
                    reason='ranking vacío'))
                continue

            score_by_symbol = {r['symbol']: r['score'] for r in ranking}
            top_keep_set    = {r['symbol'] for r in ranking[: self.top_keep]}

            # 5a. Actions iniciales
            actions:     list[str]                 = []
            new_targets: list[str | None]          = [None] * self.k
            for i in range(self.k):
                actions.append('EMPTY' if slots[i] is None else 'HOLD')

            # 5b. Cierres forzosos: símbolo desapareció o salió de top_keep
            for i, slot in enumerate(slots):
                if slot is None:
                    continue
                sym = slot['symbol']
                if sym not in score_by_symbol or sym not in top_keep_set:
                    actions[i] = 'CLOSE'

            # 5c. Régimen alcista → llenar slots vacíos / cerrados
            if bull:
                held_alive = set()
                for i, s in enumerate(slots):
                    if s and actions[i] != 'CLOSE':
                        held_alive.add(s['symbol'])
                candidates = [r for r in ranking if r['symbol'] not in held_alive]
                cand_iter  = iter(candidates)
                for i in range(self.k):
                    if actions[i] in ('EMPTY', 'CLOSE'):
                        nxt = next(cand_iter, None)
                        if nxt is None:
                            continue
                        new_targets[i] = nxt['symbol']
                        actions[i] = 'CLOSE_AND_OPEN' if actions[i] == 'CLOSE' else 'OPEN'

                # 5d. Rotación por mejora de score:
                #     comparar el slot proyectado más débil vs el mejor
                #     candidato no usado.
                if self.rotate_diff > 0:
                    projected: list[tuple[int, str, float]] = []
                    for i in range(self.k):
                        proj_sym = (new_targets[i] or
                                    (slots[i]['symbol']
                                     if slots[i] and actions[i] == 'HOLD' else None))
                        if proj_sym and proj_sym in score_by_symbol:
                            projected.append((i, proj_sym, score_by_symbol[proj_sym]))

                    used   = {p[1] for p in projected}
                    unused = [r for r in ranking if r['symbol'] not in used]
                    if projected and unused:
                        weakest = min(projected, key=lambda t: t[2])
                        w_idx, _w_sym, w_score = weakest
                        best = unused[0]
                        if (best['score'] - w_score) >= self.rotate_diff:
                            new_targets[w_idx] = best['symbol']
                            if actions[w_idx] == 'HOLD':
                                actions[w_idx] = 'CLOSE_AND_OPEN'
                            elif actions[w_idx] == 'OPEN':
                                actions[w_idx] = 'OPEN'
                            elif actions[w_idx] == 'CLOSE_AND_OPEN':
                                pass

            # else (bear): nada se abre. Slots EMPTY quedan en cash, los
            # marcados a CLOSE se cierran a cash, los HOLD siguen.

            # 5e. ¿Hay trades?
            any_trade = any(a in ('CLOSE', 'CLOSE_AND_OPEN', 'OPEN') for a in actions)
            if not any_trade:
                history.append(self._row(
                    decision_day, 'HOLD', self._held_str(slots),
                    self._mark_total(slots, cash_per_slot, universe,
                                     date_idx_map, decision_day),
                    score=ranking[0]['score'],
                    regime=('bull' if bull else 'bear')))
                continue

            exec_day = _next_trading_day(spy_dates, decision_day)
            if exec_day is None or exec_day > end:
                history.append(self._row(
                    decision_day, 'SKIP', self._held_str(slots),
                    self._mark_total(slots, cash_per_slot, universe,
                                     date_idx_map, decision_day),
                    reason='sin exec_day en rango'))
                continue

            # 5f. Ejecutar acciones por slot
            closed_syms: list[str] = []
            opened_syms: list[str] = []
            for i, action in enumerate(actions):
                if action in ('HOLD', 'EMPTY'):
                    continue
                slot = slots[i]
                if action == 'CLOSE':
                    cash = self._sell_slot(
                        slot, exec_day, universe, date_idx_map, sorted_dates_map)
                    if cash is None:
                        continue
                    cash_per_slot[i] = cash
                    closed_syms.append(slot['symbol'])
                    slots[i] = None
                elif action == 'CLOSE_AND_OPEN':
                    cash = self._sell_slot(
                        slot, exec_day, universe, date_idx_map, sorted_dates_map)
                    if cash is None:
                        continue
                    cash_per_slot[i] = cash
                    closed_syms.append(slot['symbol'])
                    slots[i] = None
                    new_sym = new_targets[i]
                    opened = self._buy_slot(
                        new_sym, cash_per_slot[i], exec_day,
                        universe, date_idx_map, sorted_dates_map)
                    if opened is None:
                        continue
                    slots[i] = opened
                    cash_per_slot[i] = 0.0
                    opened_syms.append(new_sym)
                    rotations += 1
                elif action == 'OPEN':
                    new_sym = new_targets[i]
                    opened = self._buy_slot(
                        new_sym, cash_per_slot[i], exec_day,
                        universe, date_idx_map, sorted_dates_map)
                    if opened is None:
                        continue
                    slots[i] = opened
                    cash_per_slot[i] = 0.0
                    opened_syms.append(new_sym)
                    rotations += 1

            # 5g. Snapshot del nuevo estado
            state_history.append({
                'effective_from': exec_day,
                'slots': [dict(s) if s else None for s in slots],
                'cash':  list(cash_per_slot),
            })

            # 5h. History row
            if opened_syms and closed_syms:
                agg_action = 'ROTATE'
            elif opened_syms:
                agg_action = 'BUY'
            elif closed_syms:
                agg_action = 'CLOSE'
            else:
                agg_action = 'HOLD'

            equity_now = self._mark_total(
                slots, cash_per_slot, universe, date_idx_map, exec_day)
            history.append(self._row(
                decision_day, agg_action, self._held_str(slots), equity_now,
                score=ranking[0]['score'],
                prev_symbol=', '.join(closed_syms) or None,
                new_score=score_by_symbol.get(opened_syms[0]) if opened_syms else None,
                exec_day=exec_day,
                regime=('bull' if bull else 'bear')))

        # 6. Curva diaria
        equity_curve = self._build_daily_curve(
            state_history, universe, date_idx_map,
            spy_dates_in_range, spy_close_by_date)

        # 7. Métricas
        metrics = _compute_metrics(equity_curve, rotations, start, end)
        final_eq    = equity_curve[-1]['strat'] if equity_curve else self.initial_capital
        final_spy   = equity_curve[-1]['spy']   if equity_curve else self.initial_capital
        outperf_pct = (final_eq / final_spy - 1.0) * 100 if final_spy else 0.0

        return {
            'config': {
                'initial_capital': self.initial_capital,
                'fee_rate':        self.fee_rate,
                'top_keep':        self.top_keep,
                'rotate_diff':     self.rotate_diff,
                'max_universe':    self.max_universe,
                'mode':            self.mode,
                'regime_filter':   self.regime_filter,
                'min_price':       self.min_price,
                'min_avg_vol':     self.min_avg_vol,
            },
            'period': {'start': str(start), 'end': str(end)},
            'history':      history,
            'equity_curve': equity_curve,
            'metrics':      metrics,
            'summary': {
                'final_equity':       round(final_eq, 2),
                'final_spy_equity':   round(final_spy, 2),
                'outperformance_pct': round(outperf_pct, 2),
                'evaluated_universe': len(universe),
                'decision_days':      len(decision_days),
            },
        }

    # ─── Internals ───────────────────────────────────────────────────────────

    def _rank_universe(self,
                       universe: dict[str, list[dict]],
                       date_idx_map: dict[str, dict[date, int]],
                       decision_day: date,
                       spy_ret_20d: float | None) -> list[dict]:
        scored: list[dict] = []
        for sym, candles in universe.items():
            idx = date_idx_map[sym].get(decision_day)
            if idx is None:
                # Buscar último idx ≤ decision_day (gap por holiday del símbolo)
                last_idx = -1
                for i, c in enumerate(candles):
                    if c['fecha'] <= decision_day:
                        last_idx = i
                    else:
                        break
                if last_idx < 0:
                    continue
                idx = last_idx
            res = score_symbol_at(candles, idx, spy_ret_20d)
            if res is not None:
                scored.append(res)
        scored.sort(key=lambda r: r['score'], reverse=True)
        return scored

    def _sell_slot(self, slot: dict, exec_day: date,
                   universe: dict[str, list[dict]],
                   date_idx_map: dict[str, dict[date, int]],
                   sorted_dates_map: dict[str, list[date]]) -> float | None:
        sym = slot['symbol']
        lookup = _open_at(
            universe[sym], date_idx_map[sym], exec_day, sorted_dates_map[sym])
        if lookup is None:
            return None
        sell_price, _ = lookup
        if not slot.get('buy_price'):
            return None
        proceeds = slot['equity_at_buy'] * (sell_price / slot['buy_price'])
        proceeds *= (1 - self.fee_rate)
        return proceeds

    def _buy_slot(self, sym: str, cash: float, exec_day: date,
                  universe: dict[str, list[dict]],
                  date_idx_map: dict[str, dict[date, int]],
                  sorted_dates_map: dict[str, list[date]]) -> dict | None:
        if sym not in universe or cash <= 0:
            return None
        lookup = _open_at(
            universe[sym], date_idx_map[sym], exec_day, sorted_dates_map[sym])
        if lookup is None:
            return None
        buy_price, buy_actual = lookup
        if buy_price <= 0:
            return None
        equity_at_buy = cash * (1 - self.fee_rate)
        return {
            'symbol':        sym,
            'buy_price':     buy_price,
            'buy_day':       buy_actual,
            'equity_at_buy': equity_at_buy,
        }

    def _mark_total(self, slots: list[dict | None], cash_per_slot: list[float],
                    universe: dict[str, list[dict]],
                    date_idx_map: dict[str, dict[date, int]],
                    d: date) -> float:
        total = 0.0
        for i, slot in enumerate(slots):
            if slot is None:
                total += cash_per_slot[i]
                continue
            sym = slot['symbol']
            close = _close_at(universe[sym], date_idx_map[sym], d)
            if close and slot.get('buy_price'):
                total += slot['equity_at_buy'] * (close / slot['buy_price'])
            else:
                total += slot['equity_at_buy']
        return total

    def _build_daily_curve(self,
                           state_history: list[dict],
                           universe: dict[str, list[dict]],
                           date_idx_map: dict[str, dict[date, int]],
                           spy_dates_in_range: list[date],
                           spy_close_by_date: dict[date, float]) -> list[dict]:
        if not spy_dates_in_range or not state_history:
            return []
        spy_first = next(
            (spy_close_by_date[d] for d in spy_dates_in_range
             if d in spy_close_by_date), None)
        if not spy_first:
            return []

        # Iterar snapshots cronológicamente
        snaps = sorted(state_history, key=lambda s: s['effective_from'])
        snap_idx = 0
        current  = snaps[0]
        next_snap = snaps[1] if len(snaps) > 1 else None

        curve: list[dict] = []
        last_eq = self.initial_capital
        for d in spy_dates_in_range:
            spy_close = spy_close_by_date.get(d)
            if spy_close is None:
                continue
            spy_eq = self.initial_capital * (spy_close / spy_first)

            while next_snap and next_snap['effective_from'] <= d:
                snap_idx += 1
                current  = next_snap
                next_snap = snaps[snap_idx + 1] if snap_idx + 1 < len(snaps) else None

            eq = self._mark_total(
                current['slots'], current['cash'], universe, date_idx_map, d)
            if eq <= 0:
                eq = last_eq
            else:
                last_eq = eq

            curve.append({
                'fecha': str(d),
                'strat': round(eq, 2),
                'spy':   round(spy_eq, 2),
            })
        return curve

    def _held_str(self, slots: list[dict | None]) -> str:
        syms = [s['symbol'] for s in slots if s]
        return ', '.join(syms) if syms else '—'

    def _row(self, week_end: date, action: str, symbol: str | None, equity: float,
             *, score: float | None = None, reason: str | None = None,
             prev_symbol: str | None = None, new_score: float | None = None,
             exec_day: date | None = None, exec_price: float | None = None,
             regime: str | None = None) -> dict:
        row = {
            'week_end': str(week_end),
            'action':   action,
            'symbol':   symbol,
            'equity':   round(equity, 2),
        }
        if score       is not None: row['score']        = round(score, 1)
        if reason:                   row['reason']       = reason
        if prev_symbol:              row['prev_symbol']  = prev_symbol
        if new_score   is not None: row['new_score']    = round(new_score, 1)
        if exec_day:                 row['exec_day']     = str(exec_day)
        if exec_price  is not None: row['exec_price']   = round(exec_price, 4)
        if regime:                   row['regime']       = regime
        return row

    def _empty_result(self, start: date, end: date, reason: str) -> dict:
        return {
            'config': {
                'initial_capital': self.initial_capital,
                'fee_rate':        self.fee_rate,
                'top_keep':        self.top_keep,
                'rotate_diff':     self.rotate_diff,
                'max_universe':    self.max_universe,
                'mode':            self.mode,
                'regime_filter':   self.regime_filter,
                'min_price':       self.min_price,
                'min_avg_vol':     self.min_avg_vol,
            },
            'period':       {'start': str(start), 'end': str(end)},
            'history':      [],
            'equity_curve': [],
            'metrics':      _compute_metrics([], 0, start, end),
            'summary':      {
                'final_equity':       self.initial_capital,
                'final_spy_equity':   self.initial_capital,
                'outperformance_pct': 0,
                'evaluated_universe': 0,
                'decision_days':      0,
                'error':              reason,
            },
        }


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def main() -> int:
    p = argparse.ArgumentParser(description='Rotation backtest vs SPY (V2)')
    p.add_argument('start', nargs='?', type=_parse_date, default=None)
    p.add_argument('end',   nargs='?', type=_parse_date, default=None)
    p.add_argument('--capital',       type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument('--fee',           type=float, default=DEFAULT_FEE_RATE)
    p.add_argument('--max-universe',  type=int,   default=DEFAULT_MAX_UNIVERSE)
    p.add_argument('--top-keep',      type=int,   default=DEFAULT_TOP_KEEP)
    p.add_argument('--rotate-diff',   type=float, default=DEFAULT_ROTATE_DIFF)
    p.add_argument('--mode',          choices=VALID_MODES, default=DEFAULT_MODE)
    p.add_argument('--no-regime',     action='store_true',
                   help='Desactivar el filtro de régimen')
    p.add_argument('--min-price',     type=float, default=DEFAULT_MIN_PRICE)
    p.add_argument('--min-avg-vol',   type=float, default=DEFAULT_MIN_AVG_VOL)
    p.add_argument('--json', action='store_true', help='Dump JSON a stdout')
    args = p.parse_args()

    bt = RotationBacktest(
        initial_capital=args.capital,
        fee_rate=args.fee,
        top_keep=args.top_keep,
        rotate_diff=args.rotate_diff,
        max_universe=args.max_universe,
        mode=args.mode,
        regime_filter=not args.no_regime,
        min_price=args.min_price,
        min_avg_vol=args.min_avg_vol,
    )
    result = bt.run(args.start, args.end)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    s = result['summary']
    m = result['metrics']
    c = result['config']
    print(f">>> Backtest rotation V2 {result['period']['start']} -> {result['period']['end']}")
    print(f"    mode={c['mode']}  regime_filter={c['regime_filter']}  "
          f"top_keep={c['top_keep']}  rotate_diff={c['rotate_diff']}")
    print(f"    universe={s['evaluated_universe']}  decision_days={s['decision_days']}")
    print(f"    rotaciones: {m['rotations_count']}")
    print(f"    equity final estrategia: ${s['final_equity']:,}")
    print(f"    equity final SPY:        ${s['final_spy_equity']:,}")
    print(f"    outperformance:          {s['outperformance_pct']:+.2f}%")
    print(f"    total return: {m['total_return']*100:+.2f}%  CAGR: {m['cagr']*100:+.2f}%  "
          f"max DD: {m['max_drawdown']*100:.2f}%  Sharpe: {m['sharpe']:.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
