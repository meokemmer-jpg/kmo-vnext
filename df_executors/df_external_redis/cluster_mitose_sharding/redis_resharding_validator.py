"""Redis-Resharding Validator -- Conservation-Law Verification post-Mitose [CRUX-MK].

Externe Domain: Redis-Cluster Resharding-Verification.
Pure Redis-Domain: KEINE crux/governance/Kemmer-Imports.

Bio-Pattern (Mitotic-Checkpoint):
    Cell-Cycle Quality-Control. Verifies post-mitose:
        - DNA-Integrity     -> all keys preserved (no loss)
        - Equal-Distribution -> chromatid-pairs separated correctly
        - Spindle-Function  -> slot-ranges remain disjoint + complete

Conservation-Law:
    For each key 'k' present pre-mitose:
        post-mitose: exactly one shard contains 'k'
        AND that shard's slot-range covers crc16_slot(k).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .redis_cluster_topology import (
    RedisClusterTopology,
    TOTAL_SLOTS,
    crc16_slot,
)


class ConservationViolation(str, Enum):
    """Categories of Conservation-Law violation."""
    KEY_LOST = "key_lost"                  # key missing post-mitose
    KEY_DUPLICATED = "key_duplicated"      # key in 2+ daughters
    KEY_WRONG_SHARD = "key_wrong_shard"    # key in shard not owning its slot
    SLOT_COVERAGE_GAP = "slot_coverage_gap"
    SLOT_OVERLAP = "slot_overlap"


@dataclass(frozen=True)
class ValidationFinding:
    """One Conservation-Law violation."""
    violation: ConservationViolation
    key: Optional[str] = None
    shard_id: Optional[str] = None
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    """Resharding-Validation summary."""
    pre_key_count: int
    post_key_count: int
    findings: tuple[ValidationFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings and self.pre_key_count == self.post_key_count


class RedisReshardingValidator:
    """Validates Conservation-Law across a mitose-cycle.

    Usage:
        validator = RedisReshardingValidator(topology)
        pre_keys = collect_keys(kv_store_before)
        # ... run mitose ...
        post_keys = collect_keys(kv_store_after)
        report = validator.validate(pre_keys, post_keys, kv_store_after)
        assert report.passed
    """

    def __init__(self, topology: RedisClusterTopology) -> None:
        self.topology = topology

    def validate(
        self,
        pre_keys: set[str],
        post_kv_store: dict[str, dict[str, str]],
    ) -> ValidationReport:
        """Run full Conservation-Law check post-mitose."""
        findings: list[ValidationFinding] = []
        # Aggregate post-keys across all shards.
        post_key_to_shards: dict[str, list[str]] = {}
        for shard_id, kv in post_kv_store.items():
            for k in kv.keys():
                post_key_to_shards.setdefault(k, []).append(shard_id)
        post_keys = set(post_key_to_shards.keys())
        # 1. KEY_LOST: pre-keys missing post-mitose.
        lost = pre_keys - post_keys
        for k in lost:
            findings.append(
                ValidationFinding(
                    violation=ConservationViolation.KEY_LOST,
                    key=k,
                    detail="key absent from all post-mitose shards",
                )
            )
        # 2. KEY_DUPLICATED: key present in 2+ shards.
        for k, shard_list in post_key_to_shards.items():
            if len(shard_list) > 1:
                findings.append(
                    ValidationFinding(
                        violation=ConservationViolation.KEY_DUPLICATED,
                        key=k,
                        detail=f"present in shards: {shard_list}",
                    )
                )
        # 3. KEY_WRONG_SHARD: key in shard not owning its CRC16-slot.
        snapshot = self.topology.snapshot()
        shard_lookup = {s.shard_id: s for s in snapshot.shards}
        for k, shard_list in post_key_to_shards.items():
            for sid in shard_list:
                shard = shard_lookup.get(sid)
                if shard is None:
                    findings.append(
                        ValidationFinding(
                            violation=ConservationViolation.KEY_WRONG_SHARD,
                            key=k,
                            shard_id=sid,
                            detail="shard not in current topology",
                        )
                    )
                    continue
                slot = crc16_slot(k)
                if not shard.owns(slot):
                    findings.append(
                        ValidationFinding(
                            violation=ConservationViolation.KEY_WRONG_SHARD,
                            key=k,
                            shard_id=sid,
                            detail=f"slot {slot} not in shard's ranges",
                        )
                    )
        # 4. Slot-coverage: delegated to topology.verify_invariants().
        try:
            self.topology.verify_invariants()
        except ValueError as exc:
            msg = str(exc)
            if "gap" in msg or "not covered" in msg:
                violation = ConservationViolation.SLOT_COVERAGE_GAP
            elif "overlap" in msg:
                violation = ConservationViolation.SLOT_OVERLAP
            else:
                violation = ConservationViolation.SLOT_COVERAGE_GAP
            findings.append(
                ValidationFinding(violation=violation, detail=msg)
            )
        return ValidationReport(
            pre_key_count=len(pre_keys),
            post_key_count=len(post_keys),
            findings=tuple(findings),
        )

    def quick_invariant_check(self) -> Optional[str]:
        """Lightweight check: only topology-invariants (skip key-level).

        Returns None on pass, error-message on fail.
        """
        try:
            self.topology.verify_invariants()
            return None
        except ValueError as exc:
            return str(exc)


# CRUX-MK
