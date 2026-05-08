"""SAE-v8 Chaos-Engineering Tests [CRUX-MK].

Welle-30 W-30-2 Test-Pack. Pflicht: >=14 Tests + Coverage >=80% +
KEINE echte SAE-Slot-Aktivierung.

Test-Klassen:
    A) Failure-Injector core API     B) Trinity-Variant-Verhalten
    C) K_0-Schutz                    D) Multi-Tenancy-Isolation
    E) Robustness-Metrics            F) Chaos-Orchestrator
    G) Bcl-2-Analogon                H) Edge-Cases
"""

from __future__ import annotations

import pytest

from df_executors.df_sae_v8.chaos_engineering import (
    BoundedVetoOutcome, ChaosCampaign, DEFAULT_TOKEN_BUDGET,
    FailureMode, InjectionEvent, MockSlot, RobustnessReport,
    SaeChaosOrchestrator, SaeFailureInjector, SaeRobustnessMetrics, SlotVariant,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def fixed_clock():
    """Injectable clock fuer reproducible time-tests."""
    state = {"t": 1_700_000_000.0}

    def clock() -> float:
        return state["t"]

    def tick(dt: float) -> None:
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def injector(fixed_clock):
    return SaeFailureInjector(clock=fixed_clock)


@pytest.fixture
def metrics(injector):
    return SaeRobustnessMetrics(injector)


@pytest.fixture
def orch(injector, metrics, fixed_clock):
    return SaeChaosOrchestrator(injector=injector, metrics=metrics, clock=fixed_clock)


@pytest.fixture
def trinity_slots(injector):
    """Registriere SAE-Trinity-Slot (3 Varianten) fuer hotel-A."""
    slots = []
    for variant in SlotVariant:
        s = MockSlot(
            slot_id=f"slot-1-{variant.value}", hotel_id="hotel-A",
            variant=variant, mock_mode_only=True,
        )
        injector.register_slot(s)
        slots.append(s)
    return slots


# ============================================================
# A) Failure-Injector core API
# ============================================================


def test_a01_register_and_get_slot(injector):
    slot = MockSlot(slot_id="slot-1", hotel_id="hotel-A",
                    variant=SlotVariant.CONSERVATIVE, mock_mode_only=True)
    injector.register_slot(slot)
    fetched = injector.get_slot("slot-1", "hotel-A")
    assert fetched is slot
    assert fetched.health_score == 1.0


def test_a02_inject_slot_crash_zeroes_health(injector, trinity_slots):
    """SLOT_CRASH intensity=1.0 -> is_crashed + health=0."""
    event = injector.inject(
        slot_id="slot-1-conservative", hotel_id="hotel-A",
        mode=FailureMode.SLOT_CRASH, intensity=1.0,
    )
    assert isinstance(event, InjectionEvent)
    assert event.mode is FailureMode.SLOT_CRASH
    slot = injector.get_slot("slot-1-conservative", "hotel-A")
    assert slot.is_crashed
    assert slot.health_score == 0.0
    assert len(slot.injection_history) == 1
    assert slot.injection_history[0].event_id == event.event_id


def test_a03_inject_token_starvation_consumes_budget(injector, trinity_slots):
    """TOKEN_STARVATION intensity=0.5 -> 50% des Budgets verbraucht."""
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.TOKEN_STARVATION, intensity=0.5)
    slot = injector.get_slot("slot-1-conservative", "hotel-A")
    assert slot.token_consumed == DEFAULT_TOKEN_BUDGET // 2
    assert 0.4 < slot.health_score < 0.6


def test_a04_inject_byzantine_fault_lies_about_qnorm(injector, trinity_slots):
    """BYZANTINE_FAULT erhoeht q_norm (slot luegt) ohne is_crashed."""
    injector.inject("slot-1-aggressive", "hotel-A",
                    FailureMode.BYZANTINE_FAULT, intensity=1.0)
    slot = injector.get_slot("slot-1-aggressive", "hotel-A")
    assert slot.is_byzantine
    assert not slot.is_crashed
    assert slot.q_norm > 0
    assert slot.health_score == 1.0  # Byzantine ist subtil


def test_a05_reset_slot_restores_pristine_state(injector, trinity_slots):
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.SLOT_CRASH, intensity=1.0)
    injector.reset_slot("slot-1-conservative", "hotel-A")
    slot = injector.get_slot("slot-1-conservative", "hotel-A")
    assert slot.health_score == 1.0
    assert slot.token_consumed == 0
    assert not slot.is_crashed
    assert not slot.is_partitioned
    assert not slot.is_byzantine
    assert slot.q_norm == 0.0


# ============================================================
# B) Trinity-Variant-spezifisches Verhalten
# ============================================================


def test_b01_conservative_variant_recovers_exponentially(
    injector, trinity_slots, fixed_clock
):
    """Conservative Slot erholt sich exponentiell nach Network-Partition."""
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.NETWORK_PARTITION, intensity=0.7)
    health_immediate = injector.compute_health("slot-1-conservative", "hotel-A")
    assert health_immediate < 1.0
    fixed_clock.tick(60.0)
    health_later = injector.compute_health("slot-1-conservative", "hotel-A")
    assert health_later > health_immediate
    assert health_later > 0.7


def test_b02_aggressive_variant_damage_ramp(injector, trinity_slots, fixed_clock):
    """Aggressive Slot verschlimmert sich linear ueber Zeit."""
    injector.inject("slot-1-aggressive", "hotel-A",
                    FailureMode.NETWORK_PARTITION, intensity=0.3)
    health_initial = injector.compute_health("slot-1-aggressive", "hotel-A")
    fixed_clock.tick(5.0)
    health_after = injector.compute_health("slot-1-aggressive", "hotel-A")
    assert health_after < health_initial


def test_b03_contrarian_variant_binary_no_decay(injector, trinity_slots, fixed_clock):
    """Contrarian-Slot ist binaer: kein gradient mit Zeit."""
    injector.inject("slot-1-contrarian", "hotel-A",
                    FailureMode.NETWORK_PARTITION, intensity=0.4)
    health_initial = injector.compute_health("slot-1-contrarian", "hotel-A")
    fixed_clock.tick(120.0)
    health_later = injector.compute_health("slot-1-contrarian", "hotel-A")
    assert health_later == health_initial


# ============================================================
# C) K_0-Schutz
# ============================================================


def test_c01_mock_mode_false_rejected_at_construction():
    """K_0-Schutz: MockSlot mit mock_mode_only=False raises PermissionError."""
    with pytest.raises(PermissionError, match="mock_mode_only"):
        MockSlot(slot_id="evil", hotel_id="hotel-A",
                 variant=SlotVariant.CONSERVATIVE, mock_mode_only=False)


def test_c02_orchestrator_pre_run_blocks_non_mock_slots(orch, injector):
    """Orchestrator blockiert Run wenn mock_mode_only=False (post-construction-leak)."""
    slot = MockSlot(slot_id="slot-1", hotel_id="hotel-A",
                    variant=SlotVariant.CONSERVATIVE, mock_mode_only=True)
    injector.register_slot(slot)
    slot.mock_mode_only = False  # simuliere production-leak
    campaign = ChaosCampaign(
        campaign_id="c-evil", hotel_id="hotel-A", target_slot_id="slot-1",
        modes=(FailureMode.SLOT_CRASH,),
    )
    result = orch.run_campaign(campaign)
    assert not result.completed
    assert result.error is not None
    assert "K_0-Schutz" in result.error or "mock_mode_only" in result.error


# ============================================================
# D) Multi-Tenancy-Isolation
# ============================================================


def test_d01_inject_hotel_a_does_not_affect_hotel_b(injector):
    """Failure in hotel-A Slot beeinflusst hotel-B Slot nicht."""
    slot_a = MockSlot(slot_id="slot-1", hotel_id="hotel-A",
                      variant=SlotVariant.CONSERVATIVE, mock_mode_only=True)
    slot_b = MockSlot(slot_id="slot-1", hotel_id="hotel-B",
                      variant=SlotVariant.CONSERVATIVE, mock_mode_only=True)
    injector.register_slot(slot_a)
    injector.register_slot(slot_b)
    injector.inject("slot-1", "hotel-A", FailureMode.SLOT_CRASH, intensity=1.0)
    assert slot_a.is_crashed
    assert not slot_b.is_crashed
    assert slot_b.health_score == 1.0


def test_d02_list_slots_for_hotel_filters_correctly(injector):
    slot_a = MockSlot(slot_id="slot-A", hotel_id="hotel-A",
                      variant=SlotVariant.CONSERVATIVE, mock_mode_only=True)
    slot_b = MockSlot(slot_id="slot-B", hotel_id="hotel-B",
                      variant=SlotVariant.AGGRESSIVE, mock_mode_only=True)
    injector.register_slot(slot_a)
    injector.register_slot(slot_b)
    a_slots = injector.list_slots_for_hotel("hotel-A")
    b_slots = injector.list_slots_for_hotel("hotel-B")
    assert len(a_slots) == 1 and a_slots[0].slot_id == "slot-A"
    assert len(b_slots) == 1 and b_slots[0].slot_id == "slot-B"


# ============================================================
# E) Robustness-Metrics
# ============================================================


def test_e01_recovery_time_conservative_meets_deadline(
    injector, metrics, trinity_slots
):
    """Conservative variant: RTH < deadline (60s)."""
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.NETWORK_PARTITION, intensity=0.4)
    rth = metrics.recovery_time_to_threshold(
        "slot-1-conservative", "hotel-A", threshold=0.5
    )
    assert rth >= 0
    assert rth < 60.0


def test_e02_aggressive_variant_no_recovery_without_reset(
    injector, metrics, trinity_slots
):
    """Aggressive variant: nach Damage kein automatic Recovery (RTH = inf)."""
    injector.inject("slot-1-aggressive", "hotel-A",
                    FailureMode.NETWORK_PARTITION, intensity=0.95)
    slot = injector.get_slot("slot-1-aggressive", "hotel-A")
    slot.health_score = 0.2
    rth = metrics.recovery_time_to_threshold(
        "slot-1-aggressive", "hotel-A", threshold=0.5
    )
    assert rth == float("inf")


def test_e03_cascade_containment_perfect_when_isolated(
    injector, metrics, trinity_slots
):
    """Wenn nur target-slot betroffen: CCS = 1.0."""
    target = injector.get_slot("slot-1-conservative", "hotel-A")
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.SLOT_CRASH, intensity=1.0)
    peers = injector.list_slots_for_hotel("hotel-A")
    ccs = metrics.cascade_containment_score(target, peers)
    assert ccs == 1.0


def test_e04_bounded_veto_correctness_perfect_when_aligned(metrics):
    outcomes = [
        BoundedVetoOutcome(
            decision_id=f"d-{i}", slot_id="slot-1", hotel_id="hotel-A",
            veto_activated=(i % 2 == 0),
            slot_was_actually_unhealthy=(i % 2 == 0), timestamp=0.0,
        ) for i in range(4)
    ]
    bvk = metrics.bounded_veto_correctness(outcomes)
    assert bvk == 1.0


def test_e05_bounded_veto_outcome_classifies_false_positive_negative(metrics):
    """is_false_positive / is_false_negative klassifizieren korrekt."""
    fp = BoundedVetoOutcome(
        decision_id="d-fp", slot_id="slot-1", hotel_id="hotel-A",
        veto_activated=True, slot_was_actually_unhealthy=False, timestamp=0.0,
    )
    assert fp.is_false_positive
    assert not fp.is_false_negative
    assert not fp.is_correct
    fn = BoundedVetoOutcome(
        decision_id="d-fn", slot_id="slot-1", hotel_id="hotel-A",
        veto_activated=False, slot_was_actually_unhealthy=True, timestamp=0.0,
    )
    assert fn.is_false_negative
    assert not fn.is_false_positive
    assert not fn.is_correct


def test_e06_evaluate_bounded_veto_uses_groundtruth(injector, metrics, trinity_slots):
    """evaluate_bounded_veto matched Veto-Aktivierung mit echtem Slot-State."""
    slot = injector.get_slot("slot-1-conservative", "hotel-A")
    outcome = metrics.evaluate_bounded_veto(
        slot=slot, veto_activated=True, decision_id="d-1", timestamp=0.0,
    )
    assert outcome.is_false_positive
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.SLOT_CRASH, intensity=1.0)
    slot_after = injector.get_slot("slot-1-conservative", "hotel-A")
    outcome2 = metrics.evaluate_bounded_veto(
        slot=slot_after, veto_activated=False, decision_id="d-2", timestamp=0.0,
    )
    assert outcome2.is_false_negative


# ============================================================
# F) Chaos-Orchestrator
# ============================================================


def test_f01_run_campaign_completes_with_report(orch, trinity_slots):
    """Campaign laeuft durch; ExperimentResult.completed=True + Report."""
    campaign = ChaosCampaign(
        campaign_id="c-1", hotel_id="hotel-A",
        target_slot_id="slot-1-conservative",
        modes=(FailureMode.NETWORK_PARTITION, FailureMode.HEARTBEAT_TIMEOUT),
        intensities=(0.6, 0.4),
    )
    result = orch.run_campaign(campaign)
    assert result.completed
    assert result.error is None
    assert len(result.injection_events) == 2
    assert isinstance(result.report, RobustnessReport)
    assert result.report.target_slot_id == "slot-1-conservative"
    assert result.report.variant == SlotVariant.CONSERVATIVE


def test_f02_run_campaign_with_byzantine_triggers_correct_veto(orch, trinity_slots):
    """Byzantine-Slot sollte Bounded-Veto ausloesen (correct decision)."""
    campaign = ChaosCampaign(
        campaign_id="c-byz", hotel_id="hotel-A",
        target_slot_id="slot-1-aggressive",
        modes=(FailureMode.BYZANTINE_FAULT,), intensities=(1.0,),
    )
    result = orch.run_campaign(campaign)
    assert result.completed
    correct_vetos = [o for o in result.veto_outcomes
                     if o.veto_activated and o.is_correct]
    assert len(correct_vetos) > 0


def test_f03_invalid_target_slot_returns_error_not_crash(orch, trinity_slots):
    """Campaign mit unbekanntem target_slot -> result.error gesetzt, kein Exception."""
    campaign = ChaosCampaign(
        campaign_id="c-bad", hotel_id="hotel-A",
        target_slot_id="slot-does-not-exist",
        modes=(FailureMode.SLOT_CRASH,),
    )
    result = orch.run_campaign(campaign)
    assert not result.completed
    assert result.error is not None
    assert ("not in hotel" in result.error or "not registered" in result.error
            or "KeyError" in result.error)


# ============================================================
# G) Bcl-2-Analogon (Bounded-Veto-Protection)
# ============================================================


def test_g01_protect_decision_holds_back_veto(orch, injector, trinity_slots):
    """Bounded-Veto-Protection blockiert Veto-Aktivierung waehrend TTL."""
    decision_id = "critical-decision-1"
    orch.protect_decision(decision_id, ttl_sec=300)
    injector.inject("slot-1-conservative", "hotel-A",
                    FailureMode.SLOT_CRASH, intensity=1.0)
    campaign = ChaosCampaign(
        campaign_id="c-protected", hotel_id="hotel-A",
        target_slot_id="slot-1-conservative",
        modes=(FailureMode.HEARTBEAT_TIMEOUT,), intensities=(0.5,),
        veto_protection_decision_ids=(decision_id,),
    )
    result = orch.run_campaign(campaign)
    assert result.completed
    held_back = [o for o in result.veto_outcomes
                 if not o.veto_activated and o.slot_was_actually_unhealthy]
    assert len(held_back) > 0


def test_g02_release_protection_returns_bool(orch):
    """release_protection: True wenn token bekannt, False wenn unbekannt."""
    orch.protect_decision("d-known", ttl_sec=10)
    assert orch.release_protection("d-known") is True
    assert orch.release_protection("d-known") is False
    assert orch.release_protection("d-never-existed") is False


def test_g03_protect_decision_invalid_input_raises(orch):
    """protect_decision mit invalid input raises ValueError."""
    with pytest.raises(ValueError):
        orch.protect_decision("", ttl_sec=10)
    with pytest.raises(ValueError):
        orch.protect_decision("d-1", ttl_sec=0)
    with pytest.raises(ValueError):
        orch.protect_decision("d-1", ttl_sec=-5)


# ============================================================
# H) Edge-Cases
# ============================================================


def test_h01_chaos_campaign_validates_input():
    """ChaosCampaign-Constructor enforces invariants."""
    with pytest.raises(ValueError, match="required"):
        ChaosCampaign(campaign_id="", hotel_id="hotel-A",
                      target_slot_id="slot-1", modes=(FailureMode.SLOT_CRASH,))
    with pytest.raises(ValueError, match="modes must contain"):
        ChaosCampaign(campaign_id="c-1", hotel_id="hotel-A",
                      target_slot_id="slot-1", modes=())
    with pytest.raises(ValueError, match="intensities length"):
        ChaosCampaign(campaign_id="c-1", hotel_id="hotel-A",
                      target_slot_id="slot-1",
                      modes=(FailureMode.SLOT_CRASH,),
                      intensities=(0.5, 0.6))
    with pytest.raises(ValueError, match=r"intensity .* not in"):
        ChaosCampaign(campaign_id="c-1", hotel_id="hotel-A",
                      target_slot_id="slot-1",
                      modes=(FailureMode.SLOT_CRASH,), intensities=(1.5,))


def test_h02_inject_invalid_input_raises(injector, trinity_slots):
    with pytest.raises(TypeError):
        injector.inject("slot-1-conservative", "hotel-A",
                        "not-a-mode", intensity=0.5)  # type: ignore
    with pytest.raises(ValueError):
        injector.inject("slot-1-conservative", "hotel-A",
                        FailureMode.SLOT_CRASH, intensity=1.5)
    with pytest.raises(KeyError):
        injector.inject("slot-does-not-exist", "hotel-A",
                        FailureMode.SLOT_CRASH, intensity=0.5)


def test_h03_overall_score_combines_metrics():
    """RobustnessReport.overall_score gewichtet 3 Komponenten."""
    report = RobustnessReport(
        recovery_time_sec=30.0, cascade_radius=0,
        cascade_containment_score=1.0, bounded_veto_correctness=1.0,
        deadline_met=True, cascade_within_limits=True,
    )
    assert report.overall_score == pytest.approx(1.0)
    report2 = RobustnessReport(
        recovery_time_sec=300.0, cascade_radius=5,
        cascade_containment_score=0.0, bounded_veto_correctness=0.5,
        deadline_met=False, cascade_within_limits=False,
    )
    assert report2.overall_score == pytest.approx(0.2)


def test_h04_multiple_injections_audit_trail_preserved(injector, trinity_slots):
    """Mehrere Inject-Calls werden alle in injection_history gespeichert."""
    for mode in (FailureMode.NETWORK_PARTITION,
                 FailureMode.HEARTBEAT_TIMEOUT,
                 FailureMode.GOVERNANCE_DRIFT):
        injector.inject("slot-1-conservative", "hotel-A", mode, intensity=0.3)
    slot = injector.get_slot("slot-1-conservative", "hotel-A")
    assert len(slot.injection_history) == 3
    assert [e.mode for e in slot.injection_history] == [
        FailureMode.NETWORK_PARTITION, FailureMode.HEARTBEAT_TIMEOUT,
        FailureMode.GOVERNANCE_DRIFT,
    ]


def test_h05_orchestrator_get_result_after_run(orch, trinity_slots):
    """get_result und list_results funktionieren nach run_campaign."""
    campaign = ChaosCampaign(
        campaign_id="c-stored", hotel_id="hotel-A",
        target_slot_id="slot-1-conservative",
        modes=(FailureMode.HEARTBEAT_TIMEOUT,),
    )
    orch.run_campaign(campaign)
    fetched = orch.get_result("c-stored")
    assert fetched is not None
    assert fetched.campaign_id == "c-stored"
    all_results = orch.list_results()
    assert any(r.campaign_id == "c-stored" for r in all_results)
    hotel_a_results = orch.list_results(hotel_id="hotel-A")
    assert len(hotel_a_results) >= 1
    assert len(orch.list_results(hotel_id="hotel-B")) == 0


# CRUX-MK
