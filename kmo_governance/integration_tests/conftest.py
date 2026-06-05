"""Cross-Module Integration-Test conftest [CRUX-MK]."""
import sys
from pathlib import Path

# Add all module roots to path
ROOT = Path(__file__).parent.parent
for mod_dir in [
    "tenant_lifecycle",
    "multi_tenant_approval",
    "compliance_backbone",
    "cross_tenant_filter",
    "hot_switch_adapter",
]:
    sys.path.insert(0, str(ROOT / mod_dir))
