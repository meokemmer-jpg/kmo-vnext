"""KMO Hotel-Membrane Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-3.2.
"""

from __future__ import annotations

import pytest

from kmo_governance.hotel_membrane import (
    CrossHotelQueryBlocker,
    DataCategory,
    GDPRComplianceLayer,
    HotelMembrane,
)


# ---------------- HotelMembrane Tests ----------------


def test_hotel_membrane_path_isolation(tmp_path):
    """hotel_state_dir returns isolated subtree per hotel_id."""
    m1 = HotelMembrane(hotel_id="apaleo-eu-001", base_state_dir=tmp_path)
    m2 = HotelMembrane(hotel_id="mews-us-002", base_state_dir=tmp_path)
    d1 = m1.hotel_state_dir()
    d2 = m2.hotel_state_dir()
    assert d1 != d2
    assert d1.name == "hotel-apaleo-eu-001"
    assert d2.name == "hotel-mews-us-002"
    assert d1.exists()
    assert d2.exists()


def test_hotel_membrane_id_validation(tmp_path):
    with pytest.raises(ValueError):
        HotelMembrane(hotel_id="", base_state_dir=tmp_path)
    with pytest.raises(ValueError):
        HotelMembrane(hotel_id="hotel/with/slashes", base_state_dir=tmp_path)
    with pytest.raises(ValueError):
        HotelMembrane(hotel_id="hotel; DROP TABLE", base_state_dir=tmp_path)


def test_hotel_membrane_validate_payload_tag(tmp_path):
    m = HotelMembrane(hotel_id="hA", base_state_dir=tmp_path)
    assert m.validate_payload_tag({"hotel_id": "hA", "data": 1}) is True
    assert m.validate_payload_tag({"hotel_id": "hB", "data": 1}) is False
    # Untagged passes (caller's responsibility)
    assert m.validate_payload_tag({"data": 1}) is True
    # Non-dict pass-through
    assert m.validate_payload_tag("string") is True


# ---------------- CrossHotelQueryBlocker Tests ----------------


def test_hotel_membrane_blocks_cross_hotel_query():
    """SQL without hotel_id filter raises PermissionError (unless whitelisted)."""
    blocker = CrossHotelQueryBlocker()
    with pytest.raises(PermissionError):
        blocker.check_query("SELECT * FROM bookings", caller_id="df-untrusted")
    # With filter: passes
    assert blocker.check_query(
        "SELECT * FROM bookings WHERE hotel_id = ?", caller_id="df-untrusted"
    )


def test_cross_hotel_aggregation_whitelist():
    """Whitelisted callers may run cross-hotel queries."""
    blocker = CrossHotelQueryBlocker(whitelist={"organism-aggregator"})
    assert blocker.check_query(
        "SELECT COUNT(*) FROM bookings", caller_id="organism-aggregator"
    )
    # Non-whitelisted same query: blocked
    with pytest.raises(PermissionError):
        blocker.check_query(
            "SELECT COUNT(*) FROM bookings", caller_id="ad-hoc-query"
        )


def test_blocker_whitelist_management():
    blocker = CrossHotelQueryBlocker()
    blocker.add_to_whitelist("caller-A")
    assert blocker.check_query("SELECT 1", caller_id="caller-A")
    assert blocker.remove_from_whitelist("caller-A") is True
    assert blocker.remove_from_whitelist("never-added") is False


# ---------------- GDPRComplianceLayer Tests ----------------


def test_gdpr_consent_per_data_category(tmp_path):
    """grant/revoke/has_consent per (hotel_id, category)."""
    audit = tmp_path / "gdpr_audit.jsonl"
    gdpr = GDPRComplianceLayer(audit_path=audit)
    gdpr.grant_consent("hA", DataCategory.BOOKING, notes="email-confirmation")
    assert gdpr.has_consent("hA", DataCategory.BOOKING)
    assert not gdpr.has_consent("hA", DataCategory.PAYMENT)
    assert not gdpr.has_consent("hB", DataCategory.BOOKING)

    # Revoke
    assert gdpr.revoke_consent("hA", DataCategory.BOOKING)
    assert not gdpr.has_consent("hA", DataCategory.BOOKING)
    # Revoke unknown: False
    assert not gdpr.revoke_consent("hA", DataCategory.PAYMENT)


def test_gdpr_purge_cascade_complete(tmp_path):
    """purge_hotel_data removes ALL consent for that hotel."""
    audit = tmp_path / "gdpr_audit.jsonl"
    gdpr = GDPRComplianceLayer(audit_path=audit)
    gdpr.grant_consent("hA", DataCategory.BOOKING)
    gdpr.grant_consent("hA", DataCategory.PAYMENT)
    gdpr.grant_consent("hB", DataCategory.BOOKING)

    result = gdpr.purge_hotel_data("hA")
    assert result["consent_records_purged"] == 2
    assert result["existed"] is True

    assert not gdpr.has_consent("hA", DataCategory.BOOKING)
    assert not gdpr.has_consent("hA", DataCategory.PAYMENT)
    # hB unaffected
    assert gdpr.has_consent("hB", DataCategory.BOOKING)

    # Audit-log contains forensic events
    audit_lines = audit.read_text(encoding="utf-8").strip().split("\n")
    assert any('"event": "purge_hotel_data"' in line for line in audit_lines)


def test_gdpr_invalid_category_type(tmp_path):
    audit = tmp_path / "audit.jsonl"
    gdpr = GDPRComplianceLayer(audit_path=audit)
    with pytest.raises(TypeError):
        gdpr.grant_consent("hA", "booking")  # type: ignore[arg-type]


def test_gdpr_purge_unknown_hotel(tmp_path):
    audit = tmp_path / "audit.jsonl"
    gdpr = GDPRComplianceLayer(audit_path=audit)
    result = gdpr.purge_hotel_data("never-existed")
    assert result["existed"] is False
    assert result["consent_records_purged"] == 0


# ---------------- Phase-1 Cell-Boundary Compatibility ----------------


def test_membrane_compatible_with_phase1_cell_boundary(tmp_path):
    """HotelMembrane + Phase-1 CellBoundary share hotel_id semantically.

    Cross-Layer-Test: HotelMembrane.hotel_id corresponds to CellBoundary.hotel_id.
    """
    from kmo_governance.cell_boundary import CellBoundary, CellBoundaryManager

    m = HotelMembrane(hotel_id="apaleo-eu-001", base_state_dir=tmp_path)
    boundary = CellBoundary(
        cell_id="saga-run-1",
        hotel_id=m.hotel_id,
    )
    mgr = CellBoundaryManager(boundary)
    mgr.assert_hotel_id(m.hotel_id)  # no raise

    # Cross-tenant attempt: PermissionError
    other_membrane = HotelMembrane(hotel_id="mews-us-002", base_state_dir=tmp_path)
    import pytest
    with pytest.raises(PermissionError):
        mgr.assert_hotel_id(other_membrane.hotel_id)
