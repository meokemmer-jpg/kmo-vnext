"""CRUX-MK MAPE-K engine for DF-89 Research-Gate-Inquirer."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import time

from .analyze import Analyzer
from .config import DFConfig
from .execute import ExecutionResult, Executor
from .knowledge import KnowledgeStore
from .monitor import Monitor, Paper
from .plan import Plan, Planner


@dataclass(frozen=True)
class RunResult:
    """Result of one complete MAPE-K iteration."""

    topic: str
    papers: list[Paper]
    analyze_output: dict[str, object]
    plans: list[Plan]
    execution: ExecutionResult
    stress_mode: str


class MAPEKEngine:
    """Coordinates Monitor, Analyze, Plan, Execute, and Knowledge phases."""

    def __init__(self, config: DFConfig, knowledge: KnowledgeStore) -> None:
        """Pre: config is validated and knowledge is initialized. Post: engine is ready."""
        self.config = config
        self.knowledge = knowledge
        self.monitor = Monitor(knowledge)
        self.analyzer = Analyzer(knowledge, config.state_dir)
        self.planner = Planner(config.convergence_budget_pct, config.innovation_budget_pct)
        self.executor = Executor(config)
        self._recent_convergence: list[float] = []

    def run_once(self, topic: str) -> RunResult:
        """Pre: topic is non-empty. Post: completes one MAPE-K loop."""
        if not topic.strip():
            raise ValueError("topic must not be blank")
        with self._spawn_guard():
            papers = self.monitor.collect(topic, 3)
            analyze_output = self.analyzer.topic_convergence(papers, topic)
            analyze_output["top_papers"] = self._top_papers(papers)
            llm_report = self.analyzer.cross_llm_sanity(
                papers,
                {f"llm-{idx}": papers[0].title if papers else topic for idx in range(3)},
            )
            analyze_output["llm_consensus"] = llm_report.consensus_count
            plans = self.planner.plan_next(analyze_output, self.knowledge)
            convergence, innovation = self.planner.dual_lane_split(plans)
            selected = convergence[0] if convergence else innovation[0]
            execution = self.executor.execute_plan(selected, self.knowledge)
            self._knowledge_phase(topic, analyze_output)
            stress_mode = self._stress_mode(analyze_output)
        return RunResult(topic, papers, analyze_output, plans, execution, stress_mode)

    @contextmanager
    def _spawn_guard(self) -> Iterator[None]:
        lock_dir = Path(self.config.lock_dir)
        self._acquire_lock(lock_dir)
        try:
            self._self_detect()
            yield
        finally:
            self._release_lock(lock_dir)

    def _acquire_lock(self, lock_dir: Path) -> None:
        if self.config.concurrent_spawn_protection not in {"wrapper_mutex_only", "both"}:
            return
        stale_age_s = self.config.lock_stale_age_h * 3600
        if lock_dir.exists() and time.time() - lock_dir.stat().st_mtime > stale_age_s:
            shutil.rmtree(lock_dir, ignore_errors=True)
        try:
            lock_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RuntimeError("DF-89 lock already held") from exc
        (lock_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")

    def _release_lock(self, lock_dir: Path) -> None:
        if lock_dir.exists():
            shutil.rmtree(lock_dir, ignore_errors=True)

    def _self_detect(self) -> None:
        if self.config.concurrent_spawn_protection not in {"engine_self_detect_only", "both"}:
            return
        try:
            result = subprocess.run(
                ["pgrep", "-f", r"python.*-m[[:space:]]+df_89"],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return
        others = [line for line in result.stdout.splitlines() if line.strip() and int(line) != os.getpid()]
        if len(others) > 1:
            raise RuntimeError("possible concurrent DF-89 process detected")

    def _top_papers(self, papers: list[Paper]) -> list[dict[str, object]]:
        scored = [
            {
                "paper_id": paper.id,
                "score": self.analyzer.score_paper(
                    paper,
                    {"citation": 0.35, "recency": 0.20, "peer_review": 0.20, "domain_match": 0.25},
                ),
                "tier": self.analyzer.paper_tier_classify(paper),
            }
            for paper in papers
        ]
        return sorted(scored, key=lambda item: float(item["score"]), reverse=True)

    def _knowledge_phase(self, topic: str, analyze_output: dict[str, object]) -> None:
        claim_ids: list[str] = []
        for term, count in dict(analyze_output.get("term_counts", {})).items():
            claim_ids.append(
                self.knowledge.add_methodik(term, f"{topic} convergence count {count}", min(count / 3.0, 1.0))
            )
        if len(claim_ids) >= 2:
            self.knowledge.add_relation(claim_ids[0], claim_ids[1], "supports")
        self.knowledge.find_cycles()
        self.knowledge.apply_decay()

    def _stress_mode(self, analyze_output: dict[str, object]) -> str:
        paper_count = max(1, len(list(analyze_output.get("paper_ids", []))))
        term_counts = dict(analyze_output.get("term_counts", {}))
        convergence = max(term_counts.values(), default=0) / paper_count
        self._recent_convergence.append(convergence)
        self._recent_convergence = self._recent_convergence[-3:]
        if len(self._recent_convergence) == 3 and all(value < 0.30 for value in self._recent_convergence):
            return "tiefen-recherche-modus"
        return "normal"
