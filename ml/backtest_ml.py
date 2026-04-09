"""
ml/backtest_ml.py — walk-forward validator + métricas.

Splits temporales (NUNCA random k-fold). Para cada fold:
  - train = todas las filas con fecha < cutoff_i
  - test  = filas con cutoff_i <= fecha < cutoff_i + window
  - entrena un modelo (callable) con train, predice probas en test
  - mide AUC + precision@top_k (k = top 10% del test, métrica crítica)

El modelo es un callable que recibe (X_train, y_train) y devuelve un objeto
con .predict_proba(X_test). Compatible con sklearn / lightgbm / cualquier
estimator binario.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def _temporal_cutoffs(dates: pd.Series, n_folds: int) -> list:
    """
    Devuelve n_folds cutoffs equiespaciados en el rango. Cada cutoff es el
    inicio del bloque de test del fold.
    """
    sorted_dates = sorted(dates.unique())
    if len(sorted_dates) < n_folds + 1:
        n_folds = max(1, len(sorted_dates) // 2)
    chunk = max(1, len(sorted_dates) // (n_folds + 1))
    return [sorted_dates[(i + 1) * chunk] for i in range(n_folds)]


def precision_at_top_k(y_true: np.ndarray, y_score: np.ndarray, k_frac: float = 0.10) -> tuple[float, int]:
    """
    Precision@top-k: ordenamos por score desc, tomamos el top k% y
    medimos qué fracción de esos son positivos. Métrica crítica del brief.
    """
    n = len(y_true)
    k = max(1, int(round(n * k_frac)))
    order = np.argsort(-y_score)
    top_idx = order[:k]
    return float(y_true[top_idx].mean()), k


def walk_forward(
    df: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    train_fn: Callable,
    n_folds: int = 5,
    test_window_days: int = 30,
    k_frac: float = 0.10,
    verbose: bool = True,
) -> dict:
    """
    Args:
        df:               dataframe ordenado por fecha
        feature_cols:     columnas a usar como X
        label_col:        nombre de la columna binaria (0/1)
        train_fn:         callable(X_train, y_train) -> estimator con .predict_proba
        n_folds:          cantidad de folds temporales
        test_window_days: ancho del bloque de test (desde el cutoff)
        k_frac:           fracción para precision@top-k

    Returns:
        dict con per_fold y mean_auc / mean_precision_at_top_k
    """
    df = df.copy()
    df['fecha'] = pd.to_datetime(df['fecha'])
    df = df.sort_values('fecha').reset_index(drop=True)

    cutoffs = _temporal_cutoffs(df['fecha'], n_folds)
    fold_results = []

    for i, cutoff in enumerate(cutoffs, 1):
        cutoff = pd.to_datetime(cutoff)
        end_test = cutoff + pd.Timedelta(days=test_window_days)
        train_mask = df['fecha'] < cutoff
        test_mask  = (df['fecha'] >= cutoff) & (df['fecha'] < end_test)

        train = df[train_mask]
        test  = df[test_mask]

        if len(train) < 30 or len(test) < 10:
            if verbose:
                print(f'  fold {i}: SKIP (train={len(train)} test={len(test)})')
            continue

        # Imputar NaNs simples con la mediana del train (Fase 1, sin Imputer fancy)
        train_med = train[feature_cols].median()
        X_train = train[feature_cols].fillna(train_med).to_numpy()
        y_train = train[label_col].to_numpy().astype(int)
        X_test  = test[feature_cols].fillna(train_med).to_numpy()
        y_test  = test[label_col].to_numpy().astype(int)

        # Skip si el train no tiene ambas clases (no se puede entrenar binario)
        if len(set(y_train)) < 2:
            if verbose:
                print(f'  fold {i}: SKIP (train tiene 1 clase sola)')
            continue

        model = train_fn(X_train, y_train)
        # Pasar DataFrame con feature names a predict para evitar warnings
        X_test_df = pd.DataFrame(X_test, columns=feature_cols)
        scores = model.predict_proba(X_test_df)[:, 1]

        try:
            auc = float(roc_auc_score(y_test, scores)) if len(set(y_test)) > 1 else float('nan')
        except ValueError:
            auc = float('nan')

        prec_k, k = precision_at_top_k(y_test, scores, k_frac=k_frac)
        base_rate = float(y_test.mean()) if len(y_test) else 0.0

        fold_results.append({
            'fold':      i,
            'cutoff':    cutoff.date().isoformat(),
            'n_train':   int(len(train)),
            'n_test':    int(len(test)),
            'auc':       auc,
            'prec_at_k': prec_k,
            'k':         k,
            'base_rate': base_rate,
        })

        if verbose:
            print(f'  fold {i}: cutoff={cutoff.date()}  train={len(train):4d} test={len(test):4d} | '
                  f'AUC={auc:.3f} | prec@top{int(k_frac*100)}%={prec_k:.3f} (k={k}, base={base_rate:.3f})')

    if not fold_results:
        return {'per_fold': [], 'mean_auc': float('nan'), 'mean_prec_at_k': float('nan')}

    valid_aucs  = [r['auc'] for r in fold_results if not math.isnan(r['auc'])]
    valid_precs = [r['prec_at_k'] for r in fold_results]
    base_rates  = [r['base_rate'] for r in fold_results]

    summary = {
        'per_fold':       fold_results,
        'mean_auc':       float(np.mean(valid_aucs)) if valid_aucs else float('nan'),
        'mean_prec_at_k': float(np.mean(valid_precs)),
        'mean_base_rate': float(np.mean(base_rates)),
        'lift':           (float(np.mean(valid_precs)) / float(np.mean(base_rates)))
                          if base_rates and np.mean(base_rates) > 0 else float('nan'),
        'k_frac':         k_frac,
    }
    return summary
