from __future__ import annotations

from dataclasses import dataclass
import json
import os
import threading
from typing import Any
from xml.etree import ElementTree as ET


class BookingComError(ValueError):
    pass


@dataclass(frozen=True)
class PropertyResult:
    ok: bool
    property_id: str
    data: dict[str, Any]
    format: str
    message: str = ""


@dataclass(frozen=True)
class AvailabilityPushResult:
    ok: bool
    property_id: str
    updated: dict[str, Any]
    format: str
    notification_id: str
    message: str = ""


@dataclass(frozen=True)
class ReservationResult:
    ok: bool
    reservation_id: str
    data: dict[str, Any]
    format: str
    message: str = ""


@dataclass(frozen=True)
class CancellationResult:
    ok: bool
    reservation_id: str
    cancelled: bool
    format: str
    message: str = ""


@dataclass(frozen=True)
class ContentManagementResult:
    ok: bool
    property_id: str
    content: dict[str, Any]
    format: str
    message: str = ""


class BookingComClient:
    def __init__(
        self,
        *,
        property_id: str = "demo-property",
        api_key: str | None = None,
        use_mock: bool | None = None,
    ) -> None:
        self.property_id = self._require_non_empty(property_id, "property_id")
        self.api_key = api_key or os.getenv("BOOKING_COM_API_KEY")
        self.use_mock = (
            os.getenv("BOOKING_COM_USE_MOCK", "1").strip().lower()
            not in {"0", "false", "no"}
            if use_mock is None
            else use_mock
        )
        self._lock = threading.RLock()
        self._notifications: list[dict[str, Any]] = []
        self._properties: dict[str, dict[str, Any]] = {
            self.property_id: {
                "property_id": self.property_id,
                "name": "Demo Hotel",
                "currency": "EUR",
                "rooms": {"STD": {"name": "Standard Room", "max_occupancy": 2}},
                "availability": {},
                "content": {},
            }
        }
        self._reservations: dict[str, dict[str, Any]] = {}

    @property
    def notifications(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._notifications)

    def get_property(self, property_id: str | None = None, *, format: str = "json") -> PropertyResult:
        fmt = self._format(format)
        pid = self._property_id(property_id)
        self._ensure_mock()

        with self._lock:
            prop = self._properties.get(pid)
            if prop is None:
                return PropertyResult(False, pid, {}, fmt, "property not found")
            return PropertyResult(True, pid, self._clone(prop, fmt), fmt)

    def push_availability(
        self,
        rates: dict[str, Any],
        restrictions: dict[str, Any],
        inventory: dict[str, Any],
        *,
        property_id: str | None = None,
        format: str = "json",
    ) -> AvailabilityPushResult:
        fmt = self._format(format)
        pid = self._property_id(property_id)
        self._validate_mapping(rates, "rates")
        self._validate_mapping(restrictions, "restrictions")
        self._validate_mapping(inventory, "inventory")
        self._ensure_mock()

        with self._lock:
            prop = self._properties.get(pid)
            if prop is None:
                return AvailabilityPushResult(False, pid, {}, fmt, "", "property not found")

            updated = {
                "rates": self._roundtrip(rates, fmt),
                "restrictions": self._roundtrip(restrictions, fmt),
                "inventory": self._roundtrip(inventory, fmt),
            }
            prop["availability"] = updated
            notification_id = self._push_notification("availability", pid, updated)
            return AvailabilityPushResult(True, pid, self._clone(updated, fmt), fmt, notification_id)

    def confirm_reservation(
        self,
        reservation: dict[str, Any],
        *,
        format: str = "json",
    ) -> ReservationResult:
        fmt = self._format(format)
        self._validate_mapping(reservation, "reservation")
        rid = self._require_non_empty(str(reservation.get("reservation_id", "")), "reservation_id")
        pid = self._property_id(str(reservation.get("property_id", self.property_id)))
        self._ensure_mock()

        with self._lock:
            if pid not in self._properties:
                return ReservationResult(False, rid, {}, fmt, "property not found")
            if rid in self._reservations:
                return ReservationResult(False, rid, self._clone(self._reservations[rid], fmt), fmt, "reservation already exists")

            payload = self._roundtrip({**reservation, "property_id": pid, "status": "confirmed"}, fmt)
            self._reservations[rid] = payload
            self._push_notification("reservation_confirmed", pid, payload)
            return ReservationResult(True, rid, self._clone(payload, fmt), fmt)

    def modify_reservation(
        self,
        reservation_id: str,
        changes: dict[str, Any],
        *,
        format: str = "json",
    ) -> ReservationResult:
        fmt = self._format(format)
        rid = self._require_non_empty(reservation_id, "reservation_id")
        self._validate_mapping(changes, "changes")
        self._ensure_mock()

        with self._lock:
            existing = self._reservations.get(rid)
            if existing is None:
                return ReservationResult(False, rid, {}, fmt, "reservation not found")
            if existing.get("status") == "cancelled":
                return ReservationResult(False, rid, self._clone(existing, fmt), fmt, "reservation already cancelled")

            updated = self._roundtrip({**existing, **changes, "reservation_id": rid, "status": "modified"}, fmt)
            self._reservations[rid] = updated
            self._push_notification("reservation_modified", str(updated["property_id"]), updated)
            return ReservationResult(True, rid, self._clone(updated, fmt), fmt)

    def cancel_reservation(
        self,
        reservation_id: str,
        *,
        reason: str = "",
        format: str = "json",
    ) -> CancellationResult:
        fmt = self._format(format)
        rid = self._require_non_empty(reservation_id, "reservation_id")
        self._ensure_mock()

        with self._lock:
            existing = self._reservations.get(rid)
            if existing is None:
                return CancellationResult(False, rid, False, fmt, "reservation not found")
            if existing.get("status") == "cancelled":
                return CancellationResult(False, rid, True, fmt, "reservation already cancelled")

            existing["status"] = "cancelled"
            existing["cancellation_reason"] = reason
            self._push_notification("reservation_cancelled", str(existing["property_id"]), existing)
            return CancellationResult(True, rid, True, fmt)

    def content_management(
        self,
        content: dict[str, Any],
        *,
        property_id: str | None = None,
        format: str = "json",
    ) -> ContentManagementResult:
        fmt = self._format(format)
        pid = self._property_id(property_id)
        self._validate_mapping(content, "content")
        self._ensure_mock()

        with self._lock:
            prop = self._properties.get(pid)
            if prop is None:
                return ContentManagementResult(False, pid, {}, fmt, "property not found")

            prop["content"] = self._roundtrip(content, fmt)
            notification_id = self._push_notification("content_updated", pid, prop["content"])
            result_content = self._clone({**prop["content"], "notification_id": notification_id}, fmt)
            return ContentManagementResult(True, pid, result_content, fmt)

    def serialize(self, payload: dict[str, Any], *, format: str = "json") -> str:
        fmt = self._format(format)
        if fmt == "json":
            return json.dumps(payload, sort_keys=True)
        root = ET.Element("booking_com")
        self._xml_add(root, payload)
        return ET.tostring(root, encoding="unicode")

    def deserialize(self, payload: str, *, format: str = "json") -> dict[str, Any]:
        fmt = self._format(format)
        if fmt == "json":
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise BookingComError("json payload must decode to an object")
            return data
        root = ET.fromstring(payload)
        return self._xml_read(root)

    def _ensure_mock(self) -> None:
        if not self.use_mock:
            raise NotImplementedError("real Booking.com OTA API switch is gated; mock backend is the MVP default")

    def _push_notification(self, event: str, property_id: str, payload: dict[str, Any]) -> str:
        notification_id = f"mock-notification-{len(self._notifications) + 1}"
        self._notifications.append(
            {
                "notification_id": notification_id,
                "event": event,
                "property_id": property_id,
                "payload": self._clone(payload, "json"),
            }
        )
        return notification_id

    def _property_id(self, property_id: str | None) -> str:
        return self._require_non_empty(property_id or self.property_id, "property_id")

    @staticmethod
    def _format(format: str) -> str:
        fmt = format.strip().lower()
        if fmt not in {"json", "xml"}:
            raise BookingComError("format must be 'json' or 'xml'")
        return fmt

    @staticmethod
    def _require_non_empty(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise BookingComError(f"{field} is required")
        return value.strip()

    @staticmethod
    def _validate_mapping(value: dict[str, Any], field: str) -> None:
        if not isinstance(value, dict) or not value:
            raise BookingComError(f"{field} must be a non-empty dict")

    def _roundtrip(self, value: dict[str, Any], fmt: str) -> dict[str, Any]:
        return self.deserialize(self.serialize(value, format=fmt), format=fmt)

    def _clone(self, value: dict[str, Any], fmt: str) -> dict[str, Any]:
        return self._roundtrip(value, fmt)

    def _xml_add(self, parent: ET.Element, value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            node = ET.SubElement(parent, key or "object") if key else parent
            for child_key, child_value in value.items():
                self._xml_add(node, child_value, str(child_key))
            return
        if isinstance(value, list):
            node = ET.SubElement(parent, key or "list")
            for item in value:
                self._xml_add(node, item, "item")
            return
        node = ET.SubElement(parent, key or "value")
        node.text = "" if value is None else str(value)

    def _xml_read(self, element: ET.Element) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for child in element:
            if list(child):
                value: Any = self._xml_read(child)
                if all(grandchild.tag == "item" for grandchild in child):
                    value = list(value.values())
            else:
                value = child.text or ""

            if child.tag in result:
                existing = result[child.tag]
                if not isinstance(existing, list):
                    result[child.tag] = [existing]
                result[child.tag].append(value)
            else:
                result[child.tag] = value
        return result
