"""
ml/models/baseline_logreg.py — baseline #1: regresión logística.

Es el PISO del benchmark. Si el lift sobre la base rate es < 1.2x algo está
mal en el dataset (no en el modelo). Es el sanity check antes de pasar a
LightGBM.

Uso:
  .venv/Scripts/python.exe -m ml.models.baseline_logreg
"""
from __future__ import annotations

import sys
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.backtest_ml import walk_forward
from ml.models.utils import FEATURE_COLS, LABEL_COL, load_dataset


def train_logreg(X_train: np.ndarray, y_train: np.ndarray):
    """
    Entrena una pipeline StandardScaler + LogisticRegression con class_weight
    'balanced' (la base rate ronda 15-20%, hay que compensar).
    """
    pipe = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', LogisticRegression(
            C=1.0,
            class_weight='balanced',
            max_iter=2000,
            solver='lbfgs',
            random_state=42,
        )),
    ])
    pipe.fit(X_train, y_train)
    return pipe


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    except Exception:
        pass

    print('=== ml/models/baseline_logreg.py ===')
    df = load_dataset(strategy='trend_pullback', require_label=True)
    base = float(df[LABEL_COL].mean())
    print(f'Dataset: {len(df)} rows | {len(FEATURE_COLS)} features | '
          f'label_5d_strong base rate = {base*100:.1f}%')
    print(f'Variants: {dict(df["variant"].value_counts())}')
    print()

    print('Walk-forward (5 folds, k=10%):')
    t0 = time.time()
    res = walk_forward(
        df,
        feature_cols=FEATURE_COLS,
        label_col=LABEL_COL,
        train_fn=train_logreg,
        n_folds=5,
        test_window_days=20,
        k_frac=0.10,
    )
    elapsed = time.time() - t0

    print()
    if res['per_fold']:
        print(f'mean: AUC={res["mean_auc"]:.3f} | '
              f'prec@top{int(res["k_frac"]*100)}%={res["mean_prec_at_k"]:.3f} | '
              f'base={res["mean_base_rate"]:.3f} → lift x{res["lift"]:.2f}')
    else:
        print('NO HAY FOLDS VÁLIDOS — dataset demasiado chico para walk-forward.')
    print(f'elapsed_seconds = {elapsed:.1f}')


if __name__ == '__main__':
    main()
