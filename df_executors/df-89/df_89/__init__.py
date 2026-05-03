"""CRUX-MK package exports for DF-89 Research-Gate-Inquirer."""

from .config import DFConfig as Config
from .engine import MAPEKEngine as Engine
from .knowledge import KnowledgeStore

__version__ = "0.1.0-skeleton"

__all__ = ["Config", "KnowledgeStore", "Engine", "__version__"]
