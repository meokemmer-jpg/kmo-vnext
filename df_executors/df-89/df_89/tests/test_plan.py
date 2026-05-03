"""CRUX-MK tests for the DF-89 planning phase."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from df_89.knowledge import KnowledgeStore
from df_89.monitor import Paper
from df_89.plan import Plan, Planner, TrinityViolationError


def seed_store(tmp_path: Path) -> KnowledgeStore:
    store = KnowledgeStore(tmp_path / "knowledge.sqlite")
    for idx, venue in enumerate(("Nature", "Science", "Cell")):
        store.add_paper(
            Paper(
                id=f"p{idx}",
                title=f"paper {idx} method",
                abstract="method pipeline",
                venue=venue,
                authors=[f"Author {idx}"],
                citations=100 + idx,
                year=2024,
                source_type="stub",
                source_url=f"https://example.com/p{idx}",
                fetched_at=datetime.now(UTC),
            )
        )
    return store


def test_enforce_trinity_raises_for_too_few_plans() -> None:
    with pytest.raises(TrinityViolationError):
        Planner().enforce_trinity([Plan("conservative", "candidate")])


def test_plan_next_returns_three_lanes(tmp_path: Path) -> None:
    store = seed_store(tmp_path)
    plans = Planner().plan_next(
        {"paper_ids": ["p0", "p1", "p2"], "llm_consensus": 3, "top_papers": [{"paper_id": "p0"}]},
        store,
    )
    assert [plan.lane for plan in plans] == ["conservative", "aggressive", "contrarian"]


def test_dual_lane_split_places_contrarian_into_innovation(tmp_path: Path) -> None:
    store = seed_store(tmp_path)
    plans = Planner().plan_next(
        {"paper_ids": ["p0", "p1", "p2"], "llm_consensus": 2, "top_papers": [{"paper_id": "p2"}]},
        store,
    )
    convergence, innovation = Planner().dual_lane_split(plans)
    assert all(plan.lane != "contrarian" for plan in convergence)
    assert innovation[0].status == "candidate-outlier"


def test_conservative_plan_becomes_canonical_with_quorum(tmp_path: Path) -> None:
    store = seed_store(tmp_path)
    conservative = Planner().plan_next(
        {"paper_ids": ["p0", "p1", "p2"], "llm_consensus": 3, "top_papers": [{"paper_id": "p0"}]},
        store,
    )[0]
    assert conservative.status == "canonical"
