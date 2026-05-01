"""
ml/migrations.py — DDL idempotente para la tabla ml_signals.

Se invoca desde ml/dataset.py al inicio de cada build, y también puede
correrse standalone:

    .venv/Scripts/python.exe -m ml.migrations
"""
from __future__ import annotations

from db.connection import get_conn


_CREATE_ML_SIGNALS = """
CREATE TABLE IF NOT EXISTS ml_signals (
    id                 BIGINT       NOT NULL AUTO_INCREMENT,
    -- ── identificación ──
    symbol             VARCHAR(20)  NOT NULL,
    fecha              DATE         NOT NULL,
    strategy           VARCHAR(40)  NOT NULL,         -- 'trend_pullback' en Fase 1
    variant            VARCHAR(40)  NOT NULL,         -- subtipo de la señal (p. ej. setup_state)
    signal_score       DECIMAL(6,3) DEFAULT NULL,     -- score principal de la estrategia origen

    -- ── features de precio / volumen ──
    price              DECIMAL(12,4) DEFAULT NULL,
    volume_ratio       DECIMAL(8,3)  DEFAULT NULL,    -- vol_ratio_20d (vs media 20)
    gap_pct            DECIMAL(7,3)  DEFAULT NULL,
    range_position     DECIMAL(5,3)  DEFAULT NULL,    -- (close-low)/(high-low) del día

    -- ── features técnicos (de indicadortecnico) ──
    rsi_14             DECIMAL(6,2)  DEFAULT NULL,
    adx_14             DECIMAL(6,2)  DEFAULT NULL,
    dist_sma200        DECIMAL(7,3)  DEFAULT NULL,    -- (price-sma200)/sma200
    ret_5d             DECIMAL(7,3)  DEFAULT NULL,    -- momentum_5d
    ret_20d            DECIMAL(7,3)  DEFAULT NULL,    -- momentum_20d
    rs_vs_spy          DECIMAL(7,3)  DEFAULT NULL,    -- ret_20d - spy_return_20d
    atr14_rel          DECIMAL(7,3)  DEFAULT NULL,
    vs_52w_high        DECIMAL(7,3)  DEFAULT NULL,
    rs_sector          DECIMAL(7,3)  DEFAULT NULL,
    pullback_score     DECIMAL(5,2)  DEFAULT NULL,    -- score secundario de trend_pullback

    -- ── contexto de zonas (nullable hasta Fase 2) ──
    dist_to_support    DECIMAL(7,3)  DEFAULT NULL,
    dist_to_resistance DECIMAL(7,3)  DEFAULT NULL,

    -- ── contexto macro (de indicadormercado) ──
    market_regime      TINYINT       DEFAULT NULL,    -- el mismo enum que indicadormercado
    vix_percentile     DECIMAL(6,4)  DEFAULT NULL,
    spy_return_20d     DECIMAL(8,4)  DEFAULT NULL,

    -- ── labels (forward, computados desde price_history) ──
    return_1d          DECIMAL(8,4)  DEFAULT NULL,
    return_5d          DECIMAL(8,4)  DEFAULT NULL,
    return_10d         DECIMAL(8,4)  DEFAULT NULL,
    max_drawdown_5d    DECIMAL(8,4)  DEFAULT NULL,
    label_5d_strong    TINYINT       DEFAULT NULL,    -- 1 si return_5d>0.03 AND max_dd_5d>-0.02

    created_at         TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uniq_sym_fecha_strat_var (symbol, fecha, strategy, variant),
    KEY idx_fecha (fecha),
    KEY idx_strategy_variant (strategy, variant),
    KEY idx_label (label_5d_strong)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


# Columnas extra (agregadas 2026-04-15) — features basadas en dynamic_supports
# y ATH. Se agregan con ALTER TABLE idempotente para no romper datasets viejos.
_EXTRA_COLUMNS = [
    ('has_dyn_short',      "TINYINT       DEFAULT NULL"),
    ('dyn_short_dist_pct', "DECIMAL(7,3)  DEFAULT NULL"),
    ('dist_to_ath_pct',    "DECIMAL(8,3)  DEFAULT NULL"),
    # dynamic_resistances (2026-04-23)
    ('has_res_long',       "TINYINT       DEFAULT NULL"),
    ('res_long_dist_pct',  "DECIMAL(8,3)  DEFAULT NULL"),
    ('has_res_mid',        "TINYINT       DEFAULT NULL"),
    ('res_mid_dist_pct',   "DECIMAL(8,3)  DEFAULT NULL"),
    ('res_mid_slope',      "DECIMAL(8,3)  DEFAULT NULL"),
    ('has_res_short',      "TINYINT       DEFAULT NULL"),
    ('res_short_dist_pct', "DECIMAL(8,3)  DEFAULT NULL"),
]


def ensure_schema() -> None:
    """Crea ml_signals si no existe. Idempotente. Agrega columnas faltantes."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_ML_SIGNALS)
            # agregar columnas faltantes (MySQL 8.0.29+ soporta IF NOT EXISTS)
            cur.execute(
                """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='ml_signals'"""
            )
            existing = {r['COLUMN_NAME'] for r in cur.fetchall()}
            for col, ddl in _EXTRA_COLUMNS:
                if col not in existing:
                    cur.execute(f"ALTER TABLE ml_signals ADD COLUMN {col} {ddl}")
    finally:
        conn.close()


if __name__ == '__main__':
    ensure_schema()
    print('[+] ml_signals schema asegurado')
