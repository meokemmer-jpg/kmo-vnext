"""CRUX-MK analyze phase for DF-89 methodology convergence."""

from collections import Counter
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel

from .knowledge import KnowledgeStore
from .monitor import Paper


class Hypothesis(BaseModel):
    """Candidate bio-software mapping."""

    methodik_term: str
    bio_mechanism: str
    confidence: float


class ConsensusReport(BaseModel):
    """Minimal 3-LLM convergence report."""

    participating_models: list[str]
    consensus_count: int
    converged: bool
    notes: str = ""


class Analyzer:
    """Transforms paper stubs into convergence signals and reports."""

    methodology_terms = ("method", "pipeline", "benchmark", "graph", "retrieval", "agent")
    peer_review_venues = ("nature", "science", "neurips", "icml", "cell", "acl")

    def __init__(self, knowledge: KnowledgeStore | None = None, state_dir: Path = Path("state/df-89")) -> None:
        self.knowledge = knowledge
        self.state_dir = state_dir

    def topic_convergence(self, papers: list[Paper], topic: str) -> dict[str, object]:
        """Pre: topic is non-empty. Post: returns term counts and writes a pattern artifact."""
        if not topic.strip():
            raise ValueError("topic must not be blank")
        counts: Counter[str] = Counter()
        for paper in papers:
            text = f"{paper.title} {paper.abstract}".lower()
            counts.update(term for term in self.methodology_terms if term in text)
        payload = {"topic": topic, "paper_ids": [paper.id for paper in papers], "term_counts": dict(counts)}
        self._write_patterns(topic, payload)
        return payload

    def paper_tier_classify(self, paper: Paper) -> Literal["HIGH", "MID", "LOW"]:
        """Pre: paper has citation and venue data. Post: returns HIGH, MID, or LOW."""
        venue = paper.venue.lower()
        if paper.citations >= 250 or any(token in venue for token in self.peer_review_venues):
            return "HIGH"
        if paper.citations >= 50 or paper.year >= datetime.now(UTC).year - 2:
            return "MID"
        return "LOW"

    def bio_software_mapping(self, methodik_term: str) -> Hypothesis | None:
        """Pre: methodik_term is non-empty. Post: returns an optional mapping hypothesis."""
        mappings = {
            "graph": ("synaptic coordination", 0.55),
            "retrieval": ("hippocampal cue recall", 0.50),
            "pipeline": ("metabolic staging", 0.45),
        }
        if methodik_term not in mappings:
            return None
        mechanism, confidence = mappings[methodik_term]
        return Hypothesis(methodik_term=methodik_term, bio_mechanism=mechanism, confidence=confidence)

    def cross_llm_sanity(self, papers: list[Paper], llm_outputs: dict[str, str]) -> ConsensusReport:
        """Pre: llm_outputs contains model-name to text mappings. Post: returns a consensus report."""
        if not llm_outputs:
            return ConsensusReport(participating_models=[], consensus_count=0, converged=False, notes="no LLMs")
        titles = {paper.title.lower() for paper in papers}
        normalized = [" ".join(text.lower().split()) for text in llm_outputs.values()]
        majority = Counter(normalized).most_common(1)[0][1]
        title_hits = sum(1 for text in normalized if any(title in text for title in titles))
        consensus = min(majority, title_hits) if titles else majority
        return ConsensusReport(
            participating_models=list(llm_outputs),
            consensus_count=consensus,
            converged=consensus >= min(3, len(llm_outputs)),
            notes="TODO replace stubbed convergence heuristic",
        )

    def score_paper(
        self,
        paper: Paper,
        weights: dict[str, float],
        hill_n: dict[str, float] | None = None,
    ) -> float:
        """Pre: weights are non-negative. Post: returns a Hill-function aggregate score."""
        signals = self._signals_for_paper(paper)
        exponents = {
            "citation": 2.5,
            "recency": 1.5,
            "peer_review": 3.0,
            "domain_match": 2.0,
            "cross_llm_mention": 2.7,
        }
        if hill_n is not None:
            exponents.update(hill_n)
        score = 0.0
        for name, weight in weights.items():
            if weight < 0.0:
                raise ValueError("weights must be non-negative")
            signal = max(0.0, min(1.0, signals.get(name, 0.0)))
            exponent = exponents.get(name, 2.0)
            numerator = signal**exponent
            denominator = (0.5**exponent) + numerator
            score += 0.0 if numerator == 0.0 else weight * numerator / denominator
        return score

    def source_independence_quorum(self, paper_ids: list[str]) -> bool:
        """Pre: paper_ids may be empty. Post: returns true for 3+ papers with diversity > 0.6."""
        if self.knowledge is None:
            return False
        return len(paper_ids) >= 3 and self.knowledge.compute_diversity_score(paper_ids) > 0.6

    def _signals_for_paper(self, paper: Paper) -> dict[str, float]:
        age = max(0, datetime.now(UTC).year - paper.year)
        venue = paper.venue.lower()
        return {
            "citation": min(paper.citations / 500.0, 1.0),
            "recency": max(0.0, 1.0 - age / 10.0),
            "peer_review": 1.0 if any(token in venue for token in self.peer_review_venues) else 0.2,
            "domain_match": 1.0 if "method" in f"{paper.title} {paper.abstract}".lower() else 0.4,
            "cross_llm_mention": 0.0,
        }

    def _write_patterns(self, topic: str, payload: dict[str, object]) -> None:
        target_dir = self.state_dir / "analyze"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{topic}-{datetime.now(UTC).date().isoformat()}-patterns.md"
        content = "\n".join(
            [
                f"# {topic}",
                "",
                f"paper_ids: {json.dumps(payload['paper_ids'])}",
                f"term_counts: {json.dumps(payload['term_counts'], sort_keys=True)}",
            ]
        )
        fd, tmp_name = tempfile.mkstemp(prefix=target.name, dir=target_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
