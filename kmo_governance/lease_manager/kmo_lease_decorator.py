"""KMO Lease Decorator [CRUX-MK].

Convenience-Decorator fuer einfache DF-Integration.
Auto-acquire vor Function-Call, Auto-release danach, Heartbeat-Thread fuer langlaufende Tasks.

Usage:
    from kmo_lease_manager import LeaseManager, ResourceType
    from kmo_lease_decorator import with_lease

    mgr = LeaseManager()

    @with_lease(
        manager=mgr,
        resource_type=ResourceType.DF,
        resource_id_func=lambda *a, **kw: kw.get("df_name", "unknown"),
        holder_func=lambda *a, **kw: f"mac.{kw.get('df_name', 'x')}.pid-{os.getpid()}",
        ttl_sec=300,
    )
    def run_df(df_name: str) -> None:
        # ... long-running work ...
        pass
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from kmo_lease_manager import (
    DEFAULT_TTL_SEC,
    HEARTBEAT_INTERVAL_SEC,
    LeaseManager,
    ResourceType,
)

logger = logging.getLogger(__name__)


class LeaseAcquireFailed(RuntimeError):
    """Raised when @with_lease cannot acquire the lease (resource busy / STOP.flag)."""


def _default_holder(*args: Any, **kwargs: Any) -> str:
    """Fallback holder string: 'pid-{os.getpid()}-tid-{thread.ident}'."""
    return f"pid-{os.getpid()}-tid-{threading.get_ident()}"


def with_lease(
    manager: LeaseManager,
    resource_type: ResourceType,
    resource_id_func: Callable[..., str],
    holder_func: Optional[Callable[..., str]] = None,
    ttl_sec: int = DEFAULT_TTL_SEC,
    heartbeat_interval_sec: int = HEARTBEAT_INTERVAL_SEC,
    raise_on_acquire_fail: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: acquires a lease before the wrapped function, releases after.

    Args:
        manager: shared LeaseManager instance
        resource_type: ResourceType enum value
        resource_id_func: callable(*args, **kwargs) -> resource_id string
        holder_func: callable(*args, **kwargs) -> holder string (optional, default: pid+tid)
        ttl_sec: lease TTL
        heartbeat_interval_sec: background heartbeat cadence
        raise_on_acquire_fail: if True, raise LeaseAcquireFailed; if False, return None

    Pre: callables resolve to non-empty strings; ttl_sec > heartbeat_interval_sec
    Post: lease is released even if wrapped function raises
    """
    if ttl_sec <= heartbeat_interval_sec:
        raise ValueError("ttl_sec must be > heartbeat_interval_sec")
    holder_func = holder_func or _default_holder

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            resource_id = resource_id_func(*args, **kwargs)
            holder = holder_func(*args, **kwargs)
            token = manager.acquire(
                resource_type=resource_type,
                resource_id=resource_id,
                holder=holder,
                ttl_sec=ttl_sec,
            )
            if token is None:
                msg = (
                    f"Could not acquire lease for {resource_type.value}/{resource_id} "
                    f"(holder={holder}). Resource busy or STOP.flag present."
                )
                if raise_on_acquire_fail:
                    raise LeaseAcquireFailed(msg)
                logger.warning(msg)
                return None

            stop_event = threading.Event()
            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                args=(manager, token, ttl_sec, heartbeat_interval_sec, stop_event),
                daemon=True,
                name=f"kmo-heartbeat-{resource_id}",
            )
            heartbeat_thread.start()

            try:
                return func(*args, **kwargs)
            finally:
                stop_event.set()
                heartbeat_thread.join(timeout=2.0)
                manager.release(token)

        return wrapper

    return decorator


def _heartbeat_loop(
    manager: LeaseManager,
    token: str,
    ttl_sec: int,
    interval_sec: int,
    stop_event: threading.Event,
) -> None:
    """Background thread: refresh lease every interval_sec until stop_event set."""
    while not stop_event.wait(timeout=interval_sec):
        ok = manager.heartbeat(token, ttl_sec=ttl_sec)
        if not ok:
            logger.warning("Heartbeat failed for token %s (lease may be lost)", token)
            return


# CRUX-MK
