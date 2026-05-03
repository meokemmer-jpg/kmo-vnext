"""CRUX-MK planning phase with Trinity options for DF-89."""

from dataclasses import dataclass, field
from typing import Any, Literal

from .knowledge import KnowledgeStore


class TrinityViolationError(RuntimeError):
    """Raised when DF-89 cannot produce three Trinity options."""


@dataclass(frozen=True)
class Plan:
    """Single candidate action emitted by the planning phase."""

    lane: Literal["conservative", "aggressive", "contrarian"]
    status: str
    candidate_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    confidence: float = 0.0


class Planner:
    """Builds conservative, aggressive, and contrarian research plans."""

    def __init__(self, convergence_budget_pct: float = 0.80, innovation_budget_pct: float = 0.20) -> None:
        self.convergence_budget_pct = convergence_budget_pct
        self.innovation_budget_pct = innovation_budget_pct

    def plan_next(self, analyze_output: dict[str, Any], knowledge: KnowledgeStore) -> list[Plan]:
        """Pre: analyze_output contains candidate paper ids. Post: returns three Trinity plans."""
        paper_ids = list(analyze_output.get("paper_ids", []))
        llm_consensus = int(analyze_output.get("llm_consensus", 0))
        diversity = knowledge.compute_diversity_score(paper_ids)
        top_papers = list(analyze_output.get("top_papers", []))
        contrarian_id = top_papers[0]["paper_id"] if top_papers else (paper_ids[0] if paper_ids else "")
        plans = [
            Plan(
                lane="conservative",
                status="canonical"
                if len(paper_ids) >= 3 and llm_consensus >= 3 and diversity > 0.6
                else "candidate",
                candidate_ids=paper_ids[:3],
                rationale="HARDENED-pfad: 3+ sources + 3/3 LLM consensus + diversity > 0.6",
                confidence=min(1.0, 0.4 + diversity),
            ),
            Plan(
                lane="aggressive",
                status="provisional" if len(paper_ids) >= 2 and llm_consensus >= 2 else "candidate",
                candidate_ids=paper_ids[:2],
                rationale="PROVISIONAL: 2+ sources + 2/3 LLM consensus",
                confidence=0.60 if len(paper_ids) >= 2 else 0.25,
            ),
            Plan(
                lane="contrarian",
                status="candidate-outlier",
                candidate_ids=[contrarian_id] if contrarian_id else [],
                rationale="Outlier-Lane: single top paper, promotion after 2+ confirmations",
                confidence=0.35 if contrarian_id else 0.0,
            ),
        ]
        self.enforce_trinity(plans)
        return plans

    def dual_lane_split(self, candidates: list[Plan]) -> tuple[list[Plan], list[Plan]]:
        """Pre: candidates contains plan objects. Post: returns convergence and innovation lanes."""
        convergence = [plan for plan in candidates if plan.lane != "contrarian"]
        innovation = [plan for plan in candidates if plan.lane == "contrarian"]
        return convergence, innovation

    def enforce_trinity(self, plans: list[Plan]) -> None:
        """Pre: plans is materialized. Post: raises when fewer than three plans exist."""
        if len(plans) < 3:
            raise TrinityViolationError("Trinity-Pflicht requires three options")
