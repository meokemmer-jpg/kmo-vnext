"""Adapter-Health Tests [CRUX-MK]."""
import pytest
import time

from src.adapter_health import (
    AdapterHealthMonitor, AdapterStatus, CircuitState,
)


def test_initial_state_closed():
    m = AdapterHealthMonitor("apaleo")
    assert m.circuit_state == CircuitState.CLOSED
    assert m.is_available()


def test_record_success_keeps_closed():
    m = AdapterHealthMonitor("apaleo")
    m.record_success(latency_ms=120.0)
    assert m.circuit_state == CircuitState.CLOSED
    assert m.get_status() == AdapterStatus.HEALTHY


def test_record_failure_below_threshold_degraded():
    m = AdapterHealthMonitor("mews", threshold_open_after_n_fails=3)
    m.record_failure("connection refused")
    assert m.get_status() == AdapterStatus.DEGRADED
    assert m.circuit_state == CircuitState.CLOSED


def test_threshold_opens_circuit():
    m = AdapterHealthMonitor("mews", threshold_open_after_n_fails=3)
    for _ in range(3):
        m.record_failure("timeout")
    assert m.circuit_state == CircuitState.OPEN
    assert m.get_status() == AdapterStatus.UNHEALTHY


def test_open_circuit_blocks_availability():
    m = AdapterHealthMonitor("mews", threshold_open_after_n_fails=2,
                              half_open_test_interval_s=999)
    m.record_failure("x")
    m.record_failure("y")
    assert not m.is_available()


def test_half_open_after_interval():
    m = AdapterHealthMonitor("mews", threshold_open_after_n_fails=2,
                              half_open_test_interval_s=0)  # Sofort Half-Open
    m.record_failure("x")
    m.record_failure("y")
    # Auch wenn open, half_open_interval=0 macht is_available True
    assert m.is_available()
    assert m.circuit_state == CircuitState.HALF_OPEN


def test_force_close_resets():
    m = AdapterHealthMonitor("mews", threshold_open_after_n_fails=2)
    m.record_failure("x")
    m.record_failure("y")
    m.force_close()
    assert m.circuit_state == CircuitState.CLOSED
    assert m.consecutive_fails == 0


def test_success_after_half_open_closes_circuit():
    m = AdapterHealthMonitor("mews", threshold_open_after_n_fails=2,
                              half_open_test_interval_s=0)
    m.record_failure("x")
    m.record_failure("y")
    m.is_available()  # Half-Open transition
    m.record_success()
    assert m.circuit_state == CircuitState.CLOSED


def test_invalid_adapter_name_rejected():
    with pytest.raises(ValueError):
        AdapterHealthMonitor("")


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        AdapterHealthMonitor("apaleo", threshold_open_after_n_fails=0)


def test_status_unknown_initially():
    m = AdapterHealthMonitor("apaleo")
    assert m.get_status() == AdapterStatus.UNKNOWN  # No history yet


def test_history_grows_with_records():
    m = AdapterHealthMonitor("apaleo")
    m.record_success()
    m.record_failure("x")
    assert len(m.history) == 2
