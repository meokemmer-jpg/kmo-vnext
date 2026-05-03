"""CRUX-MK tests for the DF-89 MAPE-K engine."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from df_89.config import DFConfig
from df_89.engine import MAPEKEngine
from df_89.execute import ExecutionResult
from df_89.knowledge import KnowledgeStore
from df_89.monitor import Paper
from df_89.plan import Plan


def build_engine(tmp_path: Path) -> MAPEKEngine:
    config = DFConfig(
        topic="graphs",
        state_dir=tmp_path / "state",
        lock_dir=str(tmp_path / "lock"),
        concurrent_spawn_protection="wrapper_mutex_only",
    )
    return MAPEKEngine(config, KnowledgeStore(tmp_path / "knowledge.sqlite"))


def sample_papers() -> list[Paper]:
    return [
        Paper(
            id=f"p{idx}",
            title=f"Graph Method {idx}",
            abstract="method pipeline graph",
            venue="Nature",
            authors=[f"Author {idx}"],
            citations=100 + idx,
            year=2024,
            source_type="stub",
            source_url=f"https://example.com/{idx}",
            fetched_at=datetime.now(UTC),
        )
        for idx in range(3)
    ]


@dataclass
class FakeMonitor:
    papers: list[Paper]

    def collect(self, query: str, max_results: int = 3) -> list[Paper]:
        return self.papers


@dataclass
class FakeExecutor:
    result: ExecutionResult

    def execute_plan(self, plan: Plan, knowledge: KnowledgeStore) -> ExecutionResult:
        knowledge.record_processed_event("fake-event", {"lane": plan.lane})
        return self.result


def test_run_once_completes_full_loop(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    engine.monitor = FakeMonitor(sample_papers())
    engine.executor = FakeExecutor(ExecutionResult("evt", True, 4, "ok"))
    result = engine.run_once("graphs")
    assert result.execution.executed is True
    assert len(result.plans) == 3
    assert result.stress_mode == "normal"


def test_engine_enters_stress_mode_after_three_weak_iterations(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    weak = [
        Paper(
            id="p0",
            title="Noise",
            abstract="unrelated text",
            venue="Workshop",
            authors=["Ada"],
            citations=1,
            year=2020,
            source_type="stub",
            source_url="https://example.com/0",
            fetched_at=datetime.now(UTC),
        )
    ]
    engine.monitor = FakeMonitor(weak)
    engine.executor = FakeExecutor(ExecutionResult("evt", True, 4, "ok"))
    assert engine.run_once("noise").stress_mode == "normal"
    assert engine.run_once("noise").stress_mode == "normal"
    assert engine.run_once("noise").stress_mode == "tiefen-recherche-modus"


def test_run_once_updates_knowledge_catalog(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    engine.monitor = FakeMonitor(sample_papers())
    engine.executor = FakeExecutor(ExecutionResult("evt", True, 4, "ok"))
    engine.run_once("graphs")
    assert engine.knowledge.dump_snapshot()["methodik_catalog"] > 0
