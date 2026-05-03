"""KMO Hotel-Membrane Module [CRUX-MK].

Welle-9γ Phase-3 Modul 3.2: Multi-Tenancy + GDPR + Cross-Hotel-Blocker.
"""

from .hotel_membrane import (
    ConsentRecord,
    CrossHotelQueryBlocker,
    DataCategory,
    GDPRComplianceLayer,
    HotelMembrane,
    ast_check_hotel_id_filter,
)

__all__ = [
    "ConsentRecord",
    "CrossHotelQueryBlocker",
    "DataCategory",
    "GDPRComplianceLayer",
    "HotelMembrane",
    "ast_check_hotel_id_filter",
]

# CRUX-MK
