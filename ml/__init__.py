"""
ml/ — Track A: ML signal filter para trading-assist.

Objetivo: filtrar/rankear las señales que YA generan las estrategias actuales
para reducir ruido en el feed. NO predicción de precios. NO va a producción
todavía — convive en paralelo con el stack existente.

Roadmap canónico: PLAN_ML.md (4 fases). Este módulo cubre Fase 1 (dataset) y
los baselines de Fase 2 (logreg + lightgbm).
"""
