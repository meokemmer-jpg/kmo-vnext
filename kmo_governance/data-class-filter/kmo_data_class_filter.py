"""KMO Data-Class Filter [CRUX-MK]

Pre-Routing-Hook for KMO Dark-Factory: classifies prompts into 4 data-classes
(PUBLIC / INTERNAL / CONFIDENTIAL / SECRET) and blocks LLM-routing at provider
incompatibility.

Architecture:
- DataClass enum with hierarchy (1=PUBLIC ... 4=SECRET)
- Provider-Compatibility-Matrix loaded from YAML (max-data-class per provider)
- Frontmatter-Tag-First classification, fallback to regex pattern detection for SECRET
- Append-only JSONL audit log (branch-hub/audit/kmo-routing-decisions.jsonl)

Implements KMO v0.2.0 Patch P-KMO-A5 (Daten-Klassifikation No-Go-Matrix).

CRUX-Bindung:
- K_0 protected: SECRET-class never routed to flat-LLMs (credential leak prevention)
- Q_0 protected: CONFIDENTIAL/SECRET stays in tightly-controlled providers
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Optional

import yaml

# Constants (no magic numbers; units explicit)
DEFAULT_CONFIG_PATH: Path = Path(__file__).parent / "provider_compat.yaml"
DEFAULT_AUDIT_LOG_PATH: Path = (
    Path.home()
    / "Library"
    / "CloudStorage"
    / "GoogleDrive-m.e.o.kemmer@gmail.com"
    / "Meine Ablage"
    / "Claude-Knowledge-System"
    / "branch-hub"
    / "audit"
    / "kmo-routing-decisions.jsonl"
)
FALLBACK_AUDIT_LOG_PATH: Path = Path.home() / ".kmo" / "kmo-routing-decisions.jsonl"


class DataClass(IntEnum):
    """4-stage data classification (higher value = stricter)."""

    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3
    SECRET = 4

    @classmethod
    def from_tag(cls, tag: str) -> Optional["DataClass"]:
        """Parse data-class-tag from frontmatter. Pre: tag is str. Post: DataClass or None."""
        if not isinstance(tag, str):
            return None
        normalized = tag.strip().upper().replace("-", "_").replace(" ", "_")
        # Accept "PUBLIC", "CLASS-1", "CLASS_1", "1"
        if normalized in cls.__members__:
            return cls[normalized]
        for member in cls:
            if normalized == f"CLASS_{int(member)}" or normalized == str(int(member)):
                return member
        return None


# SECRET pattern detection: regex for credentials, finance, PII
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"\b(?:API[_-]?KEY|APIKEY)\s*[:=]\s*\S+", re.IGNORECASE)),
    ("token", re.compile(r"\b(?:TOKEN|BEARER)\s*[:=]\s*\S+", re.IGNORECASE)),
    ("password", re.compile(r"\b(?:PASSWORD|PASSWD|PWD)\s*[:=]\s*\S+", re.IGNORECASE)),
    ("secret", re.compile(r"\b(?:SECRET|SECRET[_-]?KEY)\s*[:=]\s*\S+", re.IGNORECASE)),
    ("bearer_header", re.compile(r"\bAuthorization\s*:\s*Bearer\s+\S+", re.IGNORECASE)),
    ("bearer_jwt", re.compile(r"\bBearer\s+[A-Za-z0-9._\-=]{20,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}\s?(?:\d{4}\s?){3,7}\d{0,4}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
)


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable routing-decision record. Pre: classified. Post: ALLOW or BLOCK with reason."""

    allowed: bool
    data_class: DataClass
    target_provider: str
    reason: str
    detected_patterns: tuple[str, ...] = field(default_factory=tuple)

    def to_log_entry(self) -> dict:
        """Serialize to JSONL-compatible dict."""
        return {
            "ts": time.time(),
            "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "decision": "ALLOW" if self.allowed else "BLOCK",
            "data_class": self.data_class.name,
            "data_class_int": int(self.data_class),
            "target_provider": self.target_provider,
            "reason": self.reason,
            "detected_patterns": list(self.detected_patterns),
        }


class DataClassFilter:
    """Pre-routing filter for KMO Data-Class No-Go-Matrix.

    Workflow:
        1. classify_input(prompt, frontmatter) -> DataClass
        2. is_provider_allowed(data_class, provider) -> bool
        3. pre_routing_check(prompt, target_provider, frontmatter) -> RoutingDecision
        4. all decisions logged via _append_audit()

    Pre-Conditions:
        - provider_compat.yaml must exist at config_path
        - audit_log_path's parent dir must be writable
    Post-Conditions:
        - Every pre_routing_check call produces exactly one JSONL audit entry
        - SECRET-class never returns ALLOW for any flat-LLM provider
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        audit_log_path: Optional[Path] = None,
    ) -> None:
        self.config_path: Path = config_path or DEFAULT_CONFIG_PATH
        self.audit_log_path: Path = audit_log_path or self._resolve_audit_path()
        self._compat: dict[str, int] = self._load_compat_matrix()

    @staticmethod
    def _resolve_audit_path() -> Path:
        """Use Drive-Sync path if mounted, else local fallback."""
        primary = DEFAULT_AUDIT_LOG_PATH
        if primary.parent.exists():
            return primary
        FALLBACK_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        return FALLBACK_AUDIT_LOG_PATH

    def _load_compat_matrix(self) -> dict[str, int]:
        """Load provider->max-data-class from YAML. Pre: file exists. Post: dict[str, int]."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Provider-Compat-Matrix nicht gefunden: {self.config_path}"
            )
        with self.config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        providers = raw.get("providers", {})
        compat: dict[str, int] = {}
        for provider, spec in providers.items():
            max_class_name = spec.get("max_data_class")
            if isinstance(max_class_name, int):
                compat[provider] = max_class_name
            elif isinstance(max_class_name, str):
                parsed = DataClass.from_tag(max_class_name)
                if parsed is None:
                    raise ValueError(
                        f"Ungueltige max_data_class '{max_class_name}' fuer Provider '{provider}'"
                    )
                compat[provider] = int(parsed)
            else:
                raise ValueError(f"Provider '{provider}' hat keine gueltige max_data_class")
        return compat

    def classify_input(self, prompt: str, frontmatter: Optional[dict] = None) -> DataClass:
        """Classify prompt into DataClass.

        Priority:
            1. Frontmatter-Tag `data_class` (or `data-class`)
            2. Pattern-Detection -> SECRET if any SECRET_PATTERN matches
            3. Default: PUBLIC

        Pre: prompt is str. Post: DataClass enum value.
        """
        # Priority 1: explicit frontmatter tag
        if frontmatter:
            tag = frontmatter.get("data_class") or frontmatter.get("data-class")
            if tag is not None:
                parsed = DataClass.from_tag(str(tag))
                if parsed is not None:
                    return parsed

        # Priority 2: SECRET pattern detection in prompt
        if self._detect_secret_patterns(prompt):
            return DataClass.SECRET

        # Priority 3: default
        return DataClass.PUBLIC

    @staticmethod
    def _detect_secret_patterns(prompt: str) -> tuple[str, ...]:
        """Return tuple of pattern-names matched in prompt."""
        if not isinstance(prompt, str) or not prompt:
            return ()
        matches: list[str] = []
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(prompt):
                matches.append(name)
        return tuple(matches)

    def is_provider_allowed(self, data_class: DataClass, provider: str) -> bool:
        """Check provider-compatibility for given data_class.

        Pre: provider in compat matrix. Post: bool.
        Unknown providers default to DENY (fail-closed).
        """
        if provider not in self._compat:
            return False
        max_allowed = self._compat[provider]
        return int(data_class) <= max_allowed

    def pre_routing_check(
        self,
        prompt: str,
        target_provider: str,
        frontmatter: Optional[dict] = None,
    ) -> RoutingDecision:
        """Full pre-routing check: classify + compat + log.

        Pre: prompt is str, target_provider is str.
        Post: RoutingDecision, audit log appended.
        """
        data_class = self.classify_input(prompt, frontmatter)
        detected = self._detect_secret_patterns(prompt) if data_class == DataClass.SECRET else ()

        if target_provider not in self._compat:
            decision = RoutingDecision(
                allowed=False,
                data_class=data_class,
                target_provider=target_provider,
                reason=f"Unbekannter Provider '{target_provider}' (fail-closed)",
                detected_patterns=detected,
            )
        elif self.is_provider_allowed(data_class, target_provider):
            decision = RoutingDecision(
                allowed=True,
                data_class=data_class,
                target_provider=target_provider,
                reason=f"Provider '{target_provider}' akzeptiert {data_class.name}",
                detected_patterns=detected,
            )
        else:
            max_allowed = DataClass(self._compat[target_provider])
            decision = RoutingDecision(
                allowed=False,
                data_class=data_class,
                target_provider=target_provider,
                reason=(
                    f"Mismatch: prompt={data_class.name} > "
                    f"provider-max={max_allowed.name}"
                ),
                detected_patterns=detected,
            )

        self._append_audit(decision)
        return decision

    def _append_audit(self, decision: RoutingDecision) -> None:
        """Append decision to JSONL audit log. Pre: parent dir writable. Post: 1 line appended."""
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_log_entry(), ensure_ascii=False) + "\n")
