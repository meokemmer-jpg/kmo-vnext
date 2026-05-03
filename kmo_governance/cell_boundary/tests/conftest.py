"""Shared pytest config: ensure kmo/ is on sys.path so we can import
`kmo_governance.cell_boundary` as a fully-qualified package."""

import sys
from pathlib import Path

# tests/ -> cell_boundary/ -> kmo_governance/ -> kmo/
_KMO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))
