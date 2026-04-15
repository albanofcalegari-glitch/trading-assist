"""
ml/models/utils.py — helpers compartidos por los modelos baseline.

  - load_dataset(): trae filas de ml_signals como pandas DataFrame
  - FEATURE_COLS:    lista canónica de features para entrenar
  - LABEL_COL:       label objetivo (label_5d_strong)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from db.connection import get_conn


# Columnas que usamos como features (TODAS las del dataset minus identificación
# y minus labels). Excluimos dist_to_support/dist_to_resistance porque hoy son
# 100% NULL — se enchufan en Fase 2 cuando integremos zones.
FEATURE_COLS: list[str] = [
    'signal_score',
    'pullback_score',
    'volume_ratio',
    'gap_pct',
    'range_position',
    'rsi_14',
    'adx_14',
    'dist_sma200',
    'ret_5d',
    'ret_20d',
    'rs_vs_spy',
    'atr14_rel',
    'vs_52w_high',
    'rs_sector',
    'market_regime',
    'vix_percentile',
    'spy_return_20d',
    # dynamic_supports / ATH (agregadas 2026-04-15)
    'has_dyn_short',
    'dyn_short_dist_pct',
    'dist_to_ath_pct',
]

LABEL_COL = 'label_5d_strong'


def load_dataset(
    strategy: str = 'trend_pullback',
    variant: Optional[str] = None,
    require_label: bool = True,
) -> pd.DataFrame:
    """
    Devuelve un DataFrame ordenado por fecha. Filtra opcionalmente por variant.
    Convierte todas las columnas numéricas a float (pymysql las trae como Decimal).
    """
    where = ['strategy = %s']
    params: list = [strategy]
    if variant:
        where.append('variant = %s')
        params.append(variant)
    if require_label:
        where.append('label_5d_strong IS NOT NULL')

    sql = (
        'SELECT symbol, fecha, strategy, variant, '
        + ', '.join(FEATURE_COLS)
        + f', {LABEL_COL}, return_5d '
        + 'FROM ml_signals WHERE ' + ' AND '.join(where)
        + ' ORDER BY fecha ASC, symbol ASC'
    )

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    finally:
        conn.close()

    df = pd.DataFrame(rows)

    # Cast a float (pymysql devuelve Decimal para los DECIMAL de MySQL)
    for c in FEATURE_COLS + [LABEL_COL, 'return_5d']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    return df


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    df = load_dataset()
    print(f'shape: {df.shape}')
    print(f'columns: {list(df.columns)}')
    print(f'label rate: {df[LABEL_COL].mean():.3f}')
    print(df.head(3))
