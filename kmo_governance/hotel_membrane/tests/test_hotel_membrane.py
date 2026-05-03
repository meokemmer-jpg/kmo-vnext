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


# ---------- Patch P3 AST-Query-Validator (Welle-9-gamma Open-Item #3 Gemini Finding) ----------


def test_p3_ast_validator_passes_simple_legitimate_query():
    """P3: einfache Query mit hotel_id-Filter im outer-WHERE besteht."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    sql = "SELECT * FROM bookings WHERE hotel_id = 'hotel-A'"
    ok, reason = ast_check_hotel_id_filter(sql)
    assert ok is True
    assert reason == "ok"


def test_p3_ast_validator_blocks_subquery_only_filter():
    """P3 (Gemini): hotel_id nur in Subquery, NICHT in outer-WHERE -> BLOCK."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    # Bypass-Versuch: outer-Query hat kein hotel_id, nur Subquery
    sql = """
        SELECT *
        FROM bookings
        WHERE booking_id IN (
            SELECT booking_id FROM other_table WHERE hotel_id = 'hotel-A'
        )
    """
    ok, reason = ast_check_hotel_id_filter(sql)
    assert ok is False
    assert "subquery" in reason


def test_p3_ast_validator_blocks_or_clause_bypass():
    """P3 (Gemini): WHERE hotel_id='X' OR 1=1 -> Filter ist void, BLOCK."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    sql = "SELECT * FROM bookings WHERE hotel_id = 'hotel-A' OR 1=1"
    ok, reason = ast_check_hotel_id_filter(sql)
    assert ok is False
    assert "or" in reason


def test_p3_ast_validator_blocks_negation_filter():
    """P3 (Gemini): hotel_id != 'X' erlaubt Table-Scan, BLOCK."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    sql_neq = "SELECT * FROM bookings WHERE hotel_id != 'hotel-A'"
    sql_lg = "SELECT * FROM bookings WHERE hotel_id <> 'hotel-A'"
    sql_notin = "SELECT * FROM bookings WHERE hotel_id NOT IN ('hotel-A')"
    for sql in (sql_neq, sql_lg, sql_notin):
        ok, reason = ast_check_hotel_id_filter(sql)
        assert ok is False, f"Should block negation: {sql}"
        assert "negat" in reason or "scan" in reason


def test_p3_ast_validator_blocks_comment_only_filter():
    """P3 (Gemini): hotel_id-Filter nur in Kommentar, NICHT in echtem SQL -> BLOCK."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    # Bypass: regex sieht hotel_id, aber es ist auskommentiert
    sql = """
        SELECT * FROM bookings
        -- WHERE hotel_id = 'hotel-A'
        WHERE 1=1
    """
    ok, reason = ast_check_hotel_id_filter(sql)
    assert ok is False
    # After comment-strip, hotel_id is gone from outer-WHERE
    assert "hotel_id" in reason or "no-outer" in reason


def test_p3_ast_validator_blocks_block_comment_filter():
    """P3 (Gemini): hotel_id im /* ... */ Block-Comment -> BLOCK."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    sql = "SELECT * FROM bookings /* hotel_id='hotel-A' */ WHERE booking_date > '2026-01-01'"
    ok, reason = ast_check_hotel_id_filter(sql)
    assert ok is False


def test_p3_ast_validator_passes_legitimate_with_subquery():
    """P3: outer-WHERE hat hotel_id, Subquery zusaetzlich, OK."""
    from kmo_governance.hotel_membrane import ast_check_hotel_id_filter
    sql = """
        SELECT *
        FROM bookings
        WHERE hotel_id = 'hotel-A'
          AND booking_id IN (SELECT id FROM other_table)
    """
    ok, reason = ast_check_hotel_id_filter(sql)
    assert ok is True


def test_p3_blocker_ast_strict_mode_blocks_bypass():
    """P3: CrossHotelQueryBlocker mit ast_strict=True blockt OR-bypass."""
    from kmo_governance.hotel_membrane import CrossHotelQueryBlocker
    blocker = CrossHotelQueryBlocker(ast_strict=True)
    bypass_sql = "SELECT * FROM bookings WHERE hotel_id = 'X' OR 1=1"
    import pytest
    with pytest.raises(PermissionError) as exc:
        blocker.check_query(bypass_sql, caller_id="some-df")
    assert "AST-validation" in str(exc.value)


def test_p3_blocker_ast_strict_passes_legitimate():
    """P3: ast_strict=True laesst legitimate query durch."""
    from kmo_governance.hotel_membrane import CrossHotelQueryBlocker
    blocker = CrossHotelQueryBlocker(ast_strict=True)
    legit = "SELECT * FROM bookings WHERE hotel_id = 'hotel-A'"
    assert blocker.check_query(legit, caller_id="some-df") is True


def test_p3_blocker_check_query_ast_diagnostic():
    """P3: check_query_ast returns (bool, reason) without raising."""
    from kmo_governance.hotel_membrane import CrossHotelQueryBlocker
    blocker = CrossHotelQueryBlocker()
    bypass = "SELECT * FROM b WHERE hotel_id='X' OR 1=1"
    ok, reason = blocker.check_query_ast(bypass, caller_id="some-df")
    assert ok is False
    assert "or" in reason


def test_p3_backwards_compat_default_strict_off():
    """P3: ast_strict=False (Default) verhaelt sich wie vorher."""
    from kmo_governance.hotel_membrane import CrossHotelQueryBlocker
    blocker = CrossHotelQueryBlocker()  # default ast_strict=False
    # OR-Bypass: regex sieht hotel_id, alter Verhalten = pass
    sql = "SELECT * FROM b WHERE hotel_id='X' OR 1=1"
    assert blocker.check_query(sql, caller_id="some-df") is True
