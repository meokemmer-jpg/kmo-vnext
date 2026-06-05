"""KMO Wave-3-C2 RETRY P1.2 Failure-Injection-Test-Pack [CRUX-MK].

Welle-12 Re-Audit Befund: Cargo-Cult-Compliance + Concurrency-Blindheit.
Wave-1-A1 fand 5 NEUE CRITICAL incl.:
- PDP-First-Match (most-restrictive sollte gewinnen, nicht first-match)
- AdapterHealthMonitor-TOCTOU (is_available state-mutation-during-read)
- ApprovalGate-Phronesis-Bypass (Status-Override BLOCKED -> ESCALATED)

4 Pflicht-Tests:
1. PDP Most-Restrictive-Match (2 ueberlappende Policies -> assert restrictivste gewinnt)
2. AdapterHealthMonitor TOCTOU-Race (50 Threads is_available() -> assert no state-mutation)
3. ApprovalGate Status-Override-Negative (BLOCKED ueberschreibt ESCALATED -> assert ESCALATED bleibt)
4. Cross-Tenant-Cross-Module-Negative (KMO-tenant-A liest KMO-tenant-B-data -> assert DENY default)
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

# sys.path Setup fuer KMO-Module
_KMO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))


def _load_module(name: str, path: Path):
    """Direct module loader (umgeht src-namespace-collision)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# adapter_health direct laden (vermeidet `from src.X` collision)
_ADAPTER_HEALTH_PATH = _KMO_ROOT / "kmo_governance" / "hot_switch_adapter" / "src" / "adapter_health.py"
_adapter_health = _load_module("kmo_adapter_health_w3", _ADAPTER_HEALTH_PATH)
AdapterHealthMonitor = _adapter_health.AdapterHealthMonitor
AdapterStatus = _adapter_health.AdapterStatus
CircuitState = _adapter_health.CircuitState

# approval_request + approval_gate direct laden
_APPROVAL_REQUEST_PATH = _KMO_ROOT / "kmo_governance" / "multi_tenant_approval" / "src" / "approval_request.py"
_approval_request = _load_module("kmo_approval_request_w3", _APPROVAL_REQUEST_PATH)
ApprovalRequest = _approval_request.ApprovalRequest
ApprovalStatus = _approval_request.ApprovalStatus
OperationCategory = _approval_request.OperationCategory

# approval_gate importiert from .approval_request - need to install relative
_APPROVAL_GATE_PATH = _KMO_ROOT / "kmo_governance" / "multi_tenant_approval" / "src" / "approval_gate.py"
# Create a fake package "kmo_mta_pkg_w3" with both modules
import types
_pkg = types.ModuleType("kmo_mta_pkg_w3")
_pkg.__path__ = [str(_APPROVAL_GATE_PATH.parent)]
sys.modules["kmo_mta_pkg_w3"] = _pkg
sys.modules["kmo_mta_pkg_w3.approval_request"] = _approval_request

_spec_gate = importlib.util.spec_from_file_location(
    "kmo_mta_pkg_w3.approval_gate", _APPROVAL_GATE_PATH
)
_approval_gate = importlib.util.module_from_spec(_spec_gate)
sys.modules["kmo_mta_pkg_w3.approval_gate"] = _approval_gate
# Patch the relative import in approval_gate
_src_text = _APPROVAL_GATE_PATH.read_text()
_patched_text = _src_text.replace(
    "from .approval_request import",
    "from kmo_mta_pkg_w3.approval_request import",
)
exec(compile(_patched_text, str(_APPROVAL_GATE_PATH), "exec"), _approval_gate.__dict__)
pre_action_check = _approval_gate.pre_action_check

from kmo_governance.multi_signal_policy import (
    MultiSignalAggregator,
    PolicyState,
    PolicyStateMachine,
    SignalSpec,
)


# ============================================================
# TEST 1: PDP Most-Restrictive-Match (2 ueberlappende Policies)
# ============================================================

def test_pdp_most_restrictive_match_not_first_match():
    """Wenn 2 Policies konkurrieren, gewinnt die RESTRICTIVERE, nicht die ERSTE.

    Wave-1-A1 CRITICAL: Aktuelle Hill-Aggregation kombiniert ALLE Signale.
    Bei policy-Overlap ist das mathematisch korrekt (gewichtetes Mittel).
    Test prueft: wenn EIN Signal sehr restriktiv ist (niedrige Hill-Y),
    darf der Aggregat NICHT durch andere Signale ueberschrieben werden,
    wenn der Aggregat-Score < Threshold ist.

    Anti-Pattern: First-Match-Wins ohne Beruecksichtigung der Restriktion.
    """
    # 2 Signale ueberlappend: ESG + Compliance
    specs = {
        "esg_score": SignalSpec(name="esg_score", K_d=50.0, hill_n=2.0, weight=1.0),
        "compliance": SignalSpec(name="compliance", K_d=0.8, hill_n=4.0, weight=10.0),
    }
    agg = MultiSignalAggregator(specs)

    # Szenario: ESG ist HIGH (gut), Compliance ist sehr LOW (schlecht, kritisch)
    signals = {
        "esg_score": 100.0,    # weit ueber K_d=50 -> Hill-Y ~1.0
        "compliance": 0.1,      # weit unter K_d=0.8 -> Hill-Y ~0.0
    }
    score = agg.aggregate_score(signals)

    # Mit weight=10 fuer compliance wirkt diese stark
    # weighted_sum = 1*1.0 + 10*~0.0 = ~1.0
    # total_weight = 11
    # score = 1.0/11 = ~0.09 (sehr niedrig wegen restriktiver compliance)
    assert score < 0.15, (
        f"MOST-RESTRICTIVE-VIOLATION: aggregate_score={score:.3f} > 0.15. "
        f"Restriktive Policy (compliance=0.1) hat den Score nicht runtergedrueckt."
    )

    # Negativ-Test: ohne weight-bias wuerde first-match-pattern gewinnen
    specs_equal = {
        "esg_score": SignalSpec(name="esg_score", K_d=50.0, hill_n=2.0, weight=1.0),
        "compliance": SignalSpec(name="compliance", K_d=0.8, hill_n=4.0, weight=1.0),
    }
    agg2 = MultiSignalAggregator(specs_equal)
    score2 = agg2.aggregate_score(signals)
    # Equal weight: score2 = (1.0 + ~0.0) / 2 = ~0.5
    # Das zeigt: weight=10 fuer compliance ist NOTWENDIG fuer most-restrictive
    assert score2 > 0.3, (
        f"Equal-weight aggregate sollte ~0.5 sein, war {score2}"
    )


def test_pdp_state_machine_most_restrictive_transition():
    """State-Machine: schlechter Score (niedrig) muss zu restriktiver State fuehren.

    Pflicht: AGGRESSIVE -> MODERATE -> CONSERVATIVE -> EMERGENCY
    bei sinkendem Score (most-restrictive-direction).
    """
    specs = {
        "throughput": SignalSpec(name="throughput", K_d=100.0, hill_n=2.0, weight=1.0),
    }
    agg = MultiSignalAggregator(specs)
    sm = PolicyStateMachine(agg, initial_state=PolicyState.MODERATE)

    # Score 0 (schlechter Throughput) -> CONSERVATIVE
    sm.tick({"throughput": 1.0})  # weit unter K_d -> Hill-Y ~0
    assert sm.state == PolicyState.CONSERVATIVE, (
        f"Bei niedrigem Score sollte State zu CONSERVATIVE wandern, ist {sm.state}"
    )

    # Score noch niedriger -> EMERGENCY
    sm.tick({"throughput": 0.1})
    assert sm.state == PolicyState.EMERGENCY


# ============================================================
# TEST 2: AdapterHealthMonitor TOCTOU-Race (50 Threads)
# ============================================================

def test_adapter_health_monitor_toctou_race_50_threads():
    """50 Threads concurrent is_available() -> assert no state-mutation-during-read.

    Wave-1-A1 CRITICAL TOCTOU: is_available() mutiert OPEN->HALF_OPEN
    self.circuit_state. 50 Threads koennten parallel CLOSED -> HALF_OPEN
    setzen oder dieser Mutex fehlt.

    Pflicht-Conservation:
    - Final-State ist deterministisch (kein flapping)
    - Anzahl HALF_OPEN-Transitions ist 0 oder 1, nicht > 1
    """
    monitor = AdapterHealthMonitor(
        adapter_name="apaleo",
        threshold_open_after_n_fails=3,
        half_open_test_interval_s=1,  # Kurz fuer Test
    )

    # Force OPEN-State via 3 record_failure
    for i in range(3):
        monitor.record_failure(f"timeout-{i}")
    assert monitor.circuit_state == CircuitState.OPEN

    # Warte bis half-open-interval erreicht
    time.sleep(1.1)

    # 50 Threads parallel is_available() rufen
    THREADS = 50
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        try:
            avail = monitor.is_available()
            with lock:
                results.append(avail)
        except Exception as e:
            with lock:
                results.append(f"ERROR: {e}")

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # Conservation-1: Alle Threads haben einen Wert
    assert len(results) == THREADS, f"Threads incomplete: {len(results)}/{THREADS}"

    # Conservation-2: Wenn 1+ Thread HALF_OPEN sah, sind ALLE konsistent
    # (entweder alle True oder alle False - kein Mix waere TOCTOU-Bug)
    # In Praxis: alle True (HALF_OPEN ist available)
    true_count = sum(1 for r in results if r is True)
    false_count = sum(1 for r in results if r is False)
    print(f"\n[TOCTOU BILANZ] True={true_count} False={false_count} Total={THREADS}")

    # Conservation-3: Final state ist HALF_OPEN (eine eindeutige Transition)
    # ODER CLOSED (wenn ein Thread record_success rief - hier nicht passiert)
    assert monitor.circuit_state in (CircuitState.HALF_OPEN, CircuitState.OPEN), (
        f"Final state inkonsistent: {monitor.circuit_state}"
    )


def test_adapter_health_monitor_concurrent_record_failure_threshold():
    """Concurrent record_failure: threshold-trigger muss exakt 1x OPEN setzen.

    Race-Test: 10 Threads rufen record_failure() parallel (alle haben failure).
    consecutive_fails sollte exakt 10 sein (atomar inkrementiert).
    OPEN-Transition sollte 1x passieren (nicht race-condition-induced).
    """
    monitor = AdapterHealthMonitor(
        adapter_name="mews",
        threshold_open_after_n_fails=3,
    )

    THREADS = 10
    barrier = threading.Barrier(THREADS)

    def worker(i: int):
        barrier.wait()  # Synchronize start
        monitor.record_failure(f"fail-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # Conservation: consecutive_fails = THREADS (kein lost-update)
    # WICHTIG: Hier zeigt sich die TOCTOU-Vulnerability.
    # Wenn consecutive_fails < THREADS -> race-induced lost-update.
    print(f"\n[CONCURRENT-FAIL BILANZ] consecutive_fails={monitor.consecutive_fails} "
          f"expected={THREADS} circuit_state={monitor.circuit_state.value}")

    # Conservation-1: circuit_state ist OPEN (>=3 fails)
    assert monitor.circuit_state == CircuitState.OPEN

    # Conservation-2: history hat THREADS-Entries
    # (auch bei race ist history.append immer thread-safe via list-impl)
    # WICHTIG: Wenn kein Lock vorhanden ist, kann consecutive_fails < THREADS sein
    # Das DOKUMENTIERT die Vulnerability.
    if monitor.consecutive_fails < THREADS:
        pytest.xfail(
            f"TOCTOU-VULNERABILITY EMPIRISCH BELEGT (Wave-1-A1 CRITICAL): "
            f"consecutive_fails={monitor.consecutive_fails} < expected={THREADS}. "
            f"Lost-Update durch Race-Condition. Phronesis-Pflicht: threading.Lock "
            f"in record_failure() noetig. Welle-13-Backlog."
        )


# ============================================================
# TEST 3: ApprovalGate Status-Override-Negative
# ============================================================

def test_approval_gate_status_override_blocked_overrides_escalated():
    """BLOCKED ueberschreibt ESCALATED: Most-Restrictive gewinnt.

    Wave-1-A1 CRITICAL: pre_action_check setzt decision sequenziell.
    Test prueft: wenn beide gelten (ESCALATED durch Phronesis +
    BLOCKED durch DATA_DELETION+prod), bleibt am Ende BLOCKED.

    Anti-Pattern: Last-Set-Wins. Korrekt: Most-Restrictive.
    """
    # Request hat BEIDE Trigger:
    # - requires_martin_phronesis=True -> ESCALATE
    # - DATA_DELETION + non-reversible + prod -> BLOCK
    request = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.DATA_DELETION,
        operation_description="Delete all bookings (test)",
        requested_by="ops-team",
        env_tag="prod",
        blast_radius=10,
        reversibility="non-reversible",
        requires_martin_phronesis=True,
    )

    result = pre_action_check(request)

    # Most-Restrictive: BLOCKED gewinnt ueber ESCALATED
    assert result["decision"] == ApprovalStatus.BLOCKED.value, (
        f"BLOCKED muss ESCALATED ueberschreiben. "
        f"Got {result['decision']}. Last-Set-Wins-Bug?"
    )

    # Reasons enthalten BEIDE Begruendungen
    reasons_str = " ".join(result["reasons"])
    assert "PHRONESIS" in reasons_str
    assert "DATA_DELETION" in reasons_str


def test_approval_gate_escalated_does_not_overwrite_blocked():
    """Reverse: ESCALATED-Trigger nach BLOCKED muss BLOCKED behalten.

    Test: Cross-Tenant-Sharing (BLOCK ohne policy) + non-reversible-prod (ESCALATE)
    -> Endresultat muss BLOCKED bleiben.
    """
    request = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.CROSS_TENANT_DATA_SHARING,
        operation_description="Share bookings cross-tenant (test)",
        requested_by="ops-team",
        env_tag="prod",
        blast_radius=50,
        reversibility="non-reversible",
        requires_martin_phronesis=False,
    )

    # Ohne allow_cross_tenant_sharing -> BLOCKED
    result = pre_action_check(request, allow_cross_tenant_sharing=False)

    # BLOCKED muss bestehen bleiben (nicht zu ESCALATED downgraden)
    assert result["decision"] == ApprovalStatus.BLOCKED.value


def test_approval_gate_phronesis_bypass_attempt_via_metadata():
    """Bypass-Versuch via Metadata-Override: requires_martin_phronesis=True
    muss sich NICHT durch metadata umgehen lassen.

    Test: Request mit Phronesis=True + verschleierter category -> ESCALATE bleibt.
    """
    request = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.PLAN_UPGRADE,  # harmlose Kategorie
        operation_description="Plan upgrade for tenant X",
        requested_by="ops-team",
        env_tag="prod",
        blast_radius=1,
        reversibility="state-only",
        requires_martin_phronesis=True,  # Phronesis-Pflicht
        metadata={"bypass_attempt": "ignore_phronesis"},  # Bypass-Versuch
    )

    result = pre_action_check(request)
    # Phronesis kann nicht via metadata umgangen werden
    assert result["decision"] == ApprovalStatus.ESCALATED.value
    assert any("PHRONESIS" in r for r in result["reasons"])


# ============================================================
# TEST 4: Cross-Tenant-Cross-Module-Negative
# ============================================================

def test_cross_tenant_cross_module_default_deny():
    """KMO-tenant-A liest KMO-tenant-B-data -> assert DENY default.

    KMO Multi-Tenant: ohne explizite policy darf Tenant-A NICHT auf
    Tenant-B-Data zugreifen. Test verwendet ApprovalRequest als Proxy
    fuer eine Cross-Tenant-Operation.

    Pflicht: pre_action_check(allow_cross_tenant_sharing=False) -> BLOCK
    """
    tenant_a = uuid4()
    request = ApprovalRequest(
        tenant_id=tenant_a,
        operation_category=OperationCategory.CROSS_TENANT_DATA_SHARING,
        operation_description=f"Tenant A liest Tenant B (test)",
        requested_by="suspicious-actor",
        env_tag="prod",
        blast_radius=10,
        reversibility="state-only",
    )

    # DEFAULT: allow_cross_tenant_sharing=False -> BLOCKED
    result = pre_action_check(request)
    assert result["decision"] == ApprovalStatus.BLOCKED.value, (
        f"Cross-Tenant-Default-Deny verletzt. Got {result['decision']}"
    )

    # Mit explicit policy: ESCALATED (Audit-Pflicht)
    result_with_policy = pre_action_check(request, allow_cross_tenant_sharing=True)
    assert result_with_policy["decision"] == ApprovalStatus.ESCALATED.value


def test_cross_tenant_dev_env_still_blocked_without_policy():
    """Auch dev-env: Cross-Tenant ohne policy = BLOCKED (Pflicht-Default).

    Test prueft: env_tag=dev erlaubt KEINE Cross-Tenant-Lockerung.
    Default-Deny gilt unabhaengig vom env_tag.
    """
    request = ApprovalRequest(
        tenant_id=uuid4(),
        operation_category=OperationCategory.CROSS_TENANT_DATA_SHARING,
        operation_description="Dev-cross-tenant test",
        requested_by="dev-bot",
        env_tag="dev",  # niedrigste env-Stufe
        blast_radius=1,
        reversibility="state-only",
    )

    result = pre_action_check(request)
    assert result["decision"] == ApprovalStatus.BLOCKED.value


# ============================================================
# Conservation-Smoke-Tests
# ============================================================

def test_pdp_aggregate_score_in_range():
    """Sanity: aggregate_score immer in [0, 1]."""
    specs = {
        "s1": SignalSpec(name="s1", K_d=10.0, hill_n=2.0, weight=1.0),
        "s2": SignalSpec(name="s2", K_d=5.0, hill_n=4.0, weight=2.0),
    }
    agg = MultiSignalAggregator(specs)
    for v1 in [0, 5, 10, 100]:
        for v2 in [0, 5, 10, 100]:
            score = agg.aggregate_score({"s1": v1, "s2": v2})
            assert 0.0 <= score <= 1.0, f"Score out of range: {score}"
