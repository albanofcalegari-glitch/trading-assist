"""
generate_chart_pdf.py
3 paginas en PDF — una por activo (BABA, GOOGL, NU).
Cada pagina muestra Diario | Semanal | Mensual lado a lado.
Escala logaritmica. Canal dinamico (soporte + resistencia + relleno).
"""

import sys, io, math
import numpy as np
import pandas as pd
import pymysql, pymysql.cursors
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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
    {'id': 7783, 'simbolo': 'NU',    'nombre': 'Nu Holdings Ltd.'},
]

OUTPUT_PDF = r'C:\Users\DELL\Desktop\charts_SRdin.pdf'
DAYS_BACK  = 1800

TIMEFRAMES = [
    ('Diario',  'D'),
    ('Semanal', 'W'),
    ('Mensual', 'M'),
]

# Colores del canal (identicos para soporte y resistencia, igual que TradingView)
CHANNEL_COLOR = '#14b8a6'
CHANNEL_ALPHA = 0.12

# Estilo oscuro tipo TradingView
STYLE = mpf.make_mpf_style(
    base_mpf_style='nightclouds',
    rc={
        'axes.facecolor':  '#0f1117',
        'figure.facecolor':'#0f1117',
        'axes.edgecolor':  '#2a3245',
        'axes.labelcolor': '#8899aa',
        'xtick.color':     '#8899aa',
        'ytick.color':     '#8899aa',
        'xtick.labelsize': 8,
        'ytick.labelsize': 8,
        'grid.color':      '#1e2a3a',
        'grid.linestyle':  '-',
        'grid.alpha':      0.5,
        'font.family':     'monospace',
        'font.size':       8,
    },
    marketcolors=mpf.make_marketcolors(
        up='#26a65b', down='#e74c3c',
        edge='inherit', wick='inherit',
        volume={'up': '#26a65b55', 'down': '#e74c3c55'},
    ),
)

BG = '#0f1117'

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
    df = df.set_index('fecha').sort_index()
    return df


def resample(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    rule = 'W-FRI' if freq == 'W' else 'ME'
    agg  = {'open': 'first', 'high': 'max', 'low': 'min',
             'close': 'last', 'volume': 'sum'}
    return df.resample(rule).agg(agg).dropna(subset=['close', 'high', 'low'])


# ── Algoritmo trendline (identico a PriceChart.tsx) ───────────────────────────

def find_best_trendline(df: pd.DataFrame, kind: str):
    """
    Retorna (line_dates, line_vals, pivot_dates, pivot_vals)
    o ([], [], [], []) si no hay linea valida.
    """
    n     = len(df)
    lows  = df['low'].values.astype(float)
    highs = df['high'].values.astype(float)
    vals  = lows if kind == 'support' else highs
    dates = df.index

    if n < 10:
        return [], [], [], []

    win = max(2, min(5, n // 100))

    # 1. Pivotes con ventana variable
    raw = []
    for i in range(win, n - win):
        v = vals[i]
        if v <= 0 or math.isnan(v):
            continue
        if kind == 'support':
            ok = all(vals[j] >= v for j in range(i-win, i)) and \
                 all(vals[j] >= v for j in range(i+1, i+win+1))
        else:
            ok = all(vals[j] <= v for j in range(i-win, i)) and \
                 all(vals[j] <= v for j in range(i+1, i+win+1))
        if ok:
            raw.append((i, dates[i], v, math.log(v)))

    if len(raw) < 2:
        return [], [], [], []

    # 2. Filtro de significancia: rebote >=2% en 15 barras
    REACT_PCT, REACT_BARS = 0.02, 15
    sig = []
    for (i, d, v, lv) in raw:
        slc = highs[i+1:min(i+1+REACT_BARS, n)] if kind == 'support' \
              else lows[i+1:min(i+1+REACT_BARS, n)]
        slc = slc[slc > 0]
        if kind == 'support':
            if len(slc) and slc.max() >= v * (1 + REACT_PCT):
                sig.append((i, d, v, lv))
        else:
            if len(slc) and slc.min() <= v * (1 - REACT_PCT):
                sig.append((i, d, v, lv))

    if len(sig) < 2:
        return [], [], [], []

    # 3. Deduplicar
    min_sep = max(5, n // 50)
    pivots  = []
    for p in sig:
        if pivots and p[0] - pivots[-1][0] < min_sep:
            if (kind == 'support' and p[2] < pivots[-1][2]) or \
               (kind == 'resistance' and p[2] > pivots[-1][2]):
                pivots[-1] = p
        else:
            pivots.append(p)

    if len(pivots) < 2:
        return [], [], [], []

    # 4. Evaluar pares (pendiente en log, violaciones solo entre p1-p2)
    TOUCH_TOL, VIOL_TOL = 0.012, 0.008
    MIN_SEP = max(win * 3, 5)

    best_score, best_pair = -math.inf, None

    for a in range(len(pivots) - 1):
        for b in range(a + 1, len(pivots)):
            p1, p2 = pivots[a], pivots[b]
            if p2[0] - p1[0] < MIN_SEP:
                continue

            ls = (p2[3] - p1[3]) / (p2[0] - p1[0])
            li = p1[3] - ls * p1[0]

            touches, violations = 2, 0
            passed_p2 = False

            for k in range(p1[0], n):
                if k == p1[0]:
                    continue
                if k == p2[0]:
                    passed_p2 = True
                    continue
                lv = math.exp(ls * k + li)
                if kind == 'support':
                    v = lows[k]
                    if v <= 0: continue
                    if v < lv * (1 - VIOL_TOL):
                        if not passed_p2: violations += 1
                    elif abs(v - lv) / lv <= TOUCH_TOL:
                        touches += 1
                else:
                    v = highs[k]
                    if v <= 0: continue
                    if v > lv * (1 + VIOL_TOL):
                        if not passed_p2: violations += 1
                    elif abs(v - lv) / lv <= TOUCH_TOL:
                        touches += 1

            span_bonus = ((p2[0] - p1[0]) / n) * 4
            score = touches * 3 - violations * 5 + span_bonus

            if score > best_score:
                best_score, best_pair = score, (p1, p2, ls, li)

    if best_score < 7 or best_pair is None:
        return [], [], [], []

    p1, p2, ls, li = best_pair

    # 5. Generar linea (hasta 6 meses despues del ultimo dato)
    ld, lv_arr = [], []
    last = dates[-1]
    for i in range(p1[0], n + 6):
        val = math.exp(ls * i + li)
        if val <= 0 or not math.isfinite(val):
            continue
        if i < n:
            d = dates[i]
        else:
            mo = i - n + 1
            y  = last.year + (last.month - 1 + mo) // 12
            m  = (last.month - 1 + mo) % 12 + 1
            d  = pd.Timestamp(year=y, month=m, day=min(last.day, 28))
        ld.append(d)
        lv_arr.append(round(val, 4))

    return ld, lv_arr, [p1[1], p2[1]], [p1[2], p2[2]]


# ── Renderizar un chart → imagen PNG en memoria ───────────────────────────────

def make_chart_png(df: pd.DataFrame, simbolo: str, tf_label: str) -> np.ndarray:
    """Genera el chart con canal dinamico y devuelve un array RGBA (para imshow)."""

    if df.empty or len(df) < 10:
        fig, ax = plt.subplots(figsize=(9, 6), facecolor=BG)
        ax.set_facecolor(BG)
        ax.text(0.5, 0.5, 'Sin datos', color='#8899aa',
                ha='center', va='center', transform=ax.transAxes, fontsize=12)
        ax.axis('off')
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=130, facecolor=BG, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return plt.imread(buf)

    sup_ld, sup_lv, sup_pd, sup_pv = find_best_trendline(df, 'support')
    res_ld, res_lv, res_pd, res_pv = find_best_trendline(df, 'resistance')

    # Series alineadas al indice de df
    # mplfinance asigna x = 0, 1, 2 ... n-1 para cada vela en df
    def align(tdates, tvals):
        s = pd.Series(np.nan, index=df.index, dtype=float)
        for d, v in zip(tdates, tvals):
            if d in s.index:
                s[d] = v
        return s

    sup_series = None
    res_series = None
    add_plots  = []

    if sup_ld:
        s = align(sup_ld, sup_lv)
        if s.notna().sum() >= 2:
            sup_series = s
            add_plots.append(mpf.make_addplot(
                s, color=CHANNEL_COLOR, width=2.2, linestyle='-', panel=0))
    if res_ld:
        s = align(res_ld, res_lv)
        if s.notna().sum() >= 2:
            res_series = s
            add_plots.append(mpf.make_addplot(
                s, color=CHANNEL_COLOR, width=2.2, linestyle='-', panel=0))

    fig, axes = mpf.plot(
        df,
        type='candle',
        style=STYLE,
        yscale='log',
        volume=True,
        addplot=add_plots if add_plots else None,
        figsize=(9, 6),
        returnfig=True,
        panel_ratios=(4, 1),
        tight_layout=True,
        warn_too_much_data=10000,
        datetime_format='%b %Y',
        xrotation=30,
    )

    ax = axes[0]
    ax.set_title(f'{simbolo}  -  {tf_label}  |  Log',
                 color='#dde6f0', fontsize=10, pad=6)

    # ── Relleno del canal ─────────────────────────────────────────────────────
    # fill_between con indices enteros (eje x de mplfinance = 0,1,2...n-1)
    if sup_series is not None and res_series is not None:
        both = sup_series.notna() & res_series.notna()
        if both.sum() >= 2:
            x_idx = np.where(both.values)[0]
            y_s   = sup_series.values[both.values]
            y_r   = res_series.values[both.values]
            ax.fill_between(
                x_idx,
                np.minimum(y_s, y_r),
                np.maximum(y_s, y_r),
                alpha=CHANNEL_ALPHA,
                color=CHANNEL_COLOR,
                zorder=1,
                linewidth=0,
            )

    # ── Pivotes ───────────────────────────────────────────────────────────────
    for d, v in list(zip(sup_pd, sup_pv)) + list(zip(res_pd, res_pv)):
        try:
            ax.plot(d, v, 'o', color=CHANNEL_COLOR, ms=6, zorder=10,
                    mec='#0b0d11', mew=1.5)
        except Exception:
            pass

    # ── Leyenda ───────────────────────────────────────────────────────────────
    legend = []
    if sup_series is not None and res_series is not None:
        label = f'Canal  ${sup_pv[-1]:.2f} / ${res_pv[-1]:.2f}'
        legend.append(Line2D([0],[0], color=CHANNEL_COLOR, lw=2.5, label=label))
    elif sup_series is not None:
        legend.append(Line2D([0],[0], color=CHANNEL_COLOR, lw=2,
                             label=f'Soporte  ${sup_pv[0]:.2f} -> ${sup_pv[-1]:.2f}'))
    elif res_series is not None:
        legend.append(Line2D([0],[0], color=CHANNEL_COLOR, lw=2,
                             label=f'Resistencia  ${res_pv[0]:.2f} -> ${res_pv[-1]:.2f}'))
    if legend:
        ax.legend(handles=legend, loc='upper left',
                  facecolor='#111827', edgecolor='#2a3245',
                  labelcolor='#dde6f0', fontsize=8, framealpha=0.9)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=140, facecolor=BG, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)

    has_canal = sup_series is not None and res_series is not None
    print(f'    {tf_label:8s}: sup={"si" if sup_ld else "no":2s}  '
          f'res={"si" if res_ld else "no":2s}  '
          f'canal={"SI" if has_canal else "no"}')

    return plt.imread(buf)


# ── Pagina PDF: 3 graficos lado a lado ───────────────────────────────────────

def plot_asset_page(pdf: PdfPages, asset: dict, df_daily: pd.DataFrame):
    print(f'\n{asset["simbolo"]}...')

    imgs = []
    for tf_label, tf_code in TIMEFRAMES:
        if tf_code == 'D':
            df = df_daily.copy()
        elif tf_code == 'W':
            df = resample(df_daily, 'W')
        else:
            df = resample(df_daily, 'M')
        imgs.append(make_chart_png(df, asset['simbolo'], tf_label))

    # Pagina: 1 fila x 3 columnas
    fig, axes = plt.subplots(1, 3, figsize=(21, 8), facecolor=BG)

    fig.suptitle(
        f"{asset['simbolo']}  -  {asset['nombre']}  |  Canal Dinamico",
        color='#dde6f0', fontsize=14, fontweight='bold', y=1.01,
    )

    for ax, img in zip(axes, imgs):
        ax.imshow(img, aspect='auto')
        ax.axis('off')

    plt.subplots_adjust(left=0.005, right=0.995, top=0.97,
                        bottom=0.005, wspace=0.015)

    pdf.savefig(fig, facecolor=BG, dpi=140, bbox_inches='tight')
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print('Generando PDF...\n')
    with PdfPages(OUTPUT_PDF) as pdf:
        info = pdf.infodict()
        info['Title']   = 'Canal Dinamico - BABA GOOGL NU'
        info['Author']  = 'Trading Assist'
        info['Subject'] = 'Analisis tecnico - escala logaritmica'

        for asset in ASSETS:
            df = fetch_ohlcv(asset['id'])
            if df.empty:
                print(f'{asset["simbolo"]}: sin datos')
                continue
            plot_asset_page(pdf, asset, df)

    print(f'\nPDF generado -> {OUTPUT_PDF}')


if __name__ == '__main__':
    main()
