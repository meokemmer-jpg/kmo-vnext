"""CRUX-MK configuration schema for DF-89 Research-Gate-Inquirer."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DFConfig(BaseModel):
    """Validated runtime configuration for the DF-89 MAPE-K loop."""

    model_config = ConfigDict(validate_assignment=True)

    df_id: Literal["DF-89"] = "DF-89"
    df_name: str = "research-gate-inquirer"
    version: str = "0.1.0-skeleton"

    cascade_isolation: Literal["none", "soft", "hard", "strict"] = "soft"
    failure_blast_radius: int = Field(default=0, ge=0)
    output_feeds_into_training: bool = False
    provenance_required_in_output: bool = True
    external_anchor_type: Literal[
        "arxiv", "semantic_scholar", "wikipedia", "google_scholar"
    ] = "arxiv"
    pre_action_domain_check: bool = True
    pre_action_backup_check: bool = True
    pipeline_cost_estimate_required: bool = True
    quota_budget_ceiling_calls: int = Field(default=90, ge=1)
    cost_overrun_action: Literal["warn", "reduce_pipeline", "hard_stop"] = "hard_stop"
    concurrent_spawn_protection: Literal[
        "wrapper_mutex_only", "engine_self_detect_only", "both"
    ] = "both"
    lock_dir: str = "/tmp/df-89.lock"
    lock_stale_age_h: int = Field(default=6, ge=1)

    degradation_modes: list[str] = Field(
        default_factory=lambda: ["full", "degraded_arxiv", "standalone"]
    )
    direct_mode_available: bool = True
    direct_mode_capability: float = Field(default=0.30, ge=0.0, le=1.0)
    circuit_breaker_timeout_s: int = Field(default=60, ge=1)
    circuit_breaker_open_threshold: int = Field(default=3, ge=1)
    circuit_breaker_half_open_test_interval_s: int = Field(default=600, ge=1)
    state_externalization: bool = True
    idempotent_operations: bool = True
    health_check_dependencies: list[str] = Field(default_factory=list)

    trinity_compliant: bool = True
    topic: str
    daily_cron_hour: int = Field(default=3, ge=0, le=23)
    state_dir: Path
    convergence_budget_pct: float = Field(default=0.80, ge=0.0, le=1.0)
    innovation_budget_pct: float = Field(default=0.20, ge=0.0, le=1.0)

    @field_validator("topic")
    @classmethod
    def _topic_required(cls, value: str) -> str:
        """Pre: value is parsed as a string. Post: returns a non-empty topic."""
        topic = value.strip()
        if not topic:
            raise ValueError("topic must not be blank")
        return topic

    @field_validator("state_dir")
    @classmethod
    def _state_dir_required(cls, value: Path) -> Path:
        """Pre: value is parsed as a path. Post: returns a non-empty path."""
        if not str(value).strip():
            raise ValueError("state_dir must not be empty")
        return value

    @field_validator("lock_dir")
    @classmethod
    def _lock_dir_required(cls, value: str) -> str:
        """Pre: value is parsed as a string. Post: returns a non-empty lock path."""
        if not value.strip():
            raise ValueError("lock_dir must not be blank")
        return value

    @field_validator("degradation_modes")
    @classmethod
    def _check_degradation_modes(cls, value: list[str]) -> list[str]:
        """Pre: value is parsed as a list. Post: required LC modes are present."""
        required = {"full", "degraded_arxiv", "standalone"}
        if not required.issubset(set(value)):
            raise ValueError("degradation_modes must include full/degraded_arxiv/standalone")
        return value

    @model_validator(mode="after")
    def _check_invariants(self) -> "DFConfig":
        """Pre: all fields are parsed. Post: cross-field invariants hold."""
        total = self.convergence_budget_pct + self.innovation_budget_pct
        if abs(total - 1.0) > 1e-9:
            raise ValueError("convergence_budget_pct and innovation_budget_pct must sum to 1.0")
        if not self.trinity_compliant:
            raise ValueError("trinity_compliant must remain true")
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> "DFConfig":
        """Pre: path exists and contains JSON. Post: returns a validated config."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
