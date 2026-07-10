# [CRUX-MK]
"""kpm_backtest: Daten-Ingestion + Backtest-Grundlage fuer KPM Variante-D (W70-CROWN AP-K2).

K_0-DISCLAIMER: Dieses Paket liefert ausschliesslich historische Marktdaten und
deren Qualitaets-/Kreuzvalidierung. Es trifft KEINE Anlageentscheidung, enthaelt
KEINEN Broker-Zugang und fuehrt KEINE Order aus.
"""

from .data_loader import (
    CrossValidationReport,
    PriceBar,
    QualityReport,
    cross_validate,
    load_dax,
    quality_check,
)

__all__ = [
    "PriceBar",
    "QualityReport",
    "CrossValidationReport",
    "load_dax",
    "quality_check",
    "cross_validate",
]
