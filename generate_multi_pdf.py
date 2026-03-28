"""
generate_multi_pdf.py  — BABA · GOOGL · MELI
3 paginas en PDF, una por activo, mismo estilo que NU_canal.pdf.
Velas japonesas + volumen + canal dinamico (inf, sup, media, relleno) + log.
"""

import math
import numpy as np
import pandas as pd
import pymysql, pymysql.cursors
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
import mplfinance as mpf

# ── Configuracion ─────────────────────────────────────────────────────────────

MYSQL_CONFIG = dict(
    host='localhost', user='root', password='123456',
    db='bolsa', charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)

ASSETS = [
    {'id': 972,  'simbolo': 'BABA',  'nombre': 'Alibaba Group Holdings'},
    {'id': 4747, 'simbolo': 'GOOGL', 'nombre': 'Alphabet Inc. (Google)'},
    {'id': 6939, 'simbolo': 'MELI',  'nombre': 'MercadoLibre Inc.'},
]

DAYS_BACK   = 1800
FUTURE_DAYS = 130
OUTPUT_PDF  = r'C:\Users\DELL\Desktop\BABA_GOOGL_MELI_canal.pdf'

# Colores TradingView dark
TV_BG       = '#131722'
TV_GRID     = '#1e222d'
TV_BORDER   = '#2a2e39'
TV_TEXT     = '#b2b5be'
TV_UP       = '#26a69a'
TV_DOWN     = '#ef5350'
CH_LINE     = '#00897b'
CH_MID      = '#26a69a'
CH_FILL     = '#00897b'
CH_ALPHA    = 0.10
CH_LW       = 2.4

STYLE = mpf.make_mpf_style(
    base_mpf_style='nightclouds',
    rc={
        'axes.facecolor':   TV_BG,
        'figure.facecolor': TV_BG,
        'axes.edgecolor':   TV_BORDER,
        'axes.labelcolor':  TV_TEXT,
        'xtick.color':      TV_TEXT,
        'ytick.color':      TV_TEXT,
        'xtick.labelsize':  9,
        'ytick.labelsize':  9,
        'grid.color':       TV_GRID,
        'grid.linestyle':   '-',
        'grid.alpha':       1.0,
        'font.family':      'DejaVu Sans',
        'font.size':        9,
    },
    marketcolors=mpf.make_marketcolors(
        up=TV_UP, down=TV_DOWN,
        edge='inherit', wick='inherit',
        volume={'up': TV_UP + '55', 'down': TV_DOWN + '55'},
    ),
)

# ── Base de datos ─────────────────────────────────────────────────────────────

def fetch_ohlcv(accion_id: int) -> pd.DataFrame:
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha,
                       precio_apertura                      AS open,
                       COALESCE(precio_max, precio_cierre)  AS high,
                       COALESCE(precio_min, precio_cierre)  AS low,
                       precio_cierre                        AS close,
                       COALESCE(volumen, 0)                 AS volume
                FROM valorhistoricoaccion
                WHERE accion_id = %s
                  AND fecha >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY fecha
            """, [accion_id, DAYS_BACK])
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df['fecha'] = pd.to_datetime(df['fecha'])
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['close', 'high', 'low', 'open'])
    return df.set_index('fecha').sort_index()


def add_future_bars(df: pd.DataFrame, n_days: int) -> pd.DataFrame:
    last = df.index[-1]
    future = []
    d = last
    while len(future) < n_days:
        d += pd.Timedelta(days=1)
        if d.weekday() < 5:
            future.append(d)
    fut = pd.DataFrame(
        index=pd.DatetimeIndex(future),
        data={'open': np.nan, 'high': np.nan, 'low': np.nan,
              'close': np.nan, 'volume': 0.0}
    )
    return pd.concat([df, fut])


# ── Algoritmo trendline ───────────────────────────────────────────────────────

def find_trendline(df_orig: pd.DataFrame, kind: str):
    n     = len(df_orig)
    lows  = df_orig['low'].values.astype(float)
    highs = df_orig['high'].values.astype(float)
    vals  = lows if kind == 'support' else highs
    if n < 10: return None

    win = max(2, min(5, n // 100))

    raw = []
    for i in range(win, n - win):
        v = vals[i]
        if v <= 0 or math.isnan(v): continue
        if kind == 'support':
            ok = all(vals[j] >= v for j in range(i-win, i)) and \
                 all(vals[j] >= v for j in range(i+1, i+win+1))
        else:
            ok = all(vals[j] <= v for j in range(i-win, i)) and \
                 all(vals[j] <= v for j in range(i+1, i+win+1))
        if ok:
            raw.append((i, df_orig.index[i], v, math.log(v)))
    if len(raw) < 2: return None

    sig = []
    for (i, d, v, lv) in raw:
        ref = highs if kind == 'support' else lows
        slc = ref[i+1:min(i+16, n)]
        slc = slc[slc > 0]
        if kind == 'support':
            if len(slc) and slc.max() >= v * 1.02: sig.append((i, d, v, lv))
        else:
            if len(slc) and slc.min() <= v * 0.98: sig.append((i, d, v, lv))
    if len(sig) < 2: return None

    min_sep = max(5, n // 50)
    pivots  = []
    for p in sig:
        if pivots and p[0] - pivots[-1][0] < min_sep:
            if (kind == 'support' and p[2] < pivots[-1][2]) or \
               (kind == 'resistance' and p[2] > pivots[-1][2]):
                pivots[-1] = p
        else:
            pivots.append(p)
    if len(pivots) < 2: return None

    best_score, best_pair = -math.inf, None
    MIN_SEP = max(win * 3, 5)

    for a in range(len(pivots) - 1):
        for b in range(a + 1, len(pivots)):
            p1, p2 = pivots[a], pivots[b]
            if p2[0] - p1[0] < MIN_SEP: continue
            ls = (p2[3] - p1[3]) / (p2[0] - p1[0])
            li = p1[3] - ls * p1[0]
            touches, violations, passed_p2 = 2, 0, False
            for k in range(p1[0], n):
                if k == p1[0]: continue
                if k == p2[0]: passed_p2 = True; continue
                line_v = math.exp(ls * k + li)
                if kind == 'support':
                    pv = lows[k]
                    if pv <= 0: continue
                    if pv < line_v * 0.992:
                        if not passed_p2: violations += 1
                    elif abs(pv - line_v) / line_v <= 0.012: touches += 1
                else:
                    pv = highs[k]
                    if pv <= 0: continue
                    if pv > line_v * 1.008:
                        if not passed_p2: violations += 1
                    elif abs(pv - line_v) / line_v <= 0.012: touches += 1
            score = touches * 3 - violations * 5 + ((p2[0] - p1[0]) / n) * 4
            if score > best_score:
                best_score, best_pair = score, (p1, p2, ls, li)

    if best_score < 7 or best_pair is None: return None
    p1, p2, ls, li = best_pair
    return ls, li, p1[0], [p1[1], p2[1]], [p1[2], p2[2]]


def eval_line(ls, li, start_idx, n_total):
    out = np.full(n_total, np.nan)
    for i in range(start_idx, n_total):
        v = math.exp(ls * i + li)
        out[i] = v if math.isfinite(v) and v > 0 else np.nan
    return out


def build_channel(sup, res, n_total):
    sup_y = eval_line(*sup[:3], n_total) if sup else None
    res_y = eval_line(*res[:3], n_total) if res else None
    mid_y = None
    if sup_y is not None and res_y is not None:
        with np.errstate(invalid='ignore'):
            mid_y = np.exp((np.log(np.where(sup_y > 0, sup_y, np.nan)) +
                            np.log(np.where(res_y > 0, res_y, np.nan))) / 2)
    return sup_y, res_y, mid_y


def draw_channel(ax, sup_y, res_y, mid_y, n_total):
    x_all = np.arange(n_total)

    for y_arr in [sup_y, res_y]:
        if y_arr is None: continue
        mask = np.isfinite(y_arr)
        if mask.sum() >= 2:
            ax.plot(x_all[mask], y_arr[mask], color=CH_LINE,
                    linewidth=CH_LW, solid_capstyle='round', zorder=8)

    if sup_y is not None and res_y is not None:
        both = np.isfinite(sup_y) & np.isfinite(res_y)
        if both.sum() >= 2:
            xf = x_all[both]
            ax.fill_between(xf, np.minimum(sup_y[both], res_y[both]),
                            np.maximum(sup_y[both], res_y[both]),
                            alpha=CH_ALPHA, color=CH_FILL, linewidth=0, zorder=2)

    if mid_y is not None:
        mask = np.isfinite(mid_y)
        if mask.sum() >= 2:
            ax.plot(x_all[mask], mid_y[mask], color=CH_MID,
                    linewidth=1.1, linestyle=(0, (6, 5)), alpha=0.80, zorder=7)


def draw_pivots(ax, df_index, result):
    if not result: return
    for d, v in zip(result[3], result[4]):
        try:
            pos = df_index.get_loc(d)
            ax.plot(pos, v, 'o', color=CH_LINE, ms=7, zorder=12,
                    mec=TV_BG, mew=1.5)
        except Exception:
            pass


def set_log_yticks(ax, y_lo, y_hi):
    sequence = [
        0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90,
        1.00, 1.10, 1.20, 1.30, 1.50, 1.80, 2.00, 2.20, 2.60, 3.00, 3.10,
        3.50, 3.70, 4.00, 4.50, 5.00, 5.50, 6.00, 6.50, 7.00, 8.00, 9.00,
        10, 11, 12, 14, 16, 18, 20, 22, 25, 28, 32, 36, 40, 45, 50,
        55, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 175, 200,
        225, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000,
        1200, 1500, 2000, 2500, 3000,
    ]
    ticks = [v for v in sequence if y_lo * 0.8 <= v <= y_hi * 1.3]
    if not ticks: return
    ax.set_yticks(ticks)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: (f'{x:.2f}' if x < 5 else (f'{x:.0f}' if x < 1000 else f'{x:,.0f}'))
    ))


# ── Generacion de una pagina ──────────────────────────────────────────────────

def make_page(pdf: PdfPages, asset: dict):
    sym    = asset['simbolo']
    nombre = asset['nombre']
    print(f'\n{sym}  ({asset["id"]})...')

    df_orig = fetch_ohlcv(asset['id'])
    if df_orig.empty:
        print(f'  Sin datos'); return

    last_close = float(df_orig['close'].iloc[-1])
    print(f'  {len(df_orig)} velas  |  ${last_close:.2f}')

    sup = find_trendline(df_orig, 'support')
    res = find_trendline(df_orig, 'resistance')
    print(f'  sup={"OK" if sup else "no"}  res={"OK" if res else "no"}')

    df_ext = add_future_bars(df_orig, FUTURE_DAYS)
    n_ext  = len(df_ext)

    sup_y, res_y, mid_y = build_channel(sup, res, n_ext)

    # Grafico base (velas + volumen)
    fig, axes = mpf.plot(
        df_ext,
        type='candle',
        style=STYLE,
        yscale='log',
        volume=True,
        figsize=(22, 12),
        returnfig=True,
        panel_ratios=(6, 1),
        tight_layout=False,
        warn_too_much_data=15000,
        datetime_format='%b %Y',
        xrotation=0,
        ylabel='',
        ylabel_lower='',
    )

    ax     = axes[0]
    ax_vol = axes[2]

    # Canal manual
    draw_channel(ax, sup_y, res_y, mid_y, n_ext)
    draw_pivots(ax, df_ext.index, sup)
    draw_pivots(ax, df_ext.index, res)

    # Eje Y log
    y_lo = float(df_orig['low'].min())  * 0.80
    y_hi = float(df_orig['high'].max()) * 1.25
    set_log_yticks(ax, y_lo, y_hi)
    ax.set_ylim(y_lo, y_hi)
    ax.yaxis.set_label_position('right')
    ax.yaxis.tick_right()
    ax.tick_params(axis='y', which='both', right=True, left=False,
                   labelright=True, labelleft=False, colors=TV_TEXT, length=4)

    # Precio actual
    xlim = ax.get_xlim()
    ax.axhline(y=last_close, color=TV_TEXT, lw=0.6, linestyle='--',
               alpha=0.45, zorder=6)
    ax.annotate(
        f'  {last_close:.2f}  ',
        xy=(xlim[1], last_close),
        xycoords='data',
        color='white', fontsize=8.5, fontweight='bold',
        va='center', ha='left',
        annotation_clip=False,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#2a2e39',
                  edgecolor=TV_TEXT, linewidth=0.8),
        zorder=30,
    )

    # Grilla y fondo
    ax.set_facecolor(TV_BG)
    ax.grid(True, which='major', axis='both', color=TV_GRID,
            linewidth=0.5, alpha=0.8)

    # Leyenda
    handles = []
    if sup_y is not None and res_y is not None:
        v_sup = float(sup_y[np.isfinite(sup_y)][-1])
        v_res = float(res_y[np.isfinite(res_y)][-1])
        handles += [
            Line2D([0],[0], color=CH_LINE, lw=CH_LW,
                   label=f'Canal  ${v_sup:.2f} / ${v_res:.2f}'),
            Line2D([0],[0], color=CH_MID, lw=1.1, linestyle=(0,(6,5)),
                   label='Linea media'),
        ]
    if handles:
        ax.legend(handles=handles, loc='upper left',
                  facecolor='#1c2030', edgecolor=TV_BORDER,
                  labelcolor=TV_TEXT, fontsize=9, framealpha=0.92,
                  handlelength=2.8)

    # Titulo
    ax.set_title(f'{sym}  ·  {nombre}  ·  1D  ·  Log',
                 color=TV_TEXT, fontsize=11, loc='left', pad=8)

    # Volumen
    ax_vol.set_facecolor(TV_BG)
    ax_vol.grid(True, color=TV_GRID, linewidth=0.5, alpha=0.8)
    ax_vol.tick_params(colors=TV_TEXT)
    ax_vol.yaxis.set_label_position('right')
    ax_vol.yaxis.tick_right()
    ax_vol.set_ylabel('')

    fig.patch.set_facecolor(TV_BG)
    fig.subplots_adjust(left=0.02, right=0.91, top=0.95, bottom=0.05, hspace=0.03)

    pdf.savefig(fig, facecolor=TV_BG, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'  Pagina guardada')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print('Generando PDF...')
    with PdfPages(OUTPUT_PDF) as pdf:
        info = pdf.infodict()
        info['Title']  = 'Canal Dinamico - BABA GOOGL MELI'
        info['Author'] = 'Trading Assist'
        for asset in ASSETS:
            make_page(pdf, asset)
    print(f'\nPDF guardado -> {OUTPUT_PDF}')


if __name__ == '__main__':
    main()
