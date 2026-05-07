# [CRUX-MK]
"""Rate-Limiter-Pool (Welle-20 Phase-13.2 KMO-vNext, Modul 1/3).

Bio-Aequivalent: Glomerulaere-Filtration. Multi-Tenant Token-Bucket
mit Tenant-Isolation, Lazy-Refill, Burst-Allowance.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantConfig:
    """Configuration for a single tenant.

    Pre: capacity > 0, refill_rate > 0, burst_allowance >= 0
    Post: immutable; identity by tenant_id
    """

    tenant_id: str
    capacity: int
    refill_rate: float
    burst_allowance: int

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id must be non-empty")
        if self.capacity <= 0:
            raise ValueError("capacity must be > 0")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        if self.burst_allowance < 0:
            raise ValueError("burst_allowance must be >= 0")


@dataclass(frozen=True)
class RateLimitDecision:
    """Decision returned by acquire().

    Pre: tokens_remaining >= 0, retry_after_s >= 0
    Post: immutable; full audit-trail context
    """

    allowed: bool
    tenant_id: str
    tokens_remaining: float
    retry_after_s: float
    reason: str
    timestamp: float


class RateLimiterPool:
    """Multi-Tenant Token-Bucket Rate-Limiter.

    Pre: default_capacity > 0, default_refill_rate > 0
    Post: thread-safe; per-tenant isolated buckets;
          lazy-refill via time.time()-Delta;
          idempotent register_tenant; raises on unknown tenant.

    Bio-Aequivalent: Glomerulaere-Filtration mit Tenant-spezifischer
    Filtrationsrate und Druck-Kappung (capacity + burst).
    """

    def __init__(
        self,
        default_capacity: int = 100,
        default_refill_rate: float = 10.0,
    ) -> None:
        if default_capacity <= 0:
            raise ValueError("default_capacity must be > 0")
        if default_refill_rate <= 0:
            raise ValueError("default_refill_rate must be > 0")
        self.default_capacity = int(default_capacity)
        self.default_refill_rate = float(default_refill_rate)
        self._buckets: dict[str, dict] = {}
        self._lock = threading.RLock()

    def register_tenant(
        self,
        tenant_id: str,
        capacity: int | None = None,
        refill_rate: float | None = None,
        burst_allowance: int = 0,
    ) -> TenantConfig:
        """Register a tenant.

        Pre: tenant_id non-empty
        Post: idempotent if same config;
              raises ValueError if tenant_id already registered with different config.
        """
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        cap = int(capacity) if capacity is not None else self.default_capacity
        rate = float(refill_rate) if refill_rate is not None else self.default_refill_rate
        config = TenantConfig(
            tenant_id=tenant_id,
            capacity=cap,
            refill_rate=rate,
            burst_allowance=int(burst_allowance),
        )
        with self._lock:
            existing = self._buckets.get(tenant_id)
            if existing is not None:
                existing_config: TenantConfig = existing["config"]
                if existing_config == config:
                    return existing_config
                raise ValueError(
                    f"tenant_id {tenant_id!r} already registered with different config"
                )
            self._buckets[tenant_id] = {
                "config": config,
                "tokens": float(cap + config.burst_allowance),
                "last_refill": time.time(),
            }
            return config

    def _refill(self, bucket: dict, now: float) -> None:
        """Lazy-refill: add tokens proportional to elapsed time.

        Pre: bucket initialized; now >= bucket['last_refill']
        Post: tokens capped at capacity + burst_allowance
        """
        config: TenantConfig = bucket["config"]
        elapsed = max(0.0, now - bucket["last_refill"])
        added = elapsed * config.refill_rate
        max_tokens = float(config.capacity + config.burst_allowance)
        bucket["tokens"] = min(max_tokens, bucket["tokens"] + added)
        bucket["last_refill"] = now

    def acquire(self, tenant_id: str, tokens: int = 1) -> RateLimitDecision:
        """Try to consume tokens for tenant.

        Pre: tenant_id registered; tokens >= 1
        Post: returns RateLimitDecision; consumes tokens iff allowed.
        """
        if tokens < 1:
            raise ValueError("tokens must be >= 1")
        with self._lock:
            bucket = self._buckets.get(tenant_id)
            if bucket is None:
                raise ValueError(f"unknown tenant: {tenant_id!r}")
            now = time.time()
            self._refill(bucket, now)
            config: TenantConfig = bucket["config"]
            if bucket["tokens"] >= tokens:
                bucket["tokens"] -= tokens
                return RateLimitDecision(
                    allowed=True,
                    tenant_id=tenant_id,
                    tokens_remaining=bucket["tokens"],
                    retry_after_s=0.0,
                    reason=f"granted {tokens} token(s)",
                    timestamp=now,
                )
            # Not enough tokens
            deficit = tokens - bucket["tokens"]
            retry_after = deficit / config.refill_rate
            return RateLimitDecision(
                allowed=False,
                tenant_id=tenant_id,
                tokens_remaining=bucket["tokens"],
                retry_after_s=retry_after,
                reason=(
                    f"insufficient tokens: have {bucket['tokens']:.3f}, "
                    f"need {tokens}"
                ),
                timestamp=now,
            )

    def release(self, tenant_id: str, tokens: int = 1) -> None:
        """Return tokens manually (e.g. on cancellation).

        Pre: tenant_id registered; tokens >= 1
        Post: tokens added back, capped at capacity + burst_allowance
        """
        if tokens < 1:
            raise ValueError("tokens must be >= 1")
        with self._lock:
            bucket = self._buckets.get(tenant_id)
            if bucket is None:
                raise ValueError(f"unknown tenant: {tenant_id!r}")
            config: TenantConfig = bucket["config"]
            max_tokens = float(config.capacity + config.burst_allowance)
            bucket["tokens"] = min(max_tokens, bucket["tokens"] + tokens)

    def get_state(self, tenant_id: str) -> dict:
        """Snapshot of bucket state.

        Pre: tenant_id registered
        Post: returns dict with tokens, capacity, refill_rate, burst_allowance,
              last_refill (snapshot, not live reference).
        """
        with self._lock:
            bucket = self._buckets.get(tenant_id)
            if bucket is None:
                raise ValueError(f"unknown tenant: {tenant_id!r}")
            now = time.time()
            self._refill(bucket, now)
            config: TenantConfig = bucket["config"]
            return {
                "tenant_id": tenant_id,
                "tokens": bucket["tokens"],
                "capacity": config.capacity,
                "refill_rate": config.refill_rate,
                "burst_allowance": config.burst_allowance,
                "last_refill": bucket["last_refill"],
            }

    def list_tenants(self) -> list[str]:
        """Returns sorted list of registered tenant_ids."""
        with self._lock:
            return sorted(self._buckets.keys())


# CRUX-MK
