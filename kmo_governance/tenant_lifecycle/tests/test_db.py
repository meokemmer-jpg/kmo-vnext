"""Tenant-DB Tests [CRUX-MK]."""
import pytest
import tempfile
from pathlib import Path

from src.db import TenantDB
from src.tenant import Tenant, TenantStatus, PlanTier
from src.lifecycle_pipeline import provision, activate, suspend


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        jsonl = Path(td) / "events.jsonl"
        yield TenantDB(db_path=db_path, jsonl_backup=jsonl)


def test_db_init_schema_idempotent(tmp_db):
    tmp_db._init_schema()
    tmp_db._init_schema()  # Re-init should not fail
    assert tmp_db.db_path.exists()


def test_upsert_tenant_returns_hash(tmp_db):
    t = provision("Hotel A", PlanTier.STARTER)
    h = tmp_db.upsert_tenant(t)
    assert len(h) == 64


def test_get_tenant_by_id(tmp_db):
    t = provision("Hotel B", PlanTier.PROFESSIONAL)
    tmp_db.upsert_tenant(t)
    fetched = tmp_db.get_tenant(t.id)
    assert fetched is not None
    assert fetched["name"] == "Hotel B"
    assert fetched["plan_tier"] == "PROFESSIONAL"


def test_upsert_tenant_idempotent_same_state(tmp_db):
    t = provision("Hotel C", PlanTier.STARTER)
    h1 = tmp_db.upsert_tenant(t)
    h2 = tmp_db.upsert_tenant(t)
    assert h1 == h2


def test_log_transition_creates_event(tmp_db):
    t = provision("Hotel D", PlanTier.STARTER)
    tmp_db.upsert_tenant(t)
    eid = tmp_db.log_transition(t.id, TenantStatus.PROVISIONED,
                                 TenantStatus.ACTIVE, "manual")
    assert eid > 0
    events = tmp_db.get_lifecycle_events(t.id)
    assert len(events) == 1
    assert events[0]["from_status"] == "PROVISIONED"
    assert events[0]["to_status"] == "ACTIVE"


def test_list_tenants_filter_by_status(tmp_db):
    t1 = provision("A", PlanTier.STARTER)
    t2 = provision("B", PlanTier.STARTER)
    activate(t2)
    tmp_db.upsert_tenant(t1)
    tmp_db.upsert_tenant(t2)
    active = tmp_db.list_tenants(status=TenantStatus.ACTIVE)
    assert len(active) == 1
    assert active[0]["name"] == "B"


def test_jsonl_backup_appended(tmp_db):
    t = provision("E", PlanTier.STARTER)
    tmp_db.upsert_tenant(t)
    assert tmp_db.jsonl_backup.exists()
    content = tmp_db.jsonl_backup.read_text()
    assert "E" in content
    assert "upsert" in content


def test_get_tenant_returns_none_for_unknown(tmp_db):
    from uuid import uuid4
    assert tmp_db.get_tenant(uuid4()) is None


def test_list_tenants_returns_all_when_no_filter(tmp_db):
    for n in ["X", "Y", "Z"]:
        tmp_db.upsert_tenant(provision(n, PlanTier.STARTER))
    assert len(tmp_db.list_tenants()) == 3


def test_lifecycle_event_log_ordered_by_time(tmp_db):
    t = provision("F", PlanTier.STARTER)
    tmp_db.upsert_tenant(t)
    tmp_db.log_transition(t.id, TenantStatus.PROVISIONED, TenantStatus.ACTIVE)
    tmp_db.log_transition(t.id, TenantStatus.ACTIVE, TenantStatus.SUSPENDED, "test")
    events = tmp_db.get_lifecycle_events(t.id)
    assert len(events) == 2
    assert events[0]["to_status"] == "ACTIVE"
    assert events[1]["to_status"] == "SUSPENDED"
