"""Familien-Audit-Bus (Lymphatic-Pattern) [CRUX-MK]

Verteilte Familien-Decision-Filterung + persistente Audit-Trail-Sammlung
fuer Cape-Coral-Vault. Bio-Pattern-Vorbild: kmo_governance/outbox-pattern.

Welle-30 W-30-1 External-Generalisation (Hotel/Trading -> Familien-Verwaltung).
"""
import sys
from pathlib import Path

# Erlaubt Module-Resolution wenn package-import (familien_audit_bus.X)
# UND wenn direkter sys.path-Add (X) - kompatibel zu outbox-pattern-Stil
_pkg_dir = Path(__file__).resolve().parent
if str(_pkg_dir) not in sys.path:
    sys.path.insert(0, str(_pkg_dir))

from familien_audit_bus import FamilienAuditBus, FamilienDecisionEnvelope  # noqa: E402
from familien_decision_filter import (  # noqa: E402
    FamilienDecisionFilter,
    FilterDecision,
    ACTION_APPROVE,
    ACTION_VETO,
    ACTION_INFO_ACKNOWLEDGED,
    ACTION_ABSTAIN,
)
from familien_audit_persister import FamilienAuditPersister  # noqa: E402

__all__ = [
    "FamilienAuditBus",
    "FamilienDecisionEnvelope",
    "FamilienDecisionFilter",
    "FilterDecision",
    "FamilienAuditPersister",
    "ACTION_APPROVE",
    "ACTION_VETO",
    "ACTION_INFO_ACKNOWLEDGED",
    "ACTION_ABSTAIN",
]
