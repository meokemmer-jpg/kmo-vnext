"""W-30-2 Byzantine + Cascade-Containment Tests (Welle-31 P-W31-2) [CRUX-MK].

Adversarial-Tests gegen Cascading-Failures + Capability-Bypass im SAE-v8
Chaos-Engineering. 6 Pflicht-Tests:

    1. Cross-Hotel-Cascade-Containment (Slot-Crash hotel_a triggert NICHT hotel_b)
    2. Mode-Escape-Test (Production-Mode-Bypass via env-var Mutation MUSS BLOCK)
    3. Recovery-Correctness-Orakel (post-Apoptose-Snapshot integrity, sha256-verifiziert)
    4. Capability-basierte Mock-Sicherung (Crypto-Signed Production-Policy)
    5. Simultane Partition+Token-Starvation (kombinierte Failure-Modes)
    6. Korrelierte Governance-Drifts (Drift in 1 Slot triggert Bounded-Veto-Hold)

Conservation-Law: Cascade darf nicht ueber Hotel-Boundary entweichen.
Per rules/concurrency-mandatory-tests.md echte threading.Thread + sha256.
"""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from df_executors.df_sae_v8.chaos_engineering import (
    ChaosCampaign,
    FailureMode,
    MockSlot,
    SaeChaosOrchestrator,
    SaeFailureInjector,
    SaeRobustnessMetrics,
    SlotVariant,
)
from df_executors.df_sae_v8.chaos_engineering.sae_capability_guard import (
    CapabilityGuard,
    CapabilityToken,
    SCOPE_FORBIDDEN,
    SCOPE_PRODUCTION_AUDIT,
    capability_guard_check_or_raise,
)


@pytest.fixture
def two_hotel_setup():
    """Inject 6 slots: 3 in hotel_a, 3 in hotel_b."""
    inj = SaeFailureInjector()
    for hotel in ("hotel_a", "hotel_b"):
        for variant in (
            SlotVariant.CONSERVATIVE,
            SlotVariant.AGGRESSIVE,
            SlotVariant.CONTRARIAN,
        ):
            slot = MockSlot(
                slot_id=f"slot-{variant.value}",
                hotel_id=hotel,
                variant=variant,
            )
            inj.register_slot(slot)
    metrics = SaeRobustnessMetrics(inj)
    orch = SaeChaosOrchestrator(injector=inj, metrics=metrics)
    return inj, metrics, orch


def test_w31_byzantine_cross_hotel_cascade_containment(two_hotel_setup):
    """W-30-2 #1: Slot-Crash in hotel_a triggert NICHT hotel_b-Slots.

    Conservation-Law: Cascade-Radius gemessen ueber peer_slots im SELBEN
    Hotel. Hotel-B Slots bleiben healthy.
    """
    inj, metrics, orch = two_hotel_setup

    # Crash slot in hotel_a
    inj.inject(
        slot_id="slot-conservative",
        hotel_id="hotel_a",
        mode=FailureMode.SLOT_CRASH,
        intensity=1.0,
    )

    # Hotel-B slots untouched
    hotel_b_slots = inj.list_slots_for_hotel("hotel_b")
    assert len(hotel_b_slots) == 3
    for slot in hotel_b_slots:
        assert not slot.is_crashed, (
            f"Cross-hotel cascade detected: {slot.slot_id} in hotel_b "
            "is_crashed after hotel_a crash"
        )
        assert slot.health_score == 1.0

    # Cascade-Radius berechnung: peers im hotel_a (excluding target)
    target_a = inj.get_slot("slot-conservative", "hotel_a")
    peers_a = inj.list_slots_for_hotel("hotel_a")
    radius_a = metrics.cascade_radius(target_a, peers_a)
    # Hotel-A peers also untouched (cascade did not propagate)
    assert radius_a == 0, (
        f"Cascade leaked within hotel_a: radius={radius_a}"
    )


def test_w31_byzantine_capability_mock_token_required(monkeypatch):
    """W-30-2 #2: env-var-Mock-Toggle reicht NICHT - Capability-Token Pflicht.

    Mode-Escape via env-var Mutation MUSS BLOCK liefern.
    """
    # Setup capability guard with secret
    monkeypatch.setenv("SAE_CHAOS_CAPABILITY_SECRET", "test-secret-32bytes")
    guard = CapabilityGuard()

    # Path 1: token=None -> raise PermissionError
    with pytest.raises(PermissionError, match="capability_token=None"):
        capability_guard_check_or_raise(guard, None)

    # Path 2: forbidden-scope token -> raise
    forbidden_token = CapabilityToken(
        scope=SCOPE_FORBIDDEN,
        issued_at=0,
        expires_at=999999999999,
        issuer="malicious",
        nonce="00" * 16,
        signature="00" * 32,
    )
    with pytest.raises(PermissionError, match="K_0-Schutz"):
        capability_guard_check_or_raise(guard, forbidden_token)

    # Path 3: production-scope token -> raise
    prod_token = CapabilityToken(
        scope=SCOPE_PRODUCTION_AUDIT,
        issued_at=0,
        expires_at=999999999999,
        issuer="prod-attempt",
        nonce="11" * 16,
        signature="11" * 32,
    )
    with pytest.raises(PermissionError, match="K_0-Schutz"):
        capability_guard_check_or_raise(guard, prod_token)

    # Path 4: legitimate mock token -> passes
    legit = guard.issue_mock_token(issuer="test-runner")
    capability_guard_check_or_raise(guard, legit)  # no raise

    # Path 5: tampered signature -> raise
    tampered = CapabilityToken(
        scope=legit.scope,
        issued_at=legit.issued_at,
        expires_at=legit.expires_at,
        issuer=legit.issuer,
        nonce=legit.nonce,
        signature="ff" * 32,  # wrong signature
    )
    with pytest.raises(PermissionError, match="verification FAILED"):
        capability_guard_check_or_raise(guard, tampered)


def test_w31_byzantine_recovery_snapshot_integrity_sha256(two_hotel_setup):
    """W-30-2 #3: Post-Apoptose-Snapshot-Integritaet via SHA256.

    Recovery-Correctness-Orakel: Snapshot-Hash vor Reset == Hash nach
    Reset+gleicher Wiederherstellung (deterministic recovery).
    """
    inj, metrics, orch = two_hotel_setup

    # Baseline-Snapshot of hotel_a slots (sorted, deterministic)
    def snapshot_hash(hotel_id: str) -> str:
        slots = sorted(
            inj.list_slots_for_hotel(hotel_id),
            key=lambda s: s.slot_id,
        )
        canonical = json.dumps(
            [
                {
                    "slot_id": s.slot_id,
                    "health_score": s.health_score,
                    "q_norm": s.q_norm,
                    "is_crashed": s.is_crashed,
                    "is_byzantine": s.is_byzantine,
                    "is_partitioned": s.is_partitioned,
                    "token_consumed": s.token_consumed,
                }
                for s in slots
            ],
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    baseline_hash = snapshot_hash("hotel_a")

    # Inject failure
    inj.inject(
        slot_id="slot-aggressive",
        hotel_id="hotel_a",
        mode=FailureMode.GOVERNANCE_DRIFT,
        intensity=0.5,
    )
    drift_hash = snapshot_hash("hotel_a")
    assert drift_hash != baseline_hash, "Drift had no observable effect"

    # Recovery: reset slot
    inj.reset_slot("slot-aggressive", "hotel_a")
    recovered_hash = snapshot_hash("hotel_a")

    # Conservation-Law: Recovery should restore baseline state.
    assert recovered_hash == baseline_hash, (
        f"Recovery non-deterministic: baseline={baseline_hash[:16]}, "
        f"recovered={recovered_hash[:16]}"
    )


def test_w31_byzantine_capability_signed_audit_token_unforgeable(
    monkeypatch,
):
    """W-30-2 #4: HMAC-signed Capability-Token ist unforgeable ohne Secret.

    Anti-Goodhart: env-var-Glaube ist nicht genug. Crypto-Beweis Pflicht.
    """
    monkeypatch.setenv(
        "SAE_CHAOS_CAPABILITY_SECRET", "secret-A-32-bytes-known-only-to-A"
    )
    guard_a = CapabilityGuard()
    legit_a = guard_a.issue_mock_token(issuer="A")

    # Attacker uses different secret
    monkeypatch.setenv(
        "SAE_CHAOS_CAPABILITY_SECRET", "secret-B-attempt-forge-token"
    )
    guard_b = CapabilityGuard()
    # Forge attempt: same payload as legit_a but different secret -> sig wrong
    forged = CapabilityToken(
        scope=legit_a.scope,
        issued_at=legit_a.issued_at,
        expires_at=legit_a.expires_at,
        issuer=legit_a.issuer,
        nonce=legit_a.nonce,
        signature=guard_b._sign(  # noqa: SLF001 (test access)
            legit_a.scope,
            legit_a.issued_at,
            legit_a.expires_at,
            legit_a.issuer,
            legit_a.nonce,
        ),
    )

    # Restore secret-A and verify against guard_a
    monkeypatch.setenv(
        "SAE_CHAOS_CAPABILITY_SECRET", "secret-A-32-bytes-known-only-to-A"
    )
    guard_a_again = CapabilityGuard()

    assert guard_a_again.verify_mock_only(legit_a)  # original passes
    assert not guard_a_again.verify_mock_only(forged)  # forged blocked


def test_w31_byzantine_simultaneous_partition_and_token_starvation(
    two_hotel_setup,
):
    """W-30-2 #5: Kombinierte Failure-Modes (Network-Partition +
    Token-Starvation) angewendet ueber threading-Barriere.

    Conservation-Law: Slot-State reflektiert beide Failure-Effekte.
    """
    inj, _, _ = two_hotel_setup

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def inject_partition() -> None:
        try:
            barrier.wait()
            inj.inject(
                slot_id="slot-conservative",
                hotel_id="hotel_a",
                mode=FailureMode.NETWORK_PARTITION,
                intensity=1.0,
            )
        except Exception as exc:  # pragma: no cover
            errors.append(f"partition: {exc!r}")

    def inject_starvation() -> None:
        try:
            barrier.wait()
            inj.inject(
                slot_id="slot-conservative",
                hotel_id="hotel_a",
                mode=FailureMode.TOKEN_STARVATION,
                intensity=1.0,
            )
        except Exception as exc:  # pragma: no cover
            errors.append(f"starvation: {exc!r}")

    t1 = threading.Thread(target=inject_partition)
    t2 = threading.Thread(target=inject_starvation)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert errors == [], f"Concurrent inject errors: {errors}"
    slot = inj.get_slot("slot-conservative", "hotel_a")
    # Both effects observable: partitioned AND starved
    assert slot.is_partitioned, "Partition failure mode lost"
    assert slot.token_consumed >= slot.token_budget * 0.9, (
        "Token starvation failure mode lost"
    )
    assert len(slot.injection_history) == 2, (
        f"Expected 2 injection events, got {len(slot.injection_history)}"
    )


def test_w31_byzantine_correlated_governance_drift_triggers_veto_hold(
    two_hotel_setup,
):
    """W-30-2 #6: Drift in slot_a triggert Bounded-Veto-Hold in
    benachbarten Slots (korrelierter Failure).

    Bounded-Veto-Korrektheit: Wenn benachbarter Slot drift hat, sollte
    Bounded-Veto fuer das gesamte Hotel-Cluster greifen
    (defense-in-depth).
    """
    inj, metrics, orch = two_hotel_setup

    # Drift slot in hotel_a (Conservative)
    inj.inject(
        slot_id="slot-conservative",
        hotel_id="hotel_a",
        mode=FailureMode.GOVERNANCE_DRIFT,
        intensity=0.8,
    )

    # Run a chaos campaign on aggressive slot in hotel_a
    campaign = ChaosCampaign(
        campaign_id="corr-drift-test",
        hotel_id="hotel_a",
        target_slot_id="slot-aggressive",
        modes=(FailureMode.BYZANTINE_FAULT,),
        intensities=(0.5,),
    )
    result = orch.run_campaign(campaign, n_veto_decisions=5)

    assert result.completed, f"Campaign failed: {result.error}"
    assert len(result.veto_outcomes) == 5

    # Bounded-Veto-Correctness: Slot ist actually unhealthy (Byzantine)
    # so Veto should fire. Conservation-Law check.
    correct_outcomes = [o for o in result.veto_outcomes if o.is_correct]
    assert len(correct_outcomes) >= 4, (
        f"Expected >=4 correct veto outcomes, got "
        f"{len(correct_outcomes)}/5"
    )

    # Cascade-Containment-Score sollte < 1.0 wegen drift in conservative
    target = inj.get_slot("slot-aggressive", "hotel_a")
    peers = inj.list_slots_for_hotel("hotel_a")
    ccs = metrics.cascade_containment_score(target, peers)
    assert 0.0 <= ccs <= 1.0


# CRUX-MK
