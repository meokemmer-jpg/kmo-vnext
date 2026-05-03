"""CRUX-MK tests for the DF-89 knowledge store."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from df_89.knowledge import KnowledgeStore
from df_89.monitor import Paper


def build_store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.sqlite")


def build_paper(paper_id: str, venue: str, author: str, citations: int = 100) -> Paper:
    return Paper(
        id=paper_id,
        title=f"{paper_id} method benchmark",
        abstract="method pipeline graph",
        venue=venue,
        authors=[author],
        citations=citations,
        year=2024,
        source_type="stub",
        source_url=f"https://example.com/{paper_id}",
        fetched_at=datetime.now(UTC),
    )


def test_add_methodik_canonicalizes_whitespace(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    first = store.add_methodik("Graph Search", "desc", 0.8)
    second = store.add_methodik(" graph   search ", "desc", 0.8)
    assert first == second


def test_add_relation_rejects_unknown_relation_type(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    with pytest.raises(ValueError):
        store.add_relation("a", "b", "unknown")


def test_find_cycles_marks_contested_claims(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a = store.add_methodik("a", "desc", 0.5)
    b = store.add_methodik("b", "desc", 0.5)
    store.add_relation(a, b, "contradicts")
    store.add_relation(b, a, "contradicts")
    cycles = store.find_cycles()
    assert len(cycles) == 1
    with store._connect() as conn:
        statuses = {
            row["claim_id"]: row["status"]
            for row in conn.execute("SELECT claim_id,status FROM methodik_catalog").fetchall()
        }
    assert statuses[a] == "contested"
    assert statuses[b] == "contested"


def test_find_cycles_returns_empty_for_acyclic_graph(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a = store.add_methodik("a", "desc", 0.5)
    b = store.add_methodik("b", "desc", 0.5)
    store.add_relation(a, b, "supports")
    assert store.find_cycles() == []


def test_apply_decay_updates_decay_score(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    claim_id = store.add_methodik("graph", "desc", 1.0)
    store.apply_decay(0.5)
    with store._connect() as conn:
        decay = conn.execute(
            "SELECT decay_score FROM methodik_catalog WHERE claim_id=?",
            (claim_id,),
        ).fetchone()[0]
    assert decay == pytest.approx(0.5)


def test_compute_diversity_score_uses_min_cluster_ratio(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    papers = [
        build_paper("p1", "Nature", "Ada", 20),
        build_paper("p2", "Science", "Bob", 70),
        build_paper("p3", "Nature", "Cara", 120),
    ]
    for paper in papers:
        store.add_paper(paper)
    assert store.compute_diversity_score([paper.id for paper in papers]) == pytest.approx(2 / 3)


def test_compute_diversity_score_is_zero_for_empty_input(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    assert store.compute_diversity_score([]) == 0.0


def test_add_and_get_paper_roundtrip(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    paper = build_paper("p1", "Nature", "Ada")
    store.add_paper(paper)
    loaded = store.get_paper("p1")
    assert loaded is not None
    assert loaded["authors_json"] == ["Ada"]


def test_mark_failure_and_record_processed_event(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    failure_id = store.mark_failure("webfetch", "dead link", dead_link=True)
    store.record_processed_event("evt-1", {"lane": "conservative"})
    assert failure_id
    assert store.has_processed_event("evt-1") is True
