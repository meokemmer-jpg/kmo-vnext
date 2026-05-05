"""KMO feature_flag_engine [CRUX-MK].

Welle-10 Phase-6.5 SUBAGENT-G: Feature-Flag-Engine SKELETON.

Bio-Aequivalent: Genexpressions-Regulation (Promoter/Enhancer/Silencer).
Promotor-Bindung entscheidet welche Gene transkribiert werden in einer Zelle,
abhaengig vom Kontext (Konzentrationen, Modifikationen). Analog: die Feature-Flag-
Engine schaltet Software-Verhalten kontextabhaengig (User, Hotel, Environment).

Pattern-Inspiration:
  - kmo_governance/sigma_switch (Mode-State-Machine + Hysterese gegen Flapping)
  - kmo_governance/multi_signal_policy (N-Input-Aggregation, Markov-State)
  - kmo_governance/pre_production_canary (Deterministic md5 Routing)

K11 Cascade-Containment: Flags isolieren Feature-Rollouts auf Sub-Population.
K13 Pre-Action-Verification: Pre-Conditions vor jedem Flag-Update geprueft.

Komponenten:
  - FlagRuleType (Enum): BOOLEAN, PERCENTAGE, CONTEXTUAL
  - FlagRule (frozen): unveraenderlicher Regel-Kontainer
  - FlagContext (frozen): Evaluation-Kontext
  - FlagEvalRecord (frozen): Append-only Audit-Entry
  - FeatureFlagEngine: Registry + Evaluation (thread-safe RLock)
  - PercentageRollout: Deterministic via md5(flag_id+user_id) % 100
  - ContextualRule: AND/OR conditions ueber attrs (eq/neq/gt/lt/in/contains)
  - ABTestVariantSelector: Multi-variant deterministic selection mit weights
  - FlagAuditLog: Append-only audit + distribution stats per window
"""

from __future__ import annotations

import enum
import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------- Enums ----------


class FlagRuleType(str, enum.Enum):
    """Klassifikation von Flag-Regeln."""

    BOOLEAN = "boolean"
    PERCENTAGE = "percentage"
    CONTEXTUAL = "contextual"


# ---------- Frozen Dataclasses ----------


@dataclass(frozen=True)
class FlagRule:
    """Unveraenderlicher Regel-Kontainer fuer ein Feature-Flag.

    Pre:
      - flag_id non-empty
      - rule_type in FlagRuleType
      - config_dict konsistent zum rule_type:
          BOOLEAN     -> {"enabled": bool}
          PERCENTAGE  -> {"percentage": float in [0,100]}
          CONTEXTUAL  -> {"conditions": list[(attr, op, value)],
                          "match_mode": "all"|"any"  (Default "all")}
    Post: immutable, hashable
    """

    flag_id: str
    rule_type: FlagRuleType
    config: tuple  # tuple-of-(key, value) zur Hashbarkeit

    @staticmethod
    def boolean(flag_id: str, enabled: bool) -> "FlagRule":
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        return FlagRule(
            flag_id=flag_id,
            rule_type=FlagRuleType.BOOLEAN,
            config=(("enabled", bool(enabled)),),
        )

    @staticmethod
    def percentage(flag_id: str, percentage: float) -> "FlagRule":
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        if not (0.0 <= percentage <= 100.0):
            raise ValueError("percentage must be in [0, 100]")
        return FlagRule(
            flag_id=flag_id,
            rule_type=FlagRuleType.PERCENTAGE,
            config=(("percentage", float(percentage)),),
        )

    @staticmethod
    def contextual(
        flag_id: str,
        conditions: list[tuple[str, str, Any]],
        match_mode: str = "all",
    ) -> "FlagRule":
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        if match_mode not in ("all", "any"):
            raise ValueError("match_mode must be 'all' or 'any'")
        if not conditions:
            raise ValueError("conditions must be non-empty")
        # Tupel der Conditions (sicher gegen List-Mutationen)
        frozen_conditions = tuple(
            (str(attr), str(op), _freeze_value(value)) for attr, op, value in conditions
        )
        return FlagRule(
            flag_id=flag_id,
            rule_type=FlagRuleType.CONTEXTUAL,
            config=(
                ("conditions", frozen_conditions),
                ("match_mode", match_mode),
            ),
        )

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.config:
            if k == key:
                return v
        return default


def _freeze_value(value: Any) -> Any:
    """Hashbar-konvertieren von List-/Set-Values fuer config-Tuples."""
    if isinstance(value, list):
        return tuple(_freeze_value(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze_value(v)) for k, v in value.items()))
    return value


@dataclass(frozen=True)
class FlagContext:
    """Auswertungs-Kontext fuer Flag-Evaluation.

    Pre:
      - environment optional non-empty string
      - custom_attrs ist tuple-of-(key, value) (frozen-konvertiert)
    Post: immutable, hashable
    """

    user_id: Optional[str] = None
    hotel_id: Optional[str] = None
    environment: Optional[str] = None
    custom_attrs: tuple = ()  # tuple von (key, value)-Paaren

    @staticmethod
    def from_dict(
        user_id: Optional[str] = None,
        hotel_id: Optional[str] = None,
        environment: Optional[str] = None,
        custom: Optional[dict[str, Any]] = None,
    ) -> "FlagContext":
        if custom:
            attrs = tuple(sorted((k, _freeze_value(v)) for k, v in custom.items()))
        else:
            attrs = ()
        return FlagContext(
            user_id=user_id,
            hotel_id=hotel_id,
            environment=environment,
            custom_attrs=attrs,
        )

    def get_attr(self, name: str) -> Any:
        """Get attribute (built-in or custom). Returns None if absent."""
        if name == "user_id":
            return self.user_id
        if name == "hotel_id":
            return self.hotel_id
        if name == "environment":
            return self.environment
        for k, v in self.custom_attrs:
            if k == name:
                return v
        return None


@dataclass(frozen=True)
class FlagEvalRecord:
    """Append-only Audit-Eintrag pro Flag-Evaluation.

    Pre: flag_id non-empty
    Post: immutable
    """

    flag_id: str
    user_id: Optional[str]
    hotel_id: Optional[str]
    environment: Optional[str]
    result: Any  # bool fuer is_enabled, str/Any fuer Variants
    ts: float


# ---------- PercentageRollout ----------


class PercentageRollout:
    """Deterministic-Bucket-Routing fuer Percentage-Rollouts.

    Hash: md5(flag_id + ":" + user_id) -> bucket in [0,99].
    enabled := bucket < percentage.

    Pre: 0 <= percentage <= 100
    Post: gleiche (flag_id, user_id) fuehren zu gleichem Bucket
          (reproduzierbar ueber Calls hinweg + Restart-stabil)
    """

    def __init__(self, flag_id: str, percentage: float) -> None:
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        if not (0.0 <= percentage <= 100.0):
            raise ValueError("percentage must be in [0, 100]")
        self.flag_id = flag_id
        self.percentage = float(percentage)

    def bucket_for(self, user_id: str) -> int:
        """Returns bucket in [0, 99]."""
        if not user_id:
            raise ValueError("user_id must be non-empty")
        key = f"{self.flag_id}:{user_id}".encode("utf-8")
        digest = hashlib.md5(key).hexdigest()
        # Use first 8 hex chars for stability + spread
        bucket = int(digest[:8], 16) % 100
        return bucket

    def is_enabled(self, user_id: str) -> bool:
        """True iff bucket < percentage."""
        return self.bucket_for(user_id) < self.percentage


# ---------- ContextualRule ----------


class ContextualRule:
    """Evaluiert AND/OR-Conditions ueber Context-Attributen.

    Operations:
      - "eq"        : equals
      - "neq"       : not equals
      - "gt"        : greater than (numeric)
      - "lt"        : less than    (numeric)
      - "in"        : value in collection (collection als list/tuple)
      - "contains"  : collection (attr ist liste/tuple) contains value

    Pre: conditions ist non-empty list of (attr, op, value)
         match_mode in {"all", "any"}
    Post: evaluate(context) returns bool deterministic
    """

    _SUPPORTED_OPS = {"eq", "neq", "gt", "lt", "in", "contains"}

    def __init__(
        self,
        conditions: list[tuple[str, str, Any]],
        match_mode: str = "all",
    ) -> None:
        if match_mode not in ("all", "any"):
            raise ValueError("match_mode must be 'all' or 'any'")
        if not conditions:
            raise ValueError("conditions must be non-empty")
        for attr, op, _value in conditions:
            if not attr:
                raise ValueError("attr must be non-empty")
            if op not in self._SUPPORTED_OPS:
                raise ValueError(f"unsupported op {op!r}")
        self.conditions = list(conditions)
        self.match_mode = match_mode

    def evaluate(self, context: FlagContext) -> bool:
        results: list[bool] = []
        for attr, op, value in self.conditions:
            attr_val = context.get_attr(attr)
            results.append(self._apply_op(op, attr_val, value))
        if self.match_mode == "all":
            return all(results)
        return any(results)

    @staticmethod
    def _apply_op(op: str, attr_val: Any, expected: Any) -> bool:
        if op == "eq":
            return attr_val == expected
        if op == "neq":
            return attr_val != expected
        if op == "gt":
            try:
                return attr_val is not None and attr_val > expected
            except TypeError:
                return False
        if op == "lt":
            try:
                return attr_val is not None and attr_val < expected
            except TypeError:
                return False
        if op == "in":
            try:
                return attr_val in expected
            except TypeError:
                return False
        if op == "contains":
            if attr_val is None:
                return False
            try:
                return expected in attr_val
            except TypeError:
                return False
        return False


# ---------- ABTestVariantSelector ----------


class ABTestVariantSelector:
    """Multi-Variant-Selection (deterministic) mit Gewichten.

    Hash: md5(flag_id + ":" + user_id) -> bucket in [0,9999) -> position [0,100).
    Variant-Selektion via kumuliertes Walking durch Weights.

    Pre: variants + weights gleich lang; sum(weights) > 0
    Post: gleiche (flag_id, user_id) immer gleiche Variant
    """

    def __init__(self) -> None:
        # flag_id -> (variants_tuple, normalized_weights)
        self._variants: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = {}
        # flag_id -> {variant_id: count}
        self._stats: dict[str, dict[str, int]] = {}
        self._lock = threading.RLock()

    def register_variants(
        self,
        flag_id: str,
        variants: list[str],
        weights: list[float],
    ) -> None:
        """Registriere Variants + Weights. Weights werden normalisiert.

        Pre: variants non-empty; len(variants) == len(weights);
             sum(weights) > 0; weights >= 0
        Post: idempotent updateable
        """
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        if not variants:
            raise ValueError("variants must be non-empty")
        if len(variants) != len(weights):
            raise ValueError("variants + weights must have same length")
        for w in weights:
            if w < 0:
                raise ValueError("weights must be >= 0")
        total = float(sum(weights))
        if total <= 0:
            raise ValueError("sum(weights) must be > 0")
        normalized = tuple(float(w) / total for w in weights)
        with self._lock:
            self._variants[flag_id] = (tuple(variants), normalized)
            if flag_id not in self._stats:
                self._stats[flag_id] = {v: 0 for v in variants}
            else:
                # Reset Counter fuer alle bekannten Varianten
                for v in variants:
                    self._stats[flag_id].setdefault(v, 0)

    def select_variant(self, flag_id: str, context: FlagContext) -> str:
        """Waehlt Variant deterministic via md5(flag_id+user_id).

        Pre: register_variants(flag_id) wurde aufgerufen
        Post: gleiche (flag_id, user_id) immer gleiche Variant; logged stats
        """
        with self._lock:
            entry = self._variants.get(flag_id)
            if entry is None:
                raise KeyError(f"no variants registered for flag_id {flag_id!r}")
            variants, weights = entry
            user_id = context.user_id or "_anonymous"
            key = f"{flag_id}:{user_id}".encode("utf-8")
            digest = hashlib.md5(key).hexdigest()
            bucket = int(digest[:8], 16) % 10000  # 0-9999
            position = bucket / 100.0  # 0.0 - 99.99
            cumulative = 0.0
            chosen = variants[-1]  # fallback (Float-Tolerance)
            for v, w in zip(variants, weights):
                cumulative += w * 100.0
                if position < cumulative:
                    chosen = v
                    break
            self._stats[flag_id][chosen] = self._stats[flag_id].get(chosen, 0) + 1
            return chosen

    def get_distribution_stats(self, flag_id: str) -> dict[str, int]:
        """Snapshot der bisher gemessenen Variant-Counts."""
        with self._lock:
            return dict(self._stats.get(flag_id, {}))


# ---------- FlagAuditLog ----------


class FlagAuditLog:
    """Append-only Audit-Log + Distributions-Stats per Window.

    Pre: -
    Post: thread-safe; record_evaluation appended; get_history snapshot;
          get_distribution_stats fuer flag_id im Sliding-Window.
    """

    def __init__(self, max_records: int = 100_000) -> None:
        if max_records <= 0:
            raise ValueError("max_records must be > 0")
        self._max_records = int(max_records)
        # flag_id -> deque[FlagEvalRecord]
        self._records: dict[str, deque[FlagEvalRecord]] = {}
        self._lock = threading.RLock()

    def record_evaluation(
        self,
        flag_id: str,
        context: FlagContext,
        result: Any,
        ts: Optional[float] = None,
    ) -> None:
        """Append Evaluation-Record. Drops oldest at max_records.

        Pre: flag_id non-empty
        Post: record appended in arrival-order
        """
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        rec = FlagEvalRecord(
            flag_id=flag_id,
            user_id=context.user_id,
            hotel_id=context.hotel_id,
            environment=context.environment,
            result=result,
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            if flag_id not in self._records:
                self._records[flag_id] = deque(maxlen=self._max_records)
            self._records[flag_id].append(rec)

    def get_history(self, flag_id: str) -> list[FlagEvalRecord]:
        """Snapshot aller Records fuer flag_id."""
        with self._lock:
            return list(self._records.get(flag_id, deque()))

    def get_distribution_stats(
        self,
        flag_id: str,
        window_s: float = 3600.0,
    ) -> dict[str, int]:
        """Counts der Result-Werte im Sliding-Window.

        Pre: window_s > 0
        Post: dict {result_str: count} fuer Records (now - ts) <= window_s
        """
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        now = time.time()
        with self._lock:
            recs = self._records.get(flag_id, deque())
            counts: dict[str, int] = {}
            for r in recs:
                if (now - r.ts) <= window_s:
                    key = str(r.result)
                    counts[key] = counts.get(key, 0) + 1
            return counts

    def __len__(self) -> int:
        with self._lock:
            return sum(len(d) for d in self._records.values())


# ---------- FeatureFlagEngine ----------


class FeatureFlagEngine:
    """Registry + Evaluation fuer Feature-Flags. Thread-safe via RLock.

    Verbindet:
      - FlagRule-Registry
      - PercentageRollout fuer rule_type=PERCENTAGE
      - ContextualRule fuer rule_type=CONTEXTUAL
      - ABTestVariantSelector fuer Multi-Variant
      - FlagAuditLog fuer Auditing

    Pre: -
    Post:
      - register_flag idempotent
      - update_rule wirkt sofort
      - is_enabled / get_value liefern deterministic
      - unregistered flag -> default (False / None)
    """

    def __init__(
        self,
        audit_log: Optional[FlagAuditLog] = None,
        variant_selector: Optional[ABTestVariantSelector] = None,
    ) -> None:
        self._rules: dict[str, FlagRule] = {}
        self._lock = threading.RLock()
        self._audit_log = audit_log if audit_log is not None else FlagAuditLog()
        self._variant_selector = (
            variant_selector if variant_selector is not None else ABTestVariantSelector()
        )

    # ---------- Registration ----------

    def register_flag(self, flag_id: str, rule: FlagRule) -> None:
        """Registriere/Update flag_id mit rule.

        Pre: rule.flag_id == flag_id
        Post: rule sofort wirksam
        """
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        if rule.flag_id != flag_id:
            raise ValueError(
                f"rule.flag_id ({rule.flag_id!r}) must equal flag_id ({flag_id!r})"
            )
        with self._lock:
            self._rules[flag_id] = rule

    def update_rule(self, flag_id: str, new_rule: FlagRule) -> None:
        """Alias fuer register_flag (immediate effect)."""
        self.register_flag(flag_id, new_rule)

    def unregister_flag(self, flag_id: str) -> None:
        """Entfernt Flag aus Registry. Subsequente Evaluation -> default."""
        with self._lock:
            self._rules.pop(flag_id, None)

    def register_variants(
        self,
        flag_id: str,
        variants: list[str],
        weights: list[float],
    ) -> None:
        """Convenience: registriere Variants + Weights ueber den Selector."""
        self._variant_selector.register_variants(flag_id, variants, weights)

    # ---------- Evaluation ----------

    def is_enabled(self, flag_id: str, context: FlagContext) -> bool:
        """Boolean-Evaluation. Default False fuer unregistered flag.

        Post: Audit-Eintrag mit result=bool
        """
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        with self._lock:
            rule = self._rules.get(flag_id)
        if rule is None:
            self._audit_log.record_evaluation(flag_id, context, False)
            return False
        result = self._evaluate_rule_bool(rule, context)
        self._audit_log.record_evaluation(flag_id, context, result)
        return result

    def get_value(self, flag_id: str, context: FlagContext) -> Any:
        """Multi-Variant-Evaluation. Default None fuer unregistered.

        Verhalten:
          - flag NICHT registered: None
          - kein Variant-Setup: bool aus is_enabled
          - Variant-Setup vorhanden + flag enabled: gewaehlte Variant
          - flag disabled: None
        Post: Audit-Eintrag mit result=variant_id|bool|None
        """
        if not flag_id:
            raise ValueError("flag_id must be non-empty")
        with self._lock:
            rule = self._rules.get(flag_id)
        if rule is None:
            self._audit_log.record_evaluation(flag_id, context, None)
            return None
        # Pre-Check: flag enabled?
        enabled = self._evaluate_rule_bool(rule, context)
        if not enabled:
            self._audit_log.record_evaluation(flag_id, context, None)
            return None
        # Variant lookup
        try:
            variant = self._variant_selector.select_variant(flag_id, context)
            self._audit_log.record_evaluation(flag_id, context, variant)
            return variant
        except KeyError:
            # Kein Variant-Setup -> bool zurueckgeben
            self._audit_log.record_evaluation(flag_id, context, enabled)
            return enabled

    # ---------- Internal ----------

    @staticmethod
    def _evaluate_rule_bool(rule: FlagRule, context: FlagContext) -> bool:
        """Konvertiert FlagRule + Context zu bool."""
        if rule.rule_type == FlagRuleType.BOOLEAN:
            return bool(rule.get("enabled", False))
        if rule.rule_type == FlagRuleType.PERCENTAGE:
            pct = float(rule.get("percentage", 0.0))
            user_id = context.user_id or "_anonymous"
            rollout = PercentageRollout(rule.flag_id, pct)
            return rollout.is_enabled(user_id)
        if rule.rule_type == FlagRuleType.CONTEXTUAL:
            conditions = rule.get("conditions", ())
            match_mode = rule.get("match_mode", "all")
            cr = ContextualRule(list(conditions), match_mode=match_mode)
            return cr.evaluate(context)
        return False

    # ---------- Introspection ----------

    def get_audit_log(self) -> FlagAuditLog:
        return self._audit_log

    def get_variant_selector(self) -> ABTestVariantSelector:
        return self._variant_selector

    def list_flags(self) -> list[str]:
        with self._lock:
            return sorted(self._rules.keys())

    def get_rule(self, flag_id: str) -> Optional[FlagRule]:
        with self._lock:
            return self._rules.get(flag_id)


# CRUX-MK
