# PLAN_ML — trading-assist

> Documento vivo. Borrador inicial 2026-04-08. Para iterar antes de empezar a codear.
> Objetivo del doc: alinear expectativas entre lo aspiracional y lo realmente factible
> con la infraestructura, datos y tiempo disponibles, y dejar un roadmap accionable
> en fases para evitar quemar tiempo en cosas que la literatura ya demostró que no andan.

---

## 1. Objetivo

### 1.1 Lo que se planteó originalmente
> *"Empezar a hacer un ML que aprenda de las estrategias que vamos cargando, de la
> historia de los precios, patrones, y hasta que en algún momento elabore un algoritmo
> matemático para predecir movimientos de precios."*

### 1.2 La parte aspiracional
"Predecir movimientos de precios" con un modelo matemático cerrado es **el santo grial
del trading cuantitativo**. Hedge funds con PhDs en física, infraestructura millonaria
y acceso a datos alternativos llevan décadas en eso, y a duras penas baten consistentemente
al SPY. La mayoría de los papers académicos que muestran "predicción de precios" con ML,
cuando se prueban out-of-sample con costos de transacción reales, dan Sharpe ~0.2 o
directamente negativo. Eso **no significa que la ML no sirva** — significa que el framing
"predigo el precio" está mal planteado para mercados líquidos.

### 1.3 El framing que SÍ funciona
En vez de "predecir precios", el goal correcto y tractable es:

> **Rankear las señales que ya generamos hoy**, decidiendo cuáles tienen más
> probabilidad histórica de cumplirse y filtrando las que no.

La pregunta deja de ser:
> *"¿A cuánto va a estar AAPL la semana que viene?"* (imposible)

Y pasa a ser:
> *"Dado que mi screener detectó un BUY_CONFIRMATION en AAPL hoy con estas features
> (RSI=58, distancia_SMA200=+12%, market_regime=alcista, sector=tech), ¿qué probabilidad
> histórica hay de que esa configuración haya dado +3% en los 5 días siguientes?"*

Eso es un problema de **clasificación supervisada con horizonte de N días**, completamente
estándar y resoluble con técnicas convencionales (gradient boosting, etc.).

### 1.4 Resultado realista esperado
Si las 4 fases de este plan se ejecutan bien, en ~2-3 meses de trabajo razonable
deberíamos tener un sistema que:
- **Reduce ~60-70% el volumen de señales** que llegan por Telegram (filtra el ruido)
- **Mejora la win-rate** de las que sí llegan en ~5-10 puntos absolutos (ej. de 45% a 53%)
- **Sharpe esperado en producción**: 0.7 a 1.2 si las cosas salen bien
- NO predice precios en el sentido tradicional. Sirve como filtro/ranker de calidad.

Eso, sin venderse humo, es **muy valioso**. Es el tipo de mejora real que separa un
sistema amateur de uno semi-profesional. El "algoritmo matemático que predice precios"
queda como norte aspiracional sin deadline; si en algún momento aparece un edge real,
va a salir orgánicamente del trabajo de Fase 1-3, no de empezar por ahí.

---

## 2. Materia prima que ya tenemos

Una de las cosas que hace este proyecto particularmente bien posicionado es que **la
infraestructura para generar el dataset ya existe**. No estamos arrancando de cero.

### 2.1 Señales históricas disponibles
Las siguientes tablas en MySQL ya acumulan o pueden acumular signals etiquetables:
- `wma_cross` outputs (vía `scan_wma_cross.py`)
- `reversal_signals`
- `trend_pullback_signals`
- `support_zones` / `horizontal_zones`
- `rsi_divergence_signals`
- `short_signals`
- `buy_confirmation` (vía `scan_buy_confirmation.py`)
- Las nuevas notificaciones en `notification` y `batch_run` desde el sistema de batches

Cada una de estas señales tiene una fecha, un símbolo, y un score/categoría.
Falta agregar **el target**: el retorno forward a N días.

### 2.2 Features ya calculados
El sistema ya calcula y persiste:
- SMA50, SMA200, RSI14, ATR14_rel
- Distancia a SMA200 (`dist_sma200_pct`)
- Momentum 5d, 20d
- Volume ratio 5d, 20d
- `market_regime` (alcista/lateral/bajista) y `sector_regime`
- VIX level + percentil 1y
- SPY return 5d/20d
- Yield 10y

Todo esto es feature material listo para ser consumido por un modelo.

### 2.3 Pipeline diario
- `morning_alert.py` ahora corre 12:00 ART (update precios + scan oportunidades)
- `backfill_history.py --update` corre 19:00 ART (mantiene OHLCV histórico al día)
- Los 4 batches (`premarket`, `opening`, `closing`, `weekly_ranking`) generan
  snapshots tipados con payload JSON estructurado en cada corrida

→ **Esto significa que cada día se genera dataset nuevo automáticamente sin
intervención manual.** En 30 días tendríamos 30 días extra de signals etiquetables.

### 2.4 Backtest framework
- `strategies.rotation` ya tiene snapshot-based equity curves, regime filter,
  configurable churn (rotate_diff) y top-K
- `strategies.rotation_compare` permite comparar variantes contra SPY rápido
- Esa misma lógica de "tomo señales, simulo, comparo vs benchmark" es exactamente
  lo que vamos a necesitar para la Fase 2 (baseline) y Fase 3 (validación OOS)

### 2.5 Volumen de datos disponible
- ~10 años de daily OHLCV de ~500-1000 stocks USA + benchmarks/sectores
- Esto da del orden de **1.2M - 2.5M filas** de datos
- En este rango de volumen, **gradient boosting (LightGBM/XGBoost) aplasta a redes
  neuronales** y entrena 100x más rápido. Punto importante para el cap. 5.

---

## 3. Las 4 fases

### Fase 1 — Dataset etiquetado (cimiento)

**Por qué es la fase más importante**: sin un dataset bien etiquetado y limpio,
todo lo demás es imposible. Es el 80% del valor del proyecto y el 20% del trabajo
"sexy". También es la fase que la mayoría de la gente saltea para ir directo a
modelar, y es donde la mayoría de los proyectos ML financieros fracasan.

**Entregable**: una tabla nueva en MySQL, `ml_signals`, con la siguiente estructura:

```sql
CREATE TABLE ml_signals (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    fecha           DATE         NOT NULL,
    accion_id       INT          NOT NULL,
    simbolo         VARCHAR(20)  NOT NULL,
    strategy_kind   VARCHAR(40)  NOT NULL,    -- 'wma_cross', 'reversal', etc
    score           DECIMAL(10,4) NULL,        -- score raw del strategy
    -- Features snapshot al momento de la senal
    features_json   LONGTEXT     NOT NULL,     -- todos los features en JSON
    -- Targets forward (calculados con valorhistoricoaccion)
    fwd_return_1d   DECIMAL(10,4) NULL,
    fwd_return_3d   DECIMAL(10,4) NULL,
    fwd_return_5d   DECIMAL(10,4) NULL,
    fwd_return_10d  DECIMAL(10,4) NULL,
    fwd_return_20d  DECIMAL(10,4) NULL,
    fwd_max_5d      DECIMAL(10,4) NULL,        -- max retorno intradía 5d
    fwd_min_5d      DECIMAL(10,4) NULL,        -- min retorno intradía 5d
    -- Labels binarios pre-calculados
    label_5d_pos    TINYINT      NULL,         -- 1 si fwd_return_5d > 0
    label_5d_strong TINYINT      NULL,         -- 1 si fwd_return_5d > 0.02 (2%)
    -- Metadata
    market_regime   TINYINT      NULL,         -- snapshot del regime ese día
    sector_regime   TINYINT      NULL,
    created_at      DATETIME     NOT NULL,
    INDEX idx_fecha_strategy (fecha, strategy_kind),
    INDEX idx_simbolo_fecha  (simbolo, fecha),
    UNIQUE KEY uq_signal (fecha, accion_id, strategy_kind)
);
```

**Tareas concretas**:

1. **Crear el script `scripts/build_ml_dataset.py`** que:
   - Recorre todas las tablas de signals históricos
   - Para cada signal, extrae los features que estaban vigentes ese día desde
     `indicadortecnico` y `market_context_daily`
   - Calcula los retornos forward usando `valorhistoricoaccion`
   - Calcula los labels binarios
   - Inserta en `ml_signals` con `INSERT IGNORE` (idempotente)

2. **Migración inicial**: poblar con todo lo histórico que ya hay (~varios años
   de signals) en una sola corrida. Estimación: ~50k-200k rows si tenemos
   1-2 años de signals diarios sobre 500 stocks.

3. **Hook diario**: agregar al final del cron de `morning_alert.py` o como cron
   propio post-cierre, una llamada a `build_ml_dataset.py --incremental` que
   solo procesa los signals del día y los retornos disponibles (los retornos
   forward 5d se completan retrasados, 5 días después de la señal). Esto
   asegura que el dataset se mantiene fresco sin intervención.

4. **Sanity checks** (críticos):
   - ¿Cuántas filas tenemos por strategy_kind?
   - Distribución de labels: ¿`label_5d_pos` está balanceado o sesgado al 70/30?
   - ¿Hay NaNs en features clave?
   - ¿Hay duplicados de signal en el mismo día/símbolo/estrategia?
   - Plot básico de fwd_return_5d distribution para descartar outliers extremos

**Tiempo estimado**: 1-2 días de trabajo serio.

**Criterio de "fase 1 OK"**: tabla `ml_signals` con > 30k filas etiquetadas,
sanity checks pasando, hook diario corriendo.

---

### Fase 2 — Baseline tonto (gate de cordura)

**Por qué es crítico**: antes de entrenar **cualquier** modelo, hay que medir
cuánto rinden las señales si las tomás todas, sin filtro. Ese es tu baseline.
Si tu modelo ML después no le gana a este baseline, **el modelo no sirve**
y hay que tirarlo o rediseñar features.

Esto es el paso que más gente saltea, y es donde se cae el 90% de los proyectos
ML financieros — porque resulta que el baseline tonto ya era casi tan bueno como
el modelo elegante, y el modelo solo agregó complejidad.

**Entregables**:

1. **Notebook o script `analytics/ml_baseline.py`** que para cada `strategy_kind`
   en `ml_signals`, calcula:
   - **Win-rate base**: % de signals con `label_5d_pos = 1`
   - **Promedio de retorno**: media de `fwd_return_5d`
   - **Sharpe del baseline**: media / desvío de los retornos por trade
   - **Win-rate condicionado** por regime (alcista vs lateral vs bajista)
   - **Win-rate condicionado** por score quartile (top 25% vs bottom 25%)

2. **Tabla comparativa** que muestre, por strategy_kind:
   ```
   strategy           N      win_rate  avg_ret  sharpe  win_top25  win_bottom25
   wma_cross         3421     52.3%    +0.8%    0.41     58.2%      45.1%
   reversal          1872     48.7%    -0.2%    -0.08    51.0%      47.2%
   trend_pullback    2103     54.1%    +1.2%    0.62     61.5%      48.0%
   buy_confirmation   843     59.8%    +2.1%    0.85     67.0%      52.3%
   ```

3. **Conclusiones documentadas**:
   - ¿Cuáles strategies tienen edge real (Sharpe > 0.3) sin ningún ML?
   - ¿Cuáles tienen edge solo en cierto régimen?
   - ¿El score interno del strategy correlaciona con éxito? (esto es el "test
     barato": si el score top-25% rinde más que el bottom-25%, ese score ya es
     un signal útil sin necesidad de ML adicional)

**Tiempo estimado**: medio día.

**Criterio de "fase 2 OK"**: tabla baseline impresa, decisión informada de
qué strategies vale la pena modelar y cuáles directamente descartar.

**Decisión clave en este punto**: si TODAS las strategies dan baseline Sharpe < 0,
no tiene sentido pasar a Fase 3 — hay que volver a Fase 1 a mejorar features o
revisar las strategies en sí mismas. Es mejor descubrir esto ahora que después
de 2 semanas entrenando modelos.

---

### Fase 3 — Modelo simple como filtro

**Por qué empezar acá y no con redes neuronales**: con 30k-200k filas y ~20-50
features, gradient boosting (LightGBM o XGBoost) es la elección óptima. Más data
no necesita NN, las features son tabulares no secuenciales, y entrenar tarda
segundos en vez de horas.

**Entregables**:

1. **Script `ml/train_signal_classifier.py`** que:
   - Carga `ml_signals` filtrando por una `strategy_kind` específica (entrenamos
     un modelo por strategy, al menos al principio)
   - Define features (las columnas del `features_json` desempaquetadas)
   - Define target binario: `label_5d_strong` (retorno > 2% en 5d)
   - **CRÍTICO: walk-forward validation temporal**, NUNCA k-fold random:
     - Train: signals desde inicio hasta fecha T
     - Test: signals desde T hasta T+30 días
     - Sliding window: avanzo T cada 30 días
     - Esto es esencial. Random k-fold leakea futuro al pasado y te miente con
       AUC del 0.95 que en producción dan 0.51.
   - Entrena LightGBM con hiperparámetros conservadores (max_depth=5,
     num_leaves=15, learning_rate=0.05, n_estimators=200)
   - Reporta: AUC, log-loss, calibration plot, feature importance
   - Guarda el modelo en `models/{strategy_kind}_v1.pkl`

2. **Métricas mínimas para considerar el modelo "viable"**:
   - **AUC > 0.58** en validación temporal (walk-forward). Cualquier cosa por
     encima de 0.55 ya es valioso en finanzas; > 0.65 sería sospechoso de leakage.
   - **Calibration**: el modelo tiene que estar bien calibrado. Si dice "este
     signal tiene 70% de probabilidad de ganar", entonces de 100 señales con
     score 0.7, ~70 deberían terminar siendo positivas. Si no, el threshold no
     significa nada.
   - **Lift vs baseline**: cuando filtramos los top-30% del modelo, ¿la win-rate
     mejora vs tomar todas? Si no, el modelo no agrega nada.

3. **Integración como filtro en producción** (esto es la parte que da valor real):
   - Modificar `morning_alert.py` (o el batch correspondiente) para que, antes
     de mandar la notificación al Telegram, le pase los features al modelo
     entrenado y filtre las que tienen `model_score < threshold` (típicamente 0.6)
   - Cada signal filtrado y cada signal pasado se loggea en una nueva tabla
     `ml_filter_log` con: fecha, signal, model_score, decisión (pasa/filtra),
     **el outcome real cuando se conozca** (5 días después)
   - Esto permite trackear el modelo en producción y ver si el filtro está
     funcionando o se está degradando

**Tiempo estimado**: 1-2 semanas si nunca trabajamos con LightGBM antes; 3-5 días
si tenemos experiencia previa. La parte de validación temporal es la que más
toma, no el entrenamiento.

**Criterio de "fase 3 OK"**: al menos una strategy_kind tiene un modelo con
AUC > 0.58 OOS, está integrado como filtro en producción, y la primera semana
de logs muestra que el filtro reduce volumen de señales en > 40%.

---

### Fase 4 — Meta-learning y régimen-aware (opcional, mucho más adelante)

**Cuándo arrancar**: solo después de que Fase 3 esté funcionando hace al menos
1-2 meses con datos reales de producción y haya quedado claro qué está mejorando
y qué no. NO empezar antes — sin validación real, todo lo de Fase 4 es premature
optimization.

**Posibles direcciones (orden de menor a mayor complejidad)**:

1. **Régimen-aware**: en vez de entrenar un solo modelo por strategy, entrenar
   uno por (strategy × regime). Hipótesis: las features que importan en mercado
   alcista no son las mismas que en mercado lateral.

2. **Stacking**: combinar las predicciones de los modelos por strategy en un
   meta-modelo que decide cuál estrategia priorizar para una stock dada en un
   día dado. Es esencialmente el "router" que decide qué señal es más confiable.

3. **Ranking en vez de clasificación**: en vez de "este signal es bueno sí/no",
   pasar a "rankear todos los signals del día y quedarme con los top-K". Esto
   resuelve el problema de "tengo 50 signals hoy y solo puedo operar 5".

4. **Feature engineering pesado**: incorporar features alternativas como:
   - Earnings estimates / surprises
   - Insider buying
   - Short interest
   - Options flow
   - Sentimiento de noticias (ya hay `noticia_sentimiento` en la DB)

5. **Reinforcement learning** (riesgo alto): aprender directamente a optimizar
   PnL en vez de win-rate. Famosamente difícil de entrenar bien. NO recomendado
   hasta que todo lo anterior funcione.

6. **Patrones de microestructura**: si en algún momento capturamos data intraday
   o tick data, hay un mundo entero de features (orderbook imbalance, trade size
   distribution) que pueden dar edge real. Pero eso requiere infra distinta.

**Tiempo estimado**: indefinido, depende mucho de qué dirección se elija. Cada
una puede ser 2-4 semanas o un par de meses.

---

## 4. Lo que NO vamos a hacer (anti-patrones)

Esta sección es tan importante como el plan positivo. Son los caminos donde la
gente quema meses sin resultados:

### 4.1 NO usar deep learning / LSTMs / Transformers de entrada
- Marketing impecable, resultados patéticos en este tamaño de dataset.
- Con ~1M filas tabulares, gradient boosting le gana a NN consistentemente y
  entrena en segundos vs horas.
- LSTMs para predecir series temporales financieras es uno de los benchmarks
  más estudiados de los últimos 10 años. **Casi nunca le ganan a baselines
  simples** una vez que se controla por leakage.
- Si en Fase 4 hay un caso muy específico donde NN tenga sentido (ej. embeddings
  de noticias), se considera. Pero NO como punto de partida.

### 4.2 NO predecir precios absolutos (regresión)
- Convertir siempre a problemas de **clasificación binaria** sobre retornos
  (¿gana > X%?) o de **ranking relativo** entre stocks.
- Regresión sobre `close_t+5` te hace optimizar por MSE, que pondera mal los
  outliers en los extremos (que son justamente las oportunidades importantes).

### 4.3 NO usar K-fold random sobre series temporales
- Es el error #1 en ML financiero amateur.
- Random k-fold permite que el modelo "vea" data del futuro durante el train,
  lo que infla AUC de 0.55 a 0.95 en validación, y después en producción colapsa
  a 0.51.
- Walk-forward / time-series split, **siempre**.

### 4.4 NO automatizar la ejecución antes de validar OOS varios meses
- La mayoría de los modelos ML financieros se ven hermosos en backtest y pierden
  plata en producción por overfitting / data leakage / regime shift.
- Necesitamos ver el modelo correr "en vivo" varios meses con paper trading
  antes de confiarle un centavo real.
- Cualquier sistema de auto-trading antes de 6 meses de validación en producción
  es **temerario**. No importa qué tan bueno se vea el backtest.

### 4.5 NO apuntar a Sharpe altos en backtest
- Si tu backtest da Sharpe > 2, casi seguro tenés un bug de leakage.
- Sharpe realista en este nivel de sistema: **0.7 a 1.2** si las cosas salen bien.
- Sharpe > 1.5 en backtest significa "revisar el código de cerca", no "celebrar".

### 4.6 NO hacer feature engineering "creativo" sin validar
- Tentación común: "y si calculo el ratio entre RSI y volume_ratio elevado al cuadrado".
- Cada feature nueva agrega riesgo de overfitting.
- Regla: agregar 1 feature por iteración, validar que mejora AUC OOS, dejarla
  o tirarla. NO agregar 30 features juntas.

### 4.7 NO ignorar costos de transacción y slippage
- Un modelo que en backtest da +5% anual puede ser -2% en producción si no
  contás los 0.05% por trade × 200 trades al año.
- Siempre incluir comisión, spread y slippage estimados en el backtest desde
  el día 1.

---

## 5. Métricas de éxito por fase

Para no engañarnos a nosotros mismos, criterios claros de "esto está OK / esto no":

| Fase | Métrica | Threshold de éxito |
|---|---|---|
| 1 | Filas en `ml_signals` | > 30,000 con todos los targets calculados |
| 1 | NaN ratio en features | < 5% por feature |
| 1 | Duplicados | 0 (UNIQUE KEY funcionando) |
| 2 | Strategies con baseline Sharpe > 0.3 | al menos 2 |
| 2 | Lift score top25% vs bottom25% | > 5pp de diferencia en win-rate |
| 3 | AUC walk-forward | > 0.58 (mínimo); > 0.62 (bueno) |
| 3 | Calibración (Brier score) | < 0.24 |
| 3 | Reducción de volumen de señales en producción | > 40% |
| 3 | Mejora de win-rate en señales que pasan filtro | +5pp absolutos vs sin filtro |
| 4 | (depende de dirección elegida) | (TBD según la fase) |

**Reglas de oro**:
- Si Fase 1 no llega a su threshold, **no avanzar a Fase 2**.
- Si Fase 2 muestra que ninguna strategy tiene edge baseline, **volver a Fase 1**
  y revisar features o las strategies en sí mismas.
- Si Fase 3 no llega a AUC 0.58 después de 2-3 iteraciones de feature engineering,
  **considerar que no hay edge en esa estrategia con los features actuales** y
  pasar a otra strategy o agregar features alternativas (Fase 4).

---

## 6. Riesgos y trampas conocidas

Lista de cosas que sabemos que pueden complicarnos, para tenerlas en mente:

1. **Data leakage temporal**: el más común. Cualquier feature que use información
   del futuro durante el train te miente. Mitigación: validación walk-forward
   estricta y revisión manual de features.

2. **Survivorship bias**: si el dataset solo incluye stocks que sobrevivieron
   (no incluye delistadas), los retornos se inflan artificialmente. Verificar
   con el data loader si se mantienen históricos de stocks delistadas.

3. **Look-ahead bias en features**: ej. usar el SMA200 calculado con la fecha
   del cierre del día actual cuando la señal en realidad se dispara con datos
   del cierre del día anterior. Pequeño pero importante.

4. **Regime shift**: el modelo aprendido en mercado alcista 2023-2025 puede
   degradarse en mercado bajista 2026. Mitigación: features de régimen explícitas
   + monitoreo constante de performance OOS.

5. **Overfitting a un set de hiperparámetros**: si probamos 100 combinaciones de
   hyperparams y elegimos la mejor por AUC OOS, estamos sobreajustando al set
   de validación. Mitigación: holdout final (último 20% de datos en el tiempo)
   que NO se toca hasta el final, y se reporta solo una vez.

6. **Costos de transacción ignorados**: ya cubierto en 4.7. Crítico.

7. **Falsa precisión por outliers**: una sola señal con +200% de retorno puede
   inflar la media y engañarnos. Reportar siempre **mediana** y **percentiles**
   junto con la media.

8. **Bug en el cálculo de retornos forward**: si calculamos `fwd_return_5d`
   sumando 5 días de calendario en vez de 5 días hábiles, los resultados son
   inconsistentes. Atención al cálculo.

9. **Concept drift en strategies**: si cambiamos el algoritmo de `wma_cross`
   (ej. cambiamos de WMA(6,30) a WMA(8,32)), el dataset etiquetado con la
   versión vieja se vuelve inválido. Necesitamos versionar las strategies.
   Sugerencia: agregar columna `strategy_version` en `ml_signals`.

10. **El "gran problema oculto"**: la mayoría del tiempo en ML real se va en
    debugear el dataset, no en entrenar modelos. Estimar 70% del tiempo en
    plumbing/data y 30% en modeling. Si alguien promete lo opuesto, está
    vendiendo humo.

---

## 7. Próximo paso concreto cuando arranquemos

Cuando quieras empezar (días/semanas adelante), el primer paso accionable es:

**Tarea**: Crear `scripts/build_ml_dataset.py` y la tabla `ml_signals` en MySQL.

**Sub-tareas en orden**:

1. Inventario rápido: contar cuántos signals históricos tenemos en cada tabla
   relevante (`reversal_signals`, `trend_pullback_signals`, `wma_cross` outputs,
   `buy_confirmation`, `support_zones`, etc.). Esto nos dice si el dataset
   inicial va a tener 5k filas (poco para entrenar) o 100k (sobrado).

2. Decidir el set inicial de features. Propuesta mínima:
   - Técnicos del día: SMA50, SMA200, RSI14, ATR14_rel, dist_sma200_pct
   - Momentum: momentum_5d, momentum_20d
   - Volumen: volume_ratio_5d, volume_ratio_20d
   - Mercado: market_regime, vix_level, vix_percentile_1y, spy_return_5d, spy_return_20d
   - Sector: sector_regime
   - Stock-specific: precio, días desde último high/low

3. Crear migration idempotente para `ml_signals` (similar al patrón que ya usamos
   en `_ensure_batch_tables` en `api.py`).

4. Implementar `build_ml_dataset.py` con flag `--full` (rebuilds desde cero) y
   `--incremental` (solo el día actual).

5. Correr el `--full` por primera vez. Inspeccionar resultados manualmente.
   Validar sanity checks (sección 1 de Fase 1).

6. Agregar al cron: `00 23 * * 1-5` (post-cierre y post-backfill) ejecutar
   `build_ml_dataset.py --incremental`.

7. Reportar al usuario cuántas filas terminamos teniendo y qué dudas/observaciones
   surgieron del análisis del dataset inicial. Decidir juntos si pasar a Fase 2.

**Tiempo estimado**: 1-2 días de trabajo (una sentada larga o dos cortas).

---

## 8. Notas, dudas y decisiones pendientes

Espacio para anotar cosas que vayamos descubriendo o que debamos discutir antes
de empezar. Esto es lo que el documento se va a ir llenando con el tiempo.

- [ ] ¿Tenemos data de stocks delistadas en `valorhistoricoaccion`? (importante
      para survivorship bias). **Verificar antes de Fase 1**.
- [ ] ¿Cuál es el horizonte de holding objetivo realista? El plan asume 5 días
      pero podría ser 10 o 20 según el estilo de operativa que querés.
- [ ] ¿Querés que los modelos generen sus propias señales o solo filtren las
      existentes? El plan asume "filtro", pero "generador" es otra dirección
      válida (más arriesgada).
- [ ] ¿Costos de transacción en Argentina vs USA? Si operás vía CEDEARs, los
      costos son distintos a operar el ADR directo en NYSE. Esto afecta el
      threshold de "ganador" en el label.
- [ ] ¿Posición sizing entra en el scope? Si sí, agregar Fase 4.5 dedicada a
      Kelly criterion / vol targeting.
- [ ] ¿Qué hacemos con las señales correlacionadas? Si el modelo dice "comprá
      AAPL, MSFT, GOOGL, NVDA" todas el mismo día y los 4 son tech, en realidad
      es 1 sola apuesta concentrada. Esto es problema de Fase 4 pero hay que
      tenerlo presente.
- [ ] **Tu intuición de operador**: ¿qué patrones ves que se repiten en las
      señales que SÍ funcionan vs las que no? Esa intuición humana suele ser
      el mejor punto de partida para diseñar features que un modelo solo no
      descubriría. Anotalo cuando lo veas.

---

## Apéndice A — Stack técnico propuesto

Para no improvisar después:

| Capa | Tool | Justificación |
|---|---|---|
| Storage | MySQL (ya está) | El dataset no es tan grande como para necesitar Parquet. SQL ya está integrado al resto del sistema. |
| Feature engineering | pandas + numpy | Standard. Ya están en el venv. |
| Modeling | LightGBM | Mejor ratio velocidad/calidad para datasets tabulares de este tamaño. Más rápido que XGBoost en CPU. |
| Validación | sklearn `TimeSeriesSplit` | Built-in walk-forward, sin reinventar la rueda. |
| Tracking de experimentos | MLflow local (opcional) o simple CSV | Empezar simple, escalar si hace falta. |
| Persistencia de modelos | `joblib.dump` a `models/` en el filesystem | Compatible con LightGBM y sklearn. |
| Inference en producción | Cargar el .pkl al import del batch que lo necesite | Sin servir un microservicio ML separado al principio. |

**Dependencies a agregar a requirements.txt cuando arranquemos**:
- `lightgbm`
- `scikit-learn` (probablemente ya está)
- `joblib` (probablemente ya está como dep transitiva)

---

## Apéndice B — Referencias / inspiración

Cosas que vale la pena leer antes de empezar (no urgente, pero útil):

- **"Advances in Financial Machine Learning"** de Marcos López de Prado.
  El libro de cabecera del ML financiero serio. Capítulos 4 (labeling),
  5 (sample weights), 7 (cross-validation) son los más relevantes para
  Fase 1-3. Capítulo 1 directamente justifica todo el framing de "ranking
  en vez de predicción". **Si leés solo una cosa, leé este libro.**

- **"Machine Learning for Algorithmic Trading"** de Stefan Jansen.
  Más práctico, menos teórico. Buenos ejemplos de pipelines completos
  con LightGBM y validación walk-forward.

- **Quantopian Lectures** (gratis, en Github archived). Curso completo
  de quant trading que incluye varios módulos de ML aplicado a equity.

- **Papers de Marcos López de Prado en SSRN**, especialmente "The 7 Reasons
  Most Machine Learning Funds Fail" — exactamente los anti-patrones que
  pusimos en Sección 4.

---

## Changelog del documento

| Fecha | Cambio |
|---|---|
| 2026-04-08 | Versión inicial. Borrador para discutir antes de empezar a codear. |
