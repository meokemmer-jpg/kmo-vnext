"""Shared pytest config: kmo/ on sys.path for `kmo_governance.stigmergic_blackboard` imports."""

import sys
from pathlib import Path

_KMO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))
