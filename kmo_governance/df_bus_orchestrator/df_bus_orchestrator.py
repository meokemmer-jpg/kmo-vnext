"""KMO DF-Bus-Orchestrator [CRUX-MK].

Welle-10 Phase-6.4 Modul: Cross-DF-Coordination-Layer fuer Inter-Dark-Factory-Messaging.

Bio-Pattern (Hormonsystem-Aequivalent):
    - Hormone als Cross-Organ-Signal mit TTL + Diffusion -> DFMessage mit ttl_s + provenance_hash
    - Drueseny als Capability-spezifische Quellen -> DFRoutingTable.find_by_capability
    - Receptor-Sites als targeted-Subscriptions -> DFMessageBus.subscribe(df_id, callback)
    - Negative Feedback ueber Anti-Hormone -> DFCircuitBreakerPool (Schutz vor Cascade)
    - Quorum-Sensing fuer Consensus-Decisions -> DFConsensusVoter (Hill-Schwelle als Threshold)

Anorg-Mapping: A-22 Multi-Channel-Bus + A-31 Capability-Routing + A-09 Quorum-Consensus.

Komponenten:
    - DFMessage: frozen dataclass mit provenance_hash + TTL
    - DFMessageBus: pub/sub mit ttl-aware get_pending + prune_expired
    - DFRoutingTable: Capability-Registry mit Heartbeat-Liveness
    - DFCircuitBreakerPool: Per-DF-Isolation (reuse ApaleoCircuitBreaker)
    - DFOrchestrator: top-level dispatch + broadcast + health-summary
    - DFConsensusVoter: Threshold-basierte Multi-DF-Voting

Pre/Post Invarianten:
    - Alle Klassen thread-safe via threading.RLock
    - DFMessage frozen (immutable)
    - DFRoutingTable.is_alive prueft Heartbeat-Aktualitaet (default 60s timeout)
    - DFConsensusVoter.is_consensus_reached: True wenn yes-votes >= threshold,
      False wenn no-votes > 1-threshold, None solange unentschieden bzw. Timeout-Fall
"""

from __future__ import annotations

import enum
import hashlib
import secrets
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kmo_governance.apaleo_adapter.apaleo_adapter import ApaleoCircuitBreaker

# ---------------- Constants ----------------

DEFAULT_TTL_S: float = 300.0  # 5 minutes default TTL
DEFAULT_HEARTBEAT_TIMEOUT_S: float = 60.0  # alive if last heartbeat <= 60s
DEFAULT_VOTE_TIMEOUT_S: float = 30.0  # consensus timeout
DEFAULT_VOTE_THRESHOLD: float = 0.5  # majority vote


# ---------------- Message-Type Enum ----------------


class DFMessageType(str, enum.Enum):
    """Standardisierte Message-Typen fuer Cross-DF-Communication."""

    HEARTBEAT = "heartbeat"
    DISPATCH = "dispatch"
    BROADCAST = "broadcast"
    VOTE_REQUEST = "vote_request"
    VOTE_RESPONSE = "vote_response"
    HEALTH_REPORT = "health_report"
    CASCADE_ALERT = "cascade_alert"
    CUSTOM = "custom"


# ---------------- Frozen Dataclasses ----------------


@dataclass(frozen=True)
class DFMessage:
    """Immutable Cross-DF-Message mit Provenance + TTL.

    Pre:
        - df_id non-empty string (Sender-DF-ID)
        - msg_type instance of DFMessageType
        - ttl_s > 0
    Post:
        - timestamp set on creation (cannot be changed)
        - provenance_hash deterministisch ueber (df_id, msg_type, payload, timestamp)
    """

    df_id: str
    msg_type: DFMessageType
    payload: dict
    ttl_s: float
    timestamp: float
    provenance_hash: str

    def is_expired(self, now: Optional[float] = None) -> bool:
        """True wenn (now - timestamp) > ttl_s."""
        t = now if now is not None else time.time()
        return (t - self.timestamp) > self.ttl_s


@dataclass(frozen=True)
class DFVoteRecord:
    """Immutable Vote-Record fuer Consensus-Tracking."""

    proposal_id: str
    df_id: str
    vote: bool
    timestamp: float


# ---------------- Helper ----------------


def _make_provenance_hash(
    df_id: str, msg_type: DFMessageType, payload: dict, timestamp: float
) -> str:
    """Deterministischer SHA256-Hash ueber Message-Kern-Felder.

    Pre: df_id non-empty, payload dict, timestamp float.
    Post: 64-char hex string.
    """
    # Stable repr: sorted-keys for dict
    payload_repr = repr(sorted(payload.items()))
    blob = f"{df_id}|{msg_type.value}|{payload_repr}|{timestamp:.6f}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def make_df_message(
    df_id: str,
    msg_type: DFMessageType,
    payload: dict,
    ttl_s: float = DEFAULT_TTL_S,
    clock: Callable[[], float] = time.time,
) -> DFMessage:
    """Factory fuer DFMessage mit auto-generierter Provenance + Timestamp.

    Pre:
        - df_id non-empty
        - ttl_s > 0
        - payload dict
    Post:
        - DFMessage mit deterministischem provenance_hash
    """
    if not df_id:
        raise ValueError("df_id required")
    if not isinstance(msg_type, DFMessageType):
        raise TypeError("msg_type must be DFMessageType")
    if ttl_s <= 0:
        raise ValueError("ttl_s must be > 0")
    if not isinstance(payload, dict):
        raise TypeError("payload must be dict")
    ts = clock()
    return DFMessage(
        df_id=df_id,
        msg_type=msg_type,
        payload=dict(payload),  # defensive copy
        ttl_s=float(ttl_s),
        timestamp=float(ts),
        provenance_hash=_make_provenance_hash(df_id, msg_type, payload, ts),
    )


# ---------------- DFMessageBus ----------------


class DFMessageBus:
    """Pub/Sub Message-Bus mit TTL-aware Pending-Queues.

    Pre: alle Subscriptions per df_id (recipient).
    Post:
        - publish(msg) returns True
        - subscribe(df_id, callback) returns subscription_id (str)
        - get_pending(df_id) returns alle nicht-expired Messages an df_id
        - prune_expired() removes expired Messages, returns Anzahl-removed
        - thread-safe via RLock
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        # df_id -> [DFMessage]
        self._pending: dict[str, list[DFMessage]] = defaultdict(list)
        # subscription_id -> (df_id, callback)
        self._subscriptions: dict[str, tuple[str, Callable[[DFMessage], None]]] = {}
        # df_id -> set[subscription_id]
        self._subs_by_df: dict[str, set[str]] = defaultdict(set)

    def publish(self, message: DFMessage, target_df_id: Optional[str] = None) -> bool:
        """Publish Message in target queue (oder broadcast wenn target_df_id None).

        Pre: message DFMessage (not expired empfohlen).
        Post:
            - If target_df_id: enqueue + invoke callbacks fuer subscribers von target_df_id
            - If target_df_id None: enqueue zu allen subscribers (Broadcast)
            - returns True bei erfolgreicher Publikation
        """
        if not isinstance(message, DFMessage):
            raise TypeError("message must be DFMessage")
        with self._lock:
            if target_df_id is None:
                # Broadcast: alle Subscriber-DF-IDs
                target_dfs = list(self._subs_by_df.keys())
            else:
                target_dfs = [target_df_id]

            for df_id in target_dfs:
                self._pending[df_id].append(message)
                # Invoke alle Callbacks fuer diesen df_id
                for sub_id in list(self._subs_by_df.get(df_id, ())):
                    sub = self._subscriptions.get(sub_id)
                    if sub is None:
                        continue
                    _, callback = sub
                    try:
                        callback(message)
                    except Exception:
                        # Isoliere Callback-Exceptions (Bus muss weiterleben)
                        pass
        return True

    def subscribe(
        self, df_id: str, callback: Callable[[DFMessage], None]
    ) -> str:
        """Register callback fuer Messages an df_id. Returns subscription_id.

        Pre: df_id non-empty, callback callable.
        Post: subscription_id (str, 32-hex) registriert.
        """
        if not df_id:
            raise ValueError("df_id required")
        if not callable(callback):
            raise TypeError("callback must be callable")
        sub_id = secrets.token_hex(16)
        with self._lock:
            self._subscriptions[sub_id] = (df_id, callback)
            self._subs_by_df[df_id].add(sub_id)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove subscription. Returns True wenn entfernt, False wenn unbekannt."""
        with self._lock:
            sub = self._subscriptions.pop(subscription_id, None)
            if sub is None:
                return False
            df_id, _ = sub
            self._subs_by_df.get(df_id, set()).discard(subscription_id)
            return True

    def get_pending(self, df_id: str) -> list[DFMessage]:
        """Return non-expired Messages fuer df_id (without consuming them).

        Pre: df_id non-empty.
        Post: list[DFMessage] mit !is_expired(now).
        """
        now = self._clock()
        with self._lock:
            queue = self._pending.get(df_id, [])
            return [m for m in queue if not m.is_expired(now)]

    def prune_expired(self) -> int:
        """Remove all expired Messages across all queues. Returns count_removed."""
        now = self._clock()
        removed = 0
        with self._lock:
            for df_id, queue in list(self._pending.items()):
                kept = [m for m in queue if not m.is_expired(now)]
                removed += len(queue) - len(kept)
                self._pending[df_id] = kept
        return removed


# ---------------- DFRoutingTable ----------------


class DFRoutingTable:
    """Capability-Registry mit Heartbeat-basierter Liveness.

    Pre:
        - register_df: df_id non-empty, capabilities list[str]
        - heartbeat: df_id muss vorher registriert sein
    Post:
        - find_by_capability(cap): list[df_id] fuer alle DFs mit cap (alive oder not)
        - is_alive(df_id, timeout_s): True wenn last heartbeat <= timeout_s alt
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        # df_id -> set[capability]
        self._capabilities: dict[str, set[str]] = {}
        # df_id -> last_heartbeat_ts
        self._heartbeats: dict[str, float] = {}

    def register_df(self, df_id: str, capabilities: list[str]) -> None:
        """Register/Update DF mit capabilities.

        Pre: df_id non-empty, capabilities iterable von strs.
        Post:
            - capabilities-set ueberschrieben (idempotent re-register)
            - Initial-Heartbeat gesetzt
        """
        if not df_id:
            raise ValueError("df_id required")
        if not isinstance(capabilities, (list, tuple, set)):
            raise TypeError("capabilities must be list/tuple/set of str")
        with self._lock:
            self._capabilities[df_id] = set(str(c) for c in capabilities)
            self._heartbeats[df_id] = self._clock()

    def find_by_capability(self, capability: str) -> list[str]:
        """Return all df_ids that registered capability."""
        with self._lock:
            return [
                df for df, caps in self._capabilities.items() if capability in caps
            ]

    def heartbeat(self, df_id: str) -> bool:
        """Refresh Heartbeat-Timestamp. Returns True wenn DF registriert."""
        with self._lock:
            if df_id not in self._capabilities:
                return False
            self._heartbeats[df_id] = self._clock()
            return True

    def is_alive(
        self, df_id: str, timeout_s: float = DEFAULT_HEARTBEAT_TIMEOUT_S
    ) -> bool:
        """True wenn last_heartbeat innerhalb timeout_s.

        Pre: timeout_s > 0.
        """
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        with self._lock:
            ts = self._heartbeats.get(df_id)
            if ts is None:
                return False
            return (self._clock() - ts) <= timeout_s

    def all_dfs(self) -> list[str]:
        """All registered df_ids."""
        with self._lock:
            return list(self._capabilities.keys())


# ---------------- DFCircuitBreakerPool ----------------


class DFCircuitBreakerPool:
    """Per-DF Circuit-Breaker-Isolation (reuse ApaleoCircuitBreaker).

    Pre: failure_threshold > 0, reset_timeout_s > 0.
    Post:
        - get_breaker(df_id): liefert (lazy-instantiated) ApaleoCircuitBreaker
        - get_failed_dfs(): list[df_id] mit STATE_OPEN
        - reset_all(): reset alle Breaker
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout_s: float = 30.0,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be > 0")
        if reset_timeout_s <= 0:
            raise ValueError("reset_timeout_s must be > 0")
        self.failure_threshold = int(failure_threshold)
        self.reset_timeout_s = float(reset_timeout_s)
        self._lock = threading.RLock()
        self._breakers: dict[str, ApaleoCircuitBreaker] = {}

    def get_breaker(self, df_id: str) -> ApaleoCircuitBreaker:
        """Lazy-instantiate per-DF Circuit-Breaker."""
        if not df_id:
            raise ValueError("df_id required")
        with self._lock:
            if df_id not in self._breakers:
                self._breakers[df_id] = ApaleoCircuitBreaker(
                    failure_threshold=self.failure_threshold,
                    reset_timeout_s=self.reset_timeout_s,
                )
            return self._breakers[df_id]

    def get_failed_dfs(self) -> list[str]:
        """List df_ids with state == OPEN."""
        with self._lock:
            return [
                df
                for df, breaker in self._breakers.items()
                if breaker.get_state()["state"] == ApaleoCircuitBreaker.STATE_OPEN
            ]

    def reset_all(self) -> int:
        """Reset all breakers to CLOSED. Returns count reset."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()
            return len(self._breakers)


# ---------------- DFOrchestrator ----------------


class DFOrchestrator:
    """Top-level Cross-DF Orchestrator.

    Komposition aus DFMessageBus + DFRoutingTable + DFCircuitBreakerPool.

    Pre: alle DFs muessen via register_df registriert werden vor Dispatch.
    Post:
        - dispatch(msg_type, payload, target_capability): routet Message zu erstem
          alive-DF mit target_capability (oder allen wenn target_capability None)
        - broadcast(msg_type, payload): an alle alive-DFs
        - get_health_summary(): aggregiert Routing-Liveness + Breaker-State
    """

    def __init__(
        self,
        bus: Optional[DFMessageBus] = None,
        routing: Optional[DFRoutingTable] = None,
        breakers: Optional[DFCircuitBreakerPool] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self.bus = bus if bus is not None else DFMessageBus(clock=clock)
        self.routing = routing if routing is not None else DFRoutingTable(clock=clock)
        self.breakers = breakers if breakers is not None else DFCircuitBreakerPool()
        self._lock = threading.RLock()

    def register_df(
        self,
        df_id: str,
        capabilities: list[str],
        callback: Callable[[DFMessage], None],
    ) -> str:
        """Register DF inkl. Subscription. Returns subscription_id.

        Pre: df_id non-empty, capabilities list, callback callable.
        Post:
            - DF registriert in Routing
            - Bus-Subscription mit callback
            - subscription_id retournierbar
        """
        self.routing.register_df(df_id, capabilities)
        return self.bus.subscribe(df_id, callback)

    def dispatch(
        self,
        msg_type: DFMessageType,
        payload: dict,
        target_capability: Optional[str] = None,
        ttl_s: float = DEFAULT_TTL_S,
        sender_df_id: str = "orchestrator",
    ) -> list[str]:
        """Dispatch Message an passende DF(s).

        Pre:
            - msg_type DFMessageType
            - payload dict
        Post:
            - Wenn target_capability: erste alive-DF mit cap bekommt Message
              (returns [df_id] oder [] wenn keiner alive)
            - Wenn None: an alle alive-DFs (returns list[df_id])
            - Skips DFs mit STATE_OPEN Circuit-Breaker
        """
        msg = make_df_message(
            df_id=sender_df_id,
            msg_type=msg_type,
            payload=payload,
            ttl_s=ttl_s,
            clock=self._clock,
        )

        # Candidate-DFs
        if target_capability:
            candidates = self.routing.find_by_capability(target_capability)
        else:
            candidates = self.routing.all_dfs()

        # Filter: alive AND breaker not OPEN
        failed = set(self.breakers.get_failed_dfs())
        eligible = [
            df
            for df in candidates
            if self.routing.is_alive(df) and df not in failed
        ]

        delivered: list[str] = []
        if target_capability:
            # Single-target: pick first eligible
            if eligible:
                target = eligible[0]
                self.bus.publish(msg, target_df_id=target)
                delivered.append(target)
        else:
            for df in eligible:
                self.bus.publish(msg, target_df_id=df)
                delivered.append(df)
        return delivered

    def broadcast(
        self,
        msg_type: DFMessageType,
        payload: dict,
        ttl_s: float = DEFAULT_TTL_S,
        sender_df_id: str = "orchestrator",
    ) -> list[str]:
        """Broadcast an alle alive + healthy DFs."""
        return self.dispatch(
            msg_type=msg_type,
            payload=payload,
            target_capability=None,
            ttl_s=ttl_s,
            sender_df_id=sender_df_id,
        )

    def get_health_summary(self) -> dict:
        """Aggregierte Health-Snapshot.

        Returns:
            {
                "total_dfs": int,
                "alive_dfs": list[str],
                "dead_dfs": list[str],
                "failed_dfs": list[str],   # circuit breaker OPEN
                "pending_per_df": dict[df_id, int],
                "timestamp": float,
            }
        """
        all_dfs = self.routing.all_dfs()
        alive = [df for df in all_dfs if self.routing.is_alive(df)]
        dead = [df for df in all_dfs if df not in alive]
        failed = self.breakers.get_failed_dfs()
        pending = {df: len(self.bus.get_pending(df)) for df in all_dfs}
        return {
            "total_dfs": len(all_dfs),
            "alive_dfs": alive,
            "dead_dfs": dead,
            "failed_dfs": failed,
            "pending_per_df": pending,
            "timestamp": self._clock(),
        }


# ---------------- DFConsensusVoter ----------------


class DFConsensusVoter:
    """Threshold-basiertes Multi-DF Voting (Quorum-Sensing-Adaptation).

    Bio-Pattern: Wie Quorum-Sensing in Bakterien-Kolonien -- Aktion erst nach
    Consensus-Threshold.

    Pre:
        - threshold in (0, 1]
        - timeout_after_s > 0
    Post:
        - request_vote(proposal_id, df_ids, threshold): registriert Voting-Round
        - record_vote(proposal_id, df_id, vote): zeichnet einzelnen Vote
        - is_consensus_reached(proposal_id):
            * True wenn yes-votes / total >= threshold
            * False wenn no-votes / total > (1 - threshold) (impossible-to-reach)
            * None wenn unentschieden + nicht expired
            * False wenn expired (Timeout) ohne Threshold-Match
    """

    def __init__(
        self,
        timeout_after_s: float = DEFAULT_VOTE_TIMEOUT_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if timeout_after_s <= 0:
            raise ValueError("timeout_after_s must be > 0")
        self.timeout_after_s = float(timeout_after_s)
        self._clock = clock
        self._lock = threading.RLock()
        # proposal_id -> { "df_ids": set, "threshold": float, "started_at": float }
        self._proposals: dict[str, dict[str, Any]] = {}
        # proposal_id -> list[DFVoteRecord]
        self._votes: dict[str, list[DFVoteRecord]] = defaultdict(list)

    def request_vote(
        self,
        proposal_id: str,
        df_ids: list[str],
        threshold: float = DEFAULT_VOTE_THRESHOLD,
    ) -> bool:
        """Initiate Voting-Round.

        Pre:
            - proposal_id non-empty
            - df_ids non-empty
            - threshold in (0, 1]
        Post: registered, returns True (False wenn proposal_id existiert).
        """
        if not proposal_id:
            raise ValueError("proposal_id required")
        if not df_ids:
            raise ValueError("df_ids required (non-empty)")
        if not (0 < threshold <= 1):
            raise ValueError("threshold must be in (0, 1]")
        with self._lock:
            if proposal_id in self._proposals:
                return False
            self._proposals[proposal_id] = {
                "df_ids": set(df_ids),
                "threshold": float(threshold),
                "started_at": self._clock(),
            }
        return True

    def record_vote(self, proposal_id: str, df_id: str, vote: bool) -> bool:
        """Record vote von df_id fuer proposal_id.

        Pre:
            - proposal_id muss via request_vote vorher initiiert
            - df_id muss in df_ids des Proposals
        Post:
            - DFVoteRecord (frozen) angelegt; doppelte Votes fuer (proposal, df) ignored
            - Returns True wenn Vote akzeptiert, False wenn redundant/unbekannt
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return False
            if df_id not in proposal["df_ids"]:
                return False
            # Idempotenz: schon abgestimmt?
            existing = {r.df_id for r in self._votes[proposal_id]}
            if df_id in existing:
                return False
            record = DFVoteRecord(
                proposal_id=proposal_id,
                df_id=df_id,
                vote=bool(vote),
                timestamp=self._clock(),
            )
            self._votes[proposal_id].append(record)
            return True

    def is_consensus_reached(self, proposal_id: str) -> Optional[bool]:
        """Determine Consensus-Status.

        Returns:
            - True: yes-votes / total >= threshold (consensus erreicht)
            - False: definitiv nicht erreichbar (Timeout oder zu viele No-Votes)
            - None: noch unentschieden (Voting laeuft)
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return None
            total = len(proposal["df_ids"])
            threshold = proposal["threshold"]
            started = proposal["started_at"]
            now = self._clock()

            votes = self._votes[proposal_id]
            yes_count = sum(1 for v in votes if v.vote)
            no_count = sum(1 for v in votes if not v.vote)
            outstanding = total - yes_count - no_count
            # need_yes ist die Mindest-Anzahl an Yes-Votes fuer Threshold-Erfuellung.
            # Wir nutzen ceiling damit threshold=0.5 in 4-DF-Quorum 2 Yes-Votes verlangt
            # (weil 2/4 = 0.5 erfuellt >= 0.5).
            need_yes = (
                int(threshold * total)
                if abs(threshold * total - int(threshold * total)) < 1e-9
                else int(threshold * total) + 1
            )
            # Corner: threshold=1.0 -> need_yes == total
            need_yes = max(need_yes, 1) if threshold > 0 else 0

            # Definitiv erreicht?
            if yes_count >= need_yes:
                return True

            # Definitiv nicht erreichbar (selbst alle outstanding waeren Yes)?
            if yes_count + outstanding < need_yes:
                return False

            # Timeout: wenn Voting expired -> not reached
            if (now - started) > self.timeout_after_s:
                return False

            return None

    def get_vote_count(self, proposal_id: str) -> dict:
        """Audit-Snapshot der Vote-Counts.

        Returns: { "yes": int, "no": int, "outstanding": int, "total": int }
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return {"yes": 0, "no": 0, "outstanding": 0, "total": 0}
            total = len(proposal["df_ids"])
            votes = self._votes.get(proposal_id, [])
            yes = sum(1 for v in votes if v.vote)
            no = sum(1 for v in votes if not v.vote)
            return {
                "yes": yes,
                "no": no,
                "outstanding": total - yes - no,
                "total": total,
            }


# CRUX-MK
