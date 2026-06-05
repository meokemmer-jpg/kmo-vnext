import sys
from pathlib import Path

# Add module root to path so 'src' imports work
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
