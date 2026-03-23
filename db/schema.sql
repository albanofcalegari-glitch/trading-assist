-- ============================================================
-- trading-assist — DDL
-- Base de datos: trading_assist
-- ============================================================

CREATE DATABASE IF NOT EXISTS trading_assist
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE trading_assist;

-- ── 1. Catálogo de activos ────────────────────────────────────
CREATE TABLE IF NOT EXISTS asset_master (
    simbolo           VARCHAR(20)  NOT NULL,
    nombre            VARCHAR(120) NOT NULL,
    sector            VARCHAR(80)  NOT NULL,
    industria         VARCHAR(120) DEFAULT NULL,
    benchmark_sector  VARCHAR(20)  NOT NULL,       -- ETF de sector (XLK, XLF, ...)
    market            VARCHAR(20)  DEFAULT 'US',   -- mercado: US / AR / ...
    activo            TINYINT(1)   NOT NULL DEFAULT 1,
    PRIMARY KEY (simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 2. Precios OHLCV diarios ──────────────────────────────────
CREATE TABLE IF NOT EXISTS price_history (
    simbolo   VARCHAR(20)    NOT NULL,
    fecha     DATE           NOT NULL,
    open      DECIMAL(14,4)  NOT NULL,
    high      DECIMAL(14,4)  NOT NULL,
    low       DECIMAL(14,4)  NOT NULL,
    close     DECIMAL(14,4)  NOT NULL,
    volume    BIGINT         NOT NULL DEFAULT 0,
    PRIMARY KEY (simbolo, fecha),
    INDEX idx_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 3. Índice de mercado (SPY u otro) ─────────────────────────
CREATE TABLE IF NOT EXISTS market_index (
    simbolo   VARCHAR(20)    NOT NULL,   -- 'SPY'
    fecha     DATE           NOT NULL,
    open      DECIMAL(14,4)  NOT NULL,
    high      DECIMAL(14,4)  NOT NULL,
    low       DECIMAL(14,4)  NOT NULL,
    close     DECIMAL(14,4)  NOT NULL,
    volume    BIGINT         NOT NULL DEFAULT 0,
    PRIMARY KEY (simbolo, fecha),
    INDEX idx_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 4. Índices sectoriales (XLK, XLC, XLF, XLY, XLE) ─────────
CREATE TABLE IF NOT EXISTS sector_index (
    simbolo   VARCHAR(20)    NOT NULL,   -- 'XLK', 'XLC', ...
    sector    VARCHAR(80)    NOT NULL,
    fecha     DATE           NOT NULL,
    open      DECIMAL(14,4)  NOT NULL,
    high      DECIMAL(14,4)  NOT NULL,
    low       DECIMAL(14,4)  NOT NULL,
    close     DECIMAL(14,4)  NOT NULL,
    volume    BIGINT         NOT NULL DEFAULT 0,
    PRIMARY KEY (simbolo, fecha),
    INDEX idx_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 5. Contexto de mercado diario ─────────────────────────────
-- Régimen calculado sobre SPY
CREATE TABLE IF NOT EXISTS market_context_daily (
    fecha           DATE         NOT NULL,
    simbolo         VARCHAR(20)  NOT NULL DEFAULT 'SPY',
    regime          VARCHAR(20)  NOT NULL,   -- TREND_UP / TREND_DOWN / RANGE / VOLATILE
    sma50           DECIMAL(14,4) DEFAULT NULL,
    sma200          DECIMAL(14,4) DEFAULT NULL,
    mom20           DECIMAL(8,4)  DEFAULT NULL,   -- retorno 20 días (%)
    mom60           DECIMAL(8,4)  DEFAULT NULL,   -- retorno 60 días (%)
    volatility_20d  DECIMAL(8,4)  DEFAULT NULL,   -- std anualizada 20d (%)
    PRIMARY KEY (fecha, simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 7. Señales Reversal ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS reversal_signals (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    fecha            DATE          NOT NULL,
    simbolo          VARCHAR(20)   NOT NULL,
    sector           VARCHAR(80)   DEFAULT NULL,   -- sector del activo
    reversal_score   FLOAT,
    pattern_state    VARCHAR(40),  -- DOUBLE_BOTTOM_CONFIRMED/FORMING, BASE_TENTATIVE, etc.
    market_alignment VARCHAR(20),
    sector_alignment VARCHAR(20),  -- strong / neutral / weak
    sector_regime    VARCHAR(20)   DEFAULT NULL,   -- STRONG / NEUTRAL / WEAK (raw)
    sector_mom60     FLOAT         DEFAULT NULL,   -- momentum 60d del sector ETF
    overall_context  VARCHAR(20),
    decision         VARCHAR(20),
    confidence_level VARCHAR(10),
    allow_trade      TINYINT(1),
    selling_pressure TINYINT(1)    DEFAULT 0,      -- 1 si hay presion vendedora activa
    reading          VARCHAR(500),
    price            FLOAT,
    rsi14            FLOAT,
    mom20            FLOAT,
    mom60            FLOAT,
    vol_ratio        FLOAT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_reversal_fecha_sym (fecha, simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 8. Zonas de soporte estructurales ─────────────────────────────
-- Detectadas por strategies/support_zones.py
-- Capa estructural reutilizable por Reversal, T+P y alertas
CREATE TABLE IF NOT EXISTS support_zones (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    fecha                    DATE          NOT NULL,
    simbolo                  VARCHAR(20)   NOT NULL,
    support_price            FLOAT,
    zone_low                 FLOAT,
    zone_high                FLOAT,
    first_touch_date         DATE,
    second_touch_date        DATE,
    touches_count            INT           DEFAULT 1,
    deviation_pct            FLOAT,
    state                    VARCHAR(40),  -- SUPPORT_ZONE_DETECTED / RETESTED / HOLDING / BROKEN / BOUNCE_CONFIRMED
    bounce_confirmed         TINYINT(1)    DEFAULT 0,
    rebound_pct_after_first  FLOAT,
    rebound_pct_after_second FLOAT,
    reading                  VARCHAR(500),
    created_at               TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sz_fecha_sym (fecha, simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 6. Contexto sectorial diario ──────────────────────────────
CREATE TABLE IF NOT EXISTS sector_context_daily (
    fecha         DATE         NOT NULL,
    sector        VARCHAR(80)  NOT NULL,
    simbolo       VARCHAR(20)  NOT NULL,   -- ETF de referencia
    regime        VARCHAR(10)  NOT NULL,   -- STRONG / NEUTRAL / WEAK
    mom20         DECIMAL(8,4)  DEFAULT NULL,
    mom60         DECIMAL(8,4)  DEFAULT NULL,
    drawdown_52w  DECIMAL(8,4)  DEFAULT NULL,   -- % desde máximo 52 semanas
    rs_vs_spy     DECIMAL(8,4)  DEFAULT NULL,   -- retorno relativo vs SPY 60d
    PRIMARY KEY (fecha, sector)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
