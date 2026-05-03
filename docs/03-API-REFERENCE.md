---
type: api-reference
version: 0.3.0
crux-mk: true
datum: 2026-04-30
source: kmo_governance/*/kmo_*.py + event_types.py + phase_registry.py
modules: 6 (data-class-filter, lease-manager, approval-gate, durable-execution, saga-pattern, outbox-pattern)
---

# KMO API Reference [CRUX-MK]

Module-by-Module API. Type-Hints + Konstruktor-Parameter + Public-Methoden +
Beispiel-Snippets + Errors. Alle Snippets sind kopierbar (echte Imports).

Querverweise:
- [01-ARCHITECTURE.md](01-ARCHITECTURE.md) -- Komponenten-Hierarchie
- [02-PIPELINE-FLOWS.md](02-PIPELINE-FLOWS.md) -- End-to-End-Sequenzen

---

## Module 1: data-class-filter (A5)

**Pfad:** `kmo_governance/data-class-filter/kmo_data_class_filter.py`
**Patch:** P-KMO-A5
**Zweck:** 4-Stage-Klassifikation + Provider-Compatibility-Matrix.

### Klassen + Enums

#### `class DataClass(IntEnum)`

```python
class DataClass(IntEnum):
    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3
    SECRET = 4

    @classmethod
    def from_tag(cls, tag: str) -> Optional["DataClass"]: ...
```

**Konvertierung:** `from_tag()` akzeptiert `"PUBLIC"`, `"CLASS-1"`, `"CLASS_1"`, `"1"`.

#### `@dataclass(frozen=True) class RoutingDecision`

```python
@dataclass(frozen=True)
class RoutingDecision:
    allowed: bool
    data_class: DataClass
    target_provider: str
    reason: str
    detected_patterns: tuple[str, ...] = field(default_factory=tuple)

    def to_log_entry(self) -> dict: ...
```

#### `class DataClassFilter`

```python
class DataClassFilter:
    def __init__(
        self,
        config_path: Optional[Path] = None,        # Default: provider_compat.yaml in module dir
        audit_log_path: Optional[Path] = None,     # Default: branch-hub/audit/kmo-routing-decisions.jsonl
    ) -> None: ...

    def classify_input(
        self,
        prompt: str,
        frontmatter: Optional[dict] = None,
    ) -> DataClass:
        """Frontmatter-tag first, regex-fallback for SECRET, default PUBLIC."""

    def is_provider_allowed(self, data_class: DataClass, provider: str) -> bool:
        """Unknown providers fail-closed (return False)."""

    def pre_routing_check(
        self,
        prompt: str,
        target_provider: str,
        frontmatter: Optional[dict] = None,
    ) -> RoutingDecision:
        """Full check: classify + compat + JSONL audit append."""
```

### Beispiel

```python
from kmo_data_class_filter import DataClass, DataClassFilter

f = DataClassFilter()

# Frontmatter-Tag
decision = f.pre_routing_check(
    prompt="Refactor this function",
    target_provider="codex-gpt5.5",
    frontmatter={"data_class": "PUBLIC"},
)
assert decision.allowed

# SECRET-Pattern auto-detect (kein Frontmatter)
decision = f.pre_routing_check(
    prompt="API_KEY=sk-abc123",
    target_provider="claude-opus",
)
assert not decision.allowed
assert "api_key" in decision.detected_patterns

# CONFIDENTIAL gegen PUBLIC-only Provider
decision = f.pre_routing_check(
    prompt="Family financial detail",
    target_provider="perplexity-ultimate",
    frontmatter={"data_class": "CONFIDENTIAL"},
)
assert not decision.allowed  # Mismatch
```

### Errors

| Exception | Bedingung |
|---|---|
| `FileNotFoundError` | `config_path` (provider_compat.yaml) fehlt im Konstruktor |
| `ValueError` | YAML enthaelt ungueltige `max_data_class` (kein DataClass-Tag) |

### SECRET-Pattern-Liste

| Pattern | Regex (vereinfacht) |
|---|---|
| `api_key` | `\b(?:API[_-]?KEY|APIKEY)\s*[:=]\s*\S+` |
| `token` | `\b(?:TOKEN|BEARER)\s*[:=]\s*\S+` |
| `password` | `\b(?:PASSWORD|PASSWD|PWD)\s*[:=]\s*\S+` |
| `secret` | `\b(?:SECRET|SECRET[_-]?KEY)\s*[:=]\s*\S+` |
| `bearer_header` | `\bAuthorization\s*:\s*Bearer\s+\S+` |
| `bearer_jwt` | `\bBearer\s+[A-Za-z0-9._\-=]{20,}` |
| `aws_key` | `\bAKIA[0-9A-Z]{16}\b` |
| `iban` | `\b[A-Z]{2}\d{2}\s?(?:\d{4}\s?){3,7}\d{0,4}\b` |
| `credit_card` | `\b(?:\d{4}[\s-]?){3}\d{4}\b` |
| `private_key` | `-----BEGIN (?:RSA \|EC )?PRIVATE KEY-----` |

---

## Module 2: lease-manager (A1)

**Pfad:** `kmo_governance/lease-manager/kmo_lease_manager.py` + `kmo_lease_decorator.py`
**Patch:** P-KMO-A1
**Zweck:** SQLite-WAL-basierter atomic Lease-Manager mit TTL + Heartbeat + STOP.flag.

### Klassen + Enums

#### `class ResourceType(enum.Enum)`

```python
class ResourceType(enum.Enum):
    DF = "DF"                            # Dark-Factory engine instance
    PORT = "PORT"                        # TCP-Port
    API_TOKEN = "API_TOKEN"              # OAuth-/API-Token slot
    DRIVE_PATH = "DRIVE_PATH"            # Filesystem-Path
    TUNNEL_SUBDOMAIN = "TUNNEL_SUBDOMAIN" # Cloudflare/ngrok subdomain
```

#### `@dataclass(frozen=True) class LeaseInfo`

```python
@dataclass(frozen=True)
class LeaseInfo:
    lease_id: str
    resource_type: str
    resource_id: str
    holder: str
    acquired_at: float
    expires_at: float
    last_heartbeat: float
    metadata: Optional[dict]

    @property
    def is_expired(self) -> bool: ...
```

#### `class LeaseManager`

```python
DEFAULT_TTL_SEC: int = 300
HEARTBEAT_INTERVAL_SEC: int = 60

class LeaseManager:
    def __init__(
        self,
        db_path: Optional[Path] = None,         # Default: ~/Library/Application Support/kmo/leases.db
        stop_flag_dir: Optional[Path] = None,   # Default: ~/branch-hub/audit/
        schema_path: Optional[Path] = None,     # Default: schema.sql in module dir
    ) -> None: ...

    def acquire(
        self,
        resource_type: ResourceType,
        resource_id: str,
        holder: str,
        ttl_sec: int = DEFAULT_TTL_SEC,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """Atomic acquire. Returns lease_token (UUID) or None on conflict/STOP.flag."""

    def release(self, lease_token: str) -> bool:
        """Returns True iff a row was deleted."""

    def heartbeat(self, lease_token: str, ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
        """Refresh TTL. Returns True iff lease exists."""

    def is_locked(
        self, resource_type: ResourceType, resource_id: str
    ) -> Optional[LeaseInfo]:
        """LeaseInfo iff currently locked AND not expired; else None."""

    def force_release_stale(self) -> List[str]:
        """Delete all expired leases. Returns released lease_ids."""

    def list_active(self) -> List[LeaseInfo]: ...

    def get_by_token(self, lease_token: str) -> Optional[LeaseInfo]: ...

    def respect_stop_flag(self, resource_id: str) -> bool:
        """True iff STOP-{resource_id}.flag exists in stop_flag_dir."""
```

### Decorator

```python
def with_lease(
    manager: LeaseManager,
    resource_type: ResourceType,
    resource_id_func: Callable[..., str],
    holder_func: Optional[Callable[..., str]] = None,  # Default: pid+tid string
    ttl_sec: int = DEFAULT_TTL_SEC,
    heartbeat_interval_sec: int = HEARTBEAT_INTERVAL_SEC,
    raise_on_acquire_fail: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...
```

### Beispiel (manuelle API)

```python
from kmo_lease_manager import LeaseManager, ResourceType

mgr = LeaseManager()
token = mgr.acquire(
    ResourceType.DF, "df-86",
    holder="mac.df-86.pid-1234",
    ttl_sec=300,
)
if token:
    try:
        # ... work ...
        mgr.heartbeat(token)  # alle 60s bei langlaufenden Tasks
    finally:
        mgr.release(token)
else:
    # Resource busy oder STOP.flag aktiv
    pass

# Diagnostik
info = mgr.is_locked(ResourceType.DF, "df-86")
all_active = mgr.list_active()
mgr.force_release_stale()
```

### Beispiel (Decorator mit Auto-Heartbeat)

```python
import os
from kmo_lease_manager import LeaseManager, ResourceType
from kmo_lease_decorator import with_lease

mgr = LeaseManager()

@with_lease(
    manager=mgr,
    resource_type=ResourceType.DF,
    resource_id_func=lambda df_name, *a, **kw: df_name,
    holder_func=lambda df_name, *a, **kw: f"mac.{df_name}.pid-{os.getpid()}",
    ttl_sec=300,
    heartbeat_interval_sec=60,
)
def run_df_engine(df_name: str) -> None:
    # Lease ist exklusiv, Heartbeat-Thread refreshet TTL
    ...
```

### Errors

| Exception | Bedingung |
|---|---|
| `TypeError` | `resource_type` nicht ResourceType-Enum |
| `ValueError` | `resource_id` oder `holder` leer; `ttl_sec <= 0` |
| `LeaseAcquireFailed` | `@with_lease` mit `raise_on_acquire_fail=True` und Conflict |

---

## Module 3: approval-gate (A4)

**Pfad:** `kmo_governance/approval-gate/kmo_approval_gate.py` + `kmo_audit_log.py`
**Patch:** P-KMO-A4 + A4.2 (Welle-4 Dual-Control)
**Zweck:** HMAC-signed Approval-Tokens + Dual-Control + Atomic Pre-Deploy + Hash-Chain Audit.

### Klassen

#### `@dataclass(frozen=True) class ApprovalToken`

```python
@dataclass(frozen=True)
class ApprovalToken:
    requester: str
    resource: str
    action: str
    issued_at: int       # UNIX epoch seconds
    expires_at: int
    nonce: str           # hex
    signature: str       # hex HMAC-SHA256

    def serialize(self) -> str: ...

    @classmethod
    def deserialize(cls, token_str: str) -> "ApprovalToken": ...
```

#### `@dataclass(frozen=True) class DualApprovalToken`

```python
@dataclass(frozen=True)
class DualApprovalToken:
    primary: ApprovalToken
    secondary: ApprovalToken
    requester: str  # initiator (NOT a signer)

    def serialize(self) -> str: ...

    @classmethod
    def deserialize(cls, dual_str: str) -> "DualApprovalToken": ...
```

#### `class ApprovalGate`

```python
TOKEN_TTL_SECONDS: int = 24 * 60 * 60
ENV_SECRET_KEY: str = "KMO_APPROVAL_SECRET"

class ApprovalGate:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,           # ~/.kmo/approval_gate.db
        config_path: Path = DEFAULT_CONFIG_PATH,   # ~/.kmo/authorized_identities.yaml
        secret: Optional[str] = None,              # else from ENV
    ) -> None: ...

    # Single-Stage
    def request_approval(
        self, resource: str, action: str, requester: str
    ) -> str:
        """Issue HMAC-signed token. Returns serialized JSON-string."""

    def verify_token(
        self, token_str: str, resource: str, action: str
    ) -> bool:
        """Verify + consume (single-use). True iff valid+matching+unexpired+unused."""

    def revoke_token(self, token_str: str) -> None:
        """Idempotent revocation."""

    # Deploy-Lock
    def acquire_deploy_lock(
        self, resource: str, holder: str, ttl_seconds: int = TOKEN_TTL_SECONDS
    ) -> bool: ...

    def release_deploy_lock(self, resource: str, holder: str) -> bool: ...

    # Dual-Control (A4.2 Welle-4)
    def request_dual_approval(
        self,
        resource: str,
        action: str,
        requester: str,
        primary_signer: str,
        secondary_signer: str,
    ) -> DualApprovalToken:
        """Issue 2 tokens with 3-way disjoint identities."""

    def verify_dual_token(
        self,
        dual_token: DualApprovalToken,
        resource: str,
        action: str,
    ) -> bool:
        """Read-only verify. Does NOT consume."""

    def pre_deploy_atomic(
        self,
        dual_token: DualApprovalToken,
        resource: str,
        action: str,
        holder: str,
    ) -> bool:
        """Atomic verify+lock+audit in ONE SQLite-Transaction (BEGIN IMMEDIATE)."""
```

#### `class AuditLog` (Hash-Chain)

```python
@dataclass(frozen=True)
class AuditEntry:
    block_index: int
    timestamp: int
    action: str
    resource: str
    requester: str
    approver_token_nonce: str
    prev_hash: str
    block_hash: str

    def to_json_line(self) -> str: ...

class AuditLog:
    def __init__(self, log_path: Path = DEFAULT_LOG_PATH): ...
        # Default: branch-hub/audit/kmo-approval-chain.jsonl

    def append(
        self,
        action: str,
        resource: str,
        requester: str,
        approver_token_nonce: str,
    ) -> AuditEntry:
        """Standalone append. Hash-links automatic."""

    def append_within_transaction(
        self,
        conn: sqlite3.Connection,
        action: str,
        resource: str,
        requester: str,
        approver_token_nonce: str,
    ) -> AuditEntry:
        """Caller-managed TX. JSONL flush deferred to flush_entry_to_jsonl."""

    def flush_entry_to_jsonl(self, entry: AuditEntry) -> None: ...

    def verify_chain(self) -> bool:
        """SHA256-chain integrity check. False = tampered."""
```

### Beispiel: Single-Stage Approval

```python
import os
os.environ["KMO_APPROVAL_SECRET"] = "32-bytes-shared-secret-replace-me"

from kmo_approval_gate import ApprovalGate
from kmo_audit_log import AuditLog

gate = ApprovalGate()
log = AuditLog()

# Martin requests approval
token = gate.request_approval(
    resource="df-86-prod", action="deploy", requester="martin"
)

# Pipeline verifies before deploy
if gate.verify_token(token, "df-86-prod", "deploy"):
    log.append(
        action="deploy",
        resource="df-86-prod",
        requester="martin",
        approver_token_nonce=token[:32],
    )
    # ... proceed
```

### Beispiel: Dual-Control Atomic Pre-Deploy

```python
gate = ApprovalGate()

# Imke requests, Martin + Gerdi sign
dual = gate.request_dual_approval(
    resource="df-86-prod",
    action="deploy",
    requester="imke",
    primary_signer="martin",
    secondary_signer="gerdi",
)

# Atomic verify+lock+audit in einer Transaction
ok = gate.pre_deploy_atomic(dual, "df-86-prod", "deploy", holder="imke")
if ok:
    # Beide Tokens consumed, deploy_lock haelt 24h, Audit-Block geschrieben
    ...  # actual deploy
```

### Errors

| Exception | Bedingung |
|---|---|
| `RuntimeError` | `KMO_APPROVAL_SECRET` ENV nicht gesetzt UND kein `secret` arg |
| `PermissionError` | `requester` / `primary_signer` / `secondary_signer` nicht in authorized identities |
| `PermissionError` | 3-way disjoint verletzt (Identity-Duplikat) |
| `ValueError` | `resource` oder `action` leer, oder Token malformed |
| `sqlite3.IntegrityError` | (intern abgefangen) UNIQUE-Conflict bei Token-Replay |

---

## Module 4: durable-execution (A7)

**Pfad:** `kmo_governance/durable-execution/kmo_durable_state_machine.py` + `event_types.py`
**Patch:** P-KMO-A7
**Zweck:** Self-built JSON-State-Machine mit Event-Sourcing + Crash-Recovery.

### Klassen + Enums

#### `class WorkflowStatus(str, Enum)`

```python
class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DONE = "DONE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
```

#### `class EventType(str, Enum)` (in `event_types.py`)

```python
class EventType(str, Enum):
    # KMO-Domain (4 Pflicht):
    ROUTING_DECISION = "ROUTING_DECISION"
    DF_STATUS_CHANGE = "DF_STATUS_CHANGE"
    STOP_FLAG_TRANSITION = "STOP_FLAG_TRANSITION"
    APPROVAL_STATE = "APPROVAL_STATE"
    # System (3):
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    STATE_TRANSITION = "STATE_TRANSITION"
    SNAPSHOT_TAKEN = "SNAPSHOT_TAKEN"
```

#### `@dataclass(frozen=True) class Event`

```python
@dataclass(frozen=True)
class Event:
    event_id: str
    workflow_id: str
    event_type: EventType
    timestamp: float
    sequence: int
    payload: dict
    actor: Optional[str] = None
    correlation_id: Optional[str] = None

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, d: dict) -> "Event": ...
```

#### `@dataclass class WorkflowRun`

```python
@dataclass
class WorkflowRun:
    workflow_id: str
    current_phase: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    state_data: dict = field(default_factory=dict)
    sequence: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowRun": ...
```

#### `class DurableStateMachine`

```python
class DurableStateMachine:
    def __init__(
        self,
        state_root: Path | str,
        snapshot_every_n_events: int = 10,
        lock_stale_after_s: float = 300.0,
    ): ...

    def start_workflow(
        self,
        workflow_id: str,
        initial_state: Optional[dict] = None,
        initial_phase: str = "init",
    ) -> WorkflowRun:
        """Create new workflow. Raises ValueError if already exists."""

    def transition(
        self,
        workflow_id: str,
        event_type: EventType,
        payload: dict,
        actor: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> WorkflowRun:
        """Append event + materialize state. Filesystem-mutex protects sequence."""

    def transition_phase(
        self,
        workflow_id: str,
        from_phase: str,
        to_phase: str,
        state_patch: Optional[dict] = None,
        actor: Optional[str] = None,
    ) -> WorkflowRun:
        """Convenience for STATE_TRANSITION events."""

    def recover(self, workflow_id: str) -> WorkflowRun:
        """Load latest snapshot + replay newer events."""

    def snapshot(self, workflow_id: str) -> WorkflowRun:
        """Capture current state at current sequence."""

    def get_history(self, workflow_id: str) -> list[Event]: ...

    def list_workflows(self) -> list[str]: ...
```

### Helper-Konstruktoren (in `event_types.py`)

```python
def make_routing_decision(
    workflow_id: str, sequence: int, phase: str,
    chosen_target: str, candidates: list[str], rationale: str,
    actor: Optional[str] = "router",
    correlation_id: Optional[str] = None,
) -> Event: ...

def make_df_status_change(
    workflow_id: str, sequence: int, df_id: str,
    from_status: str, to_status: str,
    reason: Optional[str] = None,
    actor: Optional[str] = "df-engine",
    correlation_id: Optional[str] = None,
) -> Event: ...

def make_stop_flag_transition(
    workflow_id: str, sequence: int, flag_id: str,
    raised: bool, reason: Optional[str] = None,
    actor: Optional[str] = "operator",
    correlation_id: Optional[str] = None,
) -> Event: ...

def make_approval_state(
    workflow_id: str, sequence: int, gate_id: str,
    decision: str,  # "APPROVED" | "REJECTED" | "PENDING"
    approver: str,
    notes: Optional[str] = None,
    actor: Optional[str] = "approval-gate",
    correlation_id: Optional[str] = None,
) -> Event: ...

def make_state_transition(
    workflow_id: str, sequence: int,
    from_phase: str, to_phase: str, state_patch: dict,
    actor: Optional[str] = "state-machine",
    correlation_id: Optional[str] = None,
) -> Event: ...
```

### Beispiel

```python
from kmo_durable_state_machine import DurableStateMachine
from event_types import EventType

sm = DurableStateMachine(state_root="branch-hub/workflow-state/")

# Start
run = sm.start_workflow("kmo-run-001", initial_state={"target": "df-86"})

# Phase transitions
run = sm.transition_phase(
    "kmo-run-001",
    from_phase="init",
    to_phase="plan",
    state_patch={"plan_done": True},
)

# Domain events
sm.transition(
    "kmo-run-001",
    EventType.ROUTING_DECISION,
    payload={
        "phase": "build",
        "chosen_target": "df-86",
        "candidates": ["df-86", "df-87"],
        "rationale": "lowest-load",
    },
)

# Crash-Recovery (neuer Process)
sm2 = DurableStateMachine(state_root="branch-hub/workflow-state/")
recovered = sm2.recover("kmo-run-001")
print(f"phase={recovered.current_phase} seq={recovered.sequence}")

# History
events = sm.get_history("kmo-run-001")
```

### Storage-Layout

```
<state_root>/<workflow_id>/
    events.jsonl                # append-only, fsync per append
    snapshots/<seq:010d>.json   # auto every 10 events
    state.lock/                 # mkdir-mutex (stale TTL 300s)
```

### Errors

| Exception | Bedingung |
|---|---|
| `ValueError` | `start_workflow()` mit existierender `workflow_id` |
| `WorkflowNotFoundError` | `transition()` / `recover()` / `get_history()` ohne vorheriges `start_workflow()` |
| `ConcurrentTransitionError` | `state.lock/` von anderem Prozess gehalten und nicht stale |

---

## Module 5: saga-pattern (A2)

**Pfad:** `kmo_governance/saga-pattern/kmo_saga_engine.py` + `phase_registry.py`
**Patch:** P-KMO-A2
**Zweck:** do/undo-Saga mit reverse-chain Compensation + Crash-Recovery + Exit-Criteria.

### Klassen + Enums

#### `class PhaseStatus(str, Enum)`

```python
class PhaseStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    UNDOING = "UNDOING"
    UNDONE = "UNDONE"
    UNDO_FAILED = "UNDO_FAILED"
    SKIPPED = "SKIPPED"
```

#### `class SagaStatus(str, Enum)`

```python
class SagaStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    PARTIAL_COMPENSATION = "PARTIAL_COMPENSATION"
```

#### `@dataclass class SagaPhase`

```python
@dataclass
class SagaPhase:
    phase_id: str
    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    input: Any = None
    output: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
```

#### `@dataclass class SagaRun`

```python
@dataclass
class SagaRun:
    run_id: str
    phases: list[SagaPhase] = field(default_factory=list)
    current_phase_idx: int = 0
    overall_status: SagaStatus = SagaStatus.PENDING
    initial_input: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
```

#### `@dataclass class SagaResult`

```python
@dataclass
class SagaResult:
    run_id: str
    status: SagaStatus
    final_output: Any = None
    error: Optional[str] = None
    phases_done: int = 0
    phases_undone: int = 0
```

#### `class SagaEngine`

```python
class SagaEngine:
    def __init__(self, state_dir: Path | str): ...

    def register_phase(
        self,
        phase_id: str,
        name: str,
        do_func: Callable[[Any, dict], Any],
        undo_func: Callable[[Any, Any, dict], None],
        exit_criteria_func: Optional[Callable[[Any], bool]] = None,
    ) -> None:
        """Order of registration = execution order. Phase IDs must be unique."""

    def execute(self, saga_run_id: str, initial_input: Any) -> SagaResult:
        """Run saga from scratch. Persists state after every transition."""

    def resume(self, saga_run_id: str) -> SagaResult:
        """Crash-recovery entrypoint. Detects mid-phase RUNNING -> FAILED -> compensate."""

    def get_status(self, run_id: str) -> Optional[dict]: ...
```

### Phase-Registry-Helper (in `phase_registry.py`)

```python
def register_kmo_phases(engine: SagaEngine) -> None:
    """Register canonical KMO 7-phase pipeline:
       Plan -> Spec -> Wargame -> Build -> Test -> DEV-Demo -> Approval/Gerdi
       with exit_criteria on Wargame, Test, Approval.
    """
```

### Beispiel: Custom-Phasen

```python
from kmo_saga_engine import SagaEngine, SagaStatus

def do_step1(inp, ctx):
    return {"step": 1, "data": inp}

def undo_step1(inp, out, ctx):
    # idempotent rollback (no-op if nothing to undo)
    pass

def exit_step1(out):
    return out.get("data") is not None

engine = SagaEngine(state_dir="branch-hub/workflow-state/")
engine.register_phase("step1", "Step One", do_step1, undo_step1, exit_step1)
engine.register_phase("step2", "Step Two", do_step2, undo_step2)

result = engine.execute("my-run-001", initial_input={"target": "df-86"})

if result.status == SagaStatus.DONE:
    print(f"Phases done: {result.phases_done}, output: {result.final_output}")
elif result.status == SagaStatus.COMPENSATED:
    print(f"Compensated cleanly. Phases done: {result.phases_done}, undone: {result.phases_undone}")
elif result.status == SagaStatus.PARTIAL_COMPENSATION:
    print(f"Some undo failed: {result.error}")
```

### Beispiel: KMO-7-Phasen

```python
from kmo_saga_engine import SagaEngine
from phase_registry import register_kmo_phases

engine = SagaEngine(state_dir="branch-hub/workflow-state/")
register_kmo_phases(engine)
result = engine.execute(
    saga_run_id="kmo-run-001",
    initial_input={"action": "deploy-df-86"},
)

# Crash? Resume:
result = engine.resume(saga_run_id="kmo-run-001")
status_dict = engine.get_status("kmo-run-001")
```

### Errors

| Exception | Bedingung |
|---|---|
| `RuntimeError` | `execute()` ohne `register_phase()` |
| `ValueError` | `register_phase()` mit Duplicate-`phase_id` |
| `FileNotFoundError` | `resume()` ohne persistierten State |
| `RuntimeError` (intern) | Exit-Criteria-Fail -> Phase-FAILED -> Compensate-Trigger |

### Atomic-State-Write

Jeder Phase-Statuswechsel persistiert via `tempfile.mkstemp()` + `f.flush()` +
`os.fsync()` + `os.replace()`. Crash mid-write nicht moeglich.

---

## Module 6: outbox-pattern (A3)

**Pfad:** `kmo_governance/outbox-pattern/kmo_outbox_producer.py` + `kmo_outbox_consumer.py`
**Patch:** P-KMO-A3
**Zweck:** Cross-Machine Dispatch via Drive-Sync mit UUID4-Idempotency + DLQ.

### Klassen

#### `@dataclass class EventEnvelope`

```python
@dataclass
class EventEnvelope:
    event_id: str        # UUID4
    machine_id: str
    topic: str
    seq: int             # monotonic per (machine_id, topic) via SQLite-Counter
    timestamp: float
    payload: dict
    retry_count: int = 0

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, d: dict) -> "EventEnvelope": ...

    def filename(self) -> str:
        """Format: <machine>-<topic>-<seq:08d>.json"""
```

#### `def atomic_write_json(target: Path, data: dict) -> None`

Top-level helper. Tempfile in same dir + `fsync` + `os.replace`. Verhindert
partial-writes bei Drive-Sync-Race.

#### `class OutboxProducer`

```python
class OutboxProducer:
    def __init__(
        self,
        outbox_dir: Path,
        ack_dir: Path,
        machine_id: str,
        state_db: Path | None = None,    # Default: ~/Library/Application Support/kmo/producer-<machine_id>.db
    ): ...

    def publish(
        self,
        machine_id: str,
        topic: str,
        payload: dict,
        event_id: str | None = None,    # Auto-UUID4 if None
    ) -> EventEnvelope:
        """Atomic write to outbox_dir. Idempotent via event_id."""

    def republish_failed_acks(self) -> list[EventEnvelope]:
        """Re-publish events without ack-file. retry_count++."""
```

#### `class OutboxConsumer`

```python
@dataclass
class ConsumerStats:
    polled: int = 0
    processed: int = 0
    skipped_idempotent: int = 0
    failed: int = 0
    moved_to_dlq: int = 0
    errors: list[str] = field(default_factory=list)

class OutboxConsumer:
    MAX_RETRIES: int = 3

    def __init__(
        self,
        consumer_id: str,
        outbox_dir: Path,
        ack_dir: Path,
        dlq_dir: Path,
        state_db: Path | None = None,
    ): ...

    def subscribe(
        self,
        topics: list[str],
        handler_func: Callable[[EventEnvelope], None],
    ) -> None:
        """Handler raises Exception on failure -> retry_count++."""

    def poll_and_process(self) -> ConsumerStats:
        """Pollt outbox once. Idempotent skip via processed_events table."""

    def acknowledge(self, event_id: str) -> Path:
        """Write ack-file."""

    def move_to_dlq(self, event_id: str, reason: str) -> Path | None:
        """Move event to DLQ after MAX_RETRIES."""
```

### Beispiel

```python
from pathlib import Path
from kmo_outbox_producer import OutboxProducer, EventEnvelope
from kmo_outbox_consumer import OutboxConsumer

outbox_dir = Path("branch-hub/outbox/")
ack_dir = Path("branch-hub/outbox-ack/")
dlq_dir = Path("branch-hub/outbox-dlq/")

# Producer (Mac)
producer = OutboxProducer(outbox_dir, ack_dir, machine_id="mac")
event = producer.publish(
    machine_id="mac",
    topic="kmo-pipeline",
    payload={"action": "deploy-df-86"},
)
print(f"Published seq={event.seq} event_id={event.event_id}")

# Consumer (Windows, via Drive-Sync)
consumer = OutboxConsumer(
    consumer_id="windows-worker",
    outbox_dir=outbox_dir,
    ack_dir=ack_dir,
    dlq_dir=dlq_dir,
)

received = []
def handle(env: EventEnvelope) -> None:
    received.append(env)
    # Raises Exception -> retry_count++ -> after 3 fails -> DLQ

consumer.subscribe(["kmo-pipeline"], handle)
stats = consumer.poll_and_process()
print(f"processed={stats.processed} skipped={stats.skipped_idempotent} dlq={stats.moved_to_dlq}")
```

### File-Layout

```
branch-hub/
    outbox/
        mac-kmo-pipeline-00000001.json    # Producer-output, idempotent atomic-write
        mac-kmo-pipeline-00000002.json
    outbox-ack/
        mac-kmo-pipeline-00000001.ack.json
    outbox-dlq/
        mac-kmo-pipeline-00000099.dlq.json   # nach 3 Fails
```

### Errors

| Exception | Bedingung |
|---|---|
| `ValueError` | Producer `machine_id` mismatch (Producer schreibt nur eigene Events) |
| `ValueError` | `topic` leer |
| `ValueError` | `acknowledge()` mit unbekannter `event_id` |
| Handler raises | -> `retry_count++`; nach `MAX_RETRIES=3` -> DLQ |
| `json.JSONDecodeError` | Outbox-File corrupt -> in `stats.errors` gelistet, kein Crash |

---

## OPEN-QUESTION

**OQ-1 Cross-Module-Imports:**
`pre_deploy_atomic()` ruft intern `from kmo_audit_log import AuditLog` (lokale
Import-Vermeidung wegen Circular). Bei Refactor zu Package `kmo_governance` als
Python-Package: pruefen ob lokaler Import noch noetig.

**OQ-2 ResourceType-Erweiterung:**
Aktuell 5 ResourceTypes (DF, PORT, API_TOKEN, DRIVE_PATH, TUNNEL_SUBDOMAIN).
Bei zukuenftigen Resources (DB-Connection-Pool, NLM-Notebook): Enum-Erweiterung
vs Sub-Klassen offen.

**OQ-3 Saga-Phase-Registry-Persistenz:**
`register_phase()` ist memory-only. Bei Multi-Process-Saga (Producer-Process
+ Resume-Process auf gleicher run_id): muss Phase-Registry ebenfalls persistiert
werden? Aktuell muss der Resume-Process selbst `register_kmo_phases()` rufen.

[CRUX-MK]
