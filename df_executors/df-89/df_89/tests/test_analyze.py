"""CRUX-MK tests for the DF-89 analyze phase."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from df_89.analyze import Analyzer
from df_89.monitor import Paper


def paper(*, title: str, citations: int, venue: str = "Nature", year: int = 2024) -> Paper:
    return Paper(
        id=title.lower().replace(" ", "-"),
        title=title,
        abstract="method pipeline graph",
        venue=venue,
        authors=["Ada"],
        citations=citations,
        year=year,
        source_type="stub",
        source_url="https://example.com",
        fetched_at=datetime.now(UTC),
    )


def test_topic_convergence_writes_pattern_file(tmp_path: Path) -> None:
    analyzer = Analyzer(state_dir=tmp_path)
    output = analyzer.topic_convergence([paper(title="Method Graph", citations=10)], "graphs")
    target = next((tmp_path / "analyze").glob("graphs-*-patterns.md"))
    assert output["term_counts"]["method"] == 1
    assert target.exists()


def test_paper_tier_classify_returns_high_for_top_venue() -> None:
    analyzer = Analyzer()
    assert analyzer.paper_tier_classify(paper(title="x", citations=10, venue="NeurIPS")) == "HIGH"


def test_bio_software_mapping_returns_none_for_unknown_term() -> None:
    analyzer = Analyzer()
    assert analyzer.bio_software_mapping("unknown") is None
    assert analyzer.bio_software_mapping("graph") is not None


def test_score_paper_increases_with_stronger_signals() -> None:
    analyzer = Analyzer()
    low = analyzer.score_paper(paper(title="old", citations=5, venue="arXiv", year=2010), {"citation": 1.0})
    high = analyzer.score_paper(paper(title="new", citations=500, venue="Nature", year=2024), {"citation": 1.0})
    assert high > low


def test_score_paper_rejects_negative_weights() -> None:
    analyzer = Analyzer()
    with pytest.raises(ValueError):
        analyzer.score_paper(paper(title="x", citations=50), {"citation": -1.0})


def test_cross_llm_sanity_counts_three_way_consensus() -> None:
    analyzer = Analyzer()
    candidate = paper(title="Method Graph", citations=10)
    report = analyzer.cross_llm_sanity(
        [candidate],
        {"a": "Method Graph", "b": "Method Graph", "c": "Method Graph"},
    )
    assert report.consensus_count == 3
    assert report.converged is True
