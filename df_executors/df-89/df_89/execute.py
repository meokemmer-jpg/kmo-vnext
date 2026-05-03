"""CRUX-MK execute phase with idempotent audit logging for DF-89."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .config import DFConfig
from .knowledge import KnowledgeStore
from .plan import Plan


class BudgetExceededError(RuntimeError):
    """Raised when the configured call budget would be exceeded."""


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome produced by the execute phase."""

    event_id: str
    executed: bool
    calls_used: int
    message: str


class Executor:
    """Executes a chosen plan with quota checks and atomic audit writes."""

    def __init__(self, config: DFConfig, audit_dir: Path = Path("audit")) -> None:
        self.config = config
        self.audit_dir = audit_dir

    def execute_plan(self, plan: Plan, knowledge: KnowledgeStore) -> ExecutionResult:
        """Pre: plan is selected and knowledge is writable. Post: execution is idempotently recorded."""
        self._pre_action_verify()
        calls_used = self._estimate_calls(plan)
        if calls_used > self.config.quota_budget_ceiling_calls:
            raise BudgetExceededError("quota_budget_ceiling_calls exceeded")
        payload = {"lane": plan.lane, "status": plan.status, "candidate_ids": plan.candidate_ids}
        event_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        if knowledge.has_processed_event(event_id):
            return ExecutionResult(event_id=event_id, executed=False, calls_used=0, message="already executed")
        knowledge.record_processed_event(event_id, payload)
        result = ExecutionResult(
            event_id=event_id,
            executed=True,
            calls_used=calls_used,
            message="stubbed WebFetch + 3-LLM validation executed",
        )
        self._append_audit_record({"at": _utc_now(), "plan": asdict(plan), "result": asdict(result)})
        return result

    def _pre_action_verify(self) -> None:
        """Pre: config toggles are set. Post: raises if env, mount, or backup checks fail."""
        env_tag = os.environ.get("DF_89_ENV_TAG", "dev")
        mount_point = Path(os.environ.get("DF_89_MOUNT_POINT", "."))
        backup_status = os.environ.get("DF_89_BACKUP_STATUS", "ok")
        if self.config.pre_action_domain_check and not env_tag:
            raise RuntimeError("env_tag missing")
        if self.config.pre_action_domain_check and not mount_point.exists():
            raise RuntimeError("mount_point missing")
        if self.config.pre_action_backup_check and backup_status != "ok":
            raise RuntimeError("backup_status not ok")

    def _estimate_calls(self, plan: Plan) -> int:
        return 1 + 3 + len(plan.candidate_ids)

    def _append_audit_record(self, record: dict[str, object]) -> None:
        path = self.audit_dir / "df-89-actions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        prior = path.read_text(encoding="utf-8") if path.exists() else ""
        line = json.dumps(record, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(prior)
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
