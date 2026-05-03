from __future__ import annotations

import pytest

from df_89.patterns.m01_hotel_membrane import HotelMembrane


def membrane(default_quota: dict[str, int] | None = None) -> HotelMembrane:
    return HotelMembrane(default_quota or {"api_calls": 10, "llm_tokens": 100, "worker_slots": 2})


def test_register_tenant_initializes_with_quota() -> None:
    defaults = {"api_calls": 10, "storage_bytes": 1_024}
    hotel_membrane = HotelMembrane(defaults)
    hotel_membrane.register_tenant("hotel-A")
    defaults["api_calls"] = 0
    assert hotel_membrane.tenants["hotel-A"].quota_remaining == {"api_calls": 10, "storage_bytes": 1_024}
    assert hotel_membrane.tenants["hotel-A"].tenant_id == "hotel-A"


def test_request_resource_decrements_quota() -> None:
    hotel_membrane = membrane()
    hotel_membrane.register_tenant("hotel-A")
    assert hotel_membrane.request_resource("hotel-A", "api_calls", 5) is True
    assert hotel_membrane.tenants["hotel-A"].quota_remaining["api_calls"] == 5


def test_request_resource_returns_false_at_quota_exhaustion() -> None:
    hotel_membrane = HotelMembrane({"api_calls": 0})
    hotel_membrane.register_tenant("hotel-A")
    assert hotel_membrane.request_resource("hotel-A", "api_calls") is False
    assert hotel_membrane.tenants["hotel-A"].quota_remaining["api_calls"] == 0


def test_quota_denial_audited() -> None:
    hotel_membrane = HotelMembrane({"api_calls": 5})
    hotel_membrane.register_tenant("hotel-A")

    assert hotel_membrane.request_resource("hotel-A", "api_calls", 6) is False
    assert hotel_membrane.audit_quota_denials() == [
        ("hotel-A", "api_calls", 6, "quota_exhausted")
    ]


def test_strict_mode_blocks_cross_tenant_default() -> None:
    hotel_membrane = membrane()
    hotel_membrane.register_tenant("hotel-A")
    hotel_membrane.register_tenant("hotel-B")
    assert hotel_membrane.access_cross_tenant("hotel-A", "hotel-B", "api_calls") is False
    assert hotel_membrane.tenants["hotel-B"].quota_remaining["api_calls"] == 10


def test_grant_cross_tenant_allows_access() -> None:
    hotel_membrane = membrane()
    hotel_membrane.register_tenant("hotel-A")
    hotel_membrane.register_tenant("hotel-B")
    hotel_membrane.grant_cross_tenant("hotel-A", "hotel-B")
    assert hotel_membrane.access_cross_tenant("hotel-A", "hotel-B", "api_calls", 3) is True
    assert hotel_membrane.tenants["hotel-B"].quota_remaining["api_calls"] == 7


def test_revoke_cross_tenant_blocks_access() -> None:
    hotel_membrane = membrane()
    hotel_membrane.register_tenant("hotel-A")
    hotel_membrane.register_tenant("hotel-B")
    hotel_membrane.grant_cross_tenant("hotel-A", "hotel-B")
    hotel_membrane.revoke_cross_tenant("hotel-A", "hotel-B")
    assert hotel_membrane.access_cross_tenant("hotel-A", "hotel-B", "api_calls") is False


def test_audit_violations_records_cross_tenant_attempts() -> None:
    events: list[tuple[str, str, str, bool]] = []
    hotel_membrane = HotelMembrane(
        {"api_calls": 10},
        audit_callback=lambda source, target, resource, permitted: events.append(
            (source, target, resource, permitted)
        ),
    )
    hotel_membrane.register_tenant("hotel-A")
    hotel_membrane.register_tenant("hotel-B")
    assert hotel_membrane.access_cross_tenant("hotel-A", "hotel-B", "api_calls") is False
    assert hotel_membrane.audit_violations() == [("hotel-A", "hotel-B", "api_calls")]
    assert events == [("hotel-A", "hotel-B", "api_calls", False)]


def test_empty_tenant_id_raises() -> None:
    hotel_membrane = membrane()
    with pytest.raises(ValueError, match="tenant_id"):
        hotel_membrane.register_tenant("")


def test_self_tenant_reference_always_allowed() -> None:
    hotel_membrane = membrane()
    hotel_membrane.register_tenant("hotel-A")
    assert hotel_membrane.access_cross_tenant("hotel-A", "hotel-A", "api_calls", 4) is True
    assert hotel_membrane.audit_violations() == []
    assert hotel_membrane.tenants["hotel-A"].quota_remaining["api_calls"] == 6


def test_reset_quotas_restores_defaults() -> None:
    hotel_membrane = membrane()
    hotel_membrane.register_tenant("hotel-A")
    hotel_membrane.request_resource("hotel-A", "api_calls", 6)
    hotel_membrane.request_resource("hotel-A", "llm_tokens", 40)
    hotel_membrane.reset_quotas("hotel-A")
    assert hotel_membrane.tenants["hotel-A"].quota_remaining == {
        "api_calls": 10,
        "llm_tokens": 100,
        "worker_slots": 2,
    }
