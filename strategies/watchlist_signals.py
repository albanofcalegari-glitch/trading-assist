"""
watchlist_signals.py — Detector de señales BUY/SELL para activos de la watchlist.

Agrega todas las fuentes de señal existentes y emite eventos discretos
(uno por cada señal que dispara hoy) para un ticker dado.

Cada señal es un dict con:
  direction:  'BUY' | 'SELL'
  code:       identificador corto (ej. 'UT_BOT', 'NEAR_DYN_SUPPORT')
  title:      string humano para usar en notification.title
  body:       string humano para usar en notification.body
  data:       dict con payload detallado (para notification.data_json)

Se usan try/except locales para que una fuente que falle no rompa al resto.
"""
from __future__ import annotations

from datetime import date
from typing   import Optional

from strategies import dynamic_supports    as _ds
from strategies import dynamic_resistances as _dr
from strategies import longterm_support    as _lts
from strategies import historical_lows     as _hl
from strategies import historical_highs    as _hh
from strategies import ut_bot              as _utb
from strategies import trend_pullback      as _tp

from db.connection import get_conn as _get_conn


# Umbrales
NEAR_SUPPORT_MAX_PCT    = 3.0   # % máximo sobre el soporte para alertar
NEAR_RESISTANCE_MAX_PCT = 3.0   # % máximo bajo la resistencia para alertar
BREAKOUT_MAX_DIST_PCT   = 5.0   # % máximo arriba de la resistencia para considerar breakout fresco
BREAKOUT_SL_PCT         = 5.0   # Stop Loss: -5% desde la resistencia
BREAKOUT_TP_RATIO       = 2.0   # Risk:Reward 1:2 → TP = +10%


def _fmt_price(v: Optional[float]) -> str:
    if v is None:
        return '—'
    return f'${v:,.2f}'


# ── Sugerencias de acción (veredicto humano por tipo de señal) ────────────────
#
# Cada detector agrega al final del `body` una línea con la acción sugerida,
# y también la emite en `data.action` por si el frontend quiere destacarla.
# Son heurísticas genéricas — no reemplazan análisis del usuario.

def _action_hint(code: str, **ctx) -> str:
    if code == 'NEAR_DYN_SUPPORT':
        sup = _fmt_price(ctx.get('support'))
        tier = ctx.get('tier') or 'dinámico'
        return (f'🎯 Compra en rebote del soporte {tier}. Esperá confirmación '
                f'(vela alcista + volumen) antes de entrar. Stop debajo de {sup}: '
                f'si rompe el soporte, abortar.')
    if code == 'NEAR_LT_SUPPORT':
        sup = _fmt_price(ctx.get('support'))
        return (f'🎯 Compra en rebote del soporte estructural. Stop debajo de {sup}. '
                f'Mejor riesgo/recompensa que los dinámicos, pero la espera es más lenta.')
    if code == 'NEAR_LT_RESISTANCE':
        res = _fmt_price(ctx.get('resistance'))
        return (f'⚠️ Zona de venta / toma de ganancias. Esperá rechazo claro de {res}. '
                f'Si la rompe al alza con volumen, evaluar largo con stop debajo.')
    if code == 'UT_BOT':
        if ctx.get('direction') == 'BUY':
            return ('🎯 Gatillo de compra: el trailing stop viró alcista. Entrada directa, '
                    'stop bajo el último mínimo o sobre el nivel UP del indicador.')
        return ('⚠️ Gatillo de venta: el trailing stop viró bajista. Cerrar largos '
                'o tomar ganancias parciales.')
    if code == '52W_LOW':
        state = ctx.get('setup_state')
        if state == 'NEW_52W_LOW':
            return ('⚠️ Nuevo mínimo — NO comprar por "barato". Esperá reversión '
                    'confirmada (doble piso, divergencia, vela de giro) antes de entrar.')
        if state == 'AT_52W_LOW':
            return ('🎯 En zona de potencial rebote. Buscar vela de giro con volumen; '
                    'stop debajo del mínimo. Confirmar antes de entrar.')
        return ('👀 Cerca del mínimo 52w — vigilar, sin entrar todavía. '
                'Si toca el piso con señal de reversión, setup completo.')
    if code == '52W_HIGH':
        state = ctx.get('setup_state')
        if state == 'NEW_52W_HIGH':
            return ('⚠️ Nuevo máximo — tomar ganancias parciales o activar trailing stop. '
                    'Evitar compras acá: momentum late pero riesgo/recompensa malo.')
        if state == 'AT_52W_HIGH':
            return ('⚠️ En techo 52w: zona de resistencia dura. Tomar ganancias, '
                    'o esperar breakout confirmado con volumen antes de sumar.')
        return ('👀 Cerca del máximo 52w — alerta de toma de ganancias. '
                'Evitar compras nuevas hasta ver ruptura clara o rechazo.')
    if code == 'TREND_PULLBACK':
        return ('🎯 Setup de compra: tendencia sana + pullback estabilizado. '
                'Entrada directa con stop bajo el mínimo del pullback.')
    if code == 'RESISTANCE_BREAKOUT':
        sl = _fmt_price(ctx.get('sl'))
        tp = _fmt_price(ctx.get('tp'))
        res = _fmt_price(ctx.get('resistance'))
        strength = ctx.get('strength', 1)
        if strength >= 2:
            return (f'🚀 Breakout CONFIRMADO (2 velas). Entrada con SL en {sl} (-5%) '
                    f'y TP en {tp} (+10%, R:R 1:2). La resistencia en {res} ahora '
                    f'pasa a ser soporte — si vuelve abajo, abortar.')
        return (f'📈 Breakout (1 vela, pendiente confirmación). Entrada con SL en {sl} '
                f'(-5%) y TP en {tp} (+10%, R:R 1:2). Si mañana cierra arriba de '
                f'{res} de nuevo, la señal se fortalece.')
    return ''


def _with_action(body: str, hint: str) -> str:
    return f'{body}\n\n{hint}' if hint else body


# ── Detectores individuales ───────────────────────────────────────────────────

def _detect_ut_bot(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _utb.get_ut_bot(symbol, fecha)
    except Exception:
        return out
    today_str = str(fecha)
    for sig in r.get('signals') or []:
        if str(sig.get('fecha')) != today_str:
            continue
        kind = sig.get('kind')
        if kind not in ('BUY', 'SELL'):
            continue
        price = sig.get('price')
        hint = _action_hint('UT_BOT', direction=kind)
        body = (f'El trailing stop invirtió a {"alcista" if kind == "BUY" else "bajista"} '
                f'en la sesión de hoy ({today_str}).')
        out.append({
            'direction': kind,
            'code':      'UT_BOT',
            'title':     f'{symbol} · UT Bot {kind} @ {_fmt_price(price)}',
            'body':      _with_action(body, hint),
            'data':      {'price': price, 'fecha': today_str, 'action': hint},
        })
    return out


def _detect_dyn_support(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _ds.get_dynamic_supports(symbol, fecha)
    except Exception:
        return out
    price = r.get('price')
    if price is None:
        return out
    # Preferencia: short > mid > long
    for tier_name in ('short', 'mid', 'long'):
        tier = r.get(tier_name)
        if not tier:
            continue
        if tier.get('status') not in ('ACTIVE', 'TESTING'):
            continue
        cur = tier.get('current_value')
        if cur is None or cur <= 0:
            continue
        dist_pct = (price / cur - 1) * 100.0
        if 0 <= dist_pct <= NEAR_SUPPORT_MAX_PCT:
            hint = _action_hint('NEAR_DYN_SUPPORT', support=cur, tier=tier_name)
            body = (f'Precio {_fmt_price(price)} está a {dist_pct:.2f}% sobre el soporte '
                    f'dinámico {tier_name} ({_fmt_price(cur)}, status {tier.get("status")}).')
            out.append({
                'direction': 'BUY',
                'code':      'NEAR_DYN_SUPPORT',
                'title':     f'{symbol} · pegado a soporte dinámico ({tier_name}) a {dist_pct:.2f}%',
                'body':      _with_action(body, hint),
                'data':      {
                    'tier':         tier_name,
                    'price':        price,
                    'support':      cur,
                    'distance_pct': round(dist_pct, 3),
                    'status':       tier.get('status'),
                    'action':       hint,
                },
            })
            break  # sólo el tier más fino alcanza
    return out


def _detect_lt_support(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _lts.get_longterm_support(symbol, fecha)
    except Exception:
        return out
    if not r:
        return out
    cur    = r.get('active_current_value') or r.get('current_value')
    status = r.get('active_status')       or r.get('status')
    price  = None
    # longterm_support no devuelve "price" directo — lo derivamos de distance_pct si está
    dist   = r.get('active_distance_pct')
    if dist is None:
        dist = r.get('distance_pct')
    if cur and dist is not None:
        # distance_pct = (price / cur - 1) * 100
        price = cur * (1 + dist / 100.0)
    if cur is None or price is None or status not in ('ACTIVE', 'TESTING'):
        return out
    dist_pct = (price / cur - 1) * 100.0
    if 0 <= dist_pct <= NEAR_SUPPORT_MAX_PCT:
        hint = _action_hint('NEAR_LT_SUPPORT', support=cur)
        body = (f'Precio {_fmt_price(price)} está a {dist_pct:.2f}% sobre el soporte '
                f'estructural activo ({_fmt_price(cur)}, status {status}).')
        out.append({
            'direction': 'BUY',
            'code':      'NEAR_LT_SUPPORT',
            'title':     f'{symbol} · pegado a soporte largo plazo a {dist_pct:.2f}%',
            'body':      _with_action(body, hint),
            'data': {
                'price':        price,
                'support':      cur,
                'distance_pct': round(dist_pct, 3),
                'status':       status,
                'action':       hint,
            },
        })
    return out


def _detect_lt_resistance(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _lts.get_longterm_support(symbol, fecha)
    except Exception:
        return out
    if not r:
        return out
    cur    = r.get('active_resistance_current_value') or r.get('resistance_current_value')
    status = r.get('active_resistance_status')        or r.get('resistance_status')
    dist   = r.get('active_resistance_distance_pct')
    if dist is None:
        dist = r.get('resistance_distance_pct')
    price = None
    if cur and dist is not None:
        # distance_pct para resistencia: (price / cur - 1) * 100 (negativo si debajo)
        price = cur * (1 + dist / 100.0)
    if cur is None or price is None or status not in ('ACTIVE', 'TESTING'):
        return out
    dist_pct = (1 - price / cur) * 100.0   # positivo cuando precio < resistencia
    if 0 <= dist_pct <= NEAR_RESISTANCE_MAX_PCT:
        hint = _action_hint('NEAR_LT_RESISTANCE', resistance=cur)
        body = (f'Precio {_fmt_price(price)} está a {dist_pct:.2f}% bajo la resistencia '
                f'estructural activa ({_fmt_price(cur)}, status {status}).')
        out.append({
            'direction': 'SELL',
            'code':      'NEAR_LT_RESISTANCE',
            'title':     f'{symbol} · pegado a resistencia a {dist_pct:.2f}%',
            'body':      _with_action(body, hint),
            'data': {
                'price':        price,
                'resistance':   cur,
                'distance_pct': round(dist_pct, 3),
                'status':       status,
                'action':       hint,
            },
        })
    return out


def _detect_52w_low(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _hl.analyze_symbol(symbol, fecha)
    except Exception:
        return out
    if not r:
        return out
    state = r.get('setup_state')
    if state not in ('NEW_52W_LOW', 'AT_52W_LOW', 'NEAR_52W_LOW'):
        return out
    state_readable = {
        'NEW_52W_LOW':  'nuevo mínimo 52w',
        'AT_52W_LOW':   'tocando mínimo 52w',
        'NEAR_52W_LOW': 'cerca de mínimo 52w',
    }[state]
    is_atl = bool(r.get('is_all_time_low'))
    if is_atl:
        state_readable += ' (ATL)'
    hint = _action_hint('52W_LOW', setup_state=state)
    base_body = r.get('reading') or f'Precio en zona de mínimo 52w ({_fmt_price(r.get("price"))}).'
    out.append({
        'direction': 'BUY',
        'code':      '52W_LOW',
        'title':     f'{symbol} · {state_readable}',
        'body':      _with_action(base_body, hint),
        'data': {
            'setup_state':     state,
            'price':           r.get('price'),
            'low_52w':         r.get('low_52w'),
            'distance_52w_pct': r.get('distance_52w_pct'),
            'is_all_time_low': is_atl,
            'confidence':      r.get('confidence_level'),
            'action':          hint,
        },
    })
    return out


def _detect_52w_high(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _hh.analyze_symbol(symbol, fecha)
    except Exception:
        return out
    if not r:
        return out
    state = r.get('setup_state')
    if state not in ('NEW_52W_HIGH', 'AT_52W_HIGH', 'NEAR_52W_HIGH'):
        return out
    state_readable = {
        'NEW_52W_HIGH':  'nuevo máximo 52w',
        'AT_52W_HIGH':   'tocando máximo 52w',
        'NEAR_52W_HIGH': 'cerca de máximo 52w',
    }[state]
    is_ath = bool(r.get('is_all_time_high'))
    if is_ath:
        state_readable += ' (ATH)'
    hint = _action_hint('52W_HIGH', setup_state=state)
    base_body = r.get('reading') or f'Precio en zona de máximo 52w ({_fmt_price(r.get("price"))}).'
    out.append({
        'direction': 'SELL',
        'code':      '52W_HIGH',
        'title':     f'{symbol} · {state_readable}',
        'body':      _with_action(base_body, hint),
        'data': {
            'setup_state':      state,
            'price':            r.get('price'),
            'high_52w':         r.get('high_52w'),
            'distance_52w_pct': r.get('distance_52w_pct'),
            'is_all_time_high': is_ath,
            'confidence':       r.get('confidence_level'),
            'action':           hint,
        },
    })
    return out


def _detect_trend_pullback(symbol: str, fecha: date) -> list[dict]:
    out: list[dict] = []
    try:
        r = _tp.analyze_symbol(symbol, fecha)
    except Exception:
        return out
    if not r:
        return out
    if r.get('decision') != 'BUY_CANDIDATE':
        return out
    hint = _action_hint('TREND_PULLBACK')
    base_body = r.get('reading') or 'Trend healthy con pullback estabilizado, zona de entrada.'
    out.append({
        'direction': 'BUY',
        'code':      'TREND_PULLBACK',
        'title':     f'{symbol} · trend + pullback válido',
        'body':      _with_action(base_body, hint),
        'data': {
            'trend_score':       r.get('trend_score'),
            'pullback_score':    r.get('pullback_score'),
            'setup_state':       r.get('setup_state'),
            'context_alignment': r.get('context_alignment'),
            'confidence':        r.get('confidence_level'),
            'price':             r.get('price'),
            'action':            hint,
        },
    })
    return out


def _detect_resistance_breakout(symbol: str, fecha: date) -> list[dict]:
    """Detecta ruptura al alza de resistencia dinámica (breakout → BUY)."""
    out: list[dict] = []
    try:
        r = _dr.get_dynamic_resistances(symbol, fecha)
    except Exception:
        return out
    price = r.get('price')
    tf    = r.get('timeframe_used')
    if price is None or tf is None:
        return out

    prev_closes: list[float] = []
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT close FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = %s AND fecha <= %s
                   ORDER BY fecha DESC LIMIT 3""",
                (symbol, tf, fecha),
            )
            prev_closes = [float(row['close']) for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass

    for tier_name in ('short', 'mid', 'long'):
        tier = r.get(tier_name)
        if not tier or not isinstance(tier, dict):
            continue

        cur_val  = tier.get('current_value')
        dist_pct = tier.get('distance_pct', 0)
        if cur_val is None or cur_val <= 0:
            continue

        if tier.get('kind') == 'horizontal':
            res_level = tier.get('zone_ceiling', cur_val)
        else:
            res_level = cur_val

        if dist_pct <= 0 or dist_pct > BREAKOUT_MAX_DIST_PCT:
            continue

        lps = tier.get('line_points', [])
        prev_res = lps[-2]['value'] if len(lps) >= 2 else res_level
        prev2_res = lps[-3]['value'] if len(lps) >= 3 else prev_res

        if len(prev_closes) >= 2:
            yesterday_close = prev_closes[1]
            if yesterday_close > prev_res * 1.005:
                if len(prev_closes) >= 3:
                    day_before = prev_closes[2]
                    if day_before > prev2_res * 1.005:
                        continue
                    strength = 2
                else:
                    strength = 2
            else:
                strength = 1
        else:
            strength = 1

        sl = round(res_level * (1 - BREAKOUT_SL_PCT / 100), 2)
        tp = round(res_level * (1 + BREAKOUT_SL_PCT * BREAKOUT_TP_RATIO / 100), 2)

        hint = _action_hint('RESISTANCE_BREAKOUT',
                            sl=sl, tp=tp, resistance=res_level, strength=strength)
        strength_label = '2 velas confirmando' if strength >= 2 else '1 vela (pendiente confirmación)'
        body = (f'El precio {_fmt_price(price)} rompió al alza la resistencia dinámica '
                f'{tier_name} en {_fmt_price(res_level)} (distancia +{dist_pct:.2f}%). '
                f'Fuerza: {strength_label}.')
        out.append({
            'direction': 'BUY',
            'code':      'RESISTANCE_BREAKOUT',
            'title':     f'{symbol} · ruptura resistencia {tier_name} +{dist_pct:.1f}%',
            'body':      _with_action(body, hint),
            'data': {
                'tier':           tier_name,
                'price':          price,
                'resistance':     res_level,
                'distance_pct':   round(dist_pct, 3),
                'sl':             sl,
                'tp':             tp,
                'strength':       strength,
                'strength_label': strength_label,
                'action':         hint,
            },
        })
        break  # solo el tier más relevante
    return out


# ── Detector agregado ─────────────────────────────────────────────────────────

_DETECTORS = [
    _detect_ut_bot,
    _detect_dyn_support,
    _detect_lt_support,
    _detect_lt_resistance,
    _detect_52w_low,
    _detect_52w_high,
    _detect_trend_pullback,
    _detect_resistance_breakout,
]


def _combine_contradictions(symbol: str, signals: list[dict]) -> list[dict]:
    """Si el mismo día conviven pares aparentemente contradictorios, los fusiona
    en una única señal con veredicto claro y coloquial.

    Casos que reconoce:
      - Soporte (dyn o lt) + 52W_HIGH  → PULLBACK_IN_UPTREND  (BUY, bueno)
      - Resistencia LT    + 52W_LOW   → REBOUND_IN_DOWNTREND (SELL, malo para entrar)
    Cuando hay match, quita las individuales y deja sólo la combinada para no
    confundir al usuario con dos notificaciones que parecen opuestas.
    """
    by_code = {s['code']: s for s in signals}

    sup = by_code.get('NEAR_DYN_SUPPORT') or by_code.get('NEAR_LT_SUPPORT')
    hi  = by_code.get('52W_HIGH')
    if sup and hi:
        sup_price = (sup.get('data') or {}).get('support')
        hi_state  = (hi.get('data')  or {}).get('setup_state')
        tier      = (sup.get('data') or {}).get('tier') or 'estructural'
        hi_dist   = (hi.get('data')  or {}).get('distance_52w_pct')

        dist_str = f'{abs(hi_dist):.1f}%' if hi_dist is not None else '—'
        title = f'{symbol} · pullback en tendencia alcista 💪'
        body_ctx = (
            f'Está a {dist_str} de su máximo 52w pero hoy corrigió hasta tocar '
            f'el soporte {tier} en {_fmt_price(sup_price)}. Clásico pullback '
            f'dentro de tendencia alcista — no es para vender.'
        )
        verdict = (
            '🎯 Veredicto: NO VENDAS. Si ya la tenés, aguantala con stop '
            f'debajo de {_fmt_price(sup_price)}. Si querés sumar, esperá '
            'mañana una vela verde con volumen sobre el soporte — sin esa '
            'confirmación, no metas un peso más. Si el soporte se rompe '
            'con fuerza, el setup se canceló y achicás posición.'
        )
        combined = {
            'direction': 'BUY',
            'code':      'PULLBACK_IN_UPTREND',
            'title':     title,
            'body':      f'{body_ctx}\n\n{verdict}',
            'data': {
                'support':        sup_price,
                'support_tier':   tier,
                'high_52w_state': hi_state,
                'distance_52w_pct': hi_dist,
                'action':         verdict,
                'merged_from':    [sup['code'], hi['code']],
            },
        }
        signals = [s for s in signals
                   if s['code'] not in ('NEAR_DYN_SUPPORT', 'NEAR_LT_SUPPORT', '52W_HIGH')]
        signals.insert(0, combined)
        return signals

    res = by_code.get('NEAR_LT_RESISTANCE')
    lo  = by_code.get('52W_LOW')
    if res and lo:
        res_price = (res.get('data') or {}).get('resistance')
        lo_state  = (lo.get('data')  or {}).get('setup_state')
        lo_dist   = (lo.get('data')  or {}).get('distance_52w_pct')

        dist_str = f'{abs(lo_dist):.1f}%' if lo_dist is not None else '—'
        title = f'{symbol} · rebote débil en tendencia bajista 📉'
        body_ctx = (
            f'Está a {dist_str} de su mínimo 52w pero hoy subió hasta la '
            f'resistencia en {_fmt_price(res_price)}. Huele a rebote técnico '
            f'dentro de una tendencia bajista — no a piso real.'
        )
        verdict = (
            '⚠️ Veredicto: NO COMPRES. Si ya estás adentro, aprovechá este '
            f'rebote para achicar o tomar ganancias parciales acá. Si no la '
            f'tenés, no entres por FOMO — esperá una estructura de piso '
            '(doble piso, divergencia, vela de giro con volumen) antes de '
            'siquiera evaluarla.'
        )
        combined = {
            'direction': 'SELL',
            'code':      'REBOUND_IN_DOWNTREND',
            'title':     title,
            'body':      f'{body_ctx}\n\n{verdict}',
            'data': {
                'resistance':     res_price,
                'low_52w_state':  lo_state,
                'distance_52w_pct': lo_dist,
                'action':         verdict,
                'merged_from':    [res['code'], lo['code']],
            },
        }
        signals = [s for s in signals
                   if s['code'] not in ('NEAR_LT_RESISTANCE', '52W_LOW')]
        signals.insert(0, combined)
        return signals

    return signals


def detect_signals(symbol: str, fecha: Optional[date] = None) -> list[dict]:
    """
    Corre todos los detectores para un símbolo y devuelve la lista combinada
    de señales que disparan. Cada señal viene con direction/code/title/body/data.
    Pares contradictorios se fusionan en una señal unificada vía `_combine_contradictions`.
    """
    fecha = fecha or date.today()
    out: list[dict] = []
    for fn in _DETECTORS:
        try:
            out.extend(fn(symbol, fecha))
        except Exception:
            continue
    return _combine_contradictions(symbol, out)
