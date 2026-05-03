"""Shared pytest config: kmo/ + saga-pattern/ on sys.path."""

import sys
from pathlib import Path

_KMO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))
_SAGA_DIR = _KMO_ROOT / "kmo_governance" / "saga-pattern"
if str(_SAGA_DIR) not in sys.path:
    sys.path.insert(0, str(_SAGA_DIR))
