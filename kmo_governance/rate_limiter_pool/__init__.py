# [CRUX-MK]
"""Rate-Limiter-Pool (Welle-20 Phase-13.2 KMO-vNext, Modul 1/3).

Bio-Aequivalent: Glomerulaere-Filtration (Niere filtert Multi-Source-Substanzen
mit Tenant-Isolation). Jeder Tenant bekommt eigene Filtrationsrate. Druck-bedingte
Capacity-Kappung verhindert systemische Ueberlastung.

Multi-Tenant zentraler Token-Bucket-Rate-Limiter mit:
- Per-Tenant Capacity + Refill-Rate + Burst-Allowance
- Time-Delta-basiertes Lazy-Refill (kein Background-Thread)
- Idempotente Tenant-Registrierung
- Thread-safe via threading.RLock
- Frozen-Dataclass Decision-Type fuer Audit-Trail
"""
from .rate_limiter_pool import (
    RateLimitDecision,
    RateLimiterPool,
    TenantConfig,
)

__all__ = ["RateLimiterPool", "TenantConfig", "RateLimitDecision"]

# CRUX-MK
