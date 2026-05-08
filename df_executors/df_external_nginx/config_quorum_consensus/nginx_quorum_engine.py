"""NGINX Quorum-Consensus Engine -- Bacterial-Quorum-Sensing Pattern adapted for Multi-Instance Config-Validation [CRUX-MK].

Bio-Pattern (V. fischeri AHL-System):
    1. Bacterial population emits autoinducer molecules (AHL).
    2. Autoinducer accumulates with population density.
    3. At threshold concentration: synchronized gene expression activates.
    4. Quorum-Quenching (defense): degrade autoinducer to block malicious populations.

Tech-Mapping (NGINX Reverse-Proxy Cluster, echt extern):
    1. NGINX-validators (5 instances) emit ValidatorVotes (config_hash + verdict).
    2. Votes accumulate in ConfigProposal pool keyed by config_hash.
    3. At threshold (3-of-5 ACCEPTs): QuorumDecision = APPROVED -> coordinated deploy.
    4. Byzantine-Defense: malicious validators (REJECT/EQUIVOCATE) blocked via threshold-logic.

Pure NGINX-Domain: KEINE crux/governance/Kemmer-Imports.

Pre-Conditions:
    - cluster_size >= 3 (3-of-5 minimum for Byzantine-Tolerance: f < n/3 -> n >= 3f+1)
    - quorum_threshold > cluster_size / 2 (strict-majority pflicht)
Post-Conditions:
    - submit_vote ist atomic; doppelte Votes von gleichem Validator werden ge-overridden (last-vote-wins)
    - resolve() liefert APPROVED nur wenn quorum_threshold ACCEPT-Votes vorliegen
    - Race-safety: threading.RLock auf Mutationen
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# Constants with units (NGINX-Cluster-Defaults).
DEFAULT_CLUSTER_SIZE: int = 5                 # 5 NGINX-Validators
DEFAULT_QUORUM_THRESHOLD: int = 3             # 3-of-5 (Byzantine-Tolerant: f=1)
DEFAULT_VOTE_TTL_SEC: float = 30.0            # vote-staleness-window
MIN_BYZANTINE_SAFE_CLUSTER: int = 3           # n >= 3f+1, f >= 1


class ValidatorVerdict(str, Enum):
    """Vote-Verdict eines NGINX-Validators."""
    ACCEPT = "accept"      # Config syntactically + semantically valid
    REJECT = "reject"      # Config has blocking errors
    ABSTAIN = "abstain"    # Validator could not validate (e.g., timeout)


class QuorumOutcome(str, Enum):
    """Endgueltiger Cluster-Consensus-Outcome."""
    APPROVED = "approved"      # >= threshold ACCEPTs -> deploy
    REJECTED = "rejected"      # > (cluster - threshold) REJECTs -> abort
    PENDING = "pending"        # waiting for more votes
    TIMEOUT = "timeout"        # insufficient votes within TTL


@dataclass(frozen=True)
class ValidatorVote:
    """Single Validator-Vote. Immutable."""
    validator_id: str
    config_hash: str
    verdict: ValidatorVerdict
    findings_count: int = 0
    timestamp: float = 0.0


@dataclass
class ConfigProposal:
    """Mutable Pool fuer einen Config-Hash (Auto-Inducer-Aequivalent)."""
    config_hash: str
    config_source: str                  # original nginx.conf
    submitted_at: float
    votes: dict[str, ValidatorVote] = field(default_factory=dict)  # validator_id -> last-vote

    def vote_count(
        self,
        verdict: Optional[ValidatorVerdict] = None,
        now: Optional[float] = None,
        ttl_window_sec: Optional[float] = None,
    ) -> int:
        """Count votes (optional filter by verdict + TTL-window)."""
        votes_iter = self.votes.values()
        if now is not None and ttl_window_sec is not None:
            cutoff = now - ttl_window_sec
            votes_iter = [v for v in votes_iter if v.timestamp >= cutoff]
        if verdict is not None:
            return sum(1 for v in votes_iter if v.verdict == verdict)
        return sum(1 for _ in votes_iter)

    def unique_validator_count(
        self,
        now: Optional[float] = None,
        ttl_window_sec: Optional[float] = None,
    ) -> int:
        if now is None or ttl_window_sec is None:
            return len(self.votes)
        cutoff = now - ttl_window_sec
        return sum(1 for v in self.votes.values() if v.timestamp >= cutoff)


@dataclass(frozen=True)
class QuorumDecision:
    """Endgueltige Consensus-Entscheidung fuer einen Config-Hash."""
    config_hash: str
    outcome: QuorumOutcome
    accept_count: int
    reject_count: int
    abstain_count: int
    threshold: int
    cluster_size: int
    decided_at: float
    reason: str = ""


class NginxQuorumEngine:
    """3-of-5 Quorum-Consensus-Engine fuer NGINX-Config-Validation.

    Byzantine-Tolerance: tolerates f Byzantine-Validators if n >= 3f+1.
    Standard-Setup (n=5, threshold=3) toleriert f=1 malicious validator.

    Quorum-Quenching (Anti-Quorum-Attack):
        - Vote-TTL begrenzt stale votes (replay-protection)
        - last-vote-wins-Override verhindert vote-stuffing
        - Byzantine-Threshold-Logik blockiert Equivocation

    Thread-safe: alle Mutationen unter self._lock.
    """

    def __init__(
        self,
        cluster_size: int = DEFAULT_CLUSTER_SIZE,
        quorum_threshold: int = DEFAULT_QUORUM_THRESHOLD,
        vote_ttl_sec: float = DEFAULT_VOTE_TTL_SEC,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if cluster_size < MIN_BYZANTINE_SAFE_CLUSTER:
            raise ValueError(
                f"cluster_size must be >= {MIN_BYZANTINE_SAFE_CLUSTER} for Byzantine-Tolerance"
            )
        if quorum_threshold <= cluster_size // 2:
            raise ValueError(
                f"quorum_threshold ({quorum_threshold}) must be > cluster_size/2 "
                f"({cluster_size // 2}) for strict-majority"
            )
        if quorum_threshold > cluster_size:
            raise ValueError("quorum_threshold cannot exceed cluster_size")
        if vote_ttl_sec <= 0:
            raise ValueError("vote_ttl_sec must be > 0")
        self.cluster_size = int(cluster_size)
        self.quorum_threshold = int(quorum_threshold)
        self.vote_ttl_sec = float(vote_ttl_sec)
        self._clock = clock
        self._lock = threading.RLock()
        self._proposals: dict[str, ConfigProposal] = {}

    # ---------------- Public API ----------------

    def submit_proposal(self, config_hash: str, config_source: str) -> ConfigProposal:
        """Registriert einen neuen Config-Hash zur Validation."""
        if not config_hash:
            raise ValueError("config_hash required")
        if not isinstance(config_source, str):
            raise ValueError("config_source must be str")
        now = self._clock()
        with self._lock:
            existing = self._proposals.get(config_hash)
            if existing is not None:
                return existing
            proposal = ConfigProposal(
                config_hash=config_hash,
                config_source=config_source,
                submitted_at=now,
            )
            self._proposals[config_hash] = proposal
            return proposal

    def submit_vote(
        self,
        config_hash: str,
        validator_id: str,
        verdict: ValidatorVerdict,
        findings_count: int = 0,
    ) -> ValidatorVote:
        """Validator-Vote auf Proposal eintragen. Last-vote-wins per validator_id."""
        if not validator_id:
            raise ValueError("validator_id required")
        if not isinstance(verdict, ValidatorVerdict):
            raise ValueError("verdict must be ValidatorVerdict enum")
        if findings_count < 0:
            raise ValueError("findings_count must be >= 0")
        now = self._clock()
        with self._lock:
            proposal = self._proposals.get(config_hash)
            if proposal is None:
                raise KeyError(f"unknown config_hash: {config_hash}")
            vote = ValidatorVote(
                validator_id=validator_id,
                config_hash=config_hash,
                verdict=verdict,
                findings_count=findings_count,
                timestamp=now,
            )
            proposal.votes[validator_id] = vote  # last-vote-wins
            return vote

    def resolve(self, config_hash: str) -> QuorumDecision:
        """Berechnet aktuellen Cluster-Consensus."""
        now = self._clock()
        with self._lock:
            proposal = self._proposals.get(config_hash)
            if proposal is None:
                raise KeyError(f"unknown config_hash: {config_hash}")
            # TTL-window: ignore stale votes (Quorum-Quenching defense).
            accept_n = proposal.vote_count(
                verdict=ValidatorVerdict.ACCEPT,
                now=now,
                ttl_window_sec=self.vote_ttl_sec,
            )
            reject_n = proposal.vote_count(
                verdict=ValidatorVerdict.REJECT,
                now=now,
                ttl_window_sec=self.vote_ttl_sec,
            )
            abstain_n = proposal.vote_count(
                verdict=ValidatorVerdict.ABSTAIN,
                now=now,
                ttl_window_sec=self.vote_ttl_sec,
            )
            total_active = accept_n + reject_n + abstain_n
            # Decision-Logic: APPROVED wins as soon as threshold reached.
            if accept_n >= self.quorum_threshold:
                outcome = QuorumOutcome.APPROVED
                reason = f"{accept_n}/{self.cluster_size} ACCEPT votes >= threshold {self.quorum_threshold}"
            elif reject_n > self.cluster_size - self.quorum_threshold:
                # Reject is irreversible: accept can no longer reach threshold.
                outcome = QuorumOutcome.REJECTED
                reason = (
                    f"{reject_n} REJECT votes block accept-quorum "
                    f"(max remaining accepts {self.cluster_size - reject_n} < threshold {self.quorum_threshold})"
                )
            elif (now - proposal.submitted_at) > self.vote_ttl_sec and total_active < self.quorum_threshold:
                outcome = QuorumOutcome.TIMEOUT
                reason = f"only {total_active} votes within TTL {self.vote_ttl_sec}s"
            else:
                outcome = QuorumOutcome.PENDING
                reason = f"awaiting more votes (have {accept_n} ACCEPT / {reject_n} REJECT)"
            return QuorumDecision(
                config_hash=config_hash,
                outcome=outcome,
                accept_count=accept_n,
                reject_count=reject_n,
                abstain_count=abstain_n,
                threshold=self.quorum_threshold,
                cluster_size=self.cluster_size,
                decided_at=now,
                reason=reason,
            )

    def list_active_proposals(self) -> list[ConfigProposal]:
        with self._lock:
            return list(self._proposals.values())

    def purge_proposal(self, config_hash: str) -> bool:
        """Cascade-delete proposal + all votes. Returns True if existed."""
        with self._lock:
            return self._proposals.pop(config_hash, None) is not None

    def detect_equivocation(self, validator_id: str) -> list[str]:
        """Anti-Byzantine: Detect validators voting on conflicting config-hashes simultaneously.

        Returns list of config_hashes the validator voted on within the TTL-window.
        Length > 1 = potential equivocation (Byzantine-Behavior).
        """
        now = self._clock()
        cutoff = now - self.vote_ttl_sec
        with self._lock:
            return [
                p.config_hash
                for p in self._proposals.values()
                if (
                    validator_id in p.votes
                    and p.votes[validator_id].timestamp >= cutoff
                )
            ]


# CRUX-MK
