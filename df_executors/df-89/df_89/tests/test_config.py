"""CRUX-MK tests for DF-89 configuration validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from df_89.config import DFConfig


def test_defaults_cover_k11_and_lc_requirements() -> None:
    config = DFConfig(topic="agents", state_dir=Path("state/df-89"))
    assert config.df_id == "DF-89"
    assert config.provenance_required_in_output is True
    assert config.degradation_modes == ["full", "degraded_arxiv", "standalone"]
    assert config.concurrent_spawn_protection == "both"


def test_budget_split_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        DFConfig(
            topic="agents",
            state_dir=Path("state"),
            convergence_budget_pct=0.7,
            innovation_budget_pct=0.4,
        )


def test_required_degradation_modes_are_enforced() -> None:
    with pytest.raises(ValidationError):
        DFConfig(topic="agents", state_dir=Path("state"), degradation_modes=["full"])


def test_topic_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        DFConfig(topic="   ", state_dir=Path("state"))


def test_from_json_file_loads_valid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"topic":"graphs","state_dir":"state/df-89"}', encoding="utf-8")
    config = DFConfig.from_json_file(path)
    assert config.topic == "graphs"
    assert config.state_dir == Path("state/df-89")
