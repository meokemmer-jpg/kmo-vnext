from __future__ import annotations

from dataclasses import dataclass
import os
import threading
from typing import Any


@dataclass(frozen=True)
class EmailResult:
    ok: bool
    message_id: str | None = None
    status: str = "mocked"
    error: str | None = None


@dataclass(frozen=True)
class TemplateResult:
    ok: bool
    message_id: str | None = None
    template_id: str | None = None
    status: str = "mocked"
    error: str | None = None


@dataclass(frozen=True)
class ListResult:
    ok: bool
    action: str
    list_id: str | None = None
    list_data: dict[str, Any] | None = None
    status: str = "mocked"
    error: str | None = None


@dataclass(frozen=True)
class SuppressionResult:
    ok: bool
    email: str
    suppressed: bool | None = None
    status: str = "mocked"
    error: str | None = None


class SendGridClient:
    """MVP SendGrid API adapter with an in-memory mock backend by default."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        use_real_api: bool | None = None,
        env_var: str = "KMO_SENDGRID_USE_REAL_API",
    ) -> None:
        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")
        self.use_real_api = (
            os.getenv(env_var, "").strip().lower() in {"1", "true", "yes", "on"}
            if use_real_api is None
            else use_real_api
        )
        self._lock = threading.RLock()
        self._messages: dict[str, dict[str, Any]] = {}
        self._lists: dict[str, dict[str, Any]] = {}
        self._suppressions: set[str] = set()
        self._counter = 0

    def send_email(
        self,
        *,
        to_email: str,
        from_email: str,
        subject: str,
        content: str,
    ) -> EmailResult:
        error = self._validate_email_payload(to_email, from_email, subject, content)
        if error:
            return EmailResult(ok=False, error=error)

        if self.use_real_api:
            return EmailResult(ok=False, status="real_api_disabled", error="real API is not implemented in MVP")

        with self._lock:
            message_id = self._next_id("msg")
            self._messages[message_id] = {
                "to_email": to_email,
                "from_email": from_email,
                "subject": subject,
                "content": content,
                "kind": "email",
            }
            return EmailResult(ok=True, message_id=message_id)

    def send_template(
        self,
        *,
        to_email: str,
        from_email: str,
        template_id: str,
        dynamic_data: dict[str, Any] | None = None,
    ) -> TemplateResult:
        error = self._validate_email(to_email) or self._validate_email(from_email)
        if error:
            return TemplateResult(ok=False, template_id=template_id, error=error)
        if not template_id.strip():
            return TemplateResult(ok=False, template_id=template_id, error="template_id is required")

        if self.use_real_api:
            return TemplateResult(
                ok=False,
                template_id=template_id,
                status="real_api_disabled",
                error="real API is not implemented in MVP",
            )

        with self._lock:
            message_id = self._next_id("tmpl")
            self._messages[message_id] = {
                "to_email": to_email,
                "from_email": from_email,
                "template_id": template_id,
                "dynamic_data": dict(dynamic_data or {}),
                "kind": "template",
            }
            return TemplateResult(ok=True, message_id=message_id, template_id=template_id)

    def manage_lists(
        self,
        *,
        action: str,
        list_id: str | None = None,
        name: str | None = None,
        contacts: list[str] | None = None,
    ) -> ListResult:
        normalized_action = action.strip().lower()
        contacts = list(contacts or [])

        if normalized_action not in {"create", "get", "update", "delete"}:
            return ListResult(ok=False, action=action, error="unsupported list action")

        if self.use_real_api:
            return ListResult(
                ok=False,
                action=normalized_action,
                status="real_api_disabled",
                error="real API is not implemented in MVP",
            )

        with self._lock:
            if normalized_action == "create":
                if not name or not name.strip():
                    return ListResult(ok=False, action=normalized_action, error="name is required")
                invalid_contact = next((email for email in contacts if self._validate_email(email)), None)
                if invalid_contact:
                    return ListResult(ok=False, action=normalized_action, error=f"invalid contact: {invalid_contact}")

                new_id = self._next_id("list")
                data = {"id": new_id, "name": name, "contacts": contacts}
                self._lists[new_id] = data
                return ListResult(ok=True, action=normalized_action, list_id=new_id, list_data=dict(data))

            if not list_id:
                return ListResult(ok=False, action=normalized_action, error="list_id is required")

            if list_id not in self._lists:
                return ListResult(ok=False, action=normalized_action, list_id=list_id, error="list not found")

            if normalized_action == "get":
                return ListResult(
                    ok=True,
                    action=normalized_action,
                    list_id=list_id,
                    list_data=dict(self._lists[list_id]),
                )

            if normalized_action == "update":
                if name is not None:
                    self._lists[list_id]["name"] = name
                if contacts:
                    invalid_contact = next((email for email in contacts if self._validate_email(email)), None)
                    if invalid_contact:
                        return ListResult(
                            ok=False,
                            action=normalized_action,
                            list_id=list_id,
                            error=f"invalid contact: {invalid_contact}",
                        )
                    self._lists[list_id]["contacts"] = contacts
                return ListResult(
                    ok=True,
                    action=normalized_action,
                    list_id=list_id,
                    list_data=dict(self._lists[list_id]),
                )

            deleted = self._lists.pop(list_id)
            return ListResult(ok=True, action=normalized_action, list_id=list_id, list_data=dict(deleted))

    def suppression_handling(self, *, action: str, email: str) -> SuppressionResult:
        normalized_action = action.strip().lower()
        if normalized_action not in {"add", "remove", "check"}:
            return SuppressionResult(ok=False, email=email, error="unsupported suppression action")

        error = self._validate_email(email)
        if error:
            return SuppressionResult(ok=False, email=email, error=error)

        if self.use_real_api:
            return SuppressionResult(
                ok=False,
                email=email,
                status="real_api_disabled",
                error="real API is not implemented in MVP",
            )

        with self._lock:
            if normalized_action == "add":
                self._suppressions.add(email)
                return SuppressionResult(ok=True, email=email, suppressed=True)

            if normalized_action == "remove":
                self._suppressions.discard(email)
                return SuppressionResult(ok=True, email=email, suppressed=False)

            return SuppressionResult(ok=True, email=email, suppressed=email in self._suppressions)

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def _validate_email_payload(
        self,
        to_email: str,
        from_email: str,
        subject: str,
        content: str,
    ) -> str | None:
        return (
            self._validate_email(to_email)
            or self._validate_email(from_email)
            or ("subject is required" if not subject.strip() else None)
            or ("content is required" if not content.strip() else None)
        )

    @staticmethod
    def _validate_email(email: str) -> str | None:
        if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
            return "valid email is required"
        return None
