from __future__ import annotations

from dataclasses import dataclass
import os
from threading import RLock
from typing import Any


class HubSpotError(ValueError):
    pass


@dataclass(frozen=True)
class Result:
    ok: bool
    id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ContactResult(Result):
    contact: dict[str, Any] | None = None
    contacts: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DealResult(Result):
    deal: dict[str, Any] | None = None
    deals: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ActivityResult(Result):
    activity: dict[str, Any] | None = None


@dataclass(frozen=True)
class CompanyResult(Result):
    companies: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class OAuth2Mock:
    access_token: str = "mock-access-token"
    refresh_token: str = "mock-refresh-token"
    token_type: str = "Bearer"

    def authorize(self) -> str:
        return self.access_token


class HubSpotClient:
    def __init__(self, *, backend: str | None = None, oauth: OAuth2Mock | None = None) -> None:
        self.backend = backend or os.getenv("HUBSPOT_CRM_BACKEND", "mock")
        self.oauth = oauth or OAuth2Mock()
        self._lock = RLock()
        self._contacts: dict[str, dict[str, Any]] = {}
        self._deals: dict[str, dict[str, Any]] = {}
        self._activities: dict[str, dict[str, Any]] = {}
        self._companies: dict[str, dict[str, Any]] = {}
        self._counters = {"contact": 0, "deal": 0, "activity": 0, "company": 0}

        if self.backend != "mock":
            raise NotImplementedError("Real HubSpot API backend is gated and not implemented in MVP")

        self._seed_companies()

    def _seed_companies(self) -> None:
        self._companies["company_1"] = {
            "id": "company_1",
            "name": "Hotel Demo GmbH",
            "domain": "hotel-demo.example",
        }
        self._counters["company"] = 1

    def _next_id(self, kind: str) -> str:
        self._counters[kind] += 1
        return f"{kind}_{self._counters[kind]}"

    @staticmethod
    def _copy_record(record: dict[str, Any]) -> dict[str, Any]:
        return dict(record)

    @staticmethod
    def _require_string(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise HubSpotError(f"{field} is required")
        return value.strip()

    def list_contacts(self) -> ContactResult:
        with self._lock:
            contacts = tuple(self._copy_record(item) for item in self._contacts.values())
            return ContactResult(ok=True, contacts=contacts)

    def create_contact(self, payload: dict[str, Any]) -> ContactResult:
        try:
            email = self._require_string(payload, "email")
            first_name = self._require_string(payload, "first_name")
            last_name = self._require_string(payload, "last_name")
        except HubSpotError as exc:
            return ContactResult(ok=False, error=str(exc))

        with self._lock:
            if any(contact["email"] == email for contact in self._contacts.values()):
                return ContactResult(ok=False, error="email already exists")

            contact_id = self._next_id("contact")
            contact = {
                "id": contact_id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "phone": payload.get("phone"),
                "guest_status": payload.get("guest_status", "lead"),
            }
            self._contacts[contact_id] = contact
            return ContactResult(ok=True, id=contact_id, contact=self._copy_record(contact))

    def update_contact(self, contact_id: str, payload: dict[str, Any]) -> ContactResult:
        if not contact_id:
            return ContactResult(ok=False, error="contact_id is required")

        allowed_fields = {"email", "first_name", "last_name", "phone", "guest_status"}
        updates = {key: value for key, value in payload.items() if key in allowed_fields}

        if not updates:
            return ContactResult(ok=False, error="no valid fields to update")

        with self._lock:
            contact = self._contacts.get(contact_id)
            if contact is None:
                return ContactResult(ok=False, error="contact not found")

            if "email" in updates:
                email = updates["email"]
                if not isinstance(email, str) or not email.strip():
                    return ContactResult(ok=False, error="email is required")
                if any(
                    item_id != contact_id and item["email"] == email.strip()
                    for item_id, item in self._contacts.items()
                ):
                    return ContactResult(ok=False, error="email already exists")
                updates["email"] = email.strip()

            contact.update(updates)
            return ContactResult(ok=True, id=contact_id, contact=self._copy_record(contact))

    def list_deals(self) -> DealResult:
        with self._lock:
            deals = tuple(self._copy_record(item) for item in self._deals.values())
            return DealResult(ok=True, deals=deals)

    def create_deal(self, payload: dict[str, Any]) -> DealResult:
        try:
            name = self._require_string(payload, "name")
            contact_id = self._require_string(payload, "contact_id")
        except HubSpotError as exc:
            return DealResult(ok=False, error=str(exc))

        amount = payload.get("amount", 0)
        if not isinstance(amount, int | float) or amount < 0:
            return DealResult(ok=False, error="amount must be a non-negative number")

        with self._lock:
            if contact_id not in self._contacts:
                return DealResult(ok=False, error="contact not found")

            deal_id = self._next_id("deal")
            deal = {
                "id": deal_id,
                "name": name,
                "contact_id": contact_id,
                "amount": amount,
                "stage": payload.get("stage", "new"),
                "check_in": payload.get("check_in"),
                "check_out": payload.get("check_out"),
            }
            self._deals[deal_id] = deal
            return DealResult(ok=True, id=deal_id, deal=self._copy_record(deal))

    def log_activity(self, payload: dict[str, Any]) -> ActivityResult:
        try:
            contact_id = self._require_string(payload, "contact_id")
            activity_type = self._require_string(payload, "activity_type")
            note = self._require_string(payload, "note")
        except HubSpotError as exc:
            return ActivityResult(ok=False, error=str(exc))

        with self._lock:
            if contact_id not in self._contacts:
                return ActivityResult(ok=False, error="contact not found")

            activity_id = self._next_id("activity")
            activity = {
                "id": activity_id,
                "contact_id": contact_id,
                "activity_type": activity_type,
                "note": note,
                "metadata": dict(payload.get("metadata", {})),
            }
            self._activities[activity_id] = activity
            return ActivityResult(ok=True, id=activity_id, activity=self._copy_record(activity))

    def list_companies(self) -> CompanyResult:
        with self._lock:
            companies = tuple(self._copy_record(item) for item in self._companies.values())
            return CompanyResult(ok=True, companies=companies)
