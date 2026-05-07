"""Shared pytest config: ensure parent dir is on sys.path so we can import kmo_lease_manager."""
import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
