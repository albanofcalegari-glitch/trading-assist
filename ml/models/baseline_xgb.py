"""
ml/models/baseline_xgb.py — baseline #2: gradient boosting con LightGBM.

Decisión (acordada con el user): LightGBM en lugar de XGBoost porque en
Windows xgb suele dar fricción con libomp/wheels. La API de fit/predict_proba
es equivalente para nuestro caso.

Si el lift sobre logreg no es positivo, hay dos opciones:
  1. Más data (corrida --full)
  2. Algo en el dataset/labels está mal — investigar antes de tunear

Uso:
  .venv/Scripts/python.exe -m ml.models.baseline_xgb
"""
from __future__ import annotations

import sys
import time

import lightgbm as lgb
import numpy as np

from ml.backtest_ml import walk_forward
from ml.models.utils import FEATURE_COLS, LABEL_COL, load_dataset


def train_lgbm(X_train: np.ndarray, y_train: np.ndarray):
    """
    Entrena un LGBMClassifier con hiperparámetros conservadores. NO tuneamos
    en Fase 1 — la decisión es 'mostrar que el pipeline corre', no maximizar
    métrica.
    """
    pos_rate = max(float(y_train.mean()), 1e-6)
    scale_pos_weight = (1.0 - pos_rate) / pos_rate

    clf = lgb.LGBMClassifier(
        objective='binary',
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        max_depth=4,
        min_child_samples=10,
        reg_alpha=0.1,
        reg_lambda=0.1,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    )
    clf.fit(X_train, y_train)
    return clf


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    except Exception:
        pass

    print('=== ml/models/baseline_xgb.py (LightGBM) ===')
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
        train_fn=train_lgbm,
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

    # Feature importances: entrenamos un modelo final en todo el dataset
    print('\nFeature importances (global):')
    X_all = df[FEATURE_COLS].fillna(df[FEATURE_COLS].median()).to_numpy()
    y_all = df[LABEL_COL].to_numpy().astype(int)
    final_model = train_lgbm(X_all, y_all)
    imps = sorted(zip(FEATURE_COLS, final_model.feature_importances_),
                  key=lambda x: x[1], reverse=True)
    for name, imp in imps:
        bar = '|' * min(30, imp // 5) if imp else ''
        print(f'  {name:18} {imp:5d}  {bar}')


if __name__ == '__main__':
    main()
