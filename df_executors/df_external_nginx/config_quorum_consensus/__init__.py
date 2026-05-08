"""NGINX Config Quorum-Consensus -- Bacterial-Quorum-Sensing Pattern fuer Multi-Instance Config-Validation [CRUX-MK].

Domain-Mapping (Bio -> Tech, echt extern):
- Bacterial-Population        -> NGINX-Instanz-Cluster (5 Worker-Nodes)
- Autoinducer-Molecule (AHL)  -> Config-Hash (SHA256 ueber normalisierte nginx.conf)
- Quorum-Threshold            -> 3-of-5 Validation-Pass (Byzantine-tolerant)
- Group-Behavior-Activation   -> Coordinated Config-Deploy (atomic across cluster)
- Quorum-Quenching            -> Byzantine-Defense gegen Malicious-Validators

Externer Domain: NGINX Reverse-Proxy (https://nginx.org/en/docs/).
Config-Format: nginx.conf-Syntax mit `http`, `server`, `location` Bloecken.

Welle-30-Iter-2 echt-extern Anti-Cargo-Cult-Validation:
- KEINE crux/governance Imports
- KEINE Kemmer-spezifischen Konstanten
- Pure NGINX-Config-Domain mit Bio-Pattern-Reuse aus kmo_governance.quorum_sensing

K11 Cascade-Containment: Quorum-Failure auf Config-Hash-Ebene isoliert (kein Cluster-Wide-Crash).
K13 Pre-Action-Verification: 3-of-5 Threshold verhindert Single-Node-Bypass.
"""

from .nginx_config_validator import (
    ConfigParseError,
    NginxConfigValidator,
    NginxConfigBlock,
    ValidationFinding,
)
from .nginx_quorum_engine import (
    ConfigProposal,
    NginxQuorumEngine,
    QuorumDecision,
    ValidatorVote,
)
from .nginx_config_distributor import (
    DistributionResult,
    NginxConfigDistributor,
    RollbackReason,
)

__all__ = [
    "ConfigParseError",
    "NginxConfigValidator",
    "NginxConfigBlock",
    "ValidationFinding",
    "ConfigProposal",
    "NginxQuorumEngine",
    "QuorumDecision",
    "ValidatorVote",
    "DistributionResult",
    "NginxConfigDistributor",
    "RollbackReason",
]

# CRUX-MK
